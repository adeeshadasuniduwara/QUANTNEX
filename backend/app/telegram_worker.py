"""Background Telegram command and TP1 notification worker."""
from __future__ import annotations
import asyncio, html, json, logging, math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any
import httpx
from sqlalchemy import select, func, or_, update as sql_update
from .database import SessionLocal
from .models import GoalContribution, PaperTrade, PersonalGoal, Preference, SignalTrade, SignalTradeEvent, TelegramDelivery
from .security import decrypt_secret
from .config import TWELVE_DATA_API_KEY, QUANTNEX_MT5_ENABLED, QUANTNEX_MT5_GOLD_SYMBOL
from .signal_engine import (
    build_signal, MarketDataError, get_binance_spot_symbols,
    gold_feed_configured, gold_feed_provider,
)
from .events import event_hub
from .telegram_branding import build_personal_logo_png, normalise_telegram_name

logger = logging.getLogger("quantnex.telegram")
_SOURCE_UPDATE_PR_CACHE: dict[str, str] = {}

def _get(db, user_id: int, key: str, default: str="") -> str:
    row=db.scalar(select(Preference).where(Preference.user_id==user_id,Preference.key==key))
    return row.value if row else default

def _set(db, user_id: int, key: str, value: str) -> None:
    row=db.scalar(select(Preference).where(Preference.user_id==user_id,Preference.key==key))
    if row is None: db.add(Preference(user_id=user_id,key=key,value=value))
    else: row.value=value


def _claim_telegram_delivery(db, user_id: int, notification_key: str, lease_seconds: int = 120) -> bool:
    """Atomically claim one outbound notice; a second worker cannot send the same key."""
    from sqlalchemy.exc import IntegrityError

    now = datetime.now(timezone.utc)
    row = db.scalar(select(TelegramDelivery).where(
        TelegramDelivery.user_id == user_id,
        TelegramDelivery.notification_key == notification_key,
    ))
    if row is None:
        try:
            with db.begin_nested():
                db.add(TelegramDelivery(
                    user_id=user_id, notification_key=notification_key,
                    status="sending", attempts=1, claimed_at=now,
                ))
                db.flush()
            db.commit()
            return True
        except IntegrityError:
            # Another worker inserted the unique key first. Re-read and let the
            # compare-and-set path below decide whether its lease can be claimed.
            db.rollback()
            return _claim_telegram_delivery(db, user_id, notification_key, lease_seconds)

    if row.status == "sent":
        return False
    stale_before = now - timedelta(seconds=lease_seconds)
    claimed = db.execute(sql_update(TelegramDelivery).where(
        TelegramDelivery.id == row.id,
        TelegramDelivery.status != "sent",
        or_(TelegramDelivery.status != "sending",
            TelegramDelivery.claimed_at <= stale_before),
    ).values(
        status="sending", claimed_at=now,
        attempts=TelegramDelivery.attempts + 1,
    ).execution_options(synchronize_session=False))
    db.commit()
    return claimed.rowcount == 1

def _finish_telegram_delivery(db, user_id: int, notification_key: str, sent: bool) -> None:
    row = db.scalar(select(TelegramDelivery).where(
        TelegramDelivery.user_id == user_id,
        TelegramDelivery.notification_key == notification_key,
    ))
    if row is None:
        return
    row.status = "sent" if sent else "failed"
    row.sent_at = datetime.now(timezone.utc) if sent else None
    if not sent:
        # Release the claim immediately so the next poll can retry a failed send.
        row.claimed_at = datetime.now(timezone.utc) - timedelta(seconds=121)
    db.commit()

AUTO_SIGNAL_LEGACY_DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
AUTO_SIGNAL_MAX_BATCH_SIZE = 20
AUTO_SIGNAL_MAX_PENDING_STREAMS = 8
AUTO_SIGNAL_MAX_PENDING_RETRIES = 3


def _normalise_auto_signal_settings(raw: str) -> dict[str, Any]:
    defaults = {
        "enabled": False,
        "interval_seconds": 180,
        "universe_mode": "ALL_BINANCE_SPOT",
        "scan_batch_size": AUTO_SIGNAL_MAX_BATCH_SIZE,
        "symbols": [],
    }
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    try:
        interval = int(value.get("interval_seconds", defaults["interval_seconds"]) or defaults["interval_seconds"])
    except (TypeError, ValueError, OverflowError):
        interval = defaults["interval_seconds"]
    try:
        batch_size = int(value.get("scan_batch_size", defaults["scan_batch_size"]) or defaults["scan_batch_size"])
    except (TypeError, ValueError, OverflowError):
        batch_size = defaults["scan_batch_size"]
    symbols = value.get("symbols", [])
    if not isinstance(symbols, (list, tuple)):
        symbols = []
    selected = list(dict.fromkeys(
        str(item).strip().upper() for item in symbols
        if str(item).strip().upper() == "XAUUSD"
        or (str(item).strip().isalnum() and 5 <= len(str(item).strip()) <= 30)
    ))[:50]

    requested_mode = value.get("universe_mode")
    if requested_mode in {"ALL_BINANCE_SPOT", "SELECTED"}:
        universe_mode = requested_mode
    elif selected and selected != AUTO_SIGNAL_LEGACY_DEFAULT_SYMBOLS:
        # Preserve a genuine legacy custom watchlist. The former built-in
        # BTC/ETH/SOL defaults migrate to full-universe scanning.
        universe_mode = "SELECTED"
    else:
        universe_mode = "ALL_BINANCE_SPOT"

    if universe_mode == "ALL_BINANCE_SPOT":
        # In full-universe mode only the optional separate Gold feed is an
        # add-on; old hard-coded Binance defaults are never treated as a cap.
        selected = [symbol for symbol in selected if symbol == "XAUUSD"]

    return {
        "enabled": value.get("enabled") is True,
        "interval_seconds": max(60, min(3600, interval)),
        "universe_mode": universe_mode,
        "scan_batch_size": max(1, min(AUTO_SIGNAL_MAX_BATCH_SIZE, batch_size)),
        "symbols": selected,
    }


def _rotating_auto_signal_batch(
    symbols: list[str],
    cursor_symbol: str | None,
    batch_size: int,
    *,
    excluded: set[str] | None = None,
) -> list[str]:
    """Return the next fair, deterministic slice after the persisted cursor."""
    universe = list(dict.fromkeys(
        str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()
    ))
    if not universe or isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        return []
    start = 0
    if cursor_symbol in universe:
        start = (universe.index(cursor_symbol) + 1) % len(universe)
    ordered = universe[start:] + universe[:start]
    omitted = {str(symbol).strip().upper() for symbol in (excluded or set())}
    return [symbol for symbol in ordered if symbol not in omitted][:batch_size]


def _normalise_auto_signal_pending(raw: str, universe: list[str]) -> dict[str, int]:
    """Keep a small retry queue for symbols whose order-flow stream is bootstrapping."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        value = []
    if not isinstance(value, list):
        return {}
    allowed = set(universe)
    pending: dict[str, int] = {}
    for item in value:
        if isinstance(item, str):
            symbol, attempts = item.strip().upper(), 1
        elif isinstance(item, dict):
            symbol = str(item.get("symbol") or "").strip().upper()
            try:
                attempts = int(item.get("attempts", 1))
            except (TypeError, ValueError, OverflowError):
                attempts = 1
        else:
            continue
        if symbol in allowed and 1 <= attempts <= AUTO_SIGNAL_MAX_PENDING_RETRIES:
            pending[symbol] = attempts
        if len(pending) >= AUTO_SIGNAL_MAX_PENDING_STREAMS:
            break
    return pending


def _is_auto_signal_stream_pending(scan: dict[str, Any] | None) -> bool:
    if not isinstance(scan, dict) or scan.get("signal"):
        return False
    flow = scan.get("order_flow")
    return (
        isinstance(flow, dict)
        and flow.get("data_mode") == "PUBLIC_WEBSOCKET_STREAM"
        and flow.get("stream_ready") is False
    )


def _auto_signal_fingerprint(symbol: str, candidate: dict[str, Any] | None) -> str:
    if not isinstance(candidate, dict):
        return ""
    side = str(candidate.get("side") or "").upper()
    timeframe = str(candidate.get("timeframe") or "")
    candle_time = str(candidate.get("signal_candle_time") or "")
    if not side or not timeframe or not candle_time:
        return ""
    return "|".join([str(symbol).upper(), side, timeframe, candle_time])


def _should_send_auto_signal(fingerprint: str, previous: str | None) -> bool:
    return bool(fingerprint and fingerprint != (previous or ""))


def _normalise_signal_settings(raw: str) -> dict[str, Any]:
    defaults = {"primary": "5", "trend": "60",
                "enabled": ["60", "30", "15", "5", "1"],
                "risk_percent": 1, "min_score": 8}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    timeframes = {"1", "5", "15", "30", "50", "60", "240"}
    primary = str(value.get("primary", defaults["primary"]))
    trend = str(value.get("trend", defaults["trend"]))
    if primary not in timeframes:
        primary = defaults["primary"]
    if trend not in timeframes:
        trend = defaults["trend"]
    enabled = value.get("enabled", defaults["enabled"])
    if not isinstance(enabled, (list, tuple)):
        enabled = defaults["enabled"]
    enabled = list(dict.fromkeys(str(item) for item in enabled if str(item) in timeframes))
    if not enabled:
        enabled = defaults["enabled"]
    try:
        min_score = int(value.get("min_score", defaults["min_score"]))
    except (TypeError, ValueError, OverflowError):
        min_score = defaults["min_score"]
    return {**defaults, **value, "primary": primary, "trend": trend,
            "enabled": enabled, "min_score": max(8, min(10, min_score))}


def _publish_signal_settings_changed() -> None:
    event_hub.publish("preferences.changed","preferences","updated",{"key":"signal_settings"})


def _persist_update_offset(db, user_id: int, offset: int) -> None:
    """Commit the Telegram polling cursor independently of reply delivery."""
    _set(db, user_id, "telegram_update_offset", str(offset))
    db.commit()

BOT_COMMANDS = [
    {"command":"start","description":"Open your QUANTNEX workspace"},
    {"command":"help","description":"Show help and available features"},
    {"command":"status","description":"Check bot and market feed status"},
    {"command":"scan","description":"Scan a market, e.g. /scan BTCUSDT"},
    {"command":"report","description":"Signal PDF: daily weekly monthly yearly total"},
    {"command":"report_on","description":"Enable 21:00 signal PDF reports"},
    {"command":"report_off","description":"Disable scheduled signal PDF reports"},
    {"command":"timeframes","description":"View signal timeframes"},
    {"command":"settf","description":"Set primary timeframe"},
    {"command":"settrend","description":"Set trend timeframe"},
    {"command":"setanalysis","description":"Set analysis timeframes"},
    {"command":"gold","description":"Get a live Sri Lankan gold price image"},
    {"command":"gold_setup","description":"Enable daily Gold reports at 00:00 and 12:00"},
    {"command":"gold_status","description":"Check daily Gold report settings"},
    {"command":"gold_off","description":"Disable scheduled Gold reports"},
    {"command":"binance","description":"Open Binance demo connection setup guide"},
    {"command":"binance_status","description":"Check Binance Spot and Futures testnet status"},
    {"command":"binance_off","description":"Emergency stop: keep Binance auto trading OFF"},
]

MENU = {"inline_keyboard": [
    [{"text":"📈 Markets & scans","callback_data":"qx:menu:markets"},{"text":"🧠 Signal controls","callback_data":"qx:menu:signals"}],
    [{"text":"🤖 Paper trading","callback_data":"qx:menu:paper"},{"text":"📊 Reports & goals","callback_data":"qx:menu:reports"}],
    [{"text":"⚙ Settings & status","callback_data":"qx:menu:settings"},{"text":"❔ Help & guide","callback_data":"qx:help"}]
]}

SUBMENUS = {
    "qx:menu:markets": {"inline_keyboard": [
        [{"text":"₿ BTCUSDT","callback_data":"qx:scan:BTCUSDT"},{"text":"Ξ ETHUSDT","callback_data":"qx:scan:ETHUSDT"}],
        [{"text":"◎ SOLUSDT","callback_data":"qx:scan:SOLUSDT"},{"text":"🥇 XAUUSD","callback_data":"qx:scan:XAUUSD"}],
        [{"text":"🔄 Scan BTC now","callback_data":"qx:scan:BTCUSDT"}],
        [{"text":"🏠 Main menu","callback_data":"qx:menu:home"}]
    ]},
    "qx:menu:signals": {"inline_keyboard": [
        [{"text":"M1","callback_data":"qx:settf:1"},{"text":"M5","callback_data":"qx:settf:5"},{"text":"M15","callback_data":"qx:settf:15"}],
        [{"text":"M30","callback_data":"qx:settf:30"},{"text":"M50","callback_data":"qx:settf:50"},{"text":"H1","callback_data":"qx:settf:60"}],
        [{"text":"Trend M15","callback_data":"qx:settrend:15"},{"text":"Trend M30","callback_data":"qx:settrend:30"}],
        [{"text":"Trend H1","callback_data":"qx:settrend:60"},{"text":"Trend H4","callback_data":"qx:settrend:240"}],
        [{"text":"▶ Enable alerts","callback_data":"qx:resume"},{"text":"⏸ Pause alerts","callback_data":"qx:pause"}],
        [{"text":"🔎 Feed status","callback_data":"qx:status"},{"text":"🛡 Risk settings","callback_data":"qx:risk"}],
        [{"text":"🏠 Main menu","callback_data":"qx:menu:home"}]
    ]},
    "qx:menu:paper": {"inline_keyboard": [
        [{"text":"📊 Paper ledger","callback_data":"qx:home"}],
        [{"text":"▶ Start paper mode","callback_data":"qx:paper_start"},{"text":"⏸ Pause paper","callback_data":"qx:paper_pause"}],
        [{"text":"🤖 Paper status","callback_data":"qx:paper"}],
        [{"text":"🏠 Main menu","callback_data":"qx:menu:home"}]
    ]},
    "qx:menu:reports": {"inline_keyboard": [
        [{"text":"📈 Signal performance PDF","callback_data":"qx:signal_report"}],
        [{"text":"📄 Today's Paper PDF","callback_data":"qx:daily"}],
        [{"text":"🥇 Gold price image now","callback_data":"qx:gold"}],
        [{"text":"🌙 Enable daily Gold reports","callback_data":"qx:gold_setup"}],
        [{"text":"🕗 Daily PDF 20:00 ON/OFF","callback_data":"qx:daily_toggle"}],
        [{"text":"🎯 Personal goals","callback_data":"qx:goals"}],
        [{"text":"🏠 Main menu","callback_data":"qx:menu:home"}]
    ]},
    "qx:menu:settings": {"inline_keyboard": [
        [{"text":"🔌 Connection status","callback_data":"qx:status"}],
        [{"text":"⏱ Timeframe controls","callback_data":"qx:menu:signals"}],
        [{"text":"🛡 Risk & alert settings","callback_data":"qx:risk"}],
        [{"text":"❔ Help & guide","callback_data":"qx:help"}],
        [{"text":"🏠 Main menu","callback_data":"qx:menu:home"}]
    ]}
}

MENU_TITLES = {
    "qx:menu:markets": "📈 MARKET SCANNER",
    "qx:menu:signals": "🧠 SIGNAL & TIMEFRAME CONTROLS",
    "qx:menu:paper": "🤖 PAPER TRADING DESK",
    "qx:menu:reports": "📊 REPORTS & PERSONAL GOALS",
    "qx:menu:settings": "⚙ SETTINGS & SYSTEM STATUS",
}

async def _telegram_post(client, token: str, method: str, payload: dict):
    url=f"https://api.telegram.org/bot{token}/{method}"
    for attempt in range(3):
        response=await client.post(url,json=payload)
        try: data=response.json()
        except ValueError: data={}
        if response.status_code == 429 and attempt < 2:
            await asyncio.sleep(max(1,min(10,int((data.get("parameters") or {}).get("retry_after",2)))))
            continue
        if response.status_code >= 500 and attempt < 2:
            await asyncio.sleep(2 ** attempt)
            continue
        response.raise_for_status()
        if not data.get("ok"):
            raise httpx.HTTPStatusError("Telegram rejected the request.",request=response.request,response=response)
        return data.get("result",{})
    raise RuntimeError("Telegram retry limit reached.")

def _format_telegram_message(message: str) -> str:
    """Render branded Telegram HTML, preserving only safe formatting tags."""
    import html
    import re

    content = (str(message or "").replace("\r\n", "\n").replace("\r", "\n")
               .replace("\\\\n", "\n").replace("\\n", "\n").strip() or "No message content.")
    safe_tag = re.compile(
        r"</?(?:b|i)>|<a href=\"https://github\.com/[^\"<>\s]+\">|</a>",
        re.IGNORECASE,
    )

    def escape_text(value: str) -> str:
        return "".join(
            part if safe_tag.fullmatch(part) else html.escape(part, quote=False)
            for part in re.split(
                r"(</?(?:b|i)>|<a href=\"https://github\.com/[^\"<>\s]+\">|</a>)",
                value, flags=re.IGNORECASE,
            )
        )

    lines = content.splitlines()
    rendered = []
    if not lines or "QUANTNEX" not in lines[0].upper():
        rendered.extend(["<b>✨ QUANTNEX</b>", ""])
    for index, line in enumerate(lines):
        safe = escape_text(line)
        stripped = line.strip()
        if not stripped:
            rendered.append("")
        elif index == 0:
            if "QUANTNEX" in stripped.upper() and "<b>" in safe.lower():
                rendered.append("✨ " + safe)
            else:
                rendered.append("<b>✨ " + safe + "</b>" if "QUANTNEX" in stripped.upper() else "<b>" + safe + "</b>")
        elif stripped.isupper() and len(stripped) > 3:
            rendered.append("<b>" + safe + "</b>")
        elif ":" in line:
            label, value = line.split(":", 1)
            if "<b>" in label.lower() or "<i>" in label.lower():
                rendered.append(safe)
            else:
                rendered.append("<b>" + escape_text(label) + ":</b>" + escape_text(value))
        elif stripped.startswith(("Level-touch alert", "Not a real broker", "Signal only", "Verify any real")):
            rendered.append("<i>" + safe + "</i>")
        else:
            rendered.append(safe)
    return "\n".join(rendered)[:3900]


async def _deliver_auto_signal(client, token: str, chat_id: str, message: str,
                              fingerprint: str, previous: str | None,
                              db, user_id: int, fingerprint_key: str) -> bool:
    """Send only a new signal fingerprint and persist it only after Telegram accepts it."""
    if not _should_send_auto_signal(fingerprint, previous):
        return False
    await _send(client, token, chat_id, message)
    _set(db, user_id, fingerprint_key, fingerprint)
    return True


async def _scan_and_deliver_auto_signal(
    client,
    token: str,
    chat_id: str,
    db,
    user_id: int,
    signal_settings: dict[str, Any],
    market_symbol: str,
) -> bool | None:
    """Scan one market and report whether its order-flow stream needs a retry.

    True means keep this symbol near the front of the next cycle so its
    sequence-validated stream can finish bootstrapping. False means no stream
    retry is needed. None means a transient scan error occurred.
    """
    try:
        scan = await build_signal(signal_settings, market_symbol)
        candidate = scan.get("signal")
        if candidate:
            from .signal_lifecycle import record_signal
            _tracked, created = record_signal(db, user_id, candidate, "AUTO_TELEGRAM_SCAN")
            db.commit()
            fingerprint_key = "auto_signal_last_fingerprint_" + market_symbol.lower()
            fingerprint = _auto_signal_fingerprint(market_symbol, candidate)
            previous = _get(db, user_id, fingerprint_key)
            db.commit()
            # Suppress refreshed/alternate-timeframe candidates while this
            # symbol already has an OPEN or PENDING trade.
            if created and _should_send_auto_signal(fingerprint, previous):
                msg = (
                    "QUANTNEX · AUTO SIGNAL · " + market_symbol + " " + candidate["side"] + "\n"
                    + "Market data: " + str(scan.get("provider", "Unknown")) + "\n"
                    + "Signal TF: " + str(candidate["timeframe"]) + "m · Trend TF: " + str(candidate["trend_timeframe"]) + "m\n"
                    + "TF alignment: " + ", ".join(
                        str(tf) + "m " + str(bias)
                        for tf, bias in (candidate.get("timeframe_alignment") or {}).items()
                    ) + "\n"
                    + "Entry type: " + str(candidate.get("entry_type", "REFERENCE")) + "\n"
                    + "Entry: " + (
                        "MARKET (" + str(candidate["entry"]) + ")"
                        if candidate.get("entry_type") == "MARKET"
                        else "LIMIT (" + str(candidate.get("limit_price") or candidate["entry"]) + ")"
                    )
                    + ("\nLimit price: " + str(candidate["limit_price"]) if candidate.get("entry_type") == "LIMIT" else "") + "\n"
                    + ("Entry expires: " + str(candidate["entry_expires_at"]) + "\n" if candidate.get("entry_expires_at") else "")
                    + "Entry logic: " + str(candidate.get("entry_selection_reason", "")) + "\n"
                    + (
                        "Spread: " + str(candidate["execution_quality"]["spread_bps"])
                        + " bps · estimated round-trip cost: "
                        + str(candidate["execution_quality"]["estimated_round_trip_cost_bps"]) + " bps\n"
                        if candidate.get("execution_quality") else ""
                    )
                    + "SL: " + str(candidate["stop_loss"]) + "\n"
                    + "TP1: " + str(candidate["tp1"]) + "\nTP2: " + str(candidate["tp2"]) + "\nTP3: " + str(candidate["tp3"]) + "\n"
                    + "Confluence: " + str(candidate["score"]) + "/10 (rule count, not win probability)\n"
                    + "Confirmations: " + ", ".join(candidate["confirmations"]) + "\n"
                    + "Signal only; verify spread, fees and execution. No order is placed."
                )
                delivered = await _deliver_auto_signal(
                    client, token, chat_id, msg, fingerprint, previous,
                    db, user_id, fingerprint_key,
                )
                if delivered:
                    db.commit()
        return _is_auto_signal_stream_pending(scan)
    except (MarketDataError, httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        # Provider exceptions can contain request URLs; never log query strings or API keys.
        logger.warning(
            "Auto-signal scan failed for local user %s market %s: %s",
            user_id, market_symbol, type(exc).__name__,
        )
        return None


async def _send(client, token: str, chat_id: str, text: str, reply_markup: dict | None = None):
    # Telegram shows its animated typing indicator while a reply is being prepared.
    try:
        await _telegram_post(client, token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
    except Exception:
        pass
    payload={"chat_id":chat_id,"text":_format_telegram_message(text),"parse_mode":"HTML","disable_web_page_preview":True}
    if reply_markup: payload["reply_markup"]=reply_markup
    return await _telegram_post(client,token,"sendMessage",payload)

async def _send_pdf(client, token: str, chat_id: str, pdf: bytes, filename: str, caption: str):
    try:
        await _telegram_post(client, token, "sendChatAction", {"chat_id": chat_id, "action": "upload_document"})
    except Exception:
        pass
    url=f"https://api.telegram.org/bot{token}/sendDocument"
    for attempt in range(3):
        response=await client.post(url,data={"chat_id":chat_id,"caption":_format_telegram_message(caption)[:1000],"parse_mode":"HTML"},
            files={"document":(filename,pdf,"application/pdf")})
        try: data=response.json()
        except ValueError: data={}
        if response.status_code == 429 and attempt < 2:
            await asyncio.sleep(max(1,min(10,int((data.get("parameters") or {}).get("retry_after",2)))))
            continue
        if response.status_code >= 500 and attempt < 2:
            await asyncio.sleep(2 ** attempt)
            continue
        response.raise_for_status()
        if not data.get("ok"):
            raise httpx.HTTPStatusError("Telegram rejected the PDF.",request=response.request,response=response)
        return data.get("result",{})
    raise RuntimeError("Telegram PDF retry limit reached.")

async def _send_photo(client, token: str, chat_id: str, photo: bytes, filename: str, caption: str):
    """Upload a generated branded gold report image to the user's connected Telegram chat."""
    url=f"https://api.telegram.org/bot{token}/sendPhoto"
    for attempt in range(3):
        response=await client.post(url,data={
            "chat_id":chat_id,
            "caption":_format_telegram_message(caption)[:1000],
            "parse_mode":"HTML",
        },files={"photo":(filename,photo,"image/jpeg")})
        try: data=response.json()
        except ValueError: data={}
        if response.status_code == 429 and attempt < 2:
            await asyncio.sleep(max(1,min(10,int((data.get("parameters") or {}).get("retry_after",2)))))
            continue
        if response.status_code >= 500 and attempt < 2:
            await asyncio.sleep(2 ** attempt)
            continue
        response.raise_for_status()
        if not data.get("ok"):
            raise httpx.HTTPStatusError("Telegram rejected the gold report image.",request=response.request,response=response)
        return data.get("result",{})
    raise RuntimeError("Telegram image retry limit reached.")


async def _deliver_gold_report(client, db, user_id: int, token: str, chat_id: str,
                               generated_at: datetime | None = None) -> dict:
    from .market_data import get_market_overview
    from .gold_reporting import (
        append_gold_snapshot, build_gold_report_image, find_24h_reference,
        gold_snapshot_from_overview,
    )
    now = generated_at or datetime.now(timezone.utc)
    overview = await get_market_overview()
    snapshot = gold_snapshot_from_overview(overview, now)
    history_raw = _get(db,user_id,"telegram_gold_price_history","[]")
    previous = find_24h_reference(history_raw,now)
    history = append_gold_snapshot(history_raw,snapshot)
    image = build_gold_report_image(snapshot,previous,now)
    local = now.astimezone(ZoneInfo("Asia/Colombo"))
    caption = ("🥇 QUANTNEX GOLD MARKET · "+local.strftime("%d %b %Y %I:%M %p")+" Sri Lanka Time"
        +"\n24K: LKR "+format(snapshot["24k_per_gram"],",.2f")+"/g"
        +" · 22K: LKR "+format(snapshot["22k_per_gram"],",.2f")+"/g"
        +"\n"+("24-hour comparison available." if previous else "24-hour comparison is building from saved price snapshots.")
        +"\nIndicative XAU/USD spot conversion, not a jeweller retail quote.")
    await _send_photo(client,token,chat_id,image,
                      "QUANTNEX-Gold-"+local.strftime("%Y%m%d-%H%M")+".jpg",caption)
    _set(db,user_id,"telegram_gold_price_history",history)
    db.commit()
    return {"snapshot":snapshot,"has_24h":previous is not None}


async def _send_png_photo(client, token: str, chat_id: str, photo: bytes, filename: str, caption: str):
    """Send a generated personal logo as a real PNG image."""
    try:
        await _telegram_post(client, token, "sendChatAction", {"chat_id": chat_id, "action": "upload_photo"})
    except Exception:
        pass
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    for attempt in range(3):
        response = await client.post(
            url,
            data={"chat_id": chat_id, "caption": _format_telegram_message(caption)[:1000], "parse_mode": "HTML"},
            files={"photo": (filename, photo, "image/png")},
        )
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code == 429 and attempt < 2:
            await asyncio.sleep(max(1, min(10, int((data.get("parameters") or {}).get("retry_after", 2)))))
            continue
        if response.status_code >= 500 and attempt < 2:
            await asyncio.sleep(2 ** attempt)
            continue
        response.raise_for_status()
        if not data.get("ok"):
            raise httpx.HTTPStatusError("Telegram rejected the personal logo image.", request=response.request, response=response)
        return data.get("result", {})
    raise RuntimeError("Telegram personal logo retry limit reached.")


async def _edit_message(client, token: str, chat_id: str, message_id: int, text: str, reply_markup: dict | None = None):
    payload={"chat_id":chat_id,"message_id":message_id,"text":_format_telegram_message(text),"parse_mode":"HTML"}
    if reply_markup is not None: payload["reply_markup"]=reply_markup
    return await _telegram_post(client,token,"editMessageText",payload)

async def _deliver_signal_performance_pdf(client, db, user_id: int, token: str, chat_id: str, period="daily", symbol=None):
    from .signal_reporting import build_signal_performance_pdf
    pdf, stats = build_signal_performance_pdf(db, user_id, period, symbol)
    label = period.title() + (" · " + symbol.upper() if symbol else "")
    caption = ("📈 QUANTNEX Signal Performance · " + label + "\\n"
        + "Resolved: " + str(stats["resolved"]) + " · Win rate: " + format(stats["win_rate"], ".2f") + "%\\n"
        + "W/L/BE: " + str(stats["wins"]) + "/" + str(stats["losses"]) + "/" + str(stats["breakeven"])
        + " · P&L: " + format(stats["realized_r"], "+.3f") + " R\\n"
        + "Open: " + str(stats["open"]) + " · Simulated signals, not broker fills.")
    filename = "QUANTNEX-Signal-Performance-" + period + ("-" + symbol.upper() if symbol else "") + ".pdf"
    await _send_pdf(client, token, chat_id, pdf, filename, caption)
    return stats


async def _deliver_daily_pdf(client, db, user_id: int, token: str, chat_id: str, report_day=None):
    from .telegram_reporting import build_daily_paper_pdf
    pdf, stats=build_daily_paper_pdf(db,user_id,report_day)
    caption=("📊 QUANTNEX Daily Paper Report · "+stats["date"]+"\n"
        +"Closed: "+str(stats["closed"])+" · Win rate: "+format(stats["win_rate"],".2f")+"%\n"
        +"Gross profit: $"+format(stats["gross_profit"],".2f")+" · Losses: $"+format(stats["total_loss"],".2f")+"\n"
        +"Recorded paper P&L: $"+format(stats["net"],".2f")+" · Open at cutoff: "+str(stats["open_at_cutoff"])+"\n"
        +"Profit factor: "+(stats["profit_factor"] is not None and str(stats["profit_factor"]) or "—")+" · simulated ledger only; costs may be excluded.")
    await _send_pdf(client,token,chat_id,pdf,"QUANTNEX-Paper-Report-"+stats["date"]+".pdf",caption)
    return stats

def _gold_report_slot(local_now: datetime) -> str | None:
    """Return a Colombo schedule slot only during its first ten minutes."""
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=ZoneInfo("Asia/Colombo"))
    local_now = local_now.astimezone(ZoneInfo("Asia/Colombo"))
    if local_now.hour in {0, 12} and local_now.minute < 10:
        return local_now.strftime("%Y-%m-%d-%H")
    return None



MARKET_SESSIONS = (
    ("sydney", "Sydney", "🇦🇺", "Australia/Sydney", 8, 17),
    ("asia", "Asia · Tokyo", "🌏", "Asia/Tokyo", 9, 18),
    ("london", "London", "🇬🇧", "Europe/London", 8, 17),
    ("new-york", "New York", "🇺🇸", "America/New_York", 8, 17),
)
COLOMBO = ZoneInfo("Asia/Colombo")


def _market_session_snapshot(now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """Return currently open FX sessions and their next close, using DST-aware local zones."""
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    result: dict[str, dict[str, Any]] = {}
    for session_id, name, flag, zone_name, open_hour, close_hour in MARKET_SESSIONS:
        local = instant.astimezone(ZoneInfo(zone_name))
        is_open = local.weekday() < 5 and open_hour <= local.hour < close_hour
        if not is_open:
            continue
        close_local = local.replace(hour=close_hour, minute=0, second=0, microsecond=0)
        close_utc = close_local.astimezone(timezone.utc)
        close_colombo = close_utc.astimezone(COLOMBO)
        result[session_id] = {
            "name": name,
            "flag": flag,
            "close_utc": close_utc,
            "close_colombo": close_colombo,
        }
    return result


def _market_session_open_ids(snapshot: dict[str, dict[str, Any]]) -> str:
    return ",".join(sorted(snapshot))


async def _notify_new_market_sessions(client, db, user_id: int, token: str, chat_id: str,
                                      now: datetime | None = None) -> list[str]:
    """Notify a connected user once when a major session opens; persist state to avoid duplicates."""
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    snapshot = _market_session_snapshot(instant)
    current_ids = _market_session_open_ids(snapshot)
    previous_raw = _get(db, user_id, "telegram_market_sessions_open", "")
    # First observation establishes a baseline; it must not send misleading startup alerts.
    if previous_raw == "":
        _set(db, user_id, "telegram_market_sessions_open", current_ids)
        db.commit()
        return []
    previous_ids = {item for item in previous_raw.split(",") if item}
    current_set = set(snapshot)
    newly_opened = [session_id for session_id in snapshot if session_id not in previous_ids]
    if not newly_opened:
        if previous_raw != current_ids:
            _set(db, user_id, "telegram_market_sessions_open", current_ids)
            db.commit()
        return []
    lines = []
    for session_id in newly_opened:
        item = snapshot[session_id]
        remaining = max(0, int((item["close_utc"] - instant.astimezone(timezone.utc)).total_seconds()))
        hours, remainder = divmod(remaining, 3600)
        minutes = remainder // 60
        countdown = (str(hours) + "h " if hours else "") + str(minutes) + "m"
        lines.append(
            item["flag"] + " <b>" + item["name"] + " SESSION OPENED</b>"
            + "\nCloses in: " + countdown
            + "\nExpected close (Sri Lanka): " + item["close_colombo"].strftime("%I:%M %p")
        )
    active_names = " + ".join(snapshot[key]["name"] for key in snapshot)
    message = (
        "🌍 <b>QUANTNEX · NEW MARKET SESSION</b>\n\n"
        + "\n\n".join(lines)
        + "\n\n<b>Currently running:</b> " + active_names
        + "\n🇱🇰 All times are Sri Lanka time. Session hours follow local DST rules."
    )
    try:
        await _send(client, token, chat_id, message)
    except Exception:
        db.rollback()
        logger.warning("Market-session Telegram alert deferred for local user %s", user_id)
        return []
    _set(db, user_id, "telegram_market_sessions_open", current_ids)
    db.commit()
    return newly_opened


def _paper_dashboard(db, user_id: int) -> str:
    rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user_id)))
    opened=[row for row in rows if str(row.status).upper()=="OPEN"]
    closed=[row for row in rows if str(row.status).upper()!="OPEN" and row.realized_pnl is not None]
    recorded=sum(float(row.realized_pnl or 0) for row in closed)
    return ("📊 QUANTNEX Paper Ledger\n"
        +"Open paper positions: "+str(len(opened))+"\n"
        +"Closed paper trades: "+str(len(closed))+"\n"
        +"Recorded realized P&L: "+format(recorded,".2f")+"\n"
        +"This is persisted paper-ledger data; it is not a live unrealized P&L snapshot or real-account balance.")


def _goal_dashboard(db, user_id: int) -> str:
    goals=list(db.scalars(select(PersonalGoal).where(PersonalGoal.user_id==user_id).order_by(PersonalGoal.created_at.desc())))
    if not goals:
        return "🎯 No personal goals yet. Add goals in the QUANTNEX website."
    lines=["🎯 QUANTNEX Personal Goals"]
    for goal in goals[:6]:
        contributions=float(db.scalar(select(func.coalesce(func.sum(GoalContribution.amount),0)).where(
            GoalContribution.goal_id==goal.id,GoalContribution.user_id==user_id)) or 0)
        saved=float(goal.initial_amount or 0)+contributions
        pct=min(100,saved/goal.target_amount*100) if goal.target_amount else 0
        lines.append(goal.title+" · "+format(pct,".1f")+"% · "+goal.currency+" "+format(saved,".2f")+"/"+format(goal.target_amount,".2f"))
    lines.append("Only user-confirmed manual real-account savings/profit are counted.")
    return "\n".join(lines)


def _risk_dashboard(db, user_id: int) -> str:
    try: settings=json.loads(_get(db,user_id,"signal_settings","{}"))
    except ValueError: settings={}
    try: auto=json.loads(_get(db,user_id,"auto_signal_settings","{}"))
    except ValueError: auto={}
    return ("🛡 Risk & Alert Settings\n"
        +"Signal risk setting: "+str(settings.get("risk_percent","not set"))+"%\n"
        +"Minimum confluence: "+str(settings.get("min_score","not set"))+"/10\n"
        +"Telegram Auto Signals: "+("ON" if auto.get("enabled") else "OFF")+"\n"
        +"These are alert settings, not guaranteed account-level risk controls.")


async def _price(_client: httpx.AsyncClient | None = None) -> float | None:
    """Return a fresh XAUUSD monitoring price from MT5 or Twelve Data.

    MT5 is preferred when enabled. A stale/unavailable MT5 tick falls back to
    Twelve Data when configured. Provider timestamps are checked before a
    price can trigger a Telegram TP/SL level notification.
    """
    if QUANTNEX_MT5_ENABLED:
        from .mt5_feed import get_quote as get_mt5_quote, MT5FeedError
        try:
            quote = await get_mt5_quote(QUANTNEX_MT5_GOLD_SYMBOL)
            age = float(quote.get("age_seconds"))
            if not quote.get("stale") and math.isfinite(age) and 0 <= age <= 30:
                bid, ask = float(quote["bid"]), float(quote["ask"])
                last = float(quote.get("last") or 0)
                price = last if last > 0 else (bid + ask) / 2
                if all(math.isfinite(value) and value > 0 for value in (bid, ask, price)) and ask >= bid:
                    return price
        except (MT5FeedError, ValueError, TypeError, KeyError, OverflowError):
            pass

    if not TWELVE_DATA_API_KEY:
        return None
    try:
        from .phase07_engine import get_quote as get_twelve_data_quote, IntelligenceDataError
        from .phase10_engine import assess_quote
        quote = await get_twelve_data_quote("XAUUSD")
        health = assess_quote(quote)
        if not health.get("trading_safe"):
            return None
        price = float(quote["price"])
        return price if math.isfinite(price) and price > 0 else None
    except (IntelligenceDataError, httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
        return None

async def _handle_command(client, db, user_id: int, token: str, chat_id: str, text: str, chat_type: str = "private") -> str | None:
    clean_text = text.strip()
    if clean_text and not clean_text.startswith("/"):
        if len(clean_text) > 3500:
            return "Please keep your question under 3,500 characters."
        try:
            # End the polling transaction before waiting on the external AI provider.
            db.commit()
            from .ai_assistant import ask_openai
            answer, _model = await ask_openai(db, user_id, clean_text)
            return answer[:3900]
        except RuntimeError:
            return "QUANTNEX AI is not configured yet. Add your OpenAI API key in QUANTNEX → Connections & Integrations. Do not send API keys in Telegram."
        except httpx.HTTPStatusError as exc:
            logger.warning("Telegram AI request rejected for local user %s: HTTP %s", user_id, exc.response.status_code)
            return "QUANTNEX AI could not complete that request. Check the OpenAI key, model access and API billing in Connections & Integrations."
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.warning("Telegram AI request failed for local user %s", user_id)
            return "QUANTNEX AI is temporarily unavailable. Please try again in a moment."
    parts=text.strip().split()
    command=parts[0].split("@")[0].lower() if parts else ""
    raw=_get(db,user_id,"signal_settings",'{"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":7}')
    try: settings=json.loads(raw)
    except ValueError: settings={"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":7}
    # Release the SQLite read snapshot before any provider/Telegram network wait.
    db.commit()
    names={"1":"M1","5":"M5","15":"M15","30":"M30","50":"M50","60":"H1","240":"H4"}
    if command == "/hidden_tools":
        # Private catalogue: deliberately omitted from /start, /help and all normal menus.
        categories = [
            ("Images", "Image inspection, photo-to-PDF, resize, crop, rotate, format conversion and compression"),
            ("PDF", "Extract embedded images, render pages, extract text, merge, split, rotate and compress"),
            ("Documents", "DOCX, TXT and Markdown conversion and extraction"),
            ("Spreadsheets", "XLSX/CSV preview, conversion, filtering, cleanup and summaries"),
            ("Files & Archives", "ZIP, safe extraction, checksums, duplicate detection and inventory"),
            ("Text & OCR", "OCR, encoding, cleanup, search, comparison and reports"),
            ("Audio", "Metadata, conversion, trim, normalize and transcription"),
            ("Video", "Metadata, thumbnails, frame extraction, trim and conversion"),
            ("Trading Utilities", "Position sizing, pip/tick value, risk/reward and journal reports"),
            ("System", "Health, version, redacted logs, backups and diagnostics"),
        ]
        if len(parts) > 1:
            requested = " ".join(parts[1:]).strip().lower()
            matches = [item for item in categories if requested in item[0].lower()]
            if not matches:
                return "Hidden Tools categories: " + ", ".join(item[0] for item in categories) + "\nUse /hidden_tools <category>."
            return ("🔐 HIDDEN TOOLS · " + matches[0][0].upper() + "\n" + matches[0][1]
                + "\n\n100-tool roadmap. First implementation targets: Photo → PDF and PDF → Images."
                + "\nCatalogue entries will be marked usable only after implementation and testing.")
        lines = ["🔐 HIDDEN TOOLS · PRIVATE CATALOGUE", "Private command accepted. This catalogue is not shown in the normal bot menus.", ""]
        lines.extend("• " + name + " — " + description for name, description in categories)
        lines.extend(["", "100 capability targets across 10 categories.", "First implementation targets: Photo → PDF and PDF → Images.",
                      "Use /hidden_tools <category> to inspect a category.",
                      "Note: this is the roadmap catalogue; tools are enabled only after implementation and testing."])
        return "\n".join(lines)
    if command in {"/start","/help"}:
        saved_name = _get(db, user_id, "telegram_user_name", "").strip()
        if command == "/start" and chat_type == "private" and not saved_name:
            _set(db, user_id, "telegram_onboarding_state", "awaiting_name")
            db.commit()
            return (
                "One small step before we open your workspace.\n"
                "What name should appear on your personal QUANTNEX logo?\n"
                "Type the name exactly as you want it displayed (2–32 characters)."
            )
        welcome_back = ("Welcome back, " + saved_name + "!\n\n") if command == "/start" and saved_name else ""
        return (
            welcome_back
            + "QUANTNEX · YOUR SMART TRADING COMPANION\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🌍 ENGLISH\n"
            "Welcome to QUANTNEX — a trading intelligence workspace built to help you study markets, analyse setups and manage your trading routine.\n\n"
            "✨ WHAT YOU CAN DO\n"
            "📈 Scan supported crypto markets and Gold (when its local data feed is configured).\n"
            "🧠 Review multi-timeframe signals, confirmations and Entry / SL / TP plans.\n"
            "🛡 Manage alert settings and monitor your paper-trading workspace.\n"
            "📊 View your paper ledger, daily PDF reports and personal goals.\n"
            "🥇 Get 22K/24K Sri Lankan Gold price images and schedule daily reports.\n"
            "🔐 Your workspace settings and personal records remain in your local QUANTNEX environment.\n\n"
            "🇱🇰 සිංහල\n"
            "QUANTNEX වෙත සාදරයෙන් පිළිගනිමු! මෙය වෙළඳපොළ අධ්‍යයනය, trade setups විශ්ලේෂණය සහ ඔබගේ trading routine එක කළමනාකරණය සඳහා නිර්මාණය කළ intelligent workspace එකකි.\n\n"
            "✨ ඔබට මෙයින් කළ හැක්කේ\n"
            "📈 සහාය දක්වන Crypto markets සහ Gold market scan කිරීම.\n"
            "🧠 Multi-timeframe signals, confirmations, Entry / SL / TP සැලසුම් බැලීම.\n"
            "🛡 Alerts සහ Paper Trading පාලනය කිරීම.\n"
            "📊 Paper ledger, Daily PDF reports සහ Personal Goals පරීක්ෂා කිරීම.\n"
            "🥇 22K/24K රන් මිලේ රූප ලබාගැනීම සහ දිනපතා වාර්තා සකස් කිරීම.\n"
            "🔐 ඔබගේ පුද්ගලික දත්ත සහ settings ඔබගේ local QUANTNEX workspace එකේම පවතී.\n\n"
            "⚠️ IMPORTANT · ආරක්ෂාව\n"
            "Signals are analysis only. Paper mode is simulated. No live broker orders are placed by this Telegram assistant. Always verify market data, spread and risk yourself.\n"
            "Signals යනු විශ්ලේෂණ තොරතුරු පමණයි. මෙය profit හෝ win-rate සහතිකයක් නොවේ.\n\n"
            "👇 TAP A BUTTON BELOW TO OPEN YOUR WORKSPACE\n"
            "👇 පහත Button එකක් තෝරාගෙන ආරම්භ කරන්න."
        )
    if command=="/timeframes":
        enabled=", ".join(names.get(str(x),str(x)) for x in settings.get("enabled",[]))
        return f"Primary: {names.get(str(settings.get('primary')))}\nTrend: {names.get(str(settings.get('trend')))}\nAnalysis: {enabled}"
    if command=="/settf" and len(parts)>1 and parts[1] in {"1","5","15","30","50","60"}:
        settings["primary"]=parts[1];_set(db,user_id,"signal_settings",json.dumps(settings));db.commit();_publish_signal_settings_changed()
        return "Primary signal timeframe set to "+names[parts[1]]+"."
    if command=="/settrend" and len(parts)>1 and parts[1] in {"15","30","60","240"}:
        settings["trend"]=parts[1];_set(db,user_id,"signal_settings",json.dumps(settings));db.commit();_publish_signal_settings_changed()
        return "Trend filter set to "+names[parts[1]]+"."
    if command=="/setanalysis" and len(parts)>1:
        selected=list(dict.fromkeys(x for x in parts[1].split(",") if x in {"1","5","15","30","50","60"}))
        if not selected:return "Use /setanalysis 1,5,15,30,60"
        settings["enabled"]=selected;_set(db,user_id,"signal_settings",json.dumps(settings));db.commit();_publish_signal_settings_changed()
        return "Analysis timeframes saved: "+", ".join(names[x] for x in selected)
    if command in {"/gold","/goldprice","/goldmarket"}:
        try:
            result=await _deliver_gold_report(client,db,user_id,token,chat_id)
            return ("🥇 QUANTNEX Gold report image sent."
                + (" 24-hour comparison included." if result["has_24h"] else " 24-hour comparison will appear after 24 hours of saved snapshots.")
                + "\\nUse /gold_setup to enable automatic reports at 00:00 and 12:00 Sri Lanka time.")
        except Exception as exc:
            logger.warning("Manual gold report failed for local user %s: %s",user_id,type(exc).__name__)
            return "Gold report unavailable. Check the XAU/USD and USD/LKR provider status, then try /gold again."
    if command in {"/gold_setup","/gold_on"}:
        _set(db,user_id,"telegram_gold_report_enabled","true")
        db.commit()
        try:
            result=await _deliver_gold_report(client,db,user_id,token,chat_id)
            return ("✅ QUANTNEX Daily Gold reports enabled for 00:00 and 12:00 Asia/Colombo."
                + ("\\n24-hour comparison included." if result["has_24h"] else "\\n24-hour comparison starts building now; it will appear once a 24-hour-old snapshot is available.")
                + "\\nUse /gold to request an image any time, or /gold_off to stop scheduled reports.")
        except Exception as exc:
            logger.warning("Gold setup first report failed for local user %s: %s",user_id,type(exc).__name__)
            return "Daily Gold reports are enabled, but the first image could not be sent. Use /gold to retry."
    if command=="/gold_off":
        _set(db,user_id,"telegram_gold_report_enabled","false");db.commit()
        return "QUANTNEX Daily Gold reports are now OFF. Use /gold_setup to enable them again."
    if command=="/gold_status":
        enabled=_get(db,user_id,"telegram_gold_report_enabled","false")=="true"
        return ("QUANTNEX Daily Gold reports: "+("ON" if enabled else "OFF")
            +"\\nSchedule: 00:00 and 12:00 Asia/Colombo."
            +"\\nCommands: /gold · /gold_setup · /gold_off")
    if command in {"/binance", "/binance_connect"}:
        return ("🔐 QUANTNEX · BINANCE DEMO SETUP\\n\\n"
            "Open QUANTNEX → Binance Exchange. Enter Spot Testnet and USD-M Futures Testnet API keys/secrets separately.\\n"
            "Never send API keys or secrets in Telegram chat. Use TESTNET keys only; disable withdrawals.\\n\\n"
            "🇱🇰 සිංහල\\n"
            "QUANTNEX → Binance Exchange පිටුවට ගොස් Spot Testnet සහ Futures Testnet API Key/Secret වෙන වෙනම ඇතුළත් කරන්න.\\n"
            "API keys හෝ secrets Telegram chat එකට එවන්න එපා. Testnet keys පමණක් භාවිතා කරන්න.\\n\\n"
            "Demo connections and risk limits are available. Signal-to-order execution is not enabled in this release; Auto Trading stays OFF.")
    if command=="/binance_status":
        spot=bool(_get(db,user_id,"binance_spot_api_key_enc") and _get(db,user_id,"binance_spot_api_secret_enc"))
        futures=bool(_get(db,user_id,"binance_futures_api_key_enc") and _get(db,user_id,"binance_futures_api_secret_enc"))
        return ("🔷 BINANCE TESTNET STATUS\\nSpot: "+("CONNECTED" if spot else "NOT CONNECTED")
            +"\\nUSD-M Futures: "+("CONNECTED" if futures else "NOT CONNECTED")
            +"\\nAuto Trading: OFF · Order execution disabled in this release."
            +"\\n\\n🇱🇰 සිංහල\\nSpot: "+("සම්බන්ධයි" if spot else "සම්බන්ධ නැහැ")
            +"\\nFutures: "+("සම්බන්ධයි" if futures else "සම්බන්ධ නැහැ")
            +"\\nස්වයංක්‍රීය ගනුදෙනු: අක්‍රියයි.")
    if command=="/binance_off":
        _set(db,user_id,"binance_auto_trading_enabled","false");db.commit()
        return "🛑 Binance Auto Trading: OFF.\\n🇱🇰 Binance ස්වයංක්‍රීය ගනුදෙනු අක්‍රිය කර ඇත. No orders are submitted."
    if command=="/ai_status":
        try:
            from .ai_assistant import get_openai_config
            api_key, model = get_openai_config(db, user_id)
            return "🧠 QUANTNEX AI: "+("CONNECTED" if api_key else "NOT CONFIGURED")+"\\nModel: "+model+"\\nWeb search: "+("ON" if _get(db,user_id,"openai_web_search_enabled","false")=="true" else "OFF")+"\\nAsk me any question by sending a normal text message. Add keys only in the local QUANTNEX Integrations page."
        except ValueError:
            return "QUANTNEX AI credentials need to be saved again. Check QUANTNEX_SECRET_KEY and reconnect the OpenAI integration."
    if command=="/status":
        return "QUANTNEX bot connected. Crypto feed: Binance Spot public candles with Coinbase fallback for BTC/ETH/SOL. Gold feed: "+(gold_feed_provider() or "not configured")+". Broker execution: disabled."
    if command == "/report":
        period = parts[1].lower() if len(parts) > 1 else "daily"
        symbol = parts[2].upper() if len(parts) > 2 else None
        if period not in {"daily","weekly","monthly","yearly","total"}:
            return "Use /report daily|weekly|monthly|yearly|total [BTCUSDT]."
        if symbol and (not symbol.isalnum() or len(symbol) < 5 or len(symbol) > 30):
            return "Use a valid symbol, e.g. /report weekly BTCUSDT."
        try:
            stats = await _deliver_signal_performance_pdf(client,db,user_id,token,chat_id,period,symbol)
            return "Signal report sent · "+str(stats["resolved"])+" resolved · "+format(stats["win_rate"],".2f")+"% win rate · "+format(stats["realized_r"],"+.3f")+" R."
        except Exception as exc:
            logger.warning("Signal report failed for local user %s: %s",user_id,type(exc).__name__)
            return "Could not generate the signal report. Check the signal ledger and backend logs."
    if command == "/report_on":
        _set(db,user_id,"telegram_signal_report_enabled","true");db.commit()
        return "Automatic signal PDF reports enabled for 21:00 Asia/Colombo. Use /report_off to stop."
    if command == "/report_off":
        _set(db,user_id,"telegram_signal_report_enabled","false");db.commit()
        return "Automatic signal PDF reports are OFF. Use /report_on to enable."
    if command=="/scan":
        market=parts[1].upper() if len(parts)>1 else "BTCUSDT"
        if market != "XAUUSD" and (not market.isalnum() or len(market) < 5 or len(market) > 30):
            return "Enter a valid Binance Spot pair symbol, for example /scan BTCUSDT, or /scan XAUUSD."
        if market=="XAUUSD" and not gold_feed_configured():
            return "XAUUSD feed is not configured. Enable the local MT5 feed or add TWELVE_DATA_API_KEY to backend/.env."
        try:
            result=await build_signal(settings,market)
            sig=result.get("signal")
            if not sig:
                if market=="XAUUSD":
                    _set(db,user_id,"active_signal","");db.commit()
                return "QUANTNEX · "+market+"\nMarket data: "+str(result.get("provider","Unknown"))+"\n"+str(result.get("message","WAIT — no qualifying setup."))+"\nScore: "+str(result["confluence_score"])+"/10\n"+result["score_note"]
            if market=="XAUUSD":
                _set(db,user_id,"active_signal",json.dumps({**sig,"tp1_notified":False,"tp2_notified":False,"tp3_notified":False,"sl_notified":False}))
                db.commit()
            return ("QUANTNEX · "+market+" "+sig["side"]+"\nMarket data: "+str(result.get("provider","Unknown"))+
                "\nEntry type: "+str(sig.get("entry_type","REFERENCE"))+"\nEntry: "+str(sig["entry"])+
                ("\nLimit price: "+str(sig["limit_price"]) if sig.get("entry_type")=="LIMIT" else "")+
                ("\nEntry expires: "+str(sig["entry_expires_at"]) if sig.get("entry_expires_at") else "")+
                "\nEntry logic: "+str(sig.get("entry_selection_reason",""))+
                ("\nSpread: "+str(sig["execution_quality"]["spread_bps"])+" bps · estimated round-trip cost: "+str(sig["execution_quality"]["estimated_round_trip_cost_bps"])+" bps" if sig.get("execution_quality") else "")+
                "\nSL: "+str(sig["stop_loss"])+
                "\nTP1: "+str(sig["tp1"])+"\nTP2: "+str(sig["tp2"])+"\nTP3: "+str(sig["tp3"])+
                "\nConfluence: "+str(sig["score"])+"/10 (rule count, not win probability)\n"
                +"TF alignment: "+", ".join(str(tf)+"m "+str(bias) for tf,bias in (sig.get("timeframe_alignment") or {}).items())+"\n"
                +"Confirmations: "+", ".join(sig["confirmations"])+
                "\nSignal only. Verify spread, fees and execution. No broker order is placed.")
        except MarketDataError as exc:return "Signal scan unavailable: "+str(exc)
        except Exception:return "Signal scan failed. Check the local API logs and market-data provider configuration."
    return "Please use the buttons below to explore QUANTNEX. Tap Help & guide if you need an overview."


def _signal_lifecycle_message(trade, event) -> str:
    symbol, side, entry, observed = trade.symbol, trade.side, trade.entry_price, event.price
    if event.event_type == "TP1_HIT":
        return (f"🎯 QUANTNEX · {symbol} {side} · TP1 REACHED\\nObserved price: {observed}\\nEntry: {entry} · TP1: {trade.tp1}\\n"
                "If your partial close is confirmed, consider securing 40% and moving the remaining SL to Entry (breakeven). "
                f"Keep the remaining 60% planned for TP2 {trade.tp2} and TP3 {trade.tp3}.\\n"
                "Level-touch alert only, not proof of broker execution. QUANTNEX does not place or modify broker orders.")
    if event.event_type == "TP2_HIT":
        return (f"🎯 QUANTNEX · {symbol} {side} · TP2 REACHED\\nObserved price: {observed}\\nTP1: {trade.tp1} · TP2: {trade.tp2} · TP3: {trade.tp3}\\n"
                "If earlier partials are confirmed, consider securing the planned 30% at TP2 and trailing remaining SL to TP1. "
                "The final planned 30% is for TP3.\\nLevel-touch alert only; verify broker fills manually.")
    if event.event_type == "TP3_HIT":
        return (f"🏁 QUANTNEX · {symbol} {side} · TP3 REACHED\\nObserved price: {observed}\\n"
                "All three planned targets were touched in the candle history. Review and confirm the final close with your broker; no order was executed.")
    if event.event_type == "SL_HIT":
        return (f"⚠️ QUANTNEX · {symbol} {side} · STOP LOSS LEVEL REACHED\\nObserved price: {observed} · SL: {trade.stop_loss}\\n"
                "The setup reached its original invalidation level before TP1. Verify the actual broker fill. No order was modified.")
    if event.event_type == "PROTECTED_STOP_HIT":
        return (f"🛡️ QUANTNEX · {symbol} {side} · BREAKEVEN PROTECTION REACHED\\nObserved price: {observed} · virtual SL: {trade.active_stop_loss}\\n"
                "TP1 was reached earlier. The remaining simulated portion returned to Entry; the TP1 partial remains in the outcome ledger. Not a real broker fill confirmation.")
    if event.event_type == "LOCKED_STOP_HIT":
        return (f"🛡️ QUANTNEX · {symbol} {side} · PROFIT-LOCK STOP REACHED\\nObserved price: {observed} · virtual SL: {trade.active_stop_loss}\\n"
                "TP1 and TP2 were reached earlier. The remaining simulated portion exited at the TP1 trailing level. Verify any real broker position manually.")
    if event.event_type == "AMBIGUOUS_BAR":
        return (f"ℹ️ QUANTNEX · {symbol} {side} · OUTCOME NEEDS REVIEW\\n"
                "One historical candle touched the active stop and the next target. OHLC data cannot prove which was first. QUANTNEX marked this AMBIGUOUS instead of guessing.")
    return ""


async def _deliver_pending_signal_events(client, db, user_id: int, token: str, chat_id: str) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
    pending = list(db.scalars(select(SignalTradeEvent).where(
        SignalTradeEvent.user_id == user_id, SignalTradeEvent.telegram_sent_at.is_(None),
        or_(SignalTradeEvent.telegram_last_attempt_at.is_(None),
            SignalTradeEvent.telegram_last_attempt_at <= cutoff),
    ).order_by(SignalTradeEvent.created_at).limit(20)))
    latest_by_trade = {}
    for queued in pending:
        latest_by_trade[queued.trade_id] = queued
    for event in pending:
        if latest_by_trade.get(event.trade_id) is not event:
            event.telegram_sent_at = datetime.now(timezone.utc)
            db.commit()
            continue
        trade = db.get(SignalTrade, event.trade_id)
        message = (
            _signal_lifecycle_message(trade, event)
            if trade is not None and trade.status != "SUPERSEDED" else ""
        )
        if not message:
            event.telegram_sent_at = datetime.now(timezone.utc)
            db.commit()
            continue
        delivery_key = "signal-event:" + str(event.id)
        if not _claim_telegram_delivery(db, user_id, delivery_key):
            continue
        event = db.get(SignalTradeEvent, event.id)
        if event is None or event.telegram_sent_at is not None:
            _finish_telegram_delivery(db, user_id, delivery_key, True)
            continue
        event.telegram_attempts = int(event.telegram_attempts or 0) + 1
        event.telegram_last_attempt_at = datetime.now(timezone.utc)
        db.commit()
        try:
            await _send(client, token, chat_id, message)
            event.telegram_sent_at = datetime.now(timezone.utc)
            db.commit()
            _finish_telegram_delivery(db, user_id, delivery_key, True)
        except Exception as exc:
            db.rollback()
            _finish_telegram_delivery(db, user_id, delivery_key, False)
            logger.warning("Signal outcome Telegram delivery deferred for local user %s: %s",
                           user_id, type(exc).__name__)


async def _deliver_source_update_notice(client, db, user_id: int, token: str, chat_id: str) -> bool:
    """Send each connected personal bot one notice for each successfully installed source SHA."""
    state_path = Path(__file__).resolve().parents[2] / "data" / "quantnex_update_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        confirmation_path = state_path.parent / "updates" / "source_update_confirmed.json"
        confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    commit_sha = str(state.get("commit_sha") or "").strip().lower()
    if confirmation.get("commit_sha") != commit_sha or not state.get("previous_commit_sha"):
        return False
    if len(commit_sha) != 40 or any(ch not in "0123456789abcdef" for ch in commit_sha):
        return False
    if _get(db, user_id, "telegram_last_source_update_sha", "") == commit_sha:
        return False

    repo = "adeeshadasuniduwara/QUANTNEX"
    commit_url = f"https://github.com/{repo}/commit/{commit_sha}"
    previous_sha = str(state.get("previous_commit_sha") or "").strip().lower()
    compare_url = ""
    if len(previous_sha) == 40 and all(ch in "0123456789abcdef" for ch in previous_sha):
        compare_url = f"https://github.com/{repo}/compare/{previous_sha}...{commit_sha}"

    if commit_sha in _SOURCE_UPDATE_PR_CACHE:
        pull_url = _SOURCE_UPDATE_PR_CACHE[commit_sha]
    else:
        pull_url = ""
        try:
            response = await client.get(
                f"https://api.github.com/repos/{repo}/commits/{commit_sha}/pulls",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "QUANTNEX-Telegram-Notifier"},
                params={"per_page": 10},
            )
            if response.status_code == 200:
                pull_requests = response.json()
                if isinstance(pull_requests, list):
                    merged = [item for item in pull_requests if item.get("merged_at") and item.get("html_url")]
                    candidates = merged or [item for item in pull_requests if item.get("html_url")]
                    if candidates:
                        pull_url = str(candidates[0]["html_url"])
                _SOURCE_UPDATE_PR_CACHE[commit_sha] = pull_url
            elif response.status_code in (403, 429, 500, 502, 503, 504):
                logger.warning("GitHub PR lookup deferred for local user %s (HTTP %s)", user_id, response.status_code)
                return False
            else:
                _SOURCE_UPDATE_PR_CACHE[commit_sha] = ""
        except (httpx.HTTPError, ValueError, TypeError):
            logger.warning("GitHub PR lookup deferred for local user %s", user_id)
            return False

    version = str(state.get("version") or ("main@" + commit_sha[:7]))
    message = (
        "🚀 <b>QUANTNEX SOURCE UPDATE INSTALLED</b>\\n\\n"
        + "<b>" + html.escape(version) + "</b>\\n"
        + "Your local QUANTNEX workspace has restarted with the latest verified source.\\n"
        + "Your local settings, wallet data and encrypted credentials remain on this computer.\\n\\n"
        + '<a href="' + commit_url + '">View installed commit</a>'
    )
    if compare_url:
        message += '\\n<a href="' + compare_url + '">Compare changes</a>'
    if pull_url:
        message += '\\n<a href="' + pull_url + '">View Pull Request</a>'
    else:
        message += '\\n<a href="https://github.com/' + repo + '/pulls">Open Pull Requests</a>'
    delivery_key = "client-notice:update-installed:main-" + commit_sha[:7]
    if not _claim_telegram_delivery(db, user_id, delivery_key):
        return False
    try:
        await _send(client, token, chat_id, message)
    except Exception as exc:
        _finish_telegram_delivery(db, user_id, delivery_key, False)
        logger.warning("Source update Telegram notice deferred for local user %s: %s",
                       user_id, type(exc).__name__)
        return False
    _set(db, user_id, "telegram_last_source_update_sha", commit_sha)
    db.commit()
    _finish_telegram_delivery(db, user_id, delivery_key, True)
    return True


async def telegram_worker() -> None:
    """Poll connected user bots, respond to commands and monitor active TP1 levels."""
    last_monitor={}
    last_daily_attempt={}
    async with httpx.AsyncClient(timeout=12) as client:
        while True:
            try:
                with SessionLocal() as db:
                    rows=list(db.scalars(select(Preference).where(Preference.key=="telegram_bot_token_enc")))
                    for token_row in rows:
                        user_id=token_row.user_id
                        chat_id=_get(db,user_id,"telegram_chat_id")
                        if not chat_id:continue
                        try:token=decrypt_secret(token_row.value)
                        except ValueError:continue
                        # This runs after the supervisor restarts the backend on a verified
                        # source update, so every locally connected personal bot gets its own notice.
                        await _deliver_source_update_notice(client, db, user_id, token, chat_id)
                        if _get(db,user_id,"telegram_commands_registered","")!="binance-demo-v1":
                            try:
                                await _telegram_post(client,token,"setMyCommands",{"commands":BOT_COMMANDS})
                                _set(db,user_id,"telegram_commands_registered","binance-demo-v1")
                                db.commit()
                            except Exception as command_error:
                                logger.warning("Telegram command registration failed for local user %s: %s",
                                               user_id,type(command_error).__name__)
                        offset=int(_get(db,user_id,"telegram_update_offset","0") or "0")
                        # Do not hold a SQLite read snapshot while waiting on Telegram.
                        db.commit()
                        try:
                            resp=await client.get(f"https://api.telegram.org/bot{token}/getUpdates",
                                params={"offset":offset,"timeout":0,"allowed_updates":'["message","channel_post","callback_query"]'})
                            data=resp.json()
                            if data.get("ok"):
                                for update in data.get("result",[]):
                                    offset=max(offset,int(update.get("update_id",0))+1)
                                    try:
                                        callback=update.get("callback_query")
                                        if callback:
                                            message=callback.get("message") or {}
                                            chat=message.get("chat") or {}
                                            if str(chat.get("id")) != str(chat_id): continue
                                            try:
                                                await _telegram_post(client,token,"answerCallbackQuery",{"callback_query_id":callback.get("id")})
                                            except Exception:
                                                pass
                                            action=str(callback.get("data",""))
                                            keyboard=MENU
                                            if action=="qx:menu:home":
                                                answer="QUANTNEX · MAIN WORKSPACE\nChoose a section below. Select a button to continue — no commands needed."
                                                keyboard=MENU
                                            elif action in SUBMENUS:
                                                keyboard=SUBMENUS[action]
                                                answer=MENU_TITLES[action]+"\nChoose an action below. No command typing required."
                                            elif action.startswith("qx:settf:"):
                                                raw_settings=_get(db,user_id,"signal_settings",'{"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":7}')
                                                try: settings=json.loads(raw_settings)
                                                except ValueError: settings={"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":7}
                                                names={"1":"M1","5":"M5","15":"M15","30":"M30","50":"M50","60":"H1","240":"H4"}
                                                value=action.split(":")[-1]
                                                if value in {"1","5","15","30","50","60"}:
                                                    settings["primary"]=value
                                                    _set(db,user_id,"signal_settings",json.dumps(settings));db.commit();_publish_signal_settings_changed()
                                                    answer="✅ Primary signal timeframe updated to "+names[value]+"."
                                                    keyboard=SUBMENUS["qx:menu:signals"]
                                                else:
                                                    answer="⚠️ Unsupported timeframe.";keyboard=SUBMENUS["qx:menu:signals"]
                                            elif action.startswith("qx:settrend:"):
                                                raw_settings=_get(db,user_id,"signal_settings",'{"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":7}')
                                                try: settings=json.loads(raw_settings)
                                                except ValueError: settings={"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":7}
                                                names={"1":"M1","5":"M5","15":"M15","30":"M30","50":"M50","60":"H1","240":"H4"}
                                                value=action.split(":")[-1]
                                                if value in {"15","30","60","240"}:
                                                    settings["trend"]=value
                                                    _set(db,user_id,"signal_settings",json.dumps(settings));db.commit();_publish_signal_settings_changed()
                                                    answer="✅ Trend timeframe updated to "+names[value]+"."
                                                    keyboard=SUBMENUS["qx:menu:signals"]
                                                else:
                                                    answer="⚠️ Unsupported trend timeframe.";keyboard=SUBMENUS["qx:menu:signals"]
                                            elif action=="qx:daily_toggle":
                                                enabled=_get(db,user_id,"telegram_daily_report_enabled","false")=="true"
                                                _set(db,user_id,"telegram_daily_report_enabled","false" if enabled else "true")
                                                db.commit()
                                                answer="🕗 Daily PDF at 20:00 Asia/Colombo is now "+("OFF" if enabled else "ON")+"."
                                            elif action=="qx:gold":
                                                try:
                                                    result=await _deliver_gold_report(client,db,user_id,token,chat_id)
                                                    answer="🥇 Gold market image sent."+(" 24-hour change included." if result["has_24h"] else " 24-hour history is building.")
                                                except Exception as exc:
                                                    logger.warning("Gold report button failed for local user %s: %s",user_id,type(exc).__name__)
                                                    answer="Gold report unavailable. Try again after checking market feeds."
                                            elif action=="qx:gold_setup":
                                                _set(db,user_id,"telegram_gold_report_enabled","true");db.commit()
                                                try:
                                                    result=await _deliver_gold_report(client,db,user_id,token,chat_id)
                                                    answer="✅ Daily Gold reports ON · 00:00 and 12:00 Sri Lanka time."+(" 24-hour change included." if result["has_24h"] else " 24-hour comparison is building.")
                                                except Exception as exc:
                                                    logger.warning("Gold report setup button failed for local user %s: %s",user_id,type(exc).__name__)
                                                    answer="Daily Gold reports enabled, but first image failed. Use /gold to retry."
                                            elif action=="qx:signal_report":
                                                try:
                                                    stats=await _deliver_signal_performance_pdf(client,db,user_id,token,chat_id,"daily")
                                                    answer="Signal report sent · "+str(stats["resolved"])+" resolved · "+format(stats["win_rate"],".2f")+"% win rate · "+format(stats["realized_r"],"+.3f")+" R"
                                                except Exception as exc:
                                                    logger.warning("Signal PDF button failed for local user %s: %s",user_id,type(exc).__name__)
                                                    answer="Could not generate the signal performance PDF."
                                            elif action=="qx:daily":
                                                try:
                                                    stats=await _deliver_daily_pdf(client,db,user_id,token,chat_id)
                                                    answer="📄 Today report sent · Closed "+str(stats["closed"])+" · Win rate "+format(stats["win_rate"],".2f")+"% · Net $"+format(stats["net"],".2f")
                                                except Exception as exc:
                                                    logger.warning("Daily PDF request failed for local user %s: %s",user_id,type(exc).__name__)
                                                    answer="Could not generate/send PDF. Check the PaperTrade ledger and Telegram connection."
                                            elif action.startswith("qx:scan:"): answer=await _handle_command(client,db,user_id,token,chat_id,"/scan "+action.split(":")[-1])
                                            elif action=="qx:status": answer=await _handle_command(client,db,user_id,token,chat_id,"/status")
                                            elif action=="qx:timeframes": answer=await _handle_command(client,db,user_id,token,chat_id,"/timeframes")
                                            elif action=="qx:home": answer=_paper_dashboard(db,user_id)
                                            elif action=="qx:paper":
                                                from .phase12_20_engine import DEFAULT_SETTINGS, normalize_settings
                                                try:
                                                    paper_settings=normalize_settings(json.loads(_get(db,user_id,"paper_autopilot_settings","{}")))
                                                except (ValueError,TypeError):
                                                    paper_settings=normalize_settings(DEFAULT_SETTINGS)
                                                answer=("🤖 QUANTNEX Paper Autopilot · "+("RUNNING" if paper_settings["enabled"] else "PAUSED")+
                                                    "\nMarkets: "+", ".join(paper_settings["symbols"])+
                                                    "\nRisk/trade: "+str(paper_settings["risk_percent"])+"% · Daily stop: "+str(paper_settings["max_daily_loss_percent"])+"%"+
                                                    "\nMode: LOCAL PAPER ONLY · no broker orders.")
                                            elif action in {"qx:paper_start","qx:paper_pause"}:
                                                from .phase12_20_engine import DEFAULT_SETTINGS, normalize_settings
                                                try:
                                                    paper_settings=json.loads(_get(db,user_id,"paper_autopilot_settings","{}")) or dict(DEFAULT_SETTINGS)
                                                    paper_settings["enabled"]=(action=="qx:paper_start")
                                                    paper_settings=normalize_settings(paper_settings)
                                                    _set(db,user_id,"paper_autopilot_settings",json.dumps(paper_settings))
                                                    db.commit()
                                                    answer=(("▶ Paper autopilot STARTED" if paper_settings["enabled"] else "⏸ Paper autopilot PAUSED")
                                                        + "\nLocal simulated trades only. No broker or real-money orders.")
                                                except (ValueError,TypeError) as exc:
                                                    answer="Cannot change paper mode: "+str(exc)
                                            elif action=="qx:goals": answer=_goal_dashboard(db,user_id)
                                            elif action=="qx:risk": answer=_risk_dashboard(db,user_id)
                                            elif action=="qx:market": answer=await _handle_command(client,db,user_id,token,chat_id,"/scan BTCUSDT")
                                            elif action=="qx:pause" or action=="qx:resume":
                                                try: auto_settings=json.loads(_get(db,user_id,"auto_signal_settings",'{"enabled":false,"interval_seconds":180,"symbols":["BTCUSDT","ETHUSDT","SOLUSDT"]}'))
                                                except ValueError: auto_settings={"enabled":False,"interval_seconds":180,"symbols":["BTCUSDT","ETHUSDT","SOLUSDT"]}
                                                auto_settings["enabled"]=(action=="qx:resume")
                                                _set(db,user_id,"auto_signal_settings",json.dumps(auto_settings));db.commit()
                                                answer="Telegram Auto Signals "+("RESUMED" if auto_settings["enabled"] else "PAUSED")+". This controls alerts only, not trading execution."
                                            elif action=="qx:help":
                                                answer="QUANTNEX HELP & QUICK GUIDE\\nUse the buttons to navigate Markets, Signals, Paper Desk, Reports and Settings.\\nChoose a market to scan, select signal timeframes, pause or resume alerts, review paper results and download a daily PDF.\\nNo slash commands are needed.\\n\\nSignals are analysis only. No live broker orders are placed."
                                                keyboard=MENU
                                            else: answer="📊 QUANTNEX local workspace · Signal alerts only. Paper simulation and broker execution are separate."
                                            try: await _edit_message(client,token,chat_id,int(message.get("message_id")),answer,keyboard)
                                            except Exception: await _send(client,token,chat_id,answer,MENU)
                                            continue
                                        message=update.get("message") or update.get("channel_post") or {}
                                        chat=message.get("chat") or {}
                                        if str(chat.get("id"))!=str(chat_id) and not (str(chat_id).startswith("@") and ("@"+str(chat.get("username","")).lower())==str(chat_id).lower()):continue
                                        command=message.get("text","")
                                        onboarding_state = _get(db, user_id, "telegram_onboarding_state", "")
                                        is_private_chat = str(chat.get("type") or "") == "private"
                                        if is_private_chat and onboarding_state == "awaiting_name" and command.strip():
                                            if command.strip().split()[0].split("@")[0].lower() == "/cancel":
                                                _set(db, user_id, "telegram_onboarding_state", "")
                                                db.commit()
                                                await _send(client, token, chat_id, "Logo setup cancelled. Send /start whenever you want to set it up.", MENU)
                                            elif command.strip().startswith("/"):
                                                await _send(client, token, chat_id, "Please type the name you want on your QUANTNEX logo, or send /cancel.")
                                            else:
                                                display_name = normalise_telegram_name(command)
                                                if display_name is None:
                                                    await _send(client, token, chat_id, "That name format is not valid. Please send 2–32 letters/numbers with spaces, dots, underscores, apostrophes or hyphens.")
                                                else:
                                                    try:
                                                        logo_png = build_personal_logo_png(display_name, user_id)
                                                        caption = (
                                                            "✨ Your personal QUANTNEX logo is ready, " + display_name + "!\n\n
                                                            + "To set it as your bot's profile photo:\n"
                                                            + "1. Open @BotFather\n"
                                                            + "2. Send /mybots and choose your bot\n"
                                                            + "3. Select Edit Bot → Edit Botpic\n"
                                                            + "4. Upload this square PNG image.\n\n"
                                                            + "You can keep this image and use it again any time."
                                                        )
                                                        await _send_png_photo(
                                                            client, token, chat_id, logo_png,
                                                            "QUANTNEX-" + str(user_id) + "-logo.png", caption,
                                                        )
                                                        _set(db, user_id, "telegram_user_name", display_name)
                                                        _set(db, user_id, "telegram_onboarding_state", "completed")
                                                        db.commit()
                                                        await _send(
                                                            client, token, chat_id,
                                                            "You're all set, " + display_name + "! Welcome to your QUANTNEX workspace.\nChoose a section below to get started.",
                                                            MENU,
                                                        )
                                                    except Exception as logo_error:
                                                        db.rollback()
                                                        logger.warning("Telegram personal logo setup failed for local user %s: %s", user_id, type(logo_error).__name__)
                                                        await _send(client, token, chat_id, "I couldn't create or send the logo just now. Please send your name again and I'll retry.")
                                            continue
                                        answer=await _handle_command(client,db,user_id,token,chat_id,command,chat_type=str(chat.get("type") or ""))
                                        if answer:
                                            is_start=command.strip().split(" ")[0].split("@")[0].lower() == "/start"
                                            is_help=command.strip().split(" ")[0].split("@")[0].lower() == "/help"
                                            if is_start and is_private_chat and _get(db, user_id, "telegram_onboarding_state", "") == "awaiting_name":
                                                await _send(client, token, chat_id,
                                                    "✨ Welcome to QUANTNEX!\nYour personal trading workspace is being prepared. Let's create a logo just for you.")
                                                await _send(client, token, chat_id, answer)
                                            else:
                                                is_plain_text=bool(command.strip()) and not command.strip().startswith("/")
                                                await _send(client,token,chat_id,answer,MENU if (is_start or is_help or is_plain_text) else None)
                                    except Exception as update_error:
                                        logger.warning("Telegram update %s failed for local user %s: %s",
                                                       update.get("update_id"), user_id, type(update_error).__name__)
                                    finally:
                                        # Consume each update exactly once, even if its reply fails.
                                        _persist_update_offset(db,user_id,offset)
                        except (httpx.HTTPError,ValueError) as exc:
                            logger.warning("Telegram polling failed for local user %s: %s",user_id,type(exc).__name__)
                        await _deliver_pending_signal_events(client, db, user_id, token, chat_id)
                        await _notify_new_market_sessions(client, db, user_id, token, chat_id)
                        now=asyncio.get_running_loop().time()
                        # Automatic signals rotate through the complete eligible Spot universe
                        # by default; a custom watchlist remains an explicit opt-in mode.
                        auto_raw = _get(
                            db, user_id, "auto_signal_settings",
                            '{"enabled":false,"interval_seconds":180,"universe_mode":"ALL_BINANCE_SPOT","scan_batch_size":20,"symbols":[]}',
                        )
                        db.commit()
                        auto_settings = _normalise_auto_signal_settings(auto_raw)
                        interval = auto_settings["interval_seconds"]
                        auto_key = (user_id, "auto")
                        selected = auto_settings["symbols"]
                        if auto_settings["enabled"] and now - last_monitor.get(auto_key, 0) >= interval:
                            if auto_settings["universe_mode"] == "ALL_BINANCE_SPOT":
                                try:
                                    scan_universe = await get_binance_spot_symbols()
                                except MarketDataError as exc:
                                    logger.warning(
                                        "Dynamic Binance Spot universe refresh failed for local user %s: %s",
                                        user_id, type(exc).__name__,
                                    )
                                    scan_universe = []
                                if "XAUUSD" in selected and gold_feed_configured():
                                    scan_universe = [*scan_universe, "XAUUSD"]
                            else:
                                scan_universe = list(selected)

                            if scan_universe:
                                signal_raw = _get(
                                    db, user_id, "signal_settings",
                                    '{"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":8}',
                                )
                                signal_settings = _normalise_signal_settings(signal_raw)
                                db.commit()

                                cursor = _get(db, user_id, "auto_signal_scan_cursor", "")
                                pending = _normalise_auto_signal_pending(
                                    _get(db, user_id, "auto_signal_pending_symbols", "[]"),
                                    scan_universe,
                                )
                                next_pending: dict[str, int] = {}

                                # Revisit bootstrapping streams before admitting new candidates.
                                # This keeps the manager's eight bounded slots from being evicted
                                # before their first sequence-validated snapshot becomes ready.
                                for market_symbol, attempts in pending.items():
                                    if market_symbol == "XAUUSD" and not gold_feed_configured():
                                        continue
                                    pending_result = await _scan_and_deliver_auto_signal(
                                        client, token, chat_id, db, user_id,
                                        signal_settings, market_symbol,
                                    )
                                    if pending_result is not False:
                                        if attempts < AUTO_SIGNAL_MAX_PENDING_RETRIES:
                                            next_pending[market_symbol] = attempts + 1
                                        else:
                                            logger.warning(
                                                "Order-flow stream warm-up retries exhausted for local user %s market %s",
                                                user_id, market_symbol,
                                            )
                                    await asyncio.sleep(0.1)

                                batch = _rotating_auto_signal_batch(
                                    scan_universe,
                                    cursor,
                                    auto_settings["scan_batch_size"],
                                    excluded=set(pending) | set(next_pending),
                                )
                                processed_cursor = cursor
                                if len(next_pending) < AUTO_SIGNAL_MAX_PENDING_STREAMS:
                                    for market_symbol in batch:
                                        if market_symbol == "XAUUSD" and not gold_feed_configured():
                                            processed_cursor = market_symbol
                                            continue
                                        pending_result = await _scan_and_deliver_auto_signal(
                                            client, token, chat_id, db, user_id,
                                            signal_settings, market_symbol,
                                        )
                                        processed_cursor = market_symbol
                                        if pending_result is True:
                                            next_pending[market_symbol] = 1
                                            if len(next_pending) >= AUTO_SIGNAL_MAX_PENDING_STREAMS:
                                                break
                                        await asyncio.sleep(0.1)

                                _set(db, user_id, "auto_signal_scan_cursor", processed_cursor)
                                _set(
                                    db, user_id, "auto_signal_pending_symbols",
                                    json.dumps([
                                        {"symbol": symbol, "attempts": attempts}
                                        for symbol, attempts in next_pending.items()
                                    ]),
                                )
                                db.commit()
                            else:
                                logger.warning(
                                    "Auto-signal universe is empty for local user %s; no market was scanned",
                                    user_id,
                                )
                            last_monitor[auto_key] = now
                        # Quiet five-coin background scan, independent of the active chart tab.
                        report_scan_key = (user_id, "report_universe")
                        if now - last_monitor.get(report_scan_key, 0) >= 180:
                            raw_watchlist = _get(db,user_id,"signal_report_watchlist","BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT")
                            watchlist = list(dict.fromkeys(x.strip().upper() for x in raw_watchlist.split(",")
                                if x.strip().isalnum() and 5 <= len(x.strip()) <= 30))[:5]
                            scan_raw = _get(db,user_id,"signal_settings",'{"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":8}')
                            scan_settings = _normalise_signal_settings(scan_raw)
                            db.commit()
                            for report_symbol in watchlist:
                                try:
                                    scan_result = await build_signal(scan_settings,report_symbol)
                                    candidate = scan_result.get("signal")
                                    if candidate:
                                        from .signal_lifecycle import record_signal
                                        record_signal(db,user_id,candidate,"BACKGROUND_REPORT_SCAN")
                                        db.commit()
                                except (MarketDataError,httpx.HTTPError,ValueError,TypeError,KeyError) as scan_error:
                                    logger.warning("Background report scan unavailable for %s: %s",report_symbol,type(scan_error).__name__)
                                await asyncio.sleep(0.05)
                            last_monitor[report_scan_key] = now
                        # Scheduled Gold images: two user-local snapshots per Colombo day.
                        if _get(db,user_id,"telegram_gold_report_enabled","false")=="true":
                            local_now=datetime.now(ZoneInfo("Asia/Colombo"))
                            slot=_gold_report_slot(local_now)
                            if slot:
                                sent_slot=_get(db,user_id,"telegram_gold_report_last_slot","")
                                if sent_slot!=slot and now-last_daily_attempt.get((user_id,"gold"),0)>=300:
                                    last_daily_attempt[(user_id,"gold")]=now
                                    try:
                                        await _deliver_gold_report(client,db,user_id,token,chat_id,local_now)
                                        _set(db,user_id,"telegram_gold_report_last_slot",slot)
                                        db.commit()
                                    except Exception as exc:
                                        logger.warning("Scheduled Gold image failed for local user %s: %s",user_id,type(exc).__name__)
                        # Optional daily PDF delivery, once per Colombo calendar day at/after 20:00.
                        if _get(db,user_id,"telegram_daily_report_enabled","false")=="true":
                            local_now=datetime.now(ZoneInfo("Asia/Colombo"))
                            sent_day=_get(db,user_id,"telegram_daily_report_sent_date","")
                            if local_now.hour>=20 and sent_day!=local_now.date().isoformat() and now-last_daily_attempt.get(user_id,0)>=300:
                                last_daily_attempt[user_id]=now
                                try:
                                    await _deliver_daily_pdf(client,db,user_id,token,chat_id,local_now.date())
                                    _set(db,user_id,"telegram_daily_report_sent_date",local_now.date().isoformat())
                                    db.commit()
                                except Exception as exc:
                                    logger.warning("Scheduled Telegram PDF failed for local user %s: %s",user_id,type(exc).__name__)
                        # Send the chart-signal PDF once per Colombo day at/after 21:00.
                        if _get(db,user_id,"telegram_signal_report_enabled","true") == "true":
                            local_now = datetime.now(ZoneInfo("Asia/Colombo"))
                            sent_day = _get(db,user_id,"telegram_signal_report_sent_date","")
                            if (local_now.hour >= 21 and sent_day != local_now.date().isoformat()
                                    and now - last_daily_attempt.get((user_id, "signal_report"), 0) >= 300):
                                last_daily_attempt[(user_id, "signal_report")] = now
                                try:
                                    stats = await _deliver_signal_performance_pdf(client,db,user_id,token,chat_id,"daily")
                                    _set(db,user_id,"telegram_signal_report_sent_date",local_now.date().isoformat())
                                    db.commit()
                                except Exception as report_error:
                                    logger.warning("Scheduled signal PDF failed for local user %s: %s",user_id,type(report_error).__name__)
                        last_monitor[user_id]=now
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Telegram worker cycle failed: %s",type(exc).__name__)
            await asyncio.sleep(8)

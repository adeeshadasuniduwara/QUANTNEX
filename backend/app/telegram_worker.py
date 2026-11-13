"""Background Telegram command and TP1 notification worker."""
from __future__ import annotations
import asyncio, json, logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any
import httpx
from sqlalchemy import select, func
from .database import SessionLocal
from .models import GoalContribution, PaperTrade, PersonalGoal, Preference
from .security import decrypt_secret
from .config import TWELVE_DATA_API_KEY
from .signal_engine import build_signal, MarketDataError
from .events import event_hub

logger = logging.getLogger("quantnex.telegram")

def _get(db, user_id: int, key: str, default: str="") -> str:
    row=db.scalar(select(Preference).where(Preference.user_id==user_id,Preference.key==key))
    return row.value if row else default

def _set(db, user_id: int, key: str, value: str) -> None:
    row=db.scalar(select(Preference).where(Preference.user_id==user_id,Preference.key==key))
    if row is None: db.add(Preference(user_id=user_id,key=key,value=value))
    else: row.value=value

def _publish_signal_settings_changed() -> None:
    event_hub.publish("preferences.changed","preferences","updated",{"key":"signal_settings"})

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
        [{"text":"📄 Today's PDF report","callback_data":"qx:daily"}],
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
    """Apply a consistent branded Telegram HTML design system to every outgoing text."""
    import html
    content = str(message or "").replace("\r\n", "\n").strip() or "No message content."
    lines = content.splitlines()
    rendered = []
    if "QUANTNEX" not in lines[0].upper():
        rendered.extend(["<b>✨ QUANTNEX</b>", ""])
    for index, line in enumerate(lines):
        safe = html.escape(line, quote=False)
        if not safe.strip():
            rendered.append("")
        elif index == 0:
            rendered.append("<b>✨ " + safe + "</b>" if "QUANTNEX" in line.upper() else "<b>" + safe + "</b>")
        elif (line.strip().isupper() and len(line.strip()) > 3) or line.strip().startswith(("📈", "🧠", "🛡", "🎯", "📊", "⚙", "🚀", "🏅", "🔒")):
            rendered.append("<b>" + safe + "</b>")
        else:
            rendered.append(safe)
    return "\n".join(rendered)[:3900]


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

async def _edit_message(client, token: str, chat_id: str, message_id: int, text: str, reply_markup: dict | None = None):
    payload={"chat_id":chat_id,"message_id":message_id,"text":_format_telegram_message(text),"parse_mode":"HTML"}
    if reply_markup is not None: payload["reply_markup"]=reply_markup
    return await _telegram_post(client,token,"editMessageText",payload)

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


async def _price(client: httpx.AsyncClient) -> float | None:
    if not TWELVE_DATA_API_KEY:return None
    response=await client.get("https://api.twelvedata.com/price",
        params={"symbol":"XAU/USD","apikey":TWELVE_DATA_API_KEY})
    data=response.json()
    try:return float(data["price"])
    except (KeyError,TypeError,ValueError):return None

async def _handle_command(client, db, user_id: int, token: str, chat_id: str, text: str) -> str | None:
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
        return (
            "QUANTNEX · YOUR SMART TRADING COMPANION\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🌍 ENGLISH\n"
            "Welcome to QUANTNEX — a trading intelligence workspace built to help you study markets, analyse setups and manage your trading routine.\n\n"
            "✨ WHAT YOU CAN DO\n"
            "📈 Scan supported crypto markets and Gold (when its local data feed is configured).\n"
            "🧠 Review multi-timeframe signals, confirmations and Entry / SL / TP plans.\n"
            "🛡 Manage alert settings and monitor your paper-trading workspace.\n"
            "📊 View your paper ledger, daily PDF reports and personal goals.\n"
            "🔐 Your workspace settings and personal records remain in your local QUANTNEX environment.\n\n"
            "🇱🇰 සිංහල\n"
            "QUANTNEX වෙත සාදරයෙන් පිළිගනිමු! මෙය වෙළඳපොළ අධ්‍යයනය, trade setups විශ්ලේෂණය සහ ඔබගේ trading routine එක කළමනාකරණය සඳහා නිර්මාණය කළ intelligent workspace එකකි.\n\n"
            "✨ ඔබට මෙයින් කළ හැක්කේ\n"
            "📈 සහාය දක්වන Crypto markets සහ Gold market scan කිරීම.\n"
            "🧠 Multi-timeframe signals, confirmations, Entry / SL / TP සැලසුම් බැලීම.\n"
            "🛡 Alerts සහ Paper Trading පාලනය කිරීම.\n"
            "📊 Paper ledger, Daily PDF reports සහ Personal Goals පරීක්ෂා කිරීම.\n"
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
    if command=="/status":
        return "QUANTNEX bot connected. Crypto feed: Binance Spot public data ready. Gold feed: "+("configured" if TWELVE_DATA_API_KEY else "not configured")+". Broker execution: disabled."
    if command=="/scan":
        market=parts[1].upper() if len(parts)>1 else "BTCUSDT"
        if market not in {"BTCUSDT","ETHUSDT","SOLUSDT","XAUUSD"}:
            return "Choose /scan BTCUSDT, /scan ETHUSDT, /scan SOLUSDT or /scan XAUUSD."
        if market=="XAUUSD" and not TWELVE_DATA_API_KEY:
            return "XAUUSD feed is not configured. Crypto scans work with Binance public data and need no API key."
        try:
            result=await build_signal(settings,market)
            sig=result.get("signal")
            if not sig:
                if market=="XAUUSD":
                    _set(db,user_id,"active_signal","");db.commit()
                return "QUANTNEX · "+market+"\nWAIT — no setup reached the minimum confluence threshold.\nScore: "+str(result["confluence_score"])+"/10\n"+result["score_note"]
            if market=="XAUUSD":
                _set(db,user_id,"active_signal",json.dumps({**sig,"tp1_notified":False,"tp2_notified":False,"tp3_notified":False,"sl_notified":False}))
                db.commit()
            return ("QUANTNEX · "+market+" "+sig["side"]+"\nEntry: "+str(sig["entry"])+"\nSL: "+str(sig["stop_loss"])+
                "\nTP1: "+str(sig["tp1"])+"\nTP2: "+str(sig["tp2"])+"\nTP3: "+str(sig["tp3"])+
                "\nConfluence: "+str(sig["score"])+"/10 (rule count, not win probability)\nConfirmations: "+", ".join(sig["confirmations"])+
                "\nSignal only. Verify spread, fees and execution. No broker order is placed.")
        except MarketDataError as exc:return "Signal scan unavailable: "+str(exc)
        except Exception:return "Signal scan failed. Check the local API logs and market-data provider configuration."
    return "Please use the buttons below to explore QUANTNEX. Tap Help & guide if you need an overview."

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
                                        answer=await _handle_command(client,db,user_id,token,chat_id,command)
                                        if answer:
                                            is_start=command.strip().split(" ")[0].split("@")[0].lower() in {"/start","/help"}
                                            is_plain_text=bool(command.strip()) and not command.strip().startswith("/")
                                            await _send(client,token,chat_id,answer,MENU if (is_start or is_plain_text) else None)
                                    except Exception as update_error:
                                        logger.warning("Telegram update %s failed for local user %s: %s",
                                                       update.get("update_id"), user_id, type(update_error).__name__)
                                    finally:
                                        # Consume each update exactly once, even if its reply fails.
                                        _set(db,user_id,"telegram_update_offset",str(offset));db.commit()
                        except (httpx.HTTPError,ValueError) as exc:
                            logger.warning("Telegram polling failed for local user %s: %s",user_id,type(exc).__name__)
                        now=asyncio.get_running_loop().time()
                        if now-last_monitor.get(user_id,0)>=60:
                            active_raw=_get(db,user_id,"active_signal")
                            db.commit()
                            if active_raw and TWELVE_DATA_API_KEY:
                                try:
                                    active=json.loads(active_raw);price=await _price(client)
                                    if price is not None:
                                        side=active.get("side")
                                        hit_sl=price<=active["stop_loss"] if side=="BUY" else price>=active["stop_loss"]
                                        hit_tp1=price>=active["tp1"] if side=="BUY" else price<=active["tp1"]
                                        hit_tp2=price>=active["tp2"] if side=="BUY" else price<=active["tp2"]
                                        hit_tp3=price>=active["tp3"] if side=="BUY" else price<=active["tp3"]
                                        if hit_sl and not active.get("sl_notified") and not active.get("tp1_notified"):
                                            await _send(client,token,chat_id,f"⚠️ QUANTNEX · XAUUSD SL level touched\nObserved price: {price}\nCheck your broker execution. No order was modified.")
                                            active["sl_notified"]=True;active_raw=""
                                        elif hit_tp1 and not active.get("tp1_notified"):
                                            await _send(client,token,chat_id,f"⚠️ QUANTNEX · XAUUSD TP1 level touched\nObserved price: {price}\nReview moving Stop Loss to breakeven (Entry {active['entry']}). Verify the actual position and move SL manually in your broker. QUANTNEX does not modify broker orders.")
                                            active["tp1_notified"]=True
                                        if hit_tp2 and not active.get("tp2_notified"):
                                            await _send(client,token,chat_id,f"QUANTNEX · XAUUSD TP2 level touched at {price}. Check broker execution.")
                                            active["tp2_notified"]=True
                                        if hit_tp3 and not active.get("tp3_notified"):
                                            await _send(client,token,chat_id,f"QUANTNEX · XAUUSD TP3 level touched at {price}. Review and manage your position manually.")
                                            active["tp3_notified"]=True;active_raw=""
                                        if active_raw:_set(db,user_id,"active_signal",json.dumps(active))
                                        else:_set(db,user_id,"active_signal","")
                                        db.commit()
                                except (ValueError,KeyError,httpx.HTTPError) as exc:
                                    logger.warning("Gold level monitor failed for local user %s: %s",user_id,type(exc).__name__)
                        # Automatic signals scan each selected market independently.
                        auto_raw=_get(db,user_id,"auto_signal_settings",'{"enabled":false,"interval_seconds":180,"symbols":["BTCUSDT","ETHUSDT","SOLUSDT"]}')
                        db.commit()
                        try: auto_settings=json.loads(auto_raw)
                        except ValueError: auto_settings={"enabled":False,"interval_seconds":180,"symbols":["BTCUSDT","ETHUSDT","SOLUSDT"]}
                        interval=max(60,min(3600,int(auto_settings.get("interval_seconds",180) or 180)))
                        auto_key=(user_id,"auto")
                        selected=list(dict.fromkeys(str(value).upper() for value in auto_settings.get("symbols",["BTCUSDT","ETHUSDT","SOLUSDT"])
                            if str(value).upper() in {"BTCUSDT","ETHUSDT","SOLUSDT","XAUUSD"}))
                        if auto_settings.get("enabled") and selected and now-last_monitor.get(auto_key,0)>=interval:
                            signal_raw=_get(db,user_id,"signal_settings",'{"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":8}')
                            try: signal_settings=json.loads(signal_raw)
                            except ValueError: signal_settings={"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":8}
                            signal_settings["min_score"]=max(8,int(signal_settings.get("min_score",8)))
                            db.commit()
                            for market_symbol in selected:
                                if market_symbol=="XAUUSD" and not TWELVE_DATA_API_KEY:
                                    continue
                                fingerprint_key="auto_signal_last_fingerprint_"+market_symbol.lower()
                                try:
                                    scan=await build_signal(signal_settings,market_symbol)
                                    candidate=scan.get("signal")
                                    if candidate:
                                        fingerprint="|".join([market_symbol,str(candidate.get("side")),str(candidate.get("timeframe")),str(candidate.get("signal_candle_time"))])
                                        previous=_get(db,user_id,fingerprint_key)
                                        db.commit()
                                        if fingerprint and fingerprint!=previous:
                                            msg=("QUANTNEX · AUTO SIGNAL · "+market_symbol+" "+candidate["side"]+"\n"
                                                +"Signal TF: "+str(candidate["timeframe"])+"m · Trend TF: "+str(candidate["trend_timeframe"])+"m\n"
                                                +"Entry: "+str(candidate["entry"])+"\nSL: "+str(candidate["stop_loss"])+"\n"
                                                +"TP1: "+str(candidate["tp1"])+"\nTP2: "+str(candidate["tp2"])+"\nTP3: "+str(candidate["tp3"])+"\n"
                                                +"Confluence: "+str(candidate["score"])+"/10 (rule count, not win probability)\n"
                                                +"Confirmations: "+", ".join(candidate["confirmations"])+"\n"
                                                +"Signal only; verify spread, fees and execution. No order is placed.")
                                            await _send(client,token,chat_id,msg)
                                            _set(db,user_id,fingerprint_key,fingerprint)
                                            if market_symbol=="XAUUSD":
                                                _set(db,user_id,"active_signal",json.dumps({**candidate,"tp1_notified":False,"tp2_notified":False,"tp3_notified":False,"sl_notified":False}))
                                            db.commit()
                                    # Keep the last delivered fingerprint when no setup is present.
                                    # This prevents duplicate alerts if the same candle briefly loses and regains confluence.
                                except (MarketDataError,httpx.HTTPError,ValueError,KeyError) as exc:
                                    # Provider exceptions can contain request URLs; never log query strings or API keys.
                                    logger.warning("Auto-signal scan failed for local user %s market %s: %s",
                                                   user_id,market_symbol,type(exc).__name__)
                            last_monitor[auto_key]=now
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
                        last_monitor[user_id]=now
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Telegram worker cycle failed: %s",type(exc).__name__)
            await asyncio.sleep(8)

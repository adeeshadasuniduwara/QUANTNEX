"""Binance Spot Demo-only autonomous execution engine.

Orders are sent only to Binance's documented Demo Trading REST host. The worker
uses exchange-native OCO exits so protective orders remain at Binance if the
local QUANTNEX process stops. Live endpoints are never configured or selected.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from urllib.parse import urlencode
from typing import Any

import httpx
from sqlalchemy import select

from .database import SessionLocal
from .models import Preference, User
from .security import decrypt_secret

logger = logging.getLogger("quantnex.binance_spot")
SPOT_DEMO_BASE = "https://demo-api.binance.com"
WORKER_STATE: dict[str, Any] = {"running": False, "last_cycle": None, "last_error": None}
DEFAULT_CONFIG = {
    "enabled": False,
    "environment": "BINANCE_DEMO",
    "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "interval_seconds": 30,
    "min_score": 8,
    "risk_per_trade_percent": 0.5,
    "max_open_trades": 1,
    "max_trades_per_day": 3,
    "max_daily_loss_percent": 2.0,
    "max_spread_bps": 12.0,
    "min_24h_quote_volume": 10000000,
    "min_reward_risk": 1.5,
    "dca_enabled": False,
}


def _pref(db, user_id: int, key: str, default: str = "") -> str:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == key))
    return row.value if row else default


def _set_pref(db, user_id: int, key: str, value: str) -> None:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == key))
    if row is None:
        db.add(Preference(user_id=user_id, key=key, value=value))
    else:
        row.value = value


def normalize_config(raw: str | dict | None = None) -> dict:
    try:
        value = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    config = {**DEFAULT_CONFIG, **value}
    config["environment"] = "BINANCE_DEMO"
    config["enabled"] = bool(config.get("enabled"))
    config["dca_enabled"] = False
    config["symbols"] = list(dict.fromkeys(
        str(s).strip().upper() for s in config.get("symbols", [])
        if str(s).strip().isalnum() and str(s).strip().upper().endswith("USDT")
    ))[:30]
    config["interval_seconds"] = max(15, min(300, int(config.get("interval_seconds", 30))))
    config["min_score"] = max(4, min(20, int(config.get("min_score", 8))))
    config["risk_per_trade_percent"] = max(0.05, min(1.0, float(config.get("risk_per_trade_percent", 0.5))))
    config["max_open_trades"] = max(1, min(3, int(config.get("max_open_trades", 1))))
    config["max_trades_per_day"] = max(1, min(10, int(config.get("max_trades_per_day", 3))))
    config["max_daily_loss_percent"] = max(0.25, min(2.0, float(config.get("max_daily_loss_percent", 2))))
    config["max_spread_bps"] = max(1, min(50, float(config.get("max_spread_bps", 12))))
    config["min_24h_quote_volume"] = max(100000, float(config.get("min_24h_quote_volume", 10000000)))
    config["min_reward_risk"] = max(1.5, min(5.0, float(config.get("min_reward_risk", 1.5))))
    return config


def _signed_query(secret: str, params: dict) -> str:
    values = {k: str(v) for k, v in params.items() if v is not None}
    values.setdefault("recvWindow", "5000")
    values["timestamp"] = str(int(time.time() * 1000))
    query = urlencode(values)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + signature


async def _request(method: str, path: str, params: dict | None = None,
                   api_key: str | None = None, secret: str | None = None) -> Any:
    url = SPOT_DEMO_BASE + "/api" + path
    headers = {}
    if api_key and secret:
        headers["X-MBX-APIKEY"] = api_key
        url += "?" + _signed_query(secret, params or {})
    elif params:
        url += "?" + urlencode({k: str(v) for k, v in params.items()})
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5)) as client:
            response = await client.request(method, url, headers=headers)
    except httpx.TimeoutException:
        raise RuntimeError("Binance Demo request timed out; order status must be reconciled before retrying.") from None
    except httpx.HTTPError:
        raise RuntimeError("Binance Demo network request failed.") from None
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400:
        code = payload.get("code") if isinstance(payload, dict) else None
        message = payload.get("msg") if isinstance(payload, dict) else None
        if response.status_code in (418, 429):
            raise RuntimeError("Binance Demo rate limit reached; the engine will back off.")
        raise RuntimeError(("Binance Demo error " + str(code) + ": " if code is not None else "")
                           + str(message or "request rejected")[:180])
    return payload


def _credentials(db, user_id: int) -> tuple[str, str]:
    key = _pref(db, user_id, "binance_spot_api_key_enc")
    secret = _pref(db, user_id, "binance_spot_api_secret_enc")
    if not key or not secret:
        raise RuntimeError("Binance Spot Demo credentials are not connected.")
    return decrypt_secret(key), decrypt_secret(secret)


def _filters(info: dict) -> dict:
    return {x.get("filterType"): x for x in info.get("filters", [])}


def _floor_step(value: float, step: str) -> Decimal:
    step_d = Decimal(str(step))
    if step_d <= 0:
        raise ValueError("Invalid Binance step size.")
    amount = Decimal(str(value))
    return (amount / step_d).to_integral_value(rounding=ROUND_DOWN) * step_d


def _round_price(value: float, tick: str, rounding=ROUND_DOWN) -> Decimal:
    tick_d = Decimal(str(tick))
    if tick_d <= 0:
        raise ValueError("Invalid Binance tick size.")
    amount = Decimal(str(value))
    return (amount / tick_d).to_integral_value(rounding=rounding) * tick_d


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


async def _account(api_key: str, secret: str) -> dict:
    data = await _request("GET", "/v3/account", {"omitZeroBalances": "true"}, api_key, secret)
    if not isinstance(data, dict) or data.get("canTrade") is not True:
        raise RuntimeError("Binance Spot Demo key is not permitted to trade. Enable Spot trading permission in Demo API management.")
    return data


async def _symbol_info(symbol: str) -> dict:
    data = await _request("GET", "/v3/exchangeInfo", {"symbol": symbol})
    rows = data.get("symbols", []) if isinstance(data, dict) else []
    if not rows:
        raise RuntimeError("Binance Demo does not list this symbol.")
    info = rows[0]
    if info.get("status") != "TRADING" or info.get("quoteAsset") != "USDT" or info.get("isSpotTradingAllowed") is False:
        raise RuntimeError("Symbol is not an eligible Binance Spot USDT market.")
    return info


async def _ticker(symbol: str) -> tuple[float, float, float]:
    price_data, book, stats = await asyncio.gather(
        _request("GET", "/v3/ticker/price", {"symbol": symbol}),
        _request("GET", "/v3/ticker/bookTicker", {"symbol": symbol}),
        _request("GET", "/v3/ticker/24hr", {"symbol": symbol}),
    )
    price = float(price_data["price"])
    bid, ask = float(book["bidPrice"]), float(book["askPrice"])
    volume = float(stats["quoteVolume"])
    if not all(math.isfinite(x) and x > 0 for x in (price, bid, ask, volume)) or ask < bid:
        raise RuntimeError("Binance returned an invalid market quote.")
    spread_bps = ((ask - bid) / ((ask + bid) / 2)) * 10000
    return price, spread_bps, volume


async def _market_buy(symbol: str, quote_amount: float, client_id: str, api_key: str, secret: str) -> dict:
    return await _request("POST", "/v3/order", {
        "symbol": symbol, "side": "BUY", "type": "MARKET",
        "quoteOrderQty": f"{quote_amount:.8f}", "newClientOrderId": client_id,
        "newOrderRespType": "FULL",
    }, api_key, secret)


async def _query_order(symbol: str, client_id: str, api_key: str, secret: str) -> dict:
    return await _request("GET", "/v3/order", {"symbol": symbol, "origClientOrderId": client_id}, api_key, secret)


async def _place_oco(symbol: str, quantity: Decimal, stop: Decimal, target: Decimal,
                     tick: str, client_id: str, api_key: str, secret: str) -> dict:
    # SELL-side OCO: take-profit limit above market and stop-loss limit below market.
    tp_stop = _round_price(float(target), tick, ROUND_UP)
    tp_limit = _round_price(float(target) * 0.9995, tick, ROUND_DOWN)
    sl_stop = _round_price(float(stop), tick, ROUND_DOWN)
    sl_limit = _round_price(float(stop) * 0.999, tick, ROUND_DOWN)
    return await _request("POST", "/v3/orderList/oco", {
        "symbol": symbol, "side": "SELL", "quantity": _decimal_text(quantity),
        "listClientOrderId": client_id,
        "aboveType": "TAKE_PROFIT_LIMIT", "abovePrice": _decimal_text(tp_limit),
        "aboveStopPrice": _decimal_text(tp_stop), "aboveTimeInForce": "GTC",
        "belowType": "STOP_LOSS_LIMIT", "belowStopPrice": _decimal_text(sl_stop),
        "belowPrice": _decimal_text(sl_limit), "belowTimeInForce": "GTC",
        "newOrderRespType": "RESULT",
    }, api_key, secret)


async def _emergency_sell(symbol: str, quantity: Decimal, api_key: str, secret: str) -> dict:
    return await _request("POST", "/v3/order", {
        "symbol": symbol, "side": "SELL", "type": "MARKET",
        "quantity": _decimal_text(quantity), "newOrderRespType": "FULL",
    }, api_key, secret)


async def _notify(db, user_id: int, message: str) -> None:
    token_enc = _pref(db, user_id, "telegram_bot_token_enc")
    chat_id = _pref(db, user_id, "telegram_chat_id")
    if not token_enc or not chat_id:
        return
    try:
        token = decrypt_secret(token_enc)
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
                "chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True,
            })
    except Exception as exc:
        logger.warning("Spot trade Telegram notification failed: %s", type(exc).__name__)


async def _scan_user(db, user: User) -> None:
    raw = _pref(db, user.id, "binance_spot_auto_config", "")
    config = normalize_config(raw)
    if not config["enabled"] or _pref(db, user.id, "binance_auto_trading_enabled") != "true":
        return
    api_key, secret = _credentials(db, user.id)
    account = await _account(api_key, secret)
    balances = {x["asset"]: float(x["free"]) for x in account.get("balances", [])}
    free_usdt = balances.get("USDT", 0.0)
    if not math.isfinite(free_usdt) or free_usdt <= 0:
        return
    try:
        active = json.loads(_pref(db, user.id, "binance_spot_active_trades", "[]"))
        history = json.loads(_pref(db, user.id, "binance_spot_trade_history", "[]"))
    except (TypeError, ValueError):
        active, history = [], []
    if not isinstance(active, list): active = []
    if not isinstance(history, list): history = []
    pending_order = _pref(db, user.id, "binance_spot_pending_order", "")
    if pending_order:
        # A restart occurred during the non-atomic BUY -> OCO hand-off. Fail
        # closed and require a human to inspect Binance before automation resumes.
        _set_pref(db, user.id, "binance_auto_trading_enabled", "false")
        config["enabled"] = False
        _set_pref(db, user.id, "binance_spot_auto_config", json.dumps(config, separators=(",", ":")))
        db.commit()
        await _notify(db, user.id, "🚨 <b>QUANTNEX SPOT DEMO — RESTART RECOVERY REQUIRED</b>\\nAn order hand-off was interrupted. Auto Trading has been stopped. Inspect Binance Spot Demo open orders and balances before restarting.")
        return
    today = datetime.now(timezone.utc).date().isoformat()
    daily = [x for x in history if str(x.get("created_at", "")).startswith(today)]
    if len(daily) >= config["max_trades_per_day"]:
        return
    daily_pnl = sum(float(x.get("realized_pnl", 0) or 0) for x in history
                    if str(x.get("closed_at", "")).startswith(today))
    try:
        daily_guard = json.loads(_pref(db, user.id, "binance_spot_daily_guard", "{}"))
    except (TypeError, ValueError):
        daily_guard = {}
    if daily_guard.get("date") != today:
        daily_guard = {"date": today, "starting_equity": free_usdt + sum(
            float(x.get("entry_quote", 0) or 0) for x in active)}
        _set_pref(db, user.id, "binance_spot_daily_guard", json.dumps(daily_guard, separators=(",", ":")))
        db.commit()
    starting_equity = max(0.0, float(daily_guard.get("starting_equity", free_usdt) or free_usdt))
    daily_loss_limit = starting_equity * config["max_daily_loss_percent"] / 100
    open_stop_risk = sum(max(0.0, float(x.get("entry_price", 0)) - float(x.get("stop_loss", 0)))
                         * float(x.get("quantity", 0)) for x in active)
    if daily_pnl - open_stop_risk <= -daily_loss_limit:
        return

    # Reconcile exchange-native OCO lists before considering any new entry.
    remaining = []
    for trade in active:
        try:
            listing = await _request("GET", "/v3/orderList", {
                "origClientOrderId": trade["oco_client_id"]}, api_key, secret)
            if listing.get("listOrderStatus") == "ALL_DONE":
                trade["status"] = "CLOSED"
                trade["closed_at"] = datetime.now(timezone.utc).isoformat()
                orders = listing.get("orders", [])
                exit_quote = 0.0
                for order in orders:
                    details = await _query_order(trade["symbol"], str(order.get("clientOrderId")), api_key, secret)
                    if details.get("side") == "SELL":
                        exit_quote += float(details.get("cummulativeQuoteQty", 0) or 0)
                realized = exit_quote - float(trade.get("entry_quote", 0))
                trade["realized_pnl"] = round(realized, 8)
                history = [x for x in history if x.get("oco_client_id") != trade.get("oco_client_id")]
                history.append(trade)
                await _notify(db, user.id, f"🛡️ <b>QUANTNEX SPOT DEMO — TRADE CLOSED</b>\n{trade['symbol']} · OCO completed\nEstimated P&amp;L: {realized:.4f} USDT")
            else:
                remaining.append(trade)
        except Exception:
            remaining.append(trade)
    active = remaining
    # Recover the symbol lock from Binance itself if local state was restored or
    # interrupted after an OCO was accepted but before the local ledger commit.
    exchange_open_symbols = set()
    try:
        open_lists = await _request("GET", "/v3/openOrderList", {}, api_key, secret)
        if isinstance(open_lists, list):
            exchange_open_symbols = {
                str(x.get("symbol", "")).upper() for x in open_lists
                if str(x.get("listClientOrderId", "")).startswith("QXSO")
            }
    except Exception:
        # Fail closed: do not create new entries when exchange recovery is unavailable.
        return
    _set_pref(db, user.id, "binance_spot_active_trades", json.dumps(active, separators=(",", ":")))
    _set_pref(db, user.id, "binance_spot_trade_history", json.dumps(history[-500:], separators=(",", ":")))
    db.commit()
    if len(set(x.get("symbol") for x in active) | exchange_open_symbols) >= config["max_open_trades"]:
        return
    signal_raw = _pref(db, user.id, "signal_settings",
        '{"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":8}')
    try:
        signal_settings = json.loads(signal_raw)
    except (TypeError, ValueError):
        signal_settings = {"primary":"5", "trend":"60", "enabled":["60","30","15","5","1"], "risk_percent":1}
    signal_settings["min_score"] = config["min_score"]
    from .signal_engine import build_signal, MarketDataError
    for symbol in config["symbols"]:
        if len(active) >= config["max_open_trades"] or len(daily) >= config["max_trades_per_day"]:
            break
        if any(x.get("symbol") == symbol for x in active) or symbol in exchange_open_symbols:
            continue
        try:
            scan = await build_signal(signal_settings, symbol)
            candidate = scan.get("signal")
            if not candidate or str(candidate.get("side", "")).upper() != "BUY":
                continue
            price, spread_bps, volume = await _ticker(symbol)
            if spread_bps > config["max_spread_bps"] or volume < config["min_24h_quote_volume"]:
                continue
            info = await _symbol_info(symbol)
            filters = _filters(info)
            lot = filters.get("LOT_SIZE")
            market_lot = filters.get("MARKET_LOT_SIZE") or lot
            price_filter = filters.get("PRICE_FILTER")
            if not lot or not market_lot or not price_filter:
                continue
            distance = float(candidate.get("risk_distance", 0))
            if not math.isfinite(distance) or distance <= 0:
                continue
            signal_entry = float(candidate.get("entry", 0) or 0)
            if signal_entry <= 0 or abs(price - signal_entry) > distance * 0.5:
                continue
            stop_value = price - distance
            target_value = price + distance * max(config["min_reward_risk"], 2.0)
            if not 0 < stop_value < price < target_value:
                continue
            risk_cash = free_usdt * config["risk_per_trade_percent"] / 100
            raw_qty = risk_cash / distance
            qty = _floor_step(min(raw_qty, free_usdt * 0.90 / price), market_lot["stepSize"])
            # The BUY market order and SELL OCO legs have separate exchange filters.
            qty = _floor_step(float(qty), lot["stepSize"])
            min_qty = max(Decimal(str(lot["minQty"])), Decimal(str(market_lot["minQty"])))
            max_qty = min(Decimal(str(lot["maxQty"])), Decimal(str(market_lot["maxQty"])))
            if (qty < min_qty or qty > max_qty
                    or qty % Decimal(str(lot["stepSize"])) != 0
                    or qty % Decimal(str(market_lot["stepSize"])) != 0):
                continue
            notional = float(qty) * price
            notional_filter = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL")
            minimum_notional = float((notional_filter or {}).get("minNotional", 0))
            maximum_notional = float((notional_filter or {}).get("maxNotional", 0) or 0)
            if (notional < minimum_notional or notional > free_usdt * 0.90
                    or (maximum_notional > 0 and notional > maximum_notional)):
                continue
            # Revalidate risk after exchange precision and available-balance caps.
            if float(qty) * distance > risk_cash * 1.000001:
                continue
            fingerprint = hashlib.sha256(f"{symbol}|{candidate.get('side')}|{candidate.get('timeframe')}|{candidate.get('signal_candle_time')}".encode()).hexdigest()
            if _pref(db, user.id, "binance_spot_signal_" + symbol.lower()) == fingerprint:
                continue
            stamp = hashlib.sha256(f"{user.id}|{fingerprint}".encode()).hexdigest()[:18]
            buy_client_id = "QXSB" + stamp
            # Persist the signal lock before submitting the order so a process
            # restart cannot re-enter the same candle setup.
            _set_pref(db, user.id, "binance_spot_signal_" + symbol.lower(), fingerprint)
            _set_pref(db, user.id, "binance_spot_pending_order", json.dumps({
                "symbol": symbol, "client_order_id": buy_client_id, "fingerprint": fingerprint,
                "created_at": datetime.now(timezone.utc).isoformat()}))
            db.commit()
            try:
                buy = await _market_buy(symbol, notional, buy_client_id, api_key, secret)
            except RuntimeError:
                # A timed-out POST may have reached Binance; resolve by client ID.
                # Never blindly resubmit a market order.
                try:
                    buy = await _query_order(symbol, buy_client_id, api_key, secret)
                except Exception:
                    _set_pref(db, user.id, "binance_auto_trading_enabled", "false")
                    config["enabled"] = False
                    _set_pref(db, user.id, "binance_spot_auto_config", json.dumps(config, separators=(",", ":")))
                    db.commit()
                    await _notify(db, user.id, f"🚨 <b>QUANTNEX SPOT DEMO — ORDER STATUS UNKNOWN</b>\\n{symbol}: Binance may have received the BUY order, but QUANTNEX could not confirm it. Auto Trading has been stopped. Check Binance order history before restarting.")
                    raise RuntimeError("Market order status is unknown; Auto Trading has been stopped.")
            executed = float(buy.get("executedQty", 0) or 0)
            quote_spent = float(buy.get("cummulativeQuoteQty", 0) or 0)
            if executed <= 0 or quote_spent <= 0:
                # A timeout or non-filled response is never retried blindly.
                resolved = await _query_order(symbol, buy_client_id, api_key, secret)
                executed = float(resolved.get("executedQty", 0) or 0)
                quote_spent = float(resolved.get("cummulativeQuoteQty", 0) or 0)
                buy = resolved
            if executed <= 0 or quote_spent <= 0:
                continue
            entry = quote_spent / executed
            stop = entry - distance
            target = entry + distance * max(config["min_reward_risk"], 2.0)
            protected_qty = _floor_step(executed, lot["stepSize"])
            oco = None
            try:
                _validate_geometry(entry, stop, target, config["min_reward_risk"])
                stop_price = _round_price(stop, price_filter["tickSize"], ROUND_DOWN)
                target_price = _round_price(target, price_filter["tickSize"], ROUND_UP)
                min_price = Decimal(str(price_filter.get("minPrice", "0")))
                max_price = Decimal(str(price_filter.get("maxPrice", "0")))
                if stop_price < min_price or (max_price > 0 and target_price > max_price):
                    raise RuntimeError("Protective prices fall outside Binance PRICE_FILTER bounds.")
                # Fees may be deducted in the base asset, so use the actual free
                # balance when sizing the exchange-native protective OCO.
                refreshed = await _account(api_key, secret)
                base_asset = info["baseAsset"]
                base_free = next((float(x["free"]) for x in refreshed.get("balances", []) if x["asset"] == base_asset), 0.0)
                protected_qty = _floor_step(min(executed, base_free), lot["stepSize"])
                if protected_qty < min_qty:
                    raise RuntimeError("Filled quantity is below the exchange minimum after fees.")
                oco_id = "QXSO" + stamp
                try:
                    oco = await _place_oco(symbol, protected_qty, stop_price, target_price,
                        price_filter["tickSize"], oco_id, api_key, secret)
                    if not isinstance(oco, dict) or not oco.get("orderListId"):
                        raise RuntimeError("Binance did not confirm the protective OCO order list.")
                except Exception:
                    # Resolve an uncertain OCO POST before attempting a market exit.
                    oco = await _request("GET", "/v3/orderList", {"origClientOrderId": oco_id}, api_key, secret)
                    if not oco.get("orderListId"):
                        raise RuntimeError("Protective OCO could not be confirmed.")
            except Exception:
                # Any post-fill failure must attempt to flatten the demo position.
                try:
                    await _emergency_sell(symbol, protected_qty, api_key, secret)
                    _set_pref(db, user.id, "binance_spot_pending_order", "")
                    db.commit()
                    await _notify(db, user.id, f"🚨 <b>QUANTNEX SPOT DEMO SAFETY EXIT</b>\\n{symbol}: protective OCO setup failed after the BUY fill. Binance accepted an emergency market sell; verify order history.")
                except Exception:
                    _set_pref(db, user.id, "binance_auto_trading_enabled", "false")
                    config["enabled"] = False
                    _set_pref(db, user.id, "binance_spot_auto_config", json.dumps(config, separators=(",", ":")))
                    db.commit()
                    await _notify(db, user.id, f"🚨 <b>QUANTNEX SPOT DEMO — MANUAL ACTION REQUIRED</b>\\n{symbol}: BUY may be filled but neither protective OCO nor emergency sell was confirmed. Auto Trading has been stopped. Inspect Binance immediately.")
                raise
            _set_pref(db, user.id, "binance_spot_pending_order", "")
            trade = {"symbol": symbol, "side": "BUY", "quantity": _decimal_text(protected_qty),
                     "entry_price": entry, "stop_loss": stop, "take_profit": target,
                     "entry_quote": quote_spent, "buy_order_id": buy.get("orderId"),
                     "oco_order_list_id": oco.get("orderListId"), "oco_client_id": oco_id,
                     "created_at": datetime.now(timezone.utc).isoformat(), "status": "OPEN"}
            active.append(trade)
            daily.append(trade)
            _set_pref(db, user.id, "binance_spot_pending_order", "")
            _set_pref(db, user.id, "binance_spot_active_trades", json.dumps(active, separators=(",", ":")))
            _set_pref(db, user.id, "binance_spot_trade_history", json.dumps((history + [trade])[-500:], separators=(",", ":")))
            _set_pref(db, user.id, "binance_spot_last_execution", json.dumps({
                "symbol": symbol, "side": "BUY", "entry": entry, "quantity": _decimal_text(protected_qty),
                "stop_loss": stop, "take_profit": target, "order_id": buy.get("orderId"),
                "order_list_id": oco.get("orderListId"), "timestamp": trade["created_at"]}))
            db.commit()
            await _notify(db, user.id,
                f"🟢 <b>QUANTNEX SPOT DEMO — BUY FILLED</b>\n{symbol}\nEntry: {entry:.8g}\nQuantity: {_decimal_text(protected_qty)}\nSL: {stop:.8g}\nTP: {target:.8g}\nRisk budget: {risk_cash:.4f} USDT\nProtective OCO: ACTIVE")
            break
        except (MarketDataError, RuntimeError, ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
            logger.warning("Spot Demo scan rejected for %s: %s", symbol, type(exc).__name__)
            continue


def _validate_geometry(entry: float, stop: float, target: float, minimum_rr: float) -> None:
    if not all(math.isfinite(x) and x > 0 for x in (entry, stop, target)) or not stop < entry < target:
        raise ValueError("Invalid Spot BUY stop/target geometry.")
    if (target - entry) / (entry - stop) < minimum_rr:
        raise ValueError("Reward-to-risk is below the configured minimum.")


async def binance_spot_auto_worker() -> None:
    WORKER_STATE["running"] = True
    last_scan: dict[int, float] = {}
    while True:
        try:
            with SessionLocal() as db:
                users = list(db.scalars(select(User).order_by(User.id)))
                for user in users:
                    config = normalize_config(_pref(db, user.id, "binance_spot_auto_config", ""))
                    if not config["enabled"] or _pref(db, user.id, "binance_auto_trading_enabled") != "true":
                        continue
                    now = time.monotonic()
                    if now - last_scan.get(user.id, 0) < config["interval_seconds"]:
                        continue
                    last_scan[user.id] = now
                    try:
                        await _scan_user(db, user)
                    except Exception as exc:
                        WORKER_STATE["last_error"] = type(exc).__name__
                        logger.warning("Spot Demo worker cycle failed: %s", type(exc).__name__)
            WORKER_STATE["last_cycle"] = datetime.now(timezone.utc).isoformat()
            WORKER_STATE["last_error"] = None
        except asyncio.CancelledError:
            WORKER_STATE["running"] = False
            raise
        except Exception as exc:
            WORKER_STATE["last_error"] = type(exc).__name__
            logger.warning("Spot Demo worker loop failed: %s", type(exc).__name__)
        await asyncio.sleep(5)

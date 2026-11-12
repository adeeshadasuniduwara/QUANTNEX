import asyncio
import json
import math
import re
import sqlite3
import httpx
from datetime import datetime, timezone
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import AI_API_KEY, AI_BASE_URL, AI_MODEL, CORS_ORIGINS, DATABASE_URL
from .database import Base, engine, get_db, SessionLocal
from .models import AuditEvent, PaperTrade, Preference, StrategyLabRun, Trade, User, WalletTransaction
from .schemas import AIChatRequest, AIChatResponse, PreferenceResponse, PreferenceWrite, TelegramConnectRequest, TelegramSendRequest, SignalSettingsRequest, AutoSignalSettingsRequest, TradeCreate, TradeResponse, WalletSummaryResponse, WalletTransactionCreate, WalletTransactionResponse
from .security import decrypt_secret, encrypt_secret
from .maintenance import daily_backup_worker, record_audit_event
from .system_security import router as system_security_router

Base.metadata.create_all(bind=engine)
app = FastAPI(title="QUANTNEX Local API", description="Loopback-only local workspace API. No user login or remote account system.", version="0.8.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.include_router(system_security_router)


def local_workspace(db: Session = Depends(get_db)) -> User:
    """Return the one local workspace owner and safely consolidate legacy accounts."""
    users = list(db.scalars(select(User).order_by(User.id)))
    if not users:
        owner = User(email="local@quantnex.invalid", password_hash="")
        db.add(owner)
        db.commit()
        db.refresh(owner)
        return owner

    owner = users[0]
    changed = False
    for legacy in users[1:]:
        for preference in list(db.scalars(select(Preference).where(Preference.user_id == legacy.id))):
            existing = db.scalar(select(Preference).where(
                Preference.user_id == owner.id, Preference.key == preference.key
            ))
            if existing is None:
                preference.user_id = owner.id
            else:
                db.delete(preference)
        for trade in db.scalars(select(Trade).where(Trade.user_id == legacy.id)):
            trade.user_id = owner.id
        for transaction in db.scalars(select(WalletTransaction).where(WalletTransaction.user_id == legacy.id)):
            transaction.user_id = owner.id
        # Flush reassigned child rows before deleting the legacy owner; ORM delete cascades
        # must not interpret the moved rows as orphans.
        db.flush()
        db.delete(legacy)
        changed = True

    if changed:
        db.flush()
    if owner.email != "local@quantnex.invalid":
        owner.email = "local@quantnex.invalid"
        changed = True
    if owner.password_hash:
        owner.password_hash = ""
        changed = True
    if changed:
        db.commit()
        db.refresh(owner)
    return owner

@app.get("/api/v1/market/overview")
async def market_overview():
    """Indicative BTC/USD, XAU/USD and converted Sri Lankan gold values."""
    from .market_data import get_market_overview
    try:
        return await get_market_overview()
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="A market price provider is temporarily unavailable.")

@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "quantnex-api", "version": app.version, "database": "connected"}

@app.get("/api/v1/journal", response_model=list[TradeResponse])
def list_journal(limit: int = 100, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 500.")
    return list(db.scalars(select(Trade).where(Trade.user_id == user.id).order_by(Trade.id.desc()).limit(limit)))

@app.post("/api/v1/journal", response_model=TradeResponse, status_code=201)
def create_journal(payload: TradeCreate, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    item = Trade(user_id=user.id, symbol=payload.symbol, direction=payload.direction,
                 outcome=payload.outcome, pnl=payload.pnl, notes=payload.notes)
    db.add(item)
    db.flush()
    db.add(WalletTransaction(user_id=user.id, transaction_type="trade_pnl", amount=payload.pnl,
                             description=f"{payload.symbol} {payload.direction.upper()} journal P&L", trade_id=item.id))
    record_audit_event(db, "journal.created", {"trade_id": item.id, "symbol": item.symbol, "direction": item.direction, "pnl": item.pnl})
    db.commit()
    db.refresh(item)
    return item

@app.delete("/api/v1/journal/{trade_id}", status_code=204)
def delete_journal(trade_id: int, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    item = db.scalar(select(Trade).where(Trade.id == trade_id, Trade.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Journal entry not found.")
    linked = db.scalar(select(WalletTransaction).where(WalletTransaction.user_id == user.id,
                                                        WalletTransaction.trade_id == trade_id))
    if linked is not None:
        db.delete(linked)
    db.delete(item)
    record_audit_event(db, "journal.deleted", {"trade_id": trade_id})
    db.commit()

@app.get("/api/v1/wallet/summary", response_model=WalletSummaryResponse)
def wallet_summary(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(WalletTransaction).where(WalletTransaction.user_id == user.id)))
    deposits = sum(row.amount for row in rows if row.transaction_type == "deposit")
    withdrawals = sum(abs(row.amount) for row in rows if row.transaction_type == "withdrawal")
    trading_pnl = sum(row.amount for row in rows if row.transaction_type == "trade_pnl")
    return WalletSummaryResponse(balance=round(sum(row.amount for row in rows), 2),
                                 deposits=round(deposits, 2), withdrawals=round(withdrawals, 2),
                                 trading_pnl=round(trading_pnl, 2))

@app.get("/api/v1/wallet/transactions", response_model=list[WalletTransactionResponse])
def wallet_transactions(limit: int = 100, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 500.")
    return list(db.scalars(select(WalletTransaction).where(WalletTransaction.user_id == user.id)
                           .order_by(WalletTransaction.id.desc()).limit(limit)))

@app.post("/api/v1/wallet/transactions", response_model=WalletTransactionResponse, status_code=201)
def create_wallet_transaction(payload: WalletTransactionCreate, user: User = Depends(local_workspace),
                               db: Session = Depends(get_db)):
    balance = db.scalar(select(func.coalesce(func.sum(WalletTransaction.amount), 0.0))
                        .where(WalletTransaction.user_id == user.id)) or 0.0
    signed_amount = payload.amount if payload.transaction_type == "deposit" else -payload.amount
    if payload.transaction_type == "withdrawal" and payload.amount > balance:
        raise HTTPException(status_code=409, detail="Insufficient wallet balance for this withdrawal.")
    item = WalletTransaction(user_id=user.id, transaction_type=payload.transaction_type,
                             amount=signed_amount, description=payload.description.strip())
    db.add(item)
    record_audit_event(db, "wallet.transaction_created", {"transaction_type": item.transaction_type, "amount": item.amount})
    db.commit()
    db.refresh(item)
    return item

@app.get("/api/v1/preferences", response_model=list[PreferenceResponse])
def get_preferences(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    return list(db.scalars(select(Preference).where(Preference.user_id == user.id).order_by(Preference.key)))

@app.put("/api/v1/preferences/{key}", response_model=PreferenceResponse)
def set_preference(key: str, payload: PreferenceWrite, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    if not key.replace("_", "").isalnum() or len(key) > 64:
        raise HTTPException(status_code=422, detail="Invalid preference key.")
    item = db.scalar(select(Preference).where(Preference.user_id == user.id, Preference.key == key))
    if item is None:
        item = Preference(user_id=user.id, key=key, value=payload.value)
        db.add(item)
    else:
        item.value = payload.value
    record_audit_event(db, "preference.updated", {"key": key})
    db.commit()
    db.refresh(item)
    return item

@app.get("/api/v1/ai/status")
def ai_status(user: User = Depends(local_workspace)):
    return {"configured": bool(AI_BASE_URL and AI_API_KEY and AI_MODEL),
            "provider": "OpenAI-compatible" if AI_BASE_URL else None,
            "model": AI_MODEL or None,
            "note": "AI is disabled until server-side provider settings are configured."}

@app.post("/api/v1/ai/chat", response_model=AIChatResponse)
async def ai_chat(payload: AIChatRequest, user: User = Depends(local_workspace)):
    if not (AI_BASE_URL and AI_API_KEY and AI_MODEL):
        raise HTTPException(status_code=503, detail="AI provider is not configured on the server.")
    url = AI_BASE_URL if AI_BASE_URL.endswith("/chat/completions") else AI_BASE_URL + "/chat/completions"
    body = {"model": AI_MODEL, "messages": [
        {"role": "system", "content": "You are QUANTNEX, a cautious trading education assistant. Explain risk clearly. Never promise profits or place trades."},
        {"role": "user", "content": payload.message}
    ], "temperature": 0.2}
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post(url, headers={"Authorization": f"Bearer {AI_API_KEY}"}, json=body)
            response.raise_for_status()
            data = response.json()
        reply = data["choices"][0]["message"]["content"]
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("Empty AI response")
        return AIChatResponse(reply=reply.strip(), model=AI_MODEL)
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        raise HTTPException(status_code=502, detail="AI provider request failed. Check server configuration.")


@app.post("/api/v1/telegram/send")
async def send_telegram_message(payload: TelegramSendRequest, user: User = Depends(local_workspace)):
    """Send one user-triggered Telegram message; bot credentials are never stored."""
    import re
    if not re.fullmatch(r"[0-9]{5,12}:[A-Za-z0-9_-]{20,}", payload.bot_token):
        raise HTTPException(status_code=422, detail="Telegram bot token format is invalid.")
    if not re.fullmatch(r"(?:@[A-Za-z0-9_]{5,}|-?[0-9]{1,20})", payload.chat_id.strip()):
        raise HTTPException(status_code=422, detail="Use a numeric chat ID or @channel username.")
    url = "https://api.telegram.org/bot" + payload.bot_token + "/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(url, json={"chat_id": payload.chat_id.strip(),
                                                    "text": payload.message,
                                                    "disable_web_page_preview": True})
        data = response.json()
        if response.status_code >= 400 or not data.get("ok"):
            raise HTTPException(status_code=502, detail="Telegram rejected the message. Check the bot token, chat ID and bot permissions.")
        return {"ok": True, "message_id": data.get("result", {}).get("message_id")}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Telegram request timed out.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach Telegram. Check the server internet connection.")


def _preference(db: Session, user_id: int, key: str, default: str = "") -> str:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == key))
    return row.value if row else default

def _save_preference(db: Session, user_id: int, key: str, value: str) -> None:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == key))
    if row is None:
        db.add(Preference(user_id=user_id, key=key, value=value))
    else:
        row.value = value

DEFAULT_SIGNAL_SETTINGS = {"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1.0,"min_score":7}

@app.get("/api/v1/signals/status")
def signal_engine_status(user: User = Depends(local_workspace)):
    from .config import TWELVE_DATA_API_KEY
    return {"configured": bool(TWELVE_DATA_API_KEY), "provider":"Twelve Data",
            "symbol":"XAU/USD", "note":"Live analysis requires a valid server-side TWELVE_DATA_API_KEY. The TradingView embed does not expose its candles to this API."}

@app.get("/api/v1/signals/settings")
def get_signal_settings(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    try: settings=json.loads(_preference(db,user.id,"signal_settings",json.dumps(DEFAULT_SIGNAL_SETTINGS)))
    except ValueError: settings=DEFAULT_SIGNAL_SETTINGS
    return settings

@app.put("/api/v1/signals/settings")
def update_signal_settings(payload: SignalSettingsRequest, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    settings=payload.model_dump()
    _save_preference(db,user.id,"signal_settings",json.dumps(settings))
    record_audit_event(db, "signals.settings_updated", {"primary": settings["primary"], "trend": settings["trend"]})
    db.commit()
    return settings

@app.post("/api/v1/signals/scan")
async def scan_xauusd_signal(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .signal_engine import build_signal, MarketDataError
    from .config import TWELVE_DATA_API_KEY
    if not TWELVE_DATA_API_KEY:
        raise HTTPException(status_code=503,detail="Market feed not configured. Add TWELVE_DATA_API_KEY to backend/.env and restart the API.")
    try: settings=json.loads(_preference(db,user.id,"signal_settings",json.dumps(DEFAULT_SIGNAL_SETTINGS)))
    except ValueError: settings=DEFAULT_SIGNAL_SETTINGS
    try:
        result=await build_signal(settings)
    except MarketDataError as exc:
        raise HTTPException(status_code=502,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Could not retrieve XAUUSD candles from the configured market-data provider.")
    signal=result.get("signal")
    if signal:
        _save_preference(db,user.id,"active_signal",json.dumps({**signal,"tp1_notified":False,"tp2_notified":False,"tp3_notified":False,"sl_notified":False}))
        token_enc=_preference(db,user.id,"telegram_bot_token_enc")
        chat_id=_preference(db,user.id,"telegram_chat_id")
        try: auto_settings=json.loads(_preference(db,user.id,"auto_signal_settings",'{"enabled":false}'))
        except ValueError: auto_settings={"enabled":False}
        if token_enc and chat_id and auto_settings.get("enabled"):
            try:
                token=decrypt_secret(token_enc)
                message=("QUANTNEX · XAUUSD "+signal["side"]+"\\nEntry: "+str(signal["entry"])+"\\nSL: "+str(signal["stop_loss"])+
                    "\\nTP1: "+str(signal["tp1"])+"\\nTP2: "+str(signal["tp2"])+"\\nTP3: "+str(signal["tp3"])+
                    "\\nConfluence: "+str(signal["score"])+"/10 (not win probability)\\nConfirmations: "+", ".join(signal["confirmations"])+
                    "\\nTP1/SL level alerts run while the local API is active. No broker order is placed.")
                async with httpx.AsyncClient(timeout=12) as client:
                    response=await client.post("https://api.telegram.org/bot"+token+"/sendMessage",
                        json={"chat_id":chat_id,"text":message,"disable_web_page_preview":True})
                    response.raise_for_status()
                result["telegram_sent"]=True
            except Exception: result["telegram_sent"]=False
        else:
            result["telegram_sent"]=False
            result["telegram_note"]="Auto Signals is OFF; this manual scan did not send a Telegram alert."
    else:
        _save_preference(db,user.id,"active_signal","")
    db.commit()
    return result

@app.post("/api/v1/telegram/connect")
async def connect_telegram_bot(payload: TelegramConnectRequest, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    if not re.fullmatch(r"[0-9]{5,12}:[A-Za-z0-9_-]{20,}",payload.bot_token):
        raise HTTPException(status_code=422,detail="Telegram bot token format is invalid.")
    if not re.fullmatch(r"(?:@[A-Za-z0-9_]{5,}|-?[0-9]{1,20})",payload.chat_id.strip()):
        raise HTTPException(status_code=422,detail="Use a numeric chat ID or @channel username.")
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response=await client.get("https://api.telegram.org/bot"+payload.bot_token+"/getMe")
            data=response.json()
        if response.status_code>=400 or not data.get("ok"):
            raise HTTPException(status_code=422,detail="Telegram rejected this bot token. Check BotFather token.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Could not reach Telegram to verify the bot.")
    bot=data.get("result",{})
    _save_preference(db,user.id,"telegram_bot_token_enc",encrypt_secret(payload.bot_token))
    _save_preference(db,user.id,"telegram_chat_id",payload.chat_id.strip())
    _save_preference(db,user.id,"telegram_bot_username",bot.get("username",""))
    _save_preference(db,user.id,"telegram_bot_display_name",payload.display_name.strip() or bot.get("first_name","QUANTNEX Bot"))
    record_audit_event(db, "telegram.connected", {"bot_username": bot.get("username", "")})
    db.commit()
    return {"connected":True,"bot_username":bot.get("username"),"chat_id":payload.chat_id.strip(),
            "commands":["/help","/timeframes","/settf 5","/settrend 60","/setanalysis 1,5,15,30,60","/scan","/status"],
            "note":"The local API must remain running for bot commands and TP1/SL level alerts."}

@app.get("/api/v1/telegram/status")
def telegram_status(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    connected=bool(_preference(db,user.id,"telegram_bot_token_enc") and _preference(db,user.id,"telegram_chat_id"))
    return {"connected":connected,"bot_username":_preference(db,user.id,"telegram_bot_username") if connected else None,
            "display_name":_preference(db,user.id,"telegram_bot_display_name") if connected else None,
            "chat_id":_preference(db,user.id,"telegram_chat_id") if connected else None,
            "worker":"active while this API process is running"}

@app.delete("/api/v1/telegram/connect")
def disconnect_telegram_bot(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    for key in ["telegram_bot_token_enc","telegram_chat_id","telegram_bot_username","telegram_bot_display_name","telegram_update_offset","active_signal","auto_signal_settings","auto_signal_last_fingerprint"]:
        row=db.scalar(select(Preference).where(Preference.user_id==user.id,Preference.key==key))
        if row:db.delete(row)
    record_audit_event(db, "telegram.disconnected")
    db.commit()
    return {"connected":False}

def backup_legacy_database(db: Session) -> None:
    """Create a recoverable SQLite snapshot before clearing legacy login data."""
    users = list(db.scalars(select(User).order_by(User.id)))
    if not users:
        return
    needs_migration = len(users) > 1 or users[0].email != "local@quantnex.invalid" or bool(users[0].password_hash)
    if not needs_migration or not DATABASE_URL.startswith("sqlite:///"):
        return

    raw_path = DATABASE_URL[len("sqlite:///"):].split("?", 1)[0]
    if raw_path == ":memory:":
        return
    database_path = Path(raw_path)
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    if not database_path.is_file():
        return

    backup_dir = Path(__file__).resolve().parents[2] / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / ("quantnex-pre-local-only-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".db")
    try:
        source = sqlite3.connect(str(database_path))
        target = sqlite3.connect(str(backup_path))
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise
    print(f"[QUANTNEX] Legacy database backup created: {backup_path}", flush=True)


@app.on_event("startup")
async def prepare_local_workspace():
    """Back up and migrate legacy accounts before the Telegram worker starts."""
    db = SessionLocal()
    try:
        backup_legacy_database(db)
        local_workspace(db)
    finally:
        db.close()


@app.on_event("startup")
async def start_telegram_background_worker():
    from .telegram_worker import telegram_worker
    app.state.telegram_worker_task=asyncio.create_task(telegram_worker())

@app.on_event("shutdown")
async def stop_telegram_background_worker():
    task=getattr(app.state,"telegram_worker_task",None)
    if task:
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass

@app.get("/api/v1/telegram/auto-signals")
def get_auto_signal_settings(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    raw=_preference(db,user.id,"auto_signal_settings",'{"enabled":false,"interval_seconds":180}')
    try: settings=json.loads(raw)
    except ValueError: settings={"enabled":False,"interval_seconds":180}
    settings["telegram_connected"]=bool(_preference(db,user.id,"telegram_bot_token_enc") and _preference(db,user.id,"telegram_chat_id"))
    from .config import TWELVE_DATA_API_KEY
    settings["market_feed_configured"]=bool(TWELVE_DATA_API_KEY)
    return settings

@app.put("/api/v1/telegram/auto-signals")
def set_auto_signal_settings(payload: AutoSignalSettingsRequest, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    connected=bool(_preference(db,user.id,"telegram_bot_token_enc") and _preference(db,user.id,"telegram_chat_id"))
    if payload.enabled and not connected:
        raise HTTPException(status_code=409,detail="Connect and test your personal Telegram bot before enabling Auto Signals.")
    from .config import TWELVE_DATA_API_KEY
    if payload.enabled and not TWELVE_DATA_API_KEY:
        raise HTTPException(status_code=503,detail="Add TWELVE_DATA_API_KEY to backend/.env and restart the QUANTNEX API before enabling Auto Signals.")
    settings=payload.model_dump()
    _save_preference(db,user.id,"auto_signal_settings",json.dumps(settings))
    record_audit_event(db, "signals.auto_settings_updated", {"enabled": settings["enabled"], "interval_seconds": settings["interval_seconds"]})
    db.commit()
    return {**settings,"telegram_connected":connected,"note":"Automatic XAUUSD alerts run only while this computer's QUANTNEX API process is running."}

@app.post("/api/v1/telegram/notify")
async def notify_connected_telegram(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    message=payload.get("message")
    if not isinstance(message,str) or not message.strip() or len(message)>4096:
        raise HTTPException(status_code=422,detail="Message must contain 1–4096 characters.")
    token_enc=_preference(db,user.id,"telegram_bot_token_enc")
    chat_id=_preference(db,user.id,"telegram_chat_id")
    if not token_enc or not chat_id:
        raise HTTPException(status_code=409,detail="Connect your Telegram bot first.")
    try: token=decrypt_secret(token_enc)
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response=await client.post("https://api.telegram.org/bot"+token+"/sendMessage",
                json={"chat_id":chat_id,"text":message,"disable_web_page_preview":True})
            data=response.json()
        if response.status_code>=400 or not data.get("ok"):
            raise HTTPException(status_code=502,detail="Telegram rejected the message. Check bot permissions and chat ID.")
        return {"ok":True,"message_id":data.get("result",{}).get("message_id")}
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Could not reach Telegram.")


@app.on_event("startup")
async def start_daily_backup_worker():
    app.state.daily_backup_task = asyncio.create_task(daily_backup_worker())


@app.on_event("shutdown")
async def stop_daily_backup_worker():
    task = getattr(app.state, "daily_backup_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Phase 07 — multi-market intelligence, paper trading, performance and risk.
# All trading endpoints are simulation-only. No broker execution is available.
# ---------------------------------------------------------------------------
@app.get("/api/v1/intelligence/markets")
async def intelligence_markets(user: User = Depends(local_workspace)):
    from .phase07_engine import get_market_board
    return await get_market_board()

# Phase 10 — source-time and candle-integrity validation.
@app.get("/api/v1/data-reliability/markets")
async def data_reliability_markets(user: User = Depends(local_workspace)):
    from .phase07_engine import get_market_board
    from .phase10_engine import assess_quote
    board=await get_market_board()
    items=[]
    for item in board.get("items",[]):
        if item.get("status")!="ok":
            items.append({"symbol":item.get("symbol"),"provider":item.get("provider"),
                          "status":"UNSAFE","trading_safe":False,"issues":["PROVIDER_UNAVAILABLE"]})
        else:
            health=item.get("data_health") or assess_quote(item)
            items.append({"symbol":item.get("symbol"),"label":item.get("label"),"provider":item.get("provider"),
                          "price":item.get("price"),"change_percent":item.get("change_percent"),
                          "health":health,"status":health["status"],"trading_safe":health["trading_safe"]})
    return {"items":items,"timestamp":board.get("timestamp"),
            "trading_safe":all(x.get("trading_safe",False) for x in items),
            "note":"A failed market is isolated; it does not imply every supported market is unavailable."}

@app.get("/api/v1/data-reliability/market/{symbol}")
async def data_reliability_market(symbol: str, timeframe: str = "15m",
                                  user: User = Depends(local_workspace)):
    from .phase07_engine import get_quote,get_candles,market_info,IntelligenceDataError
    from .phase10_engine import assess_market_snapshot
    try:
        info=market_info(symbol)
        quote=await get_quote(info["symbol"])
        candles=await get_candles(info["symbol"],timeframe,250)
        health=assess_market_snapshot(quote,candles,timeframe)
        return {**health,"timeframe":timeframe,"price":quote["price"]}
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except IntelligenceDataError as exc:
        raise HTTPException(status_code=502,detail={"message":str(exc),"trading_safe":False})
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail={"message":"Market provider request failed.","trading_safe":False})

@app.get("/api/v1/intelligence/market/{symbol}/candles")
async def intelligence_candles(symbol: str, timeframe: str = "15m",
                                user: User = Depends(local_workspace)):
    from .phase07_engine import get_candles, market_info, IntelligenceDataError
    try:
        info=market_info(symbol)
        candles=await get_candles(info["symbol"],timeframe)
        return {"symbol":info["symbol"],"timeframe":timeframe,"provider":info["provider"],
                "candles":candles,"count":len(candles)}
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except IntelligenceDataError as exc:
        raise HTTPException(status_code=502,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Market provider request failed. Check API key, quota or network connection.")

@app.get("/api/v1/intelligence/market/{symbol}/orderbook")
async def intelligence_orderbook(symbol: str, user: User = Depends(local_workspace)):
    from .phase07_engine import get_order_book, market_info
    try:
        return await get_order_book(market_info(symbol)["symbol"])
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Order-book provider is temporarily unavailable.")

@app.post("/api/v1/intelligence/signals/scan")
async def intelligence_signal_scan(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import scan_market_signal, market_info, IntelligenceDataError
    symbol=payload.get("symbol","XAUUSD")
    threshold=payload.get("min_score",6)
    if not isinstance(threshold,int) or not 4<=threshold<=10:
        raise HTTPException(status_code=422,detail="min_score must be an integer between 4 and 10.")
    try:
        info=market_info(symbol)
        result=await scan_market_signal(info["symbol"],threshold)
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except IntelligenceDataError as exc:
        raise HTTPException(status_code=502,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Market provider request failed. Check API key, quota or network connection.")
    if result.get("signal"):
        record_audit_event(db,"phase07.signal_generated",{"symbol":result["symbol"],"side":result["signal"]["side"],
            "score":result["signal"]["score"],"mode":"paper_only"})
        db.commit()
    return result

@app.get("/api/v1/intelligence/news")
async def intelligence_news(days: int = 7, user: User = Depends(local_workspace)):
    from .phase07_engine import get_economic_calendar
    try:
        return await get_economic_calendar(days)
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Economic calendar provider is temporarily unavailable.")

@app.post("/api/v1/intelligence/risk/calculate")
def intelligence_risk_calculate(payload: dict, user: User = Depends(local_workspace)):
    from .phase07_engine import calculate_risk
    try:
        return calculate_risk(float(payload.get("equity",0)),float(payload.get("risk_percent",0)),
                              float(payload.get("entry",0)),float(payload.get("stop_loss",0)))
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))

@app.get("/api/v1/paper-trading/trades")
def list_paper_trades(limit: int = 100, status: str = "ALL",
                      user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    if not 1<=limit<=500: raise HTTPException(status_code=422,detail="Limit must be between 1 and 500.")
    query=select(PaperTrade).where(PaperTrade.user_id==user.id)
    if status.upper() in {"OPEN","CLOSED"}: query=query.where(PaperTrade.status==status.upper())
    elif status.upper()!="ALL": raise HTTPException(status_code=422,detail="Status must be OPEN, CLOSED or ALL.")
    rows=list(db.scalars(query.order_by(PaperTrade.id.desc()).limit(limit)))
    return [{"id":x.id,"symbol":x.symbol,"side":x.side,"quantity":x.quantity,"entry_price":x.entry_price,
             "stop_loss":x.stop_loss,"take_profit":x.take_profit,"status":x.status,"exit_price":x.exit_price,
             "realized_pnl":x.realized_pnl,"created_at":x.created_at.isoformat(),
             "closed_at":x.closed_at.isoformat() if x.closed_at else None} for x in rows]

@app.post("/api/v1/paper-trading/trades",status_code=201)
async def open_paper_trade(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import get_quote, market_info, IntelligenceDataError
    try:
        info=market_info(str(payload.get("symbol","")))
        side=str(payload.get("side","")).upper()
        quantity=float(payload.get("quantity",0))
        stop=float(payload.get("stop_loss",0))
        target=float(payload.get("take_profit",0))
        if side not in {"BUY","SELL"} or not all(math.isfinite(x) for x in (quantity,stop,target)) or not 0<quantity<=1000000 or stop<=0 or target<=0:
            raise ValueError("Side, quantity, stop loss and take profit are invalid.")
        quote=await get_quote(info["symbol"])
        from .phase10_engine import execution_gate
        data_gate=execution_gate(quote)
        if not data_gate["allowed"]:
            raise HTTPException(status_code=503,detail={"message":data_gate["reason"],"data_health":data_gate["health"]})
        entry=float(quote["price"])
        if (side=="BUY" and not stop<entry<target) or (side=="SELL" and not target<entry<stop):
            raise ValueError("For BUY, Stop Loss < live entry < Take Profit. For SELL, Take Profit < live entry < Stop Loss.")
        item=PaperTrade(user_id=user.id,symbol=info["symbol"],side=side,quantity=quantity,
                        entry_price=entry,stop_loss=stop,take_profit=target,status="OPEN")
        db.add(item)
        db.flush()
        record_audit_event(db,"paper_trade.opened",{"trade_id":item.id,"symbol":item.symbol,"side":side,
            "quantity":quantity,"entry":entry,"mode":"paper"})
        db.commit()
        db.refresh(item)
        return {"id":item.id,"symbol":item.symbol,"side":item.side,"quantity":item.quantity,
                "entry_price":item.entry_price,"stop_loss":item.stop_loss,"take_profit":item.take_profit,
                "status":item.status,"mode":"PAPER"}
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except IntelligenceDataError as exc:
        raise HTTPException(status_code=502,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Market provider request failed. Check API key, quota or network connection.")

@app.post("/api/v1/paper-trading/trades/{trade_id}/close")
async def close_paper_trade(trade_id: int, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import get_quote, IntelligenceDataError
    item=db.scalar(select(PaperTrade).where(PaperTrade.id==trade_id,PaperTrade.user_id==user.id))
    if item is None: raise HTTPException(status_code=404,detail="Paper trade not found.")
    if item.status!="OPEN": raise HTTPException(status_code=409,detail="Paper trade is already closed.")
    try:
        quote=await get_quote(item.symbol)
        exit_price=float(quote["price"])
    except IntelligenceDataError as exc:
        raise HTTPException(status_code=502,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Market provider request failed. Check API key, quota or network connection.")
    pnl=(exit_price-item.entry_price)*item.quantity*(1 if item.side=="BUY" else -1)
    item.exit_price=exit_price
    item.realized_pnl=round(pnl,8)
    item.status="CLOSED"
    item.closed_at=datetime.now(timezone.utc)
    record_audit_event(db,"paper_trade.closed",{"trade_id":item.id,"symbol":item.symbol,
        "exit":exit_price,"realized_pnl":item.realized_pnl,"mode":"paper"})
    db.commit()
    return {"id":item.id,"status":item.status,"exit_price":exit_price,"realized_pnl":item.realized_pnl,"mode":"PAPER"}

@app.get("/api/v1/paper-trading/summary")
def paper_trading_summary(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id)))
    closed=[x for x in rows if x.status=="CLOSED"]
    wins=[x for x in closed if (x.realized_pnl or 0)>0]
    losses=[x for x in closed if (x.realized_pnl or 0)<0]
    gross_profit=sum(x.realized_pnl or 0 for x in wins)
    gross_loss=abs(sum(x.realized_pnl or 0 for x in losses))
    return {"mode":"PAPER ONLY","open_trades":sum(x.status=="OPEN" for x in rows),
            "closed_trades":len(closed),"wins":len(wins),"losses":len(losses),
            "win_rate":round(len(wins)/len(closed)*100,2) if closed else None,
            "realized_pnl":round(sum(x.realized_pnl or 0 for x in closed),2),
            "profit_factor":round(gross_profit/gross_loss,3) if gross_loss else (None if not gross_profit else "infinite"),
            "note":"Separate virtual ledger. Existing wallet and journal balances are not changed."}

@app.get("/api/v1/intelligence/performance")
def intelligence_performance(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id,PaperTrade.status=="CLOSED")))
    wins=[x for x in rows if (x.realized_pnl or 0)>0]
    losses=[x for x in rows if (x.realized_pnl or 0)<0]
    gross_profit=sum(x.realized_pnl or 0 for x in wins)
    gross_loss=abs(sum(x.realized_pnl or 0 for x in losses))
    return {"mode":"PAPER ONLY","total_trades":len(rows),"wins":len(wins),"losses":len(losses),
            "breakeven":len(rows)-len(wins)-len(losses),
            "win_rate":round(len(wins)/len(rows)*100,2) if rows else None,
            "gross_profit":round(gross_profit,2),"gross_loss":round(gross_loss,2),
            "net_pnl":round(gross_profit-gross_loss,2),
            "profit_factor":round(gross_profit/gross_loss,3) if gross_loss else None,
            "average_win":round(gross_profit/len(wins),2) if wins else None,
            "average_loss":round(gross_loss/len(losses),2) if losses else None,
            "note":"Statistics use closed QUANTNEX paper trades only; no performance or win-rate guarantee."}


@app.get("/api/v1/performance/advanced")
def advanced_paper_performance(period_days: int = 0,
                               user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase11_engine import advanced_performance
    if period_days not in {0,7,30,90,365}:
        raise HTTPException(status_code=422,detail="period_days must be one of 0, 7, 30, 90 or 365.")
    rows=list(db.scalars(select(PaperTrade).where(
        PaperTrade.user_id==user.id,PaperTrade.status=="CLOSED"
    ).order_by(PaperTrade.closed_at,PaperTrade.id)))
    return advanced_performance(rows,period_days)


@app.on_event("startup")
async def start_phase07_paper_monitor():
    from .paper_worker import paper_trade_monitor
    app.state.paper_monitor_task=asyncio.create_task(paper_trade_monitor())

@app.on_event("shutdown")
async def stop_phase07_paper_monitor():
    task=getattr(app.state,"paper_monitor_task",None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Phase 08 — Strategy Laboratory (historical research + forward observation)
# ---------------------------------------------------------------------------
@app.get("/api/v1/strategy-lab/replay")
async def strategy_lab_replay(symbol: str = "BTCUSDT", timeframe: str = "15m",
                              user: User = Depends(local_workspace)):
    from .phase07_engine import market_info, get_candles
    try:
        info=market_info(symbol)
        if timeframe not in {"5m","15m","1h","4h"}: raise ValueError("Unsupported timeframe. Choose 5m, 15m, 1h or 4h.")
        candles=await get_candles(info["symbol"],timeframe,250)
        return {"symbol":info["symbol"],"timeframe":timeframe,"candles":candles,
                "count":len(candles),"mode":"HISTORICAL_REPLAY"}
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502,detail="Historical market data unavailable. Check provider configuration and quota.") from exc

@app.post("/api/v1/strategy-lab/backtest")
async def strategy_lab_backtest(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import market_info, get_candles
    from .phase08_engine import run_backtest, validate_strategy
    try:
        info=market_info(payload.get("symbol","BTCUSDT"))
        timeframe=payload.get("timeframe","15m")
        if timeframe not in {"5m","15m","1h","4h"}: raise ValueError("Unsupported timeframe. Choose 5m, 15m, 1h or 4h.")
        strategy=validate_strategy(payload.get("strategy") or {})
        candles=await get_candles(info["symbol"],timeframe,500)
        result=run_backtest(candles,strategy)
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502,detail="Backtest data unavailable. Check market provider configuration and quota.") from exc
    db.add(StrategyLabRun(user_id=user.id,run_type="BACKTEST",symbol=info["symbol"],timeframe=timeframe,
        strategy_json=json.dumps(strategy),result_json=json.dumps(result)))
    record_audit_event(db,"strategy_lab.backtest",{"symbol":info["symbol"],"timeframe":timeframe,
        "trades":result["trade_count"],"strategy":strategy})
    db.commit()
    return {"symbol":info["symbol"],"timeframe":timeframe,**result}

@app.post("/api/v1/strategy-lab/optimize")
async def strategy_lab_optimize(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import market_info, get_candles
    from .phase08_engine import optimize
    try:
        info=market_info(payload.get("symbol","BTCUSDT"))
        timeframe=payload.get("timeframe","15m")
        if timeframe not in {"5m","15m","1h","4h"}: raise ValueError("Unsupported timeframe. Choose 5m, 15m, 1h or 4h.")
        candles=await get_candles(info["symbol"],timeframe,500)
        result=optimize(candles)
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502,detail="Optimizer data unavailable. Check provider configuration and quota.") from exc
    db.add(StrategyLabRun(user_id=user.id,run_type="OPTIMIZER",symbol=info["symbol"],timeframe=timeframe,
        strategy_json="{}",result_json=json.dumps(result)))
    record_audit_event(db,"strategy_lab.optimizer",{"symbol":info["symbol"],"timeframe":timeframe,"tested":result["tested"]})
    db.commit()
    return {"symbol":info["symbol"],"timeframe":timeframe,**result}

@app.post("/api/v1/strategy-lab/forward/evaluate")
async def strategy_lab_forward_evaluate(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import market_info, get_candles
    from .phase08_engine import ema, validate_strategy
    try:
        info=market_info(payload.get("symbol","BTCUSDT"))
        timeframe=payload.get("timeframe","15m")
        if timeframe not in {"5m","15m","1h","4h"}: raise ValueError("Unsupported timeframe. Choose 5m, 15m, 1h or 4h.")
        strategy=validate_strategy(payload.get("strategy") or {})
        candles=await get_candles(info["symbol"],timeframe,250)
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502,detail="Forward observation data unavailable. Check provider configuration and quota.") from exc
    closes=[float(x["close"]) for x in candles]
    fast=ema(closes,strategy["fast_ema"]); slow=ema(closes,strategy["slow_ema"])
    side="BUY" if fast[-1]>slow[-1] else "SELL" if fast[-1]<slow[-1] else "WAIT"
    observation={"side":side,"price":closes[-1],"candle_time":candles[-1].get("time"),
                 "fast_ema":round(fast[-1],8),"slow_ema":round(slow[-1],8),
                 "note":"Observation only. This endpoint does not open paper or broker positions."}
    db.add(StrategyLabRun(user_id=user.id,run_type="FORWARD_OBSERVATION",symbol=info["symbol"],timeframe=timeframe,
        strategy_json=json.dumps(strategy),result_json=json.dumps(observation)))
    record_audit_event(db,"strategy_lab.forward_observation",{"symbol":info["symbol"],"side":side,"timeframe":timeframe})
    db.commit()
    return {"symbol":info["symbol"],"timeframe":timeframe,"strategy":strategy,**observation}

@app.get("/api/v1/strategy-lab/research")
def strategy_lab_research(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    runs=list(db.scalars(select(StrategyLabRun).where(StrategyLabRun.user_id==user.id)
                         .order_by(StrategyLabRun.created_at.desc()).limit(50)))
    closed=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id,PaperTrade.status=="CLOSED")))
    wins=[x for x in closed if (x.realized_pnl or 0)>0]
    losses=[x for x in closed if (x.realized_pnl or 0)<0]
    return {"runs":[{"id":x.id,"type":x.run_type,"symbol":x.symbol,"timeframe":x.timeframe,
                     "created_at":x.created_at.isoformat(),"strategy":json.loads(x.strategy_json),
                     "result":json.loads(x.result_json)} for x in runs],
            "paper_trades":{"closed":len(closed),"wins":len(wins),"losses":len(losses),
                "win_rate":round(len(wins)/len(closed)*100,2) if closed else None,
                "net_pnl":round(sum(x.realized_pnl or 0 for x in closed),2)},
            "guidance":"Research summaries describe historical and paper observations only; they are not a prediction or guarantee."}


# ---------------------------------------------------------------------------
# Phase 09 — advanced risk and portfolio intelligence (paper-only).
# ---------------------------------------------------------------------------
@app.get("/api/v1/risk/portfolio")
def risk_portfolio(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase09_engine import portfolio_snapshot
    rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id)))
    return portfolio_snapshot(rows)

@app.post("/api/v1/risk/position-size")
def risk_position_size(payload: dict, user: User = Depends(local_workspace)):
    from .phase09_engine import calculate_position_size
    try:
        return calculate_position_size(payload.get("equity"),payload.get("risk_percent"),
            payload.get("entry"),payload.get("stop_loss"),payload.get("contract_multiplier"))
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))

@app.post("/api/v1/risk/guardian")
def risk_guardian(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase09_engine import drawdown_guard
    try:
        rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id)))
        return drawdown_guard(rows,payload.get("equity"),payload.get("daily_loss_limit_percent",3),
            payload.get("max_drawdown_percent",8),payload.get("max_consecutive_losses",4))
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))

@app.post("/api/v1/risk/stress")
def risk_stress(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase09_engine import stress_test
    rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id)))
    try:
        return stress_test(rows,payload.get("shocks"))
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))

@app.post("/api/v1/paper-trading/smart-open",status_code=201)
async def smart_open_paper_trade(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    """Risk-checked paper entry; explicit multiplier required; never sends broker orders."""
    from .phase07_engine import get_quote, market_info, IntelligenceDataError
    from .phase09_engine import calculate_position_size, drawdown_guard
    try:
        info=market_info(str(payload.get("symbol","")))
        side=str(payload.get("side","")).upper()
        if side not in {"BUY","SELL"}: raise ValueError("Side must be BUY or SELL.")
        equity=float(payload.get("equity",0))
        risk_percent=float(payload.get("risk_percent",0.5))
        rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id)))
        guard=drawdown_guard(rows,equity,payload.get("daily_loss_limit_percent",3),
            payload.get("max_drawdown_percent",8),payload.get("max_consecutive_losses",4))
        if not guard["trading_allowed"]:
            raise HTTPException(status_code=409,detail={"message":"Risk Guardian blocked this paper entry.","guardian":guard})
        quote=await get_quote(info["symbol"])
        from .phase10_engine import execution_gate
        data_gate=execution_gate(quote)
        if not data_gate["allowed"]:
            raise HTTPException(status_code=503,detail={"message":data_gate["reason"],"data_health":data_gate["health"]})
        entry=float(quote["price"])
        stop=float(payload.get("stop_loss",0)); target=float(payload.get("take_profit",0))
        if (side=="BUY" and not stop<entry<target) or (side=="SELL" and not target<entry<stop):
            raise ValueError("For BUY, Stop Loss < live entry < Take Profit. For SELL, Take Profit < live entry < Stop Loss.")
        sizing=calculate_position_size(equity,risk_percent,entry,stop,payload.get("contract_multiplier"))
        quantity=sizing["estimated_units"]
        if not math.isfinite(quantity) or quantity<=0 or quantity>1000000:
            raise ValueError("Calculated quantity is outside the safe supported range.")
        item=PaperTrade(user_id=user.id,symbol=info["symbol"],side=side,quantity=quantity,
            entry_price=entry,stop_loss=stop,take_profit=target,status="OPEN")
        db.add(item); db.flush()
        record_audit_event(db,"phase09.smart_paper_trade.opened",{"trade_id":item.id,"symbol":item.symbol,
            "side":side,"quantity":quantity,"risk_amount":sizing["risk_amount"],"mode":"paper"})
        db.commit(); db.refresh(item)
        return {"id":item.id,"symbol":item.symbol,"side":side,"quantity":quantity,"entry_price":entry,
            "stop_loss":stop,"take_profit":target,"risk":sizing,"guardian":guard,"status":"OPEN","mode":"PAPER"}
    except HTTPException:
        raise
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except IntelligenceDataError as exc:
        raise HTTPException(status_code=502,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Market provider request failed. Check provider configuration and quota.")

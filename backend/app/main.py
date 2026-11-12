import asyncio
import json
import re
import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import AI_API_KEY, AI_BASE_URL, AI_MODEL, CORS_ORIGINS
from .database import Base, engine, get_db
from .models import Preference, Trade, User, WalletTransaction
from .schemas import AIChatRequest, AIChatResponse, PreferenceResponse, PreferenceWrite, TelegramConnectRequest, TelegramSendRequest, SignalSettingsRequest, AutoSignalSettingsRequest, TradeCreate, TradeResponse, WalletSummaryResponse, WalletTransactionCreate, WalletTransactionResponse
from .security import decrypt_secret, encrypt_secret

Base.metadata.create_all(bind=engine)
app = FastAPI(title="QUANTNEX Local API", description="Loopback-only local workspace API. No user login or remote account system.", version="0.7.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


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
    db.commit()
    return {"connected":False}

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

import asyncio
import json
import re
import time
import uuid
import base64
from urllib.parse import urlsplit
import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import AI_API_KEY, AI_BASE_URL, AI_MODEL, CORS_ORIGINS, TOKEN_MINUTES, WEBAUTHN_RP_ID, WEBAUTHN_RP_NAME, WEBAUTHN_ALLOWED_ORIGINS
from .database import Base, engine, get_db
from .models import Preference, Trade, User, WalletTransaction, PasskeyCredential, WebAuthnChallenge
from .schemas import AIChatRequest, AIChatResponse, LoginRequest, PreferenceResponse, PreferenceWrite, RegisterRequest, TelegramConnectRequest, TelegramSendRequest, SignalSettingsRequest, AutoSignalSettingsRequest, TokenResponse, TradeCreate, TradeResponse, UserResponse, WalletSummaryResponse, WalletTransactionCreate, WalletTransactionResponse
from .security import create_access_token, decode_access_token, decrypt_secret, encrypt_secret, hash_password, verify_password, enforce_auth_rate_limit
from webauthn import (generate_registration_options, verify_registration_response, generate_authentication_options, verify_authentication_response, options_to_json, base64url_to_bytes)
from webauthn.helpers.structs import (AuthenticatorAttachment, AuthenticatorSelectionCriteria, ResidentKeyRequirement, UserVerificationRequirement, PublicKeyCredentialDescriptor)

Base.metadata.create_all(bind=engine)
app = FastAPI(title="QUANTNEX API", description="Shared backend for the QUANTNEX trading workspace.", version="0.5.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])
bearer = HTTPBearer(auto_error=False)

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        user_id = decode_access_token(credentials.credentials)
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired access token.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User account not found.")
    return user

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

@app.post("/api/v1/auth/register", response_model=UserResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, _rate_limit: None = Depends(enforce_auth_rate_limit), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    return user

@app.post("/api/v1/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, _rate_limit: None = Depends(enforce_auth_rate_limit), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return TokenResponse(access_token=create_access_token(user.id), expires_in=TOKEN_MINUTES * 60)

@app.get("/api/v1/auth/me", response_model=UserResponse)
def me(user: User = Depends(current_user)):
    return user


def _webauthn_origin(request: Request) -> tuple[str, str]:
    origin = (request.headers.get("origin") or "").rstrip("/")
    if not origin or origin not in WEBAUTHN_ALLOWED_ORIGINS:
        raise HTTPException(status_code=400, detail="Passkeys are enabled only for the configured QUANTNEX browser origin. Open http://localhost:5500.")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname == "localhost"):
        raise HTTPException(status_code=400, detail="Passkeys require HTTPS, or localhost for local development.")
    if not parsed.hostname or parsed.hostname.lower() != WEBAUTHN_RP_ID:
        raise HTTPException(status_code=400, detail="The configured WebAuthn RP ID does not match this browser origin.")
    return origin, WEBAUTHN_RP_ID


def _save_webauthn_challenge(db: Session, user_id: int, purpose: str, challenge: bytes,
                             origin: str, rp_id: str) -> str:
    challenge_id = str(uuid.uuid4())
    encoded = base64.urlsafe_b64encode(challenge).rstrip(b"=").decode("ascii")
    db.add(WebAuthnChallenge(id=challenge_id, user_id=user_id, purpose=purpose,
                             challenge=encoded, expected_origin=origin,
                             expected_rp_id=rp_id, expires_at=time.time() + 300))
    db.commit()
    return challenge_id


def _consume_webauthn_challenge(db: Session, challenge_id: str, purpose: str,
                                user_id: int | None = None) -> WebAuthnChallenge:
    item = db.get(WebAuthnChallenge, challenge_id)
    if (item is None or item.purpose != purpose or item.expires_at < time.time()
            or (user_id is not None and item.user_id != user_id)):
        if item is not None:
            db.delete(item)
            db.commit()
        raise HTTPException(status_code=400, detail="Passkey challenge expired or invalid. Start again.")
    db.delete(item)
    db.commit()
    return item


@app.get("/api/v1/auth/passkeys")
def list_passkeys(user: User = Depends(current_user), db: Session = Depends(get_db)):
    credentials = list(db.scalars(select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)
                                  .order_by(PasskeyCredential.id)))
    return {"enabled": bool(credentials), "count": len(credentials),
            "credentials": [{"id": item.id, "created_at": item.created_at,
                             "label": "Windows Hello / Passkey"} for item in credentials]}


@app.post("/api/v1/auth/passkeys/register/options")
def passkey_registration_options(request: Request, user: User = Depends(current_user),
                                  db: Session = Depends(get_db)):
    origin, rp_id = _webauthn_origin(request)
    existing = list(db.scalars(select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)))
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=WEBAUTHN_RP_NAME,
        user_id=str(user.id).encode("utf-8"),
        user_name=user.email,
        user_display_name=user.email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(item.credential_id))
                             for item in existing],
        timeout=60000,
    )
    challenge_id = _save_webauthn_challenge(db, user.id, "register", options.challenge, origin, rp_id)
    return {"challenge_id": challenge_id, "publicKey": json.loads(options_to_json(options))}


@app.post("/api/v1/auth/passkeys/register/verify")
def passkey_registration_verify(payload: PasskeyVerifyRequest, request: Request,
                                user: User = Depends(current_user), db: Session = Depends(get_db)):
    origin, rp_id = _webauthn_origin(request)
    ceremony = _consume_webauthn_challenge(db, payload.challenge_id, "register", user.id)
    if ceremony.expected_origin != origin or ceremony.expected_rp_id != rp_id:
        raise HTTPException(status_code=400, detail="Passkey origin changed during registration. Start again.")
    try:
        verification = verify_registration_response(
            credential=payload.credential,
            expected_challenge=base64url_to_bytes(ceremony.challenge),
            expected_origin=ceremony.expected_origin,
            expected_rp_id=ceremony.expected_rp_id,
            require_user_verification=True,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Windows Hello could not verify this passkey. Try again.")
    credential_id = base64.urlsafe_b64encode(verification.credential_id).rstrip(b"=").decode("ascii")
    if db.scalar(select(PasskeyCredential).where(PasskeyCredential.credential_id == credential_id)):
        raise HTTPException(status_code=409, detail="This passkey is already registered.")
    transports = payload.credential.get("response", {}).get("transports", [])
    db.add(PasskeyCredential(
        user_id=user.id,
        credential_id=credential_id,
        public_key=base64.urlsafe_b64encode(verification.credential_public_key).rstrip(b"=").decode("ascii"),
        sign_count=verification.sign_count,
        transports=json.dumps(transports if isinstance(transports, list) else []),
    ))
    db.commit()
    return {"registered": True, "message": "Passkey registered. You can now sign in with Windows Hello."}


@app.post("/api/v1/auth/passkeys/login/options")
def passkey_login_options(payload: PasskeyOptionsRequest, request: Request,
                          _rate_limit: None = Depends(enforce_auth_rate_limit),
                          db: Session = Depends(get_db)):
    origin, rp_id = _webauthn_origin(request)
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None:
        raise HTTPException(status_code=401, detail="Email or passkey is not recognised.")
    credentials = list(db.scalars(select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)))
    if not credentials:
        raise HTTPException(status_code=400, detail="No passkey is registered for this account. Sign in with your existing password and add a passkey first.")
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(
            id=base64url_to_bytes(item.credential_id),
            transports=json.loads(item.transports or "[]"),
        ) for item in credentials],
        user_verification=UserVerificationRequirement.REQUIRED,
        timeout=60000,
    )
    challenge_id = _save_webauthn_challenge(db, user.id, "login", options.challenge, origin, rp_id)
    return {"challenge_id": challenge_id, "publicKey": json.loads(options_to_json(options))}


@app.post("/api/v1/auth/passkeys/login/verify", response_model=TokenResponse)
def passkey_login_verify(payload: PasskeyVerifyRequest, request: Request,
                         _rate_limit: None = Depends(enforce_auth_rate_limit),
                         db: Session = Depends(get_db)):
    origin, rp_id = _webauthn_origin(request)
    ceremony = _consume_webauthn_challenge(db, payload.challenge_id, "login")
    if ceremony.expected_origin != origin or ceremony.expected_rp_id != rp_id:
        raise HTTPException(status_code=400, detail="Passkey origin changed during login. Start again.")
    credential_value = payload.credential.get("id")
    stored = db.scalar(select(PasskeyCredential).where(
        PasskeyCredential.credential_id == credential_value,
        PasskeyCredential.user_id == ceremony.user_id,
    ))
    if stored is None:
        raise HTTPException(status_code=401, detail="This passkey is not registered to the account.")
    try:
        verification = verify_authentication_response(
            credential=payload.credential,
            expected_challenge=base64url_to_bytes(ceremony.challenge),
            expected_origin=ceremony.expected_origin,
            expected_rp_id=ceremony.expected_rp_id,
            credential_public_key=base64url_to_bytes(stored.public_key),
            credential_current_sign_count=stored.sign_count,
            require_user_verification=True,
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Passkey verification failed. Try again.")
    stored.sign_count = verification.new_sign_count
    db.commit()
    return TokenResponse(access_token=create_access_token(stored.user_id), expires_in=TOKEN_MINUTES * 60)


@app.delete("/api/v1/auth/passkeys/{credential_pk}")
def delete_passkey(credential_pk: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    credentials = list(db.scalars(select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)))
    target = next((item for item in credentials if item.id == credential_pk), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Passkey not found.")
    if len(credentials) == 1:
        raise HTTPException(status_code=409, detail="Register another passkey before removing the last one.")
    db.delete(target)
    db.commit()
    return {"deleted": True}

@app.get("/api/v1/journal", response_model=list[TradeResponse])
def list_journal(limit: int = 100, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 500.")
    return list(db.scalars(select(Trade).where(Trade.user_id == user.id).order_by(Trade.id.desc()).limit(limit)))

@app.post("/api/v1/journal", response_model=TradeResponse, status_code=201)
def create_journal(payload: TradeCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
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
def delete_journal(trade_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
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
def wallet_summary(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(WalletTransaction).where(WalletTransaction.user_id == user.id)))
    deposits = sum(row.amount for row in rows if row.transaction_type == "deposit")
    withdrawals = sum(abs(row.amount) for row in rows if row.transaction_type == "withdrawal")
    trading_pnl = sum(row.amount for row in rows if row.transaction_type == "trade_pnl")
    return WalletSummaryResponse(balance=round(sum(row.amount for row in rows), 2),
                                 deposits=round(deposits, 2), withdrawals=round(withdrawals, 2),
                                 trading_pnl=round(trading_pnl, 2))

@app.get("/api/v1/wallet/transactions", response_model=list[WalletTransactionResponse])
def wallet_transactions(limit: int = 100, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 500.")
    return list(db.scalars(select(WalletTransaction).where(WalletTransaction.user_id == user.id)
                           .order_by(WalletTransaction.id.desc()).limit(limit)))

@app.post("/api/v1/wallet/transactions", response_model=WalletTransactionResponse, status_code=201)
def create_wallet_transaction(payload: WalletTransactionCreate, user: User = Depends(current_user),
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
def get_preferences(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Preference).where(Preference.user_id == user.id).order_by(Preference.key)))

@app.put("/api/v1/preferences/{key}", response_model=PreferenceResponse)
def set_preference(key: str, payload: PreferenceWrite, user: User = Depends(current_user), db: Session = Depends(get_db)):
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
def ai_status(user: User = Depends(current_user)):
    return {"configured": bool(AI_BASE_URL and AI_API_KEY and AI_MODEL),
            "provider": "OpenAI-compatible" if AI_BASE_URL else None,
            "model": AI_MODEL or None,
            "note": "AI is disabled until server-side provider settings are configured."}

@app.post("/api/v1/ai/chat", response_model=AIChatResponse)
async def ai_chat(payload: AIChatRequest, user: User = Depends(current_user)):
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
async def send_telegram_message(payload: TelegramSendRequest, user: User = Depends(current_user)):
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
def signal_engine_status(user: User = Depends(current_user)):
    from .config import TWELVE_DATA_API_KEY
    return {"configured": bool(TWELVE_DATA_API_KEY), "provider":"Twelve Data",
            "symbol":"XAU/USD", "note":"Live analysis requires a valid server-side TWELVE_DATA_API_KEY. The TradingView embed does not expose its candles to this API."}

@app.get("/api/v1/signals/settings")
def get_signal_settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    try: settings=json.loads(_preference(db,user.id,"signal_settings",json.dumps(DEFAULT_SIGNAL_SETTINGS)))
    except ValueError: settings=DEFAULT_SIGNAL_SETTINGS
    return settings

@app.put("/api/v1/signals/settings")
def update_signal_settings(payload: SignalSettingsRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    settings=payload.model_dump()
    _save_preference(db,user.id,"signal_settings",json.dumps(settings))
    db.commit()
    return settings

@app.post("/api/v1/signals/scan")
async def scan_xauusd_signal(user: User = Depends(current_user), db: Session = Depends(get_db)):
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
async def connect_telegram_bot(payload: TelegramConnectRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
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
def telegram_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    connected=bool(_preference(db,user.id,"telegram_bot_token_enc") and _preference(db,user.id,"telegram_chat_id"))
    return {"connected":connected,"bot_username":_preference(db,user.id,"telegram_bot_username") if connected else None,
            "display_name":_preference(db,user.id,"telegram_bot_display_name") if connected else None,
            "chat_id":_preference(db,user.id,"telegram_chat_id") if connected else None,
            "worker":"active while this API process is running"}

@app.delete("/api/v1/telegram/connect")
def disconnect_telegram_bot(user: User = Depends(current_user), db: Session = Depends(get_db)):
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
def get_auto_signal_settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    raw=_preference(db,user.id,"auto_signal_settings",'{"enabled":false,"interval_seconds":180}')
    try: settings=json.loads(raw)
    except ValueError: settings={"enabled":False,"interval_seconds":180}
    settings["telegram_connected"]=bool(_preference(db,user.id,"telegram_bot_token_enc") and _preference(db,user.id,"telegram_chat_id"))
    from .config import TWELVE_DATA_API_KEY
    settings["market_feed_configured"]=bool(TWELVE_DATA_API_KEY)
    return settings

@app.put("/api/v1/telegram/auto-signals")
def set_auto_signal_settings(payload: AutoSignalSettingsRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
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
async def notify_connected_telegram(payload: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
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

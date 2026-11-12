import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import AI_API_KEY, AI_BASE_URL, AI_MODEL, CORS_ORIGINS, TOKEN_MINUTES
from .database import Base, engine, get_db
from .models import Preference, Trade, User, WalletTransaction
from .schemas import AIChatRequest, AIChatResponse, LoginRequest, PreferenceResponse, PreferenceWrite, RegisterRequest, TokenResponse, TradeCreate, TradeResponse, UserResponse, WalletSummaryResponse, WalletTransactionCreate, WalletTransactionResponse
from .security import create_access_token, decode_access_token, hash_password, verify_password

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

@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "quantnex-api", "version": app.version, "database": "connected"}

@app.post("/api/v1/auth/register", response_model=UserResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
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
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return TokenResponse(access_token=create_access_token(user.id), expires_in=TOKEN_MINUTES * 60)

@app.get("/api/v1/auth/me", response_model=UserResponse)
def me(user: User = Depends(current_user)):
    return user

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
    db.execute(select(WalletTransaction).where(WalletTransaction.user_id == user.id,
                                               WalletTransaction.trade_id == trade_id))
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

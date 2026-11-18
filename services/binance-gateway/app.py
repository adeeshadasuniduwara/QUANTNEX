"""Isolated HTTPS gateway for mobile Binance TESTNET credential setup.

This service is intentionally separate from the local QUANTNEX API. It stores
only a workspace-scoped encrypted credential record and short-lived, one-use
setup sessions. It never places orders and never returns credential material.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./binance_gateway.db")
PUBLIC_BASE_URL = os.getenv("QUANTNEX_GATEWAY_PUBLIC_URL", "").rstrip("/")
WORKSPACE_KEY_MIN_LENGTH = 40
SESSION_TTL_SECONDS = 300
SPOT_BASE = "https://testnet.binance.vision"
FUTURES_BASE = "https://testnet.binancefuture.com"
ENCRYPTION_KEY = os.getenv("QUANTNEX_GATEWAY_ENCRYPTION_KEY", "")
if not ENCRYPTION_KEY:
    raise RuntimeError("QUANTNEX_GATEWAY_ENCRYPTION_KEY must be configured with a Fernet key.")
if not PUBLIC_BASE_URL.startswith("https://") and os.getenv("QUANTNEX_GATEWAY_ALLOW_INSECURE_LOCAL", "") != "1":
    raise RuntimeError("QUANTNEX_GATEWAY_PUBLIC_URL must be an HTTPS origin.")
fernet = Fernet(ENCRYPTION_KEY.encode("ascii"))

connect_args = {"check_same_thread": False, "timeout": 20} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class SetupSession(Base):
    __tablename__ = "binance_setup_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    workspace_hash: Mapped[str] = mapped_column(String(64), index=True)
    telegram_chat_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BinanceCredential(Base):
    __tablename__ = "binance_testnet_credentials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    spot_api_key_enc: Mapped[str] = mapped_column(Text)
    spot_api_secret_enc: Mapped[str] = mapped_column(Text)
    futures_api_key_enc: Mapped[str] = mapped_column(Text)
    futures_api_secret_enc: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(20), default="testnet")
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


Base.metadata.create_all(bind=engine)
app = FastAPI(title="QUANTNEX Binance Mobile Gateway", version="1.0.0",
              description="HTTPS-only mobile credential setup for Binance Spot and USD-M Futures TESTNET.")

def _db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _workspace_hash(workspace_key: str) -> str:
    if len(workspace_key) < WORKSPACE_KEY_MIN_LENGTH:
        raise HTTPException(status_code=401, detail="Workspace authentication failed.")
    return _hash(workspace_key)


def _require_workspace(x_quantnex_workspace_key: str = Header(default="")) -> str:
    return _workspace_hash(x_quantnex_workspace_key)


def _signed_params(secret: str) -> dict[str, str]:
    params = {"recvWindow": "5000", "timestamp": str(int(time.time() * 1000))}
    params["signature"] = hmac.new(secret.encode(), urlencode(params).encode(), hashlib.sha256).hexdigest()
    return params


async def _verify(base: str, api_key: str, secret: str, path: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5)) as client:
            response = await client.get(base + path, params=_signed_params(secret),
                                        headers={"X-MBX-APIKEY": api_key})
        if response.status_code in (401, 403):
            raise HTTPException(status_code=422, detail="Binance rejected these TESTNET credentials or permissions.")
        if response.status_code == 429 or response.status_code >= 500:
            raise HTTPException(status_code=503, detail="Binance TESTNET is temporarily unavailable. Request a new setup link and retry.")
        if response.status_code >= 400:
            raise HTTPException(status_code=422, detail="Binance TESTNET credential verification failed. Check the key, secret and API permissions.")
        data = response.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="Unexpected response from Binance TESTNET.")
        return data
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Binance TESTNET timed out. Request a new setup link and retry.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach Binance TESTNET. Request a new setup link and retry.")


class CreateSession(BaseModel):
    telegram_chat_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")


class CompleteSetup(BaseModel):
    session_token: str = Field(min_length=40, max_length=100)
    spot_api_key: str = Field(min_length=20, max_length=160)
    spot_api_secret: str = Field(min_length=20, max_length=160)
    futures_api_key: str = Field(min_length=20, max_length=160)
    futures_api_secret: str = Field(min_length=20, max_length=160)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.url.path == "/v1/setup-sessions/complete" and request.headers.get("origin"):
        expected = PUBLIC_BASE_URL
        if request.headers["origin"].rstrip("/") != expected:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=403, content={"detail": "Untrusted browser origin."})
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    return response


@app.get("/health")
def health():
    return {"status": "ok", "service": "quantnex-binance-mobile-gateway", "mode": "testnet-only"}


@app.get("/setup")
def setup_page():
    return FileResponse(Path(__file__).with_name("setup.html"), media_type="text/html")


@app.post("/v1/setup-sessions")
def create_setup_session(payload: CreateSession, workspace_hash: str = Depends(_require_workspace),
                          db=Depends(_db)):
    now = datetime.now(timezone.utc)
    # Only one live setup link per workspace. Reissuing a link invalidates older links.
    db.execute(update(SetupSession).where(
        SetupSession.workspace_hash == workspace_hash,
        SetupSession.consumed_at.is_(None)
    ).values(consumed_at=now))
    raw_token = secrets.token_urlsafe(36)
    session = SetupSession(token_hash=_hash(raw_token), workspace_hash=workspace_hash,
                           telegram_chat_id=payload.telegram_chat_id,
                           created_at=now, expires_at=now + timedelta(seconds=SESSION_TTL_SECONDS))
    db.add(session)
    db.commit()
    # The token is placed in the URL fragment, so it is not sent in HTTP requests,
    # Referer headers, reverse-proxy access logs or the initial page request.
    return {"setup_url": PUBLIC_BASE_URL + "/setup#" + raw_token,
            "expires_in_seconds": SESSION_TTL_SECONDS, "one_time": True}


@app.post("/v1/setup-sessions/complete")
async def complete_setup(payload: CompleteSetup, db=Depends(_db)):
    now = datetime.now(timezone.utc)
    session = db.scalar(select(SetupSession).where(SetupSession.token_hash == _hash(payload.session_token)))
    expires_at = session.expires_at if session is not None else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if session is None or session.consumed_at is not None or expires_at <= now:
        raise HTTPException(status_code=410, detail="This setup link has expired or was already used. Send /binance to your QUANTNEX bot for a fresh link.")
    # Consume before external calls to prevent replay and concurrent double submission.
    session.consumed_at = now
    db.commit()

    spot_key, spot_secret = payload.spot_api_key.strip(), payload.spot_api_secret.strip()
    futures_key, futures_secret = payload.futures_api_key.strip(), payload.futures_api_secret.strip()
    await _verify(SPOT_BASE, spot_key, spot_secret, "/api/v3/account")
    await _verify(FUTURES_BASE, futures_key, futures_secret, "/fapi/v2/account")

    encrypted = {
        "spot_api_key_enc": fernet.encrypt(spot_key.encode()).decode("ascii"),
        "spot_api_secret_enc": fernet.encrypt(spot_secret.encode()).decode("ascii"),
        "futures_api_key_enc": fernet.encrypt(futures_key.encode()).decode("ascii"),
        "futures_api_secret_enc": fernet.encrypt(futures_secret.encode()).decode("ascii"),
    }
    credential = db.scalar(select(BinanceCredential).where(
        BinanceCredential.workspace_hash == session.workspace_hash))
    if credential is None:
        credential = BinanceCredential(workspace_hash=session.workspace_hash, **encrypted)
        db.add(credential)
    else:
        for key, value in encrypted.items():
            setattr(credential, key, value)
        credential.connected_at = now
    db.commit()
    return {"connected": True, "mode": "demo_testnet",
            "spot_verified": True, "futures_verified": True,
            "auto_trading_enabled": False, "orders_placed": False,
            "message": "Both Binance TESTNET accounts verified and encrypted. No orders were placed."}


@app.get("/v1/workspaces/status")
def workspace_status(workspace_hash: str = Depends(_require_workspace), db=Depends(_db)):
    row = db.scalar(select(BinanceCredential).where(BinanceCredential.workspace_hash == workspace_hash))
    return {"mode": "demo_testnet", "spot_connected": row is not None,
            "futures_connected": row is not None, "auto_trading_enabled": False,
            "execution": "disabled_no_order_routes"}


@app.delete("/v1/workspaces/credentials")
def delete_credentials(workspace_hash: str = Depends(_require_workspace), db=Depends(_db)):
    row = db.scalar(select(BinanceCredential).where(BinanceCredential.workspace_hash == workspace_hash))
    if row is not None:
        db.delete(row)
        db.commit()
    return {"connected": False, "deleted": True, "auto_trading_enabled": False}

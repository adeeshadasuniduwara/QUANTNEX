"""Secure Binance Spot + USD-M Futures testnet connections and demo controls.

This first release is deliberately testnet-only. It verifies credentials against
Binance test environments, stores them encrypted in the local workspace, and
persists risk/automation controls. It does not submit live or testnet orders.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Preference, User
from .security import decrypt_secret, encrypt_secret
from .binance_auto_config import AutoTradingConfig, safe_auto_status

router = APIRouter(prefix="/api/v1/exchanges/binance", tags=["Binance demo"])

SPOT_BASE = "https://testnet.binance.vision"
FUTURES_BASE = "https://testnet.binancefuture.com"


def _workspace(db: Session) -> User:
    user = db.scalar(select(User).order_by(User.id))
    if user is None:
        user = User(email="local@quantnex.invalid", password_hash="")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _get(db: Session, user_id: int, key: str, default: str = "") -> str:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == key))
    return row.value if row else default


def _set(db: Session, user_id: int, key: str, value: str) -> None:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == key))
    if row is None:
        db.add(Preference(user_id=user_id, key=key, value=value))
    else:
        row.value = value


def _signed_params(secret: str) -> dict[str, str]:
    params = {"recvWindow": "5000", "timestamp": str(int(time.time() * 1000))}
    params["signature"] = hmac.new(secret.encode(), urlencode(params).encode(), hashlib.sha256).hexdigest()
    return params


async def _verify(base: str, api_key: str, secret: str, path: str) -> dict:
    headers = {"X-MBX-APIKEY": api_key}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5)) as client:
            response = await client.get(base + path, params=_signed_params(secret), headers=headers)
        if response.status_code in (401, 403):
            raise HTTPException(status_code=422, detail="Binance rejected the API key or its testnet permissions.")
        if response.status_code == 429 or response.status_code >= 500:
            raise HTTPException(status_code=503, detail="Binance testnet is temporarily rate-limited or unavailable. Try again shortly.")
        if response.status_code >= 400:
            try:
                detail = response.json().get("msg", "Binance credential check failed.")
            except ValueError:
                detail = "Binance credential check failed."
            raise HTTPException(status_code=422, detail=str(detail)[:240])
        data = response.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="Binance returned an unexpected account response.")
        return data
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Binance testnet connection timed out.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach Binance testnet. Check the internet connection.")


class BinanceConnect(BaseModel):
    spot_api_key: str = Field(min_length=20, max_length=160)
    spot_api_secret: str = Field(min_length=20, max_length=160)
    futures_api_key: str = Field(min_length=20, max_length=160)
    futures_api_secret: str = Field(min_length=20, max_length=160)


class BinanceRiskSettings(BaseModel):
    max_trades_per_day: int = Field(default=1, ge=1, le=50)
    max_open_trades: int = Field(default=1, ge=1, le=20)
    risk_per_trade_percent: float = Field(default=0.5, gt=0, le=2, allow_inf_nan=False)
    max_daily_loss_percent: float = Field(default=2, gt=0, le=5, allow_inf_nan=False)


class BinanceAutoTrading(BaseModel):
    enabled: bool = False


@router.post("/connect")
async def connect_binance(payload: BinanceConnect, db: Session = Depends(get_db)):
    user = _workspace(db)
    spot = await _verify(SPOT_BASE, payload.spot_api_key.strip(), payload.spot_api_secret.strip(), "/api/v3/account")
    futures = await _verify(FUTURES_BASE, payload.futures_api_key.strip(), payload.futures_api_secret.strip(), "/fapi/v2/account")
    for key, value in (
        ("binance_spot_api_key_enc", encrypt_secret(payload.spot_api_key.strip())),
        ("binance_spot_api_secret_enc", encrypt_secret(payload.spot_api_secret.strip())),
        ("binance_futures_api_key_enc", encrypt_secret(payload.futures_api_key.strip())),
        ("binance_futures_api_secret_enc", encrypt_secret(payload.futures_api_secret.strip())),
    ):
        _set(db, user.id, key, value)
    _set(db, user.id, "binance_connection_mode", "testnet")
    _set(db, user.id, "binance_auto_trading_enabled", "false")
    db.commit()
    return {
        "connected": True,
        "mode": "demo_testnet",
        "spot": {"connected": True, "can_trade": bool(spot.get("canTrade"))},
        "futures": {"connected": True, "can_trade": bool(futures.get("canTrade"))},
        "message": "Both Binance testnet accounts verified. No orders were placed.",
    }


@router.get("/status")
def binance_status(db: Session = Depends(get_db)):
    user = _workspace(db)
    spot = bool(_get(db, user.id, "binance_spot_api_key_enc") and _get(db, user.id, "binance_spot_api_secret_enc"))
    futures = bool(_get(db, user.id, "binance_futures_api_key_enc") and _get(db, user.id, "binance_futures_api_secret_enc"))
    settings = _risk_settings(db, user.id)
    import json
    try:
        auto_config = AutoTradingConfig.model_validate_json(_get(db, user.id, "binance_auto_config", "{}"))
    except (ValueError, TypeError):
        auto_config = AutoTradingConfig()
    readiness = safe_auto_status(auto_config, spot_verified=spot, futures_verified=futures,
                                  worker_ready=False, protection_ready=False)
    return {"mode": "demo_testnet", "spot_connected": spot, "futures_connected": futures,
            "auto_trading_enabled": _get(db, user.id, "binance_auto_trading_enabled") == "true",
            "execution": "disabled_until_worker_and_protection_validation",
            "auto_config": auto_config.model_dump(), "readiness": readiness, "risk": settings}


def _risk_settings(db: Session, user_id: int) -> dict:
    import json
    try:
        value = json.loads(_get(db, user_id, "binance_risk_settings", "{}"))
    except (TypeError, ValueError):
        value = {}
    return {"max_trades_per_day": int(value.get("max_trades_per_day", 1)),
            "max_open_trades": int(value.get("max_open_trades", 1)),
            "risk_per_trade_percent": float(value.get("risk_per_trade_percent", 0.5)),
            "max_daily_loss_percent": float(value.get("max_daily_loss_percent", 2))}


@router.put("/risk")
def save_binance_risk(payload: BinanceRiskSettings, db: Session = Depends(get_db)):
    import json
    user = _workspace(db)
    _set(db, user.id, "binance_risk_settings", json.dumps(payload.model_dump(), separators=(",", ":")))
    db.commit()
    return {"saved": True, "risk": payload.model_dump()}


@router.get("/auto-config")
def get_binance_auto_config(db: Session = Depends(get_db)):
    user = _workspace(db)
    try:
        config = AutoTradingConfig.model_validate_json(_get(db, user.id, "binance_auto_config", "{}"))
    except (ValueError, TypeError):
        config = AutoTradingConfig()
    return {"config": config.model_dump(), "mode": "BINANCE_TESTNET"}


@router.put("/auto-config")
def save_binance_auto_config(payload: AutoTradingConfig, db: Session = Depends(get_db)):
    import json
    user = _workspace(db)
    payload.enabled = False
    _set(db, user.id, "binance_auto_config", json.dumps(payload.model_dump(), separators=(",", ":")))
    _set(db, user.id, "binance_auto_trading_enabled", "false")
    db.commit()
    return {"saved": True, "enabled": False, "config": payload.model_dump(),
            "message": "Testnet auto-trading policy saved. Execution remains OFF until worker and protective-order validation pass."}


@router.put("/auto-trading")
def set_binance_auto_trading(payload: BinanceAutoTrading, db: Session = Depends(get_db)):
    user = _workspace(db)
    if payload.enabled:
        if not (_get(db, user.id, "binance_spot_api_key_enc") and _get(db, user.id, "binance_futures_api_key_enc")):
            raise HTTPException(status_code=409, detail="Connect and verify both Binance testnet accounts first.")
        raise HTTPException(status_code=409, detail="Signal-to-order execution is not enabled in this release. Demo connection and risk controls are ready; Auto Trading remains safely OFF.")
    _set(db, user.id, "binance_auto_trading_enabled", "false")
    db.commit()
    return {"enabled": False, "message": "Auto Trading is OFF."}


@router.delete("/connect")
def disconnect_binance(db: Session = Depends(get_db)):
    user = _workspace(db)
    for key in ("binance_spot_api_key_enc", "binance_spot_api_secret_enc",
                "binance_futures_api_key_enc", "binance_futures_api_secret_enc",
                "binance_connection_mode", "binance_auto_trading_enabled"):
        row = db.scalar(select(Preference).where(Preference.user_id == user.id, Preference.key == key))
        if row:
            db.delete(row)
    db.commit()
    return {"connected": False, "auto_trading_enabled": False}


@router.post("/test")
async def test_binance_connection(db: Session = Depends(get_db)):
    user = _workspace(db)
    values = {
        "spot": ("binance_spot_api_key_enc", "binance_spot_api_secret_enc", SPOT_BASE, "/api/v3/account"),
        "futures": ("binance_futures_api_key_enc", "binance_futures_api_secret_enc", FUTURES_BASE, "/fapi/v2/account"),
    }
    results = {}
    for name, (key_name, secret_name, base, path) in values.items():
        key_enc, secret_enc = _get(db, user.id, key_name), _get(db, user.id, secret_name)
        if not key_enc or not secret_enc:
            results[name] = {"connected": False, "reason": "Not configured"}
            continue
        try:
            account = await _verify(base, decrypt_secret(key_enc), decrypt_secret(secret_enc), path)
            results[name] = {"connected": True, "can_trade": bool(account.get("canTrade"))}
        except (ValueError, HTTPException) as exc:
            results[name] = {"connected": False, "reason": exc.detail if isinstance(exc, HTTPException) else "Stored credentials could not be decrypted"}
    return {"mode": "demo_testnet", "results": results}

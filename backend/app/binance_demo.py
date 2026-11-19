"""Secure Binance Spot + USD-M Futures Demo Trading connections and controls.

This release verifies Demo Trading credentials, stores them encrypted in the
local workspace, and persists risk/automation controls. It does not submit orders.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Preference, User
from .security import decrypt_secret, encrypt_secret
from .binance_auto_config import AutoTradingConfig, safe_auto_status
from .binance_spot_engine import WORKER_STATE, normalize_config as normalize_spot_config, _account as spot_account, _credentials as spot_credentials, _symbol_info as spot_symbol_info

router = APIRouter(prefix="/api/v1/exchanges/binance", tags=["Binance demo"])

SPOT_BASE = "https://demo-api.binance.com"
FUTURES_BASE = "https://demo-fapi.binance.com"


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
            raise HTTPException(status_code=422, detail="Binance Demo Trading rejected the credentials. Check that both values are the Demo API key/secret pair, that the key is active, and that API access is permitted.")
        if response.status_code == 429 or response.status_code >= 500:
            raise HTTPException(status_code=503, detail="Binance Demo Trading is temporarily rate-limited or unavailable. Try again shortly.")
        if response.status_code >= 400:
            try:
                payload = response.json()
                code = payload.get("code")
                message = payload.get("msg", "Binance credential check failed.")
                detail = f"Binance error {code}: {message}" if code is not None else message
            except ValueError:
                detail = "Binance credential check failed."
            raise HTTPException(status_code=422, detail=str(detail)[:240])
        data = response.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="Binance returned an unexpected account response.")
        return data
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Binance Demo Trading connection timed out.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach Binance Demo Trading. Check the internet connection.")

def _store_credentials(db: Session, user_id: int, exchange: str, api_key: str, api_secret: str) -> None:
    """Update only one exchange credential pair; never overwrite the other venue."""
    prefix = "binance_spot" if exchange == "spot" else "binance_futures"
    _set(db, user_id, prefix + "_api_key_enc", encrypt_secret(api_key.strip()))
    _set(db, user_id, prefix + "_api_secret_enc", encrypt_secret(api_secret.strip()))
    _set(db, user_id, "binance_connection_mode", "demo")


def _credential_keys(exchange: str) -> tuple[str, str, str, str]:
    if exchange == "spot":
        return ("binance_spot_api_key_enc", "binance_spot_api_secret_enc", SPOT_BASE, "/api/v3/account")
    if exchange == "futures":
        return ("binance_futures_api_key_enc", "binance_futures_api_secret_enc", FUTURES_BASE, "/fapi/v3/account")
    raise ValueError("Unsupported Binance Demo Trading market.")


class BinanceConnect(BaseModel):
    spot_api_key: str = Field(min_length=1, max_length=256)
    spot_api_secret: str = Field(min_length=1, max_length=256)
    futures_api_key: str = Field(min_length=1, max_length=256)
    futures_api_secret: str = Field(min_length=1, max_length=256)


class BinanceCredentialPair(BaseModel):
    api_key: str = Field(min_length=1, max_length=256)
    api_secret: str = Field(min_length=1, max_length=256)

    @field_validator("api_key", "api_secret")
    @classmethod
    def strip_and_require_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("API key and secret cannot be blank.")
        return value


class BinanceRiskSettings(BaseModel):
    max_trades_per_day: int = Field(default=1, ge=1, le=50)
    max_open_trades: int = Field(default=1, ge=1, le=20)
    risk_per_trade_percent: float = Field(default=0.5, gt=0, le=2, allow_inf_nan=False)
    max_daily_loss_percent: float = Field(default=2, gt=0, le=5, allow_inf_nan=False)


class BinanceAutoTrading(BaseModel):
    enabled: bool = False


class BinanceSpotAutoConfig(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    interval_seconds: int = Field(default=30, ge=15, le=300)
    min_score: int = Field(default=8, ge=4, le=20)
    risk_per_trade_percent: float = Field(default=0.5, gt=0, le=1, allow_inf_nan=False)
    max_open_trades: int = Field(default=1, ge=1, le=3)
    max_trades_per_day: int = Field(default=3, ge=1, le=10)
    max_daily_loss_percent: float = Field(default=2, gt=0, le=2, allow_inf_nan=False)
    max_spread_bps: float = Field(default=12, gt=0, le=50, allow_inf_nan=False)
    min_24h_quote_volume: float = Field(default=10000000, ge=100000, allow_inf_nan=False)
    min_reward_risk: float = Field(default=1.5, ge=1.5, le=5, allow_inf_nan=False)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, values):
        cleaned = list(dict.fromkeys(str(x).strip().upper() for x in values if str(x).strip()))
        if not cleaned or len(cleaned) > 30 or any(not x.isalnum() or not x.endswith("USDT") for x in cleaned):
            raise ValueError("Choose 1–30 valid Binance Spot USDT symbols.")
        return cleaned


@router.post("/connect")
async def connect_binance(payload: BinanceConnect, db: Session = Depends(get_db)):
    user = _workspace(db)
    spot = await _verify(SPOT_BASE, payload.spot_api_key.strip(), payload.spot_api_secret.strip(), "/api/v3/account")
    futures = await _verify(FUTURES_BASE, payload.futures_api_key.strip(), payload.futures_api_secret.strip(), "/fapi/v3/account")
    for key, value in (
        ("binance_spot_api_key_enc", encrypt_secret(payload.spot_api_key.strip())),
        ("binance_spot_api_secret_enc", encrypt_secret(payload.spot_api_secret.strip())),
        ("binance_futures_api_key_enc", encrypt_secret(payload.futures_api_key.strip())),
        ("binance_futures_api_secret_enc", encrypt_secret(payload.futures_api_secret.strip())),
    ):
        _set(db, user.id, key, value)
    _set(db, user.id, "binance_connection_mode", "demo")
    _set(db, user.id, "binance_auto_trading_enabled", "false")
    db.commit()
    return {
        "connected": True,
        "mode": "binance_demo",
        "spot": {"connected": True, "can_trade": bool(spot.get("canTrade"))},
        "futures": {"connected": True, "can_trade": bool(futures.get("canTrade"))},
        "message": "Both Binance Demo Trading accounts verified. No orders were placed.",
    }


@router.post("/connect/spot")
async def connect_binance_spot(payload: BinanceCredentialPair, db: Session = Depends(get_db)):
    user = _workspace(db)
    account = await _verify(SPOT_BASE, payload.api_key.strip(), payload.api_secret.strip(), "/api/v3/account")
    _store_credentials(db, user.id, "spot", payload.api_key, payload.api_secret)
    db.commit()
    return {"connected": True, "exchange": "spot", "mode": "binance_demo",
            "can_trade": bool(account.get("canTrade")),
            "message": "Binance Spot Demo Trading credentials verified and saved. Futures credentials were left unchanged."}


@router.post("/connect/futures")
async def connect_binance_futures(payload: BinanceCredentialPair, db: Session = Depends(get_db)):
    user = _workspace(db)
    account = await _verify(FUTURES_BASE, payload.api_key.strip(), payload.api_secret.strip(), "/fapi/v3/account")
    _store_credentials(db, user.id, "futures", payload.api_key, payload.api_secret)
    db.commit()
    return {"connected": True, "exchange": "futures", "mode": "binance_demo",
            "can_trade": bool(account.get("canTrade")),
            "message": "Binance USD-M Futures Demo Trading credentials verified and saved. Spot credentials were left unchanged."}


@router.delete("/connect/spot")
def disconnect_binance_spot(db: Session = Depends(get_db)):
    import json
    user = _workspace(db)
    config = normalize_spot_config(_get(db, user.id, "binance_spot_auto_config", ""))
    config["enabled"] = False
    _set(db, user.id, "binance_spot_auto_config", json.dumps(config, separators=(",", ":")))
    _set(db, user.id, "binance_auto_trading_enabled", "false")
    for key in ("binance_spot_api_key_enc", "binance_spot_api_secret_enc"):
        row = db.scalar(select(Preference).where(Preference.user_id == user.id, Preference.key == key))
        if row:
            db.delete(row)
    db.commit()
    return {"connected": False, "exchange": "spot"}


@router.delete("/connect/futures")
def disconnect_binance_futures(db: Session = Depends(get_db)):
    user = _workspace(db)
    for key in ("binance_futures_api_key_enc", "binance_futures_api_secret_enc"):
        row = db.scalar(select(Preference).where(Preference.user_id == user.id, Preference.key == key))
        if row:
            db.delete(row)
    db.commit()
    return {"connected": False, "exchange": "futures"}


@router.post("/test/spot")
async def test_binance_spot(db: Session = Depends(get_db)):
    return await _test_exchange_connection(db, "spot")


@router.post("/test/futures")
async def test_binance_futures(db: Session = Depends(get_db)):
    return await _test_exchange_connection(db, "futures")


async def _test_exchange_connection(db: Session, exchange: str) -> dict:
    user = _workspace(db)
    key_name, secret_name, base, path = _credential_keys(exchange)
    key_enc, secret_enc = _get(db, user.id, key_name), _get(db, user.id, secret_name)
    if not key_enc or not secret_enc:
        return {"exchange": exchange, "connected": False, "reason": "Not configured"}
    try:
        account = await _verify(base, decrypt_secret(key_enc), decrypt_secret(secret_enc), path)
        return {"exchange": exchange, "connected": True, "can_trade": bool(account.get("canTrade"))}
    except (ValueError, HTTPException) as exc:
        return {"exchange": exchange, "connected": False,
                "reason": exc.detail if isinstance(exc, HTTPException) else "Stored credentials could not be decrypted"}


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
    spot_auto = normalize_spot_config(_get(db, user.id, "binance_spot_auto_config", ""))
    active = []
    try:
        active = json.loads(_get(db, user.id, "binance_spot_active_trades", "[]"))
    except (TypeError, ValueError):
        active = []
    spot_enabled = _get(db, user.id, "binance_auto_trading_enabled") == "true"
    return {"mode": "binance_demo", "spot_connected": spot, "futures_connected": futures,
            "credential_storage": "encrypted_local_database",
            "auto_trading_enabled": spot_enabled,
            "execution": "spot_demo_market_buy_with_exchange_oco_exits",
            "spot_auto_config": spot_auto, "spot_worker": dict(WORKER_STATE),
            "spot_open_trades": len(active) if isinstance(active, list) else 0,
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
    return {"config": config.model_dump(), "mode": "BINANCE_DEMO"}


@router.put("/auto-config")
def save_binance_auto_config(payload: AutoTradingConfig, db: Session = Depends(get_db)):
    import json
    user = _workspace(db)
    payload.enabled = False
    _set(db, user.id, "binance_auto_config", json.dumps(payload.model_dump(), separators=(",", ":")))
    _set(db, user.id, "binance_auto_trading_enabled", "false")
    db.commit()
    return {"saved": True, "enabled": False, "config": payload.model_dump(),
            "message": "Demo Trading auto-trading policy saved. Execution remains OFF until worker and protective-order validation pass."}


@router.put("/auto-trading")
def set_binance_auto_trading(payload: BinanceAutoTrading, db: Session = Depends(get_db)):
    user = _workspace(db)
    if payload.enabled:
        if not (_get(db, user.id, "binance_spot_api_key_enc") and _get(db, user.id, "binance_futures_api_key_enc")):
            raise HTTPException(status_code=409, detail="Connect the exchange credentials required by your selected market modes first.")
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
        "futures": ("binance_futures_api_key_enc", "binance_futures_api_secret_enc", FUTURES_BASE, "/fapi/v3/account"),
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
    return {"mode": "binance_demo", "results": results}


@router.get("/spot-auto-config")
def get_spot_auto_config(db: Session = Depends(get_db)):
    user = _workspace(db)
    config = normalize_spot_config(_get(db, user.id, "binance_spot_auto_config", ""))
    config["enabled"] = _get(db, user.id, "binance_auto_trading_enabled") == "true"
    return {"config": config, "mode": "BINANCE_DEMO_SPOT_ONLY"}


@router.put("/spot-auto-config")
def save_spot_auto_config(payload: BinanceSpotAutoConfig, db: Session = Depends(get_db)):
    import json
    user = _workspace(db)
    config = normalize_spot_config(payload.model_dump())
    config["enabled"] = False
    _set(db, user.id, "binance_spot_auto_config", json.dumps(config, separators=(",", ":")))
    _set(db, user.id, "binance_auto_trading_enabled", "false")
    db.commit()
    return {"saved": True, "enabled": False, "config": config,
            "message": "Spot Demo automation settings saved. Trading remains OFF until explicitly started."}


@router.put("/spot-auto-trading")
async def set_spot_auto_trading(payload: BinanceAutoTrading, db: Session = Depends(get_db)):
    import json
    user = _workspace(db)
    config = normalize_spot_config(_get(db, user.id, "binance_spot_auto_config", ""))
    if not payload.enabled:
        config["enabled"] = False
        _set(db, user.id, "binance_spot_auto_config", json.dumps(config, separators=(",", ":")))
        _set(db, user.id, "binance_auto_trading_enabled", "false")
        db.commit()
        return {"enabled": False, "message": "New Spot Demo entries stopped. Existing Binance OCO protective orders remain active at Binance."}
    if not (_get(db, user.id, "binance_spot_api_key_enc") and _get(db, user.id, "binance_spot_api_secret_enc")):
        raise HTTPException(status_code=409, detail="Connect Binance Spot Demo credentials first.")
    if not WORKER_STATE.get("running"):
        raise HTTPException(status_code=503, detail="Spot Demo execution worker is not running. Restart QUANTNEX and retry.")
    try:
        api_key, secret = spot_credentials(db, user.id)
        account = await spot_account(api_key, secret)
        for symbol in config["symbols"]:
            await spot_symbol_info(symbol)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    config["enabled"] = True
    _set(db, user.id, "binance_spot_auto_config", json.dumps(config, separators=(",", ":")))
    _set(db, user.id, "binance_auto_trading_enabled", "true")
    db.commit()
    return {"enabled": True, "can_trade": bool(account.get("canTrade")),
            "message": "Spot Demo Auto Trading enabled. BUY entries only; every filled entry must receive exchange-native OCO take-profit and stop-loss protection."}

"""Local Prop Firm Challenge simulator with an optional MT5 DEMO-only guardian."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal, get_db
from .models import Preference, User

router = APIRouter(prefix="/api/v1/prop-challenge", tags=["prop-firm-challenge"])
_STATE_KEY = "prop_challenge_state"
_mt5 = None
_mt5_connected = False
_mt5_login: int | None = None
_mt5_server: str | None = None
_mt5_terminal_path: str | None = None
_mt5_last_error: str | None = None


class ChallengeCreate(BaseModel):
    mode: Literal["virtual", "mt5_demo"] = "virtual"
    starting_balance: float = Field(gt=0, le=100_000_000)
    profit_target_pct: float = Field(default=10, gt=0, le=100)
    daily_loss_pct: float = Field(default=5, gt=0, le=50)
    max_loss_pct: float = Field(default=10, gt=0, le=90)
    minimum_trading_days: int = Field(default=5, ge=0, le=365)
    timezone: str = Field(default="Asia/Colombo", min_length=1, max_length=64)
    drawdown_type: Literal["static", "trailing"] = "static"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid IANA timezone, such as Asia/Colombo.")
        return value

    @field_validator("max_loss_pct")
    @classmethod
    def loss_limits_are_consistent(cls, value: float, info):
        daily = info.data.get("daily_loss_pct")
        if daily is not None and value < daily:
            raise ValueError("Maximum loss must be at least as large as daily loss.")
        return value


class VirtualTradeResult(BaseModel):
    pnl: float = Field(ge=-100_000_000, le=100_000_000)
    symbol: str = Field(default="XAUUSD", min_length=1, max_length=20)


class MT5ConnectRequest(BaseModel):
    login: int = Field(gt=0)
    password: SecretStr = Field(min_length=1, max_length=256)
    server: str = Field(min_length=1, max_length=128)
    terminal_path: str | None = Field(default=None, max_length=500)


def _workspace_user(db: Session = Depends(get_db)) -> User:
    user = db.scalar(select(User).order_by(User.id))
    if user is None:
        user = User(email="local@quantnex.invalid", password_hash="")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _load_state(db: Session, user_id: int) -> dict:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == _STATE_KEY))
    if row is None:
        return {"challenge": None, "virtual_trades": []}
    try:
        value = json.loads(row.value)
        if isinstance(value, dict):
            value.setdefault("challenge", None)
            value.setdefault("virtual_trades", [])
            return value
    except (TypeError, ValueError):
        pass
    return {"challenge": None, "virtual_trades": []}


def _save_state(db: Session, user_id: int, state: dict) -> None:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == _STATE_KEY))
    value = json.dumps(state, separators=(",", ":"), allow_nan=False)
    if row is None:
        db.add(Preference(user_id=user_id, key=_STATE_KEY, value=value))
    else:
        row.value = value
    db.commit()


def _now_for(challenge: dict) -> datetime:
    return datetime.now(timezone.utc).astimezone(ZoneInfo(challenge["timezone"]))


def _metrics(challenge: dict, equity: float, balance: float) -> dict:
    start = float(challenge["starting_balance"])
    daily_start = float(challenge.get("daily_start_equity", start))
    peak = float(challenge.get("peak_equity", start))
    daily_limit = daily_start * float(challenge["daily_loss_pct"]) / 100
    max_loss_amount = start * float(challenge["max_loss_pct"]) / 100
    max_floor = peak - max_loss_amount if challenge["drawdown_type"] == "trailing" else start - max_loss_amount
    target = start * (1 + float(challenge["profit_target_pct"]) / 100)
    return {
        "balance": round(balance, 2), "equity": round(equity, 2),
        "daily_loss_amount": round(max(0.0, daily_start - equity), 2),
        "daily_loss_limit": round(daily_limit, 2),
        "daily_loss_remaining": round(max(0.0, equity - (daily_start - daily_limit)), 2),
        "daily_loss_used_pct": round(max(0.0, daily_start - equity) / daily_limit * 100, 2) if daily_limit else 0,
        "max_loss_floor": round(max_floor, 2),
        "max_drawdown_amount": round(max(0.0, start - equity) if challenge["drawdown_type"] == "static" else max(0.0, peak - equity), 2),
        "profit_target_equity": round(target, 2), "profit_target_remaining": round(max(0.0, target - equity), 2),
        "peak_equity": round(peak, 2),
    }


def _evaluate(challenge: dict, equity: float, balance: float, now: datetime) -> tuple[dict, str | None]:
    metrics = _metrics(challenge, equity, balance)
    if challenge["status"] != "ACTIVE":
        return metrics, None
    daily_floor = float(challenge.get("daily_start_equity", challenge["starting_balance"])) - metrics["daily_loss_limit"]
    reason = None
    if equity <= daily_floor:
        reason = "Daily maximum loss breached."
    elif equity <= metrics["max_loss_floor"]:
        reason = "Maximum overall loss breached."
    elif equity >= metrics["profit_target_equity"] and len(set(challenge.get("trading_days", []))) >= int(challenge["minimum_trading_days"]):
        challenge["status"] = "PASSED"
        challenge["status_reason"] = "Profit target reached and minimum trading days completed."
    if reason:
        challenge["status"] = "FAILED"
        challenge["status_reason"] = reason
        challenge["failed_at"] = now.isoformat()
    return metrics, reason


def _mt5_module():
    global _mt5
    if os.name != "nt":
        return None
    if _mt5 is None:
        try:
            import MetaTrader5 as package
            _mt5 = package
        except ImportError:
            return None
    return _mt5


def _disconnect_mt5() -> None:
    global _mt5_connected, _mt5_login, _mt5_server, _mt5_terminal_path
    if _mt5 is not None and _mt5_connected:
        try:
            _mt5.shutdown()
        except Exception:
            pass
    _mt5_connected = False
    _mt5_login = None
    _mt5_server = None
    _mt5_terminal_path = None


def _mt5_account():
    global _mt5_last_error
    if not _mt5_connected or _mt5 is None:
        return None
    try:
        account = _mt5.account_info()
        if account is None:
            _mt5_last_error = "MT5 account information is unavailable."
            return None
        if int(account.trade_mode) != int(_mt5.ACCOUNT_TRADE_MODE_DEMO):
            _mt5_last_error = "Account mode changed; only DEMO accounts are allowed."
            _disconnect_mt5()
            return None
        return account
    except Exception:
        _mt5_last_error = "MT5 connection check failed."
        return None


def _close_all_demo_positions() -> dict:
    account = _mt5_account()
    if account is None:
        return {"attempted": 0, "closed": 0, "failures": ["MT5 demo account is not connected."]}
    positions = _mt5.positions_get()
    if positions is None:
        return {"attempted": 0, "closed": 0, "failures": ["Could not read MT5 positions: " + str(_mt5.last_error())]}
    closed, failures = 0, []
    for position in positions:
        tick = _mt5.symbol_info_tick(position.symbol)
        if tick is None:
            failures.append(f"{position.symbol} #{position.ticket}: no current tick.")
            continue
        is_buy = int(position.type) == int(_mt5.POSITION_TYPE_BUY)
        order_type = _mt5.ORDER_TYPE_SELL if is_buy else _mt5.ORDER_TYPE_BUY
        price = tick.bid if is_buy else tick.ask
        request = {
            "action": _mt5.TRADE_ACTION_DEAL, "symbol": position.symbol,
            "volume": float(position.volume), "type": order_type,
            "position": int(position.ticket), "price": float(price),
            "deviation": 30, "magic": 261112, "comment": "QUANTNEX Prop Guardian",
            "type_time": _mt5.ORDER_TIME_GTC, "type_filling": _mt5.ORDER_FILLING_IOC,
        }
        if _mt5_account() is None:
            failures.append("Demo account disconnected or account mode changed; remaining positions were not touched.")
            break
        result = _mt5.order_send(request)
        if result is not None and int(result.retcode) in {
            int(_mt5.TRADE_RETCODE_DONE), int(getattr(_mt5, "TRADE_RETCODE_DONE_PARTIAL", -1))
        }:
            closed += 1
        else:
            code = getattr(result, "retcode", None) if result is not None else _mt5.last_error()
            failures.append(f"{position.symbol} #{position.ticket}: broker rejected close ({code}).")
    return {"attempted": len(positions), "closed": closed, "failures": failures}


def _mt5_trading_days(challenge: dict) -> list[str]:
    if not _mt5_connected or _mt5 is None:
        return list(challenge.get("trading_days", []))
    try:
        start = datetime.fromisoformat(challenge["created_at"])
        deals = _mt5.history_deals_get(start, datetime.now(timezone.utc))
        if deals is None:
            return list(challenge.get("trading_days", []))
        zone = ZoneInfo(challenge["timezone"])
        days = set(challenge.get("trading_days", []))
        for deal in deals:
            timestamp = getattr(deal, "time", None)
            if timestamp and getattr(deal, "symbol", ""):
                days.add(datetime.fromtimestamp(timestamp, timezone.utc).astimezone(zone).date().isoformat())
        return sorted(days)
    except Exception:
        return list(challenge.get("trading_days", []))


def _monitor_mt5_once() -> None:
    if not _mt5_connected:
        return
    account = _mt5_account()
    if account is None:
        return
    db = SessionLocal()
    try:
        user = db.scalar(select(User).order_by(User.id))
        if user is None:
            return
        state = _load_state(db, user.id)
        challenge = state.get("challenge")
        if not challenge or challenge.get("mode") != "mt5_demo" or challenge.get("status") not in {"ACTIVE", "FAILED"}:
            return
        now = _now_for(challenge)
        today = now.date().isoformat()
        equity, balance = float(account.equity), float(account.balance)
        if challenge.get("daily_reset_date") != today:
            challenge["daily_reset_date"] = today
            challenge["daily_start_equity"] = equity
        challenge["peak_equity"] = max(float(challenge.get("peak_equity", equity)), equity)
        challenge["trading_days"] = _mt5_trading_days(challenge)
        challenge["equity"], challenge["balance"] = equity, balance
        if challenge.get("status") == "FAILED":
            metrics, breach = _metrics(challenge, equity, balance), challenge.get("status_reason") or "Challenge failed."
        else:
            metrics, breach = _evaluate(challenge, equity, balance, now)
        challenge["last_checked_at"] = now.isoformat()
        challenge["last_metrics"] = metrics
        if breach:
            last_attempt = challenge.get("guardian_attempt_at")
            due = True
            if last_attempt:
                try:
                    due = (now - datetime.fromisoformat(last_attempt)).total_seconds() >= 2
                except ValueError:
                    pass
            if due:
                challenge["guardian_attempt_at"] = now.isoformat()
                challenge["guardian_action"] = _close_all_demo_positions()
                challenge["guardian_action_at"] = now.isoformat()
        _save_state(db, user.id, state)
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        print("[QUANTNEX] Prop Guardian monitor error: " + type(exc).__name__, flush=True)
    finally:
        db.close()


async def mt5_guardian_worker() -> None:
    while True:
        if _mt5_connected:
            await asyncio.to_thread(_monitor_mt5_once)
        await asyncio.sleep(1.0)


@router.get("/state")
def get_challenge_state(user: User = Depends(_workspace_user), db: Session = Depends(get_db)):
    state = _load_state(db, user.id)
    challenge = state.get("challenge")
    connection = {"connected": False, "login": None, "server": None, "last_error": _mt5_last_error}
    if _mt5_connected:
        account = _mt5_account()
        if account is not None:
            connection = {"connected": True, "login": int(account.login), "server": str(account.server),
                          "currency": str(account.currency), "balance": round(float(account.balance), 2),
                          "equity": round(float(account.equity), 2), "last_error": None}
    if challenge:
        if challenge.get("mode") == "mt5_demo" and connection["connected"]:
            metrics = _metrics(challenge, connection["equity"], connection["balance"])
            challenge["last_metrics"] = metrics
        elif challenge.get("mode") == "virtual":
            metrics = _metrics(challenge, float(challenge["equity"]), float(challenge["balance"]))
        else:
            metrics = challenge.get("last_metrics") or {}
        return {"challenge": challenge, "metrics": metrics, "mt5": connection, "recent_trades": state.get("virtual_trades", [])[-20:]}
    return {"challenge": None, "metrics": {}, "mt5": connection, "recent_trades": []}


@router.post("/challenge", status_code=201)
def create_challenge(payload: ChallengeCreate, user: User = Depends(_workspace_user), db: Session = Depends(get_db)):
    state = _load_state(db, user.id)
    current = state.get("challenge")
    if current and current.get("status") == "ACTIVE":
        raise HTTPException(status_code=409, detail="An active challenge already exists. Reset it before creating another.")
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(payload.timezone)).date().isoformat()
    challenge = {
        "id": now.strftime("%Y%m%d%H%M%S%f"), "mode": payload.mode, "status": "ACTIVE",
        "status_reason": "Challenge created. Risk monitoring is active for the selected mode.",
        "starting_balance": float(payload.starting_balance), "balance": float(payload.starting_balance),
        "equity": float(payload.starting_balance), "profit_target_pct": float(payload.profit_target_pct),
        "daily_loss_pct": float(payload.daily_loss_pct), "max_loss_pct": float(payload.max_loss_pct),
        "minimum_trading_days": int(payload.minimum_trading_days), "timezone": payload.timezone,
        "drawdown_type": payload.drawdown_type, "daily_start_equity": float(payload.starting_balance),
        "daily_reset_date": today, "peak_equity": float(payload.starting_balance),
        "trading_days": [], "created_at": now.isoformat(),
    }
    state["challenge"], state["virtual_trades"] = challenge, []
    _save_state(db, user.id, state)
    return {"challenge": challenge, "metrics": _metrics(challenge, challenge["equity"], challenge["balance"])}


@router.post("/virtual-trades", status_code=201)
def record_virtual_trade(payload: VirtualTradeResult, user: User = Depends(_workspace_user), db: Session = Depends(get_db)):
    state = _load_state(db, user.id)
    challenge = state.get("challenge")
    if not challenge or challenge.get("mode") != "virtual":
        raise HTTPException(status_code=409, detail="Create an active Virtual Practice challenge first.")
    if challenge.get("status") != "ACTIVE":
        raise HTTPException(status_code=409, detail="This challenge is locked. Reset it before recording another trade.")
    now = _now_for(challenge)
    today = now.date().isoformat()
    if challenge.get("daily_reset_date") != today:
        challenge["daily_reset_date"], challenge["daily_start_equity"] = today, float(challenge["equity"])
    pnl = float(payload.pnl)
    challenge["balance"] = round(float(challenge["balance"]) + pnl, 8)
    challenge["equity"] = challenge["balance"]
    challenge["peak_equity"] = max(float(challenge.get("peak_equity", challenge["starting_balance"])), challenge["equity"])
    days = set(challenge.get("trading_days", []));days.add(today);challenge["trading_days"] = sorted(days)
    trade = {"time": now.isoformat(), "symbol": payload.symbol.strip().upper(), "pnl": round(pnl, 2), "balance_after": round(challenge["balance"], 2)}
    state.setdefault("virtual_trades", []).append(trade)
    metrics, breach = _evaluate(challenge, challenge["equity"], challenge["balance"], now)
    if not breach and challenge["status"] == "ACTIVE" and challenge["equity"] >= metrics["profit_target_equity"] and len(challenge["trading_days"]) < challenge["minimum_trading_days"]:
        challenge["status_reason"] = "Profit target reached. Complete the remaining minimum trading days without breaching a rule."
    elif not breach and challenge["status"] == "ACTIVE":
        challenge["status_reason"] = "Trade recorded. Challenge remains active."
    _save_state(db, user.id, state)
    return {"challenge": challenge, "metrics": metrics, "trade": trade}


@router.post("/mt5/connect")
def connect_mt5(payload: MT5ConnectRequest, user: User = Depends(_workspace_user), db: Session = Depends(get_db)):
    global _mt5_connected, _mt5_login, _mt5_server, _mt5_terminal_path, _mt5_last_error
    state = _load_state(db, user.id);challenge = state.get("challenge")
    if not challenge or challenge.get("mode") != "mt5_demo" or challenge.get("status") != "ACTIVE":
        raise HTTPException(status_code=409, detail="Create an active MT5 Demo challenge before connecting.")
    package = _mt5_module()
    if package is None:
        raise HTTPException(status_code=503, detail="MT5 bridge unavailable. On Windows, install MetaTrader 5 and the MetaTrader5 Python package in the QUANTNEX backend environment.")
    _disconnect_mt5()
    password = payload.password.get_secret_value()
    args = {"login": int(payload.login), "password": password, "server": payload.server, "timeout": 60000}
    if payload.terminal_path:args["path"] = payload.terminal_path
    try:initialized = package.initialize(**args)
    except Exception:initialized = False
    finally:
        password = ""
        args["password"] = ""
    if not initialized:
        _mt5_last_error = "MT5 initialize failed. Check terminal path, login, password, server and terminal availability."
        raise HTTPException(status_code=400, detail=_mt5_last_error)
    account = package.account_info()
    if account is None or int(account.trade_mode) != int(package.ACCOUNT_TRADE_MODE_DEMO):
        package.shutdown();_mt5_last_error = "Only MT5 DEMO accounts are permitted. REAL and CONTEST accounts are blocked."
        raise HTTPException(status_code=403, detail=_mt5_last_error)
    _mt5_connected = True;_mt5_login = int(account.login);_mt5_server = str(account.server)
    _mt5_terminal_path = payload.terminal_path;_mt5_last_error = None
    challenge["starting_balance"] = float(account.balance);challenge["balance"] = float(account.balance)
    challenge["equity"] = float(account.equity);challenge["daily_start_equity"] = float(account.equity)
    challenge["daily_reset_date"] = _now_for(challenge).date().isoformat()
    challenge["peak_equity"] = float(account.equity);challenge["created_at"] = datetime.now(timezone.utc).isoformat()
    challenge["trading_days"] = [];challenge["currency"] = str(account.currency)
    _save_state(db, user.id, state)
    return {"connected": True, "login": int(account.login), "server": str(account.server),
            "currency": str(account.currency), "balance": round(float(account.balance), 2),
            "equity": round(float(account.equity), 2), "mode": "DEMO",
            "note": "Password was used only for this connection and was not saved."}


@router.post("/mt5/disconnect")
def disconnect_mt5():
    _disconnect_mt5()
    return {"connected": False, "note": "MT5 demo connection closed. The challenge remains saved."}


@router.post("/reset")
def reset_challenge(user: User = Depends(_workspace_user), db: Session = Depends(get_db)):
    _disconnect_mt5();_save_state(db, user.id, {"challenge": None, "virtual_trades": []})
    return {"reset": True}


@router.get("/mt5/status")
def mt5_status():
    account = _mt5_account()
    if account is None:return {"connected": False, "login": None, "server": None, "last_error": _mt5_last_error}
    return {"connected": True, "login": int(account.login), "server": str(account.server),
            "currency": str(account.currency), "balance": round(float(account.balance), 2),
            "equity": round(float(account.equity), 2), "mode": "DEMO"}

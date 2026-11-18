"""Testnet-only auto-trading policy and risk primitives. No order submission or live URL."""
from __future__ import annotations
import hashlib
import math
from decimal import Decimal, ROUND_DOWN
from typing import Any
from pydantic import BaseModel, Field, model_validator


class AutoTradingConfig(BaseModel):
    enabled: bool = False
    environment: str = "BINANCE_TESTNET"
    market_modes: list[str] = Field(default_factory=lambda: ["SPOT", "USD_M_FUTURES"])
    strategies: list[str] = Field(default_factory=lambda: ["SCALPING", "SWING"])
    max_trades_per_day: int = Field(default=5, ge=1, le=30)
    max_open_positions: int = Field(default=2, ge=1, le=5)
    risk_per_trade_percent: float = Field(default=0.5, gt=0, le=1, allow_inf_nan=False)
    max_daily_loss_percent: float = Field(default=2, gt=0, le=3, allow_inf_nan=False)
    max_total_drawdown_percent: float = Field(default=5, gt=0, le=10, allow_inf_nan=False)
    futures_leverage_cap: int = Field(default=3, ge=1, le=3)
    futures_margin_type: str = "ISOLATED"
    dca_enabled: bool = False
    dca_max_addons: int = Field(default=0, ge=0, le=1)
    min_24h_quote_volume: float = Field(default=10_000_000, gt=0, allow_inf_nan=False)
    max_spread_bps: float = Field(default=12, gt=0, le=100, allow_inf_nan=False)
    min_reward_risk: float = Field(default=1.5, ge=1, le=5, allow_inf_nan=False)
    max_signal_age_seconds: int = Field(default=90, ge=5, le=600)

    @model_validator(mode="after")
    def validate_testnet_policy(self):
        if self.environment != "BINANCE_TESTNET":
            raise ValueError("Only BINANCE_TESTNET is supported.")
        if self.futures_margin_type != "ISOLATED":
            raise ValueError("Futures must use ISOLATED margin.")
        if not self.dca_enabled and self.dca_max_addons:
            raise ValueError("DCA add-ons must be zero while DCA is disabled.")
        if any(x not in {"SPOT", "USD_M_FUTURES"} for x in self.market_modes):
            raise ValueError("Unsupported market mode.")
        if any(x not in {"SCALPING", "SWING"} for x in self.strategies):
            raise ValueError("Unsupported strategy.")
        return self


def eligible_usdt_symbols(exchange_info: dict[str, Any]) -> set[str]:
    stable = {"USDT", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD"}
    excluded = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
    result = set()
    for item in exchange_info.get("symbols", []):
        symbol = str(item.get("symbol", "")).upper()
        base = str(item.get("baseAsset", "")).upper()
        if (item.get("status") == "TRADING" and item.get("quoteAsset") == "USDT"
                and item.get("isSpotTradingAllowed") is not False and symbol.endswith("USDT")
                and not any(symbol.endswith(x) for x in excluded) and base not in stable):
            result.add(symbol)
    return result


def filter_by_quote_volume(symbols: set[str], tickers: list[dict[str, Any]], minimum: float) -> set[str]:
    result = set()
    for row in tickers:
        try:
            volume = float(row.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue
        symbol = str(row.get("symbol", "")).upper()
        if symbol in symbols and math.isfinite(volume) and volume >= minimum:
            result.add(symbol)
    return result


def calculate_position_quantity(*, equity: float, risk_percent: float, entry: float, stop: float,
                                step_size: str, min_qty: str = "0", max_qty: str | None = None,
                                max_notional: float | None = None) -> Decimal:
    vals = (equity, risk_percent, entry, stop)
    if not all(math.isfinite(v) and v > 0 for v in vals) or entry == stop:
        raise ValueError("Equity, risk, entry and stop must be finite positive values.")
    step = Decimal(step_size)
    if step <= 0:
        raise ValueError("Invalid exchange quantity step.")
    risk_cash = equity * risk_percent / 100
    qty = Decimal(str(risk_cash / abs(entry - stop)))
    qty = (qty / step).to_integral_value(rounding=ROUND_DOWN) * step
    if max_notional is not None:
        cap = Decimal(str(max_notional / entry))
        qty = min(qty, (cap / step).to_integral_value(rounding=ROUND_DOWN) * step)
    if max_qty is not None:
        qty = min(qty, Decimal(max_qty))
    if qty <= 0 or qty < Decimal(min_qty):
        raise ValueError("Quantity is below exchange minimum.")
    if float(qty) * abs(entry - stop) > risk_cash * 1.000001:
        raise ValueError("Quantity exceeds configured stop risk.")
    return qty


def select_futures_leverage(symbol_max: int, configured_cap: int = 3) -> int:
    if symbol_max < 1 or configured_cap < 1:
        raise ValueError("Leverage limits must be positive.")
    return min(symbol_max, configured_cap, 3)


def validate_protection(side: str, entry: float, stop: float, target: float, min_rr: float = 1.5) -> None:
    if not all(math.isfinite(v) and v > 0 for v in (entry, stop, target)):
        raise ValueError("Protection prices must be finite and positive.")
    side = side.upper()
    if side == "BUY" and stop < entry < target:
        rr = (target - entry) / (entry - stop)
    elif side == "SELL" and target < entry < stop:
        rr = (entry - target) / (stop - entry)
    else:
        raise ValueError("Invalid stop/target geometry.")
    if rr < min_rr:
        raise ValueError("Reward-to-risk is below the configured minimum.")


def stable_event_id(user_id: int, event_type: str, order_id: str, status: str) -> str:
    return hashlib.sha256("|".join(map(str, (user_id, event_type, order_id, status))).encode()).hexdigest()


def safe_auto_status(config: AutoTradingConfig, *, spot_verified: bool, futures_verified: bool,
                     worker_ready: bool, protection_ready: bool) -> dict[str, Any]:
    selected_modes = set(config.market_modes)
    checks = {"testnet_only": config.environment == "BINANCE_TESTNET",
              "spot_credentials": ("SPOT" not in selected_modes) or spot_verified,
              "futures_credentials": ("USD_M_FUTURES" not in selected_modes) or futures_verified,
              "execution_worker": worker_ready, "protective_orders": protection_ready}
    ready = all(checks.values())
    return {"enabled": bool(config.enabled and ready), "ready": ready, "checks": checks,
            "mode": "BINANCE_TESTNET"}

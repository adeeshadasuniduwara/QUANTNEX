"""Deterministic accounting primitives for QUANTNEX paper-position partial exits.

These helpers are intentionally broker-free. They calculate simulated fills only;
they do not fetch prices, create trades, or send orders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Literal

Side = Literal["BUY", "SELL"]
CENT = Decimal("0.01")


def _decimal(value: object, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a valid number.") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite.")
    return result


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class PaperExit:
    quantity: Decimal
    price: Decimal
    gross_pnl: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    net_pnl: Decimal
    reason: str


@dataclass
class PaperPositionLedger:
    """A single simulated position with fee-aware partial close accounting."""

    symbol: str
    side: Side
    entry_price: Decimal
    original_quantity: Decimal
    entry_fee_rate: Decimal = Decimal("0")
    exit_fee_rate: Decimal = Decimal("0")
    contract_multiplier: Decimal = Decimal("1")
    remaining_quantity: Decimal = field(init=False)
    exits: list[PaperExit] = field(default_factory=list)
    break_even_armed: bool = False

    def __post_init__(self) -> None:
        self.side = str(self.side).upper()  # type: ignore[assignment]
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL.")
        self.entry_price = _decimal(self.entry_price, "entry_price")
        self.original_quantity = _decimal(self.original_quantity, "original_quantity")
        self.entry_fee_rate = _decimal(self.entry_fee_rate, "entry_fee_rate")
        self.exit_fee_rate = _decimal(self.exit_fee_rate, "exit_fee_rate")
        self.contract_multiplier = _decimal(self.contract_multiplier, "contract_multiplier")
        if self.entry_price <= 0 or self.original_quantity <= 0 or self.contract_multiplier <= 0:
            raise ValueError("Entry price, quantity and contract multiplier must be positive.")
        if not (Decimal("0") <= self.entry_fee_rate <= Decimal("0.1")):
            raise ValueError("entry_fee_rate must be between 0 and 0.1.")
        if not (Decimal("0") <= self.exit_fee_rate <= Decimal("0.1")):
            raise ValueError("exit_fee_rate must be between 0 and 0.1.")
        self.remaining_quantity = self.original_quantity

    @property
    def realized_gross_pnl(self) -> Decimal:
        return sum((item.gross_pnl for item in self.exits), Decimal("0"))

    @property
    def realized_fees(self) -> Decimal:
        return sum((item.entry_fee + item.exit_fee for item in self.exits), Decimal("0"))

    @property
    def realized_net_pnl(self) -> Decimal:
        return sum((item.net_pnl for item in self.exits), Decimal("0"))

    @property
    def closed(self) -> bool:
        return self.remaining_quantity <= 0

    def close_quantity(self, quantity: object, exit_price: object, reason: str) -> PaperExit:
        qty = _decimal(quantity, "quantity")
        price = _decimal(exit_price, "exit_price")
        if self.closed:
            raise ValueError("This paper position is already fully closed.")
        if qty <= 0 or qty > self.remaining_quantity:
            raise ValueError("Exit quantity must be positive and no greater than remaining quantity.")
        if price <= 0:
            raise ValueError("exit_price must be positive.")
        if not reason.strip():
            raise ValueError("An exit reason is required.")

        direction = Decimal("1") if self.side == "BUY" else Decimal("-1")
        notional_entry = self.entry_price * qty * self.contract_multiplier
        notional_exit = price * qty * self.contract_multiplier
        gross = (price - self.entry_price) * qty * self.contract_multiplier * direction
        # Allocate the original entry fee pro-rata across every partial exit.
        entry_fee = notional_entry * self.entry_fee_rate
        exit_fee = notional_exit * self.exit_fee_rate
        item = PaperExit(
            quantity=qty,
            price=price,
            gross_pnl=_money(gross),
            entry_fee=_money(entry_fee),
            exit_fee=_money(exit_fee),
            net_pnl=_money(gross - entry_fee - exit_fee),
            reason=reason.strip(),
        )
        self.exits.append(item)
        self.remaining_quantity -= qty
        if reason.strip().upper() in {"TP1", "TAKE_PROFIT_1"}:
            self.break_even_armed = True
        return item

    def close_remaining_at_break_even(self, exit_price: object | None = None) -> PaperExit:
        """Close the remaining quantity at entry after TP1; costs still apply."""
        if not self.break_even_armed:
            raise ValueError("Break-even exit is only allowed after a TP1 partial exit.")
        return self.close_quantity(
            self.remaining_quantity,
            self.entry_price if exit_price is None else exit_price,
            "BREAK_EVEN_AFTER_TP1",
        )

    def summary(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": str(self.entry_price),
            "original_quantity": str(self.original_quantity),
            "remaining_quantity": str(self.remaining_quantity),
            "closed": self.closed,
            "break_even_armed": self.break_even_armed,
            "exit_count": len(self.exits),
            "realized_gross_pnl": str(_money(self.realized_gross_pnl)),
            "realized_fees": str(_money(self.realized_fees)),
            "realized_net_pnl": str(_money(self.realized_net_pnl)),
            "exits": [
                {
                    "quantity": str(item.quantity),
                    "price": str(item.price),
                    "gross_pnl": str(item.gross_pnl),
                    "entry_fee": str(item.entry_fee),
                    "exit_fee": str(item.exit_fee),
                    "net_pnl": str(item.net_pnl),
                    "reason": item.reason,
                }
                for item in self.exits
            ],
        }

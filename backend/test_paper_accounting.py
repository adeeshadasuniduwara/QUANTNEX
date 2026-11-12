from decimal import Decimal

import pytest

from app.paper_accounting import PaperPositionLedger


def test_tp1_profit_is_retained_when_remaining_quantity_returns_to_entry():
    ledger = PaperPositionLedger("BTCUSDT", "BUY", Decimal("100"), Decimal("1"))
    first = ledger.close_quantity(Decimal("0.5"), Decimal("110"), "TP1")
    final = ledger.close_remaining_at_break_even()
    assert first.gross_pnl == Decimal("5.00")
    assert final.gross_pnl == Decimal("0.00")
    assert ledger.closed
    assert ledger.realized_gross_pnl == Decimal("5.00")
    assert ledger.realized_net_pnl == Decimal("5.00")


def test_break_even_after_tp1_still_deducts_fees():
    ledger = PaperPositionLedger("ETHUSDT", "BUY", "100", "1",
                                 entry_fee_rate="0.001", exit_fee_rate="0.001")
    ledger.close_quantity("0.5", "110", "TP1")
    ledger.close_remaining_at_break_even()
    assert ledger.realized_gross_pnl == Decimal("5.00")
    assert ledger.realized_fees == Decimal("0.21")
    assert ledger.realized_net_pnl == Decimal("4.79")


def test_sell_partial_exit_calculates_positive_profit():
    ledger = PaperPositionLedger("BTCUSDT", "SELL", "100", "2")
    exit_fill = ledger.close_quantity("1", "90", "TP1")
    assert exit_fill.gross_pnl == Decimal("10.00")


def test_cannot_close_more_than_remaining_quantity():
    ledger = PaperPositionLedger("BTCUSDT", "BUY", "100", "1")
    with pytest.raises(ValueError):
        ledger.close_quantity("1.1", "110", "TP1")


def test_break_even_is_not_available_before_tp1():
    ledger = PaperPositionLedger("BTCUSDT", "BUY", "100", "1")
    with pytest.raises(ValueError):
        ledger.close_remaining_at_break_even()

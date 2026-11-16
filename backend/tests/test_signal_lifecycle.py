from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import SignalTradeEvent, User
from app.signal_lifecycle import process_trade_candles, record_signal


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    user = User(email="signal-lifecycle@quantnex.invalid", password_hash="")
    db.add(user)
    db.commit()
    return db, user


def _signal(now, side="BUY"):
    entry, stop, targets = (100.0, 95.0, (105.0, 110.0, 115.0)) if side == "BUY" else (100.0, 105.0, (95.0, 90.0, 85.0))
    return {"symbol": "BTCUSDT", "side": side, "timeframe": "1m", "entry_type": "MARKET",
            "entry": entry, "stop_loss": stop, "tp1": targets[0], "tp2": targets[1],
            "tp3": targets[2], "signal_time": now.isoformat()}


def _bar(at, op, high, low, close):
    return {"time": at.isoformat(), "open": op, "high": high, "low": low, "close": close, "volume": 10}


def test_staged_targets_update_virtual_stop_and_complete_in_order():
    db, user = _session()
    now = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
    trade, created = record_signal(db, user.id, _signal(now))
    assert created is True
    bars = [_bar(now + timedelta(minutes=1), 100, 106, 99, 105),
            _bar(now + timedelta(minutes=2), 106, 111, 105, 110),
            _bar(now + timedelta(minutes=3), 111, 116, 110, 115)]
    assert process_trade_candles(db, trade, bars) == 3
    assert trade.tp1_hit and trade.tp2_hit and trade.tp3_hit
    assert trade.active_stop_loss == trade.tp1
    assert trade.status == "TARGETS_COMPLETE"
    assert trade.realized_r == 1.9
    events = list(db.scalars(select(SignalTradeEvent).where(
        SignalTradeEvent.trade_id == trade.id).order_by(SignalTradeEvent.id)))
    assert [event.event_type for event in events] == ["TP1_HIT", "TP2_HIT", "TP3_HIT"]
    db.close()


def test_tp1_then_breakeven_exit_preserves_partial_reward():
    db, user = _session()
    now = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
    trade, _ = record_signal(db, user.id, _signal(now))
    process_trade_candles(db, trade, [
        _bar(now + timedelta(minutes=1), 100, 106, 99, 105),
        _bar(now + timedelta(minutes=2), 102, 104, 99, 100)])
    assert trade.tp1_hit is True
    assert trade.status == "PROTECTED_EXIT"
    assert trade.active_stop_loss == trade.entry_price
    assert trade.realized_r == 0.4
    db.close()


def test_original_stop_before_tp1_is_a_loss():
    db, user = _session()
    now = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
    trade, _ = record_signal(db, user.id, _signal(now))
    process_trade_candles(db, trade, [_bar(now + timedelta(minutes=1), 100, 102, 94, 96)])
    assert trade.status == "STOPPED"
    assert trade.realized_r == -1.0
    db.close()


def test_signal_generation_candle_cannot_stop_trade_before_entry():
    db, user = _session()
    now = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
    trade, _ = record_signal(db, user.id, _signal(now))
    # The signal candle includes pre-entry movement through the stop; ignore it.
    process_trade_candles(db, trade, [_bar(now, 100, 102, 94, 96)])
    assert trade.status == "OPEN"
    assert trade.realized_r == 0.0
    # The next fully closed candle is post-entry and may confirm the SL.
    process_trade_candles(db, trade, [_bar(now + timedelta(minutes=1), 100, 102, 94, 96)])
    assert trade.status == "STOPPED"
    assert trade.realized_r == -1.0
    db.close()


def test_history_gap_pauses_replay_instead_of_guessing_a_later_target():
    db, user = _session()
    now = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
    trade, _ = record_signal(db, user.id, _signal(now))
    processed = process_trade_candles(db, trade, [
        _bar(now + timedelta(minutes=2), 100, 106, 99, 105)])
    assert processed == 0
    assert trade.recovery_status == "PARTIAL"
    assert trade.status == "OPEN"
    assert trade.tp1_hit is False
    db.close()


def test_same_bar_stop_and_target_is_ambiguous_not_a_guessed_win():
    db, user = _session()
    now = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
    trade, _ = record_signal(db, user.id, _signal(now))
    process_trade_candles(db, trade, [_bar(now + timedelta(minutes=1), 100, 106, 94, 101)])
    assert trade.status == "OPEN"
    assert trade.tp1_hit is False
    assert trade.realized_r == 0.0
    # A later unambiguous TP candle resolves the still-active position.
    process_trade_candles(db, trade, [_bar(now + timedelta(minutes=2), 101, 106, 100, 105)])
    assert trade.status == "OPEN"
    assert trade.tp1_hit is True
    db.close()


def test_restart_replay_is_idempotent_and_duplicate_signal_is_deduplicated():
    db, user = _session()
    now = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
    trade, created = record_signal(db, user.id, _signal(now))
    duplicate, duplicate_created = record_signal(db, user.id, _signal(now))
    assert created is True and duplicate_created is False
    assert duplicate.id == trade.id
    first = _bar(now + timedelta(minutes=1), 100, 106, 99, 105)
    second = _bar(now + timedelta(minutes=2), 106, 111, 105, 110)
    process_trade_candles(db, trade, [first])
    process_trade_candles(db, trade, [first, second])
    events = list(db.scalars(select(SignalTradeEvent).where(
        SignalTradeEvent.trade_id == trade.id).order_by(SignalTradeEvent.id)))
    assert [event.event_type for event in events] == ["TP1_HIT", "TP2_HIT"]
    db.close()


def test_staged_r_result_uses_actual_target_distance_not_fixed_one_two_three_r():
    db, user = _session()
    now = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
    signal = _signal(now)
    signal.update({"tp1": 106.0, "tp2": 113.0, "tp3": 125.0})
    trade, _ = record_signal(db, user.id, signal)
    process_trade_candles(db, trade, [
        _bar(now + timedelta(minutes=1), 100, 106, 99, 105),
        _bar(now + timedelta(minutes=2), 106, 113, 105, 110),
        _bar(now + timedelta(minutes=3), 113, 126, 110, 125)])
    assert trade.status == "TARGETS_COMPLETE"
    assert trade.realized_r == 2.76
    db.close()


def test_live_signal_refresh_deduplicates_same_active_direction_until_exit():
    db, user = _session()
    now = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
    first, created = record_signal(db, user.id, _signal(now))
    later, later_created = record_signal(db, user.id, _signal(now + timedelta(minutes=8)))
    assert created is True
    assert later_created is False
    assert later.id == first.id
    db.close()


def test_sell_direction_targets_are_evaluated_correctly():
    db, user = _session()
    now = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
    trade, _ = record_signal(db, user.id, _signal(now, "SELL"))
    process_trade_candles(db, trade, [
        _bar(now + timedelta(minutes=1), 100, 101, 94, 95),
        _bar(now + timedelta(minutes=2), 94.8, 94.9, 89, 90),
        _bar(now + timedelta(minutes=3), 89.8, 89.9, 84, 85)])
    assert trade.status == "TARGETS_COMPLETE"
    assert trade.tp1_hit and trade.tp2_hit and trade.tp3_hit
    assert trade.realized_r == 1.9
    db.close()

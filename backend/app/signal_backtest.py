"""Chronological, paper-only replay of the QUANTNEX multi-timeframe signal engine."""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .signal_engine import build_signal, round_price_to_tick
from .order_flow_replay import replay_spot_order_flow_events

TIMEFRAME_MINUTES = {"1": 1, "5": 5, "15": 15, "30": 30, "50": 50, "60": 60, "240": 240}


def _epoch(value: str) -> float:
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def _snapshot_epoch(value: Any, label: str) -> float:
    """Parse a persisted observation timestamp without accepting naive local time."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a timezone-aware ISO timestamp.")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{label} must be a timezone-aware ISO timestamp.") from None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware.")
    return stamp.astimezone(timezone.utc).timestamp()


def _validate_order_flow_observations(
    observations: list[dict[str, Any]], symbol: str
) -> list[float]:
    """Validate the persisted Spot snapshot sequence before chronological replay."""
    if not isinstance(observations, list):
        raise ValueError("Order-flow replay observations must be a list.")
    epochs: list[float] = []
    previous = float("-inf")
    for index, record in enumerate(observations):
        if not isinstance(record, dict):
            raise ValueError(f"Order-flow observation {index} must be an object.")
        if record.get("market_type") != "BINANCE_SPOT" or record.get("symbol") != symbol:
            raise ValueError("Order-flow replay observations must match the requested Binance Spot symbol.")
        captured = _snapshot_epoch(record.get("captured_at"), "captured_at")
        if captured <= previous:
            raise ValueError("Order-flow observations must have unique, strictly increasing capture timestamps.")
        epochs.append(captured)
        previous = captured
    return epochs


def _select_order_flow_snapshot(
    observations: list[dict[str, Any]],
    observation_epochs: list[float],
    symbol: str,
    as_of_epoch: float,
    settings: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Select only the latest prior snapshot and recompute source age at decision time.

    Missing, stale, malformed, gapped or future-dated snapshots return an empty
    override so the existing order-flow gate rejects a candidate. No older
    snapshot is forward-filled across a stale interval.
    """
    index = bisect_right(observation_epochs, as_of_epoch + 1e-6) - 1
    if index < 0:
        return {}, "MISSING"
    record = observations[index]
    try:
        captured = _snapshot_epoch(record.get("captured_at"), "captured_at")
        if captured > as_of_epoch + 1e-6:
            return {}, "FUTURE"
        if record.get("capture_version") != 2 or record.get("capture_scope") != "ONE_UTC_MINUTE_FEATURE_SNAPSHOT":
            return {}, "INVALID"
        if record.get("symbol") != symbol or record.get("market_type") != "BINANCE_SPOT":
            return {}, "INVALID"

        trade_state = record.get("trade_state")
        depth_book = record.get("depth_book")
        snapshot = record.get("order_flow")
        if not all(isinstance(value, dict) for value in (trade_state, depth_book, snapshot)):
            return {}, "INVALID"
        if trade_state.get("coverage_complete") is not True or trade_state.get("gap_detected") is not False:
            return {}, "INVALID"
        trade_id = trade_state.get("last_agg_trade_id")
        if isinstance(trade_id, bool) or not isinstance(trade_id, int) or trade_id < 0:
            return {}, "INVALID"
        if depth_book.get("valid") is not True or depth_book.get("sequence_validated") is not True:
            return {}, "INVALID"
        if not isinstance(depth_book.get("bids"), list) or not depth_book["bids"]:
            return {}, "INVALID"
        if not isinstance(depth_book.get("asks"), list) or not depth_book["asks"]:
            return {}, "INVALID"
        update_id = depth_book.get("last_update_id")
        if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
            return {}, "INVALID"
        if (
            snapshot.get("market_type") != "BINANCE_SPOT"
            or snapshot.get("feed_mode") != "PUBLIC_WEBSOCKET_STREAM"
            or snapshot.get("depth_is_continuous") is not True
            or snapshot.get("cvd_status") != "COMPLETE_SINCE_STATE_SEED"
            or snapshot.get("depth_snapshot_update_id") != update_id
        ):
            return {}, "INVALID"
        trade_count = snapshot.get("trade_count")
        if isinstance(trade_count, bool) or not isinstance(trade_count, int) or trade_count < 1:
            return {}, "INVALID"
        provenance = snapshot.get("data_provenance")
        sources = snapshot.get("data_sources")
        book_metrics = snapshot.get("order_book")
        if not isinstance(provenance, dict) or not isinstance(sources, dict) or not isinstance(book_metrics, dict):
            return {}, "INVALID"
        if (
            provenance.get("candle_volume_used") is not False
            or "aggressor" not in str(provenance.get("bid_ask_semantics") or "").lower()
            or not str(sources.get("stream") or "").startswith("wss://")
        ):
            return {}, "INVALID"

        trade_epoch = _snapshot_epoch(snapshot.get("last_trade_at"), "last_trade_at")
        depth_epoch = _snapshot_epoch(snapshot.get("depth_observed_at"), "depth_observed_at")
        if trade_epoch > as_of_epoch + 1e-6 or depth_epoch > as_of_epoch + 1e-6:
            return {}, "FUTURE"
        if trade_epoch > captured + 2.0 or depth_epoch > captured + 2.0:
            return {}, "INVALID"

        trade_age = as_of_epoch - trade_epoch
        depth_age = as_of_epoch - depth_epoch
        max_trade_age = float(settings.get("max_order_flow_trade_age_seconds", 15.0))
        max_depth_age = float(settings.get("max_order_book_snapshot_age_seconds", 5.0))
        if (
            not math.isfinite(max_trade_age) or max_trade_age <= 0
            or not math.isfinite(max_depth_age) or max_depth_age <= 0
        ):
            raise ValueError("Order-flow replay freshness settings must be finite and positive.")
        if trade_age < 0 or depth_age < 0:
            return {}, "FUTURE"
        if trade_age > max_trade_age or depth_age > max_depth_age:
            return {}, "STALE"

        replay_snapshot = dict(snapshot)
        replay_snapshot["trade_data_age_seconds"] = round(trade_age, 3)
        return replay_snapshot, "AVAILABLE"
    except (TypeError, ValueError, OverflowError):
        return {}, "INVALID"


def _validate_raw_order_flow_checkpoints(
    checkpoints: list[dict[str, Any]], symbol: str
) -> list[float]:
    """Validate receive-time replay checkpoints before chronological selection."""
    if not isinstance(checkpoints, list):
        raise ValueError("Raw Order Flow replay checkpoints must be a list.")
    normalized_symbol = str(symbol or "").strip().upper()
    epochs: list[float] = []
    previous_ms = -1
    for index, record in enumerate(checkpoints):
        if not isinstance(record, dict):
            raise ValueError(f"Raw Order Flow checkpoint {index} must be an object.")
        if (
            record.get("market_type") != "BINANCE_SPOT"
            or record.get("symbol") != normalized_symbol
        ):
            raise ValueError("Raw Order Flow checkpoints must match the requested Binance Spot symbol.")
        if (
            record.get("feed_mode") != "RAW_EVENT_REPLAY"
            or record.get("capture_clock") != "RECEIVED_AT_MS"
            or record.get("capture_scope") != "RECEIVE_TIME_BUCKET"
            or record.get("coverage_is_complete") is not False
        ):
            raise ValueError("Raw Order Flow checkpoint provenance or bounded-coverage declaration is invalid.")
        decision_ms = record.get("decision_at_ms")
        if isinstance(decision_ms, bool) or not isinstance(decision_ms, int) or decision_ms <= 0:
            raise ValueError("Raw Order Flow checkpoint decision_at_ms must be a positive integer.")
        if decision_ms <= previous_ms:
            raise ValueError("Raw Order Flow checkpoints must have unique, strictly increasing decision times.")
        decision_epoch = _snapshot_epoch(record.get("decision_at"), "decision_at")
        if abs(decision_epoch * 1000 - decision_ms) > 2:
            raise ValueError("Raw Order Flow checkpoint decision timestamp fields disagree.")
        if not isinstance(record.get("eligible_for_order_flow_replay"), bool):
            raise ValueError("Raw Order Flow checkpoint must declare replay eligibility.")
        epochs.append(decision_epoch)
        previous_ms = decision_ms
    return epochs


def _select_raw_order_flow_snapshot(
    checkpoints: list[dict[str, Any]],
    checkpoint_epochs: list[float],
    symbol: str,
    as_of_epoch: float,
    settings: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Adapt only the latest prior, fresh, sequence-valid raw replay checkpoint.

    The archive remains bounded and cannot prove full-session completeness. A
    later invalid checkpoint is never bypassed in favour of an older good one.
    """
    index = bisect_right(checkpoint_epochs, as_of_epoch + 1e-6) - 1
    if index < 0:
        return {}, "MISSING"
    record = checkpoints[index]
    try:
        if record.get("symbol") != symbol or record.get("market_type") != "BINANCE_SPOT":
            return {}, "INVALID"
        decision_epoch = _snapshot_epoch(record.get("decision_at"), "decision_at")
        if decision_epoch > as_of_epoch + 1e-6:
            return {}, "FUTURE"
        if record.get("eligible_for_order_flow_replay") is not True:
            return {}, (
                "STALE" if record.get("coverage_status") in {"TRADE_STALE", "DEPTH_STALE"}
                else "INVALID"
            )
        if record.get("coverage_is_complete") is not False:
            return {}, "INVALID"

        trade_state = record.get("trade_state")
        depth_book = record.get("depth_book")
        book_metrics = record.get("order_book")
        provenance = record.get("data_provenance")
        if not all(isinstance(value, dict) for value in (trade_state, depth_book, book_metrics, provenance)):
            return {}, "INVALID"
        if (
            trade_state.get("coverage_complete") is not True
            or trade_state.get("gap_detected") is not False
            or record.get("cvd_status") != "COMPLETE_SINCE_STATE_SEED"
            or depth_book.get("valid") is not True
            or depth_book.get("sequence_validated") is not True
            or record.get("depth_is_continuous") is not True
            or record.get("capture_gap_detected") is not False
            or record.get("coverage_status") != "OBSERVED_CONTIGUOUS_CAPTURE_NOT_FULL_SESSION"
            or record.get("delta_scope") != "WEBSOCKET_AND_BUFFER_AGGTRADES_RECEIVED_DURING_CAPTURE_BUCKET"
            or book_metrics.get("source") != "BINANCE_SPOT_SEQUENCE_VALIDATED_DEPTH_REPLAY"
            or trade_state.get("last_trade_time_ms") != record.get("last_trade_at_ms")
            or provenance.get("candle_volume_used") is not False
            or "aggressor" not in str(provenance.get("bid_ask_semantics") or "").lower()
        ):
            return {}, "INVALID"
        trade_id = trade_state.get("last_agg_trade_id")
        update_id = record.get("depth_snapshot_update_id")
        if isinstance(trade_id, bool) or not isinstance(trade_id, int) or trade_id < 0:
            return {}, "INVALID"
        if (
            isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0
            or depth_book.get("last_update_id") != update_id
            or not isinstance(depth_book.get("bids"), list) or not depth_book["bids"]
            or not isinstance(depth_book.get("asks"), list) or not depth_book["asks"]
        ):
            return {}, "INVALID"

        trade_count = record.get("live_trade_count")
        delta_ratio = record.get("delta_ratio")
        depth_imbalance = book_metrics.get("depth_imbalance")
        if isinstance(trade_count, bool) or not isinstance(trade_count, int) or trade_count < 1:
            return {}, "INVALID"
        delta_value = float(delta_ratio)
        depth_value = float(depth_imbalance)
        if (
            not math.isfinite(delta_value) or not math.isfinite(depth_value)
            or not -1.0 <= delta_value <= 1.0
            or not -1.0 <= depth_value <= 1.0
        ):
            return {}, "INVALID"

        trade_ms = record.get("last_trade_at_ms")
        depth_ms = record.get("last_depth_event_at_ms")
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (trade_ms, depth_ms)):
            return {}, "INVALID"
        decision_ms = record.get("decision_at_ms")
        if (
            isinstance(decision_ms, bool) or not isinstance(decision_ms, int)
            or trade_ms > decision_ms or depth_ms > decision_ms
        ):
            return {}, "FUTURE"
        trade_epoch = trade_ms / 1000.0
        depth_epoch = depth_ms / 1000.0
        if trade_epoch > as_of_epoch + 1e-6 or depth_epoch > as_of_epoch + 1e-6:
            return {}, "FUTURE"
        trade_age = as_of_epoch - trade_epoch
        depth_age = as_of_epoch - depth_epoch
        max_trade_age = float(settings.get("max_order_flow_trade_age_seconds", 15.0))
        max_depth_age = float(settings.get("max_order_book_snapshot_age_seconds", 5.0))
        if (
            not math.isfinite(max_trade_age) or max_trade_age <= 0
            or not math.isfinite(max_depth_age) or max_depth_age <= 0
        ):
            raise ValueError("Raw Order Flow replay freshness settings must be finite and positive.")
        if trade_age < 0 or depth_age < 0:
            return {}, "FUTURE"
        if trade_age > max_trade_age or depth_age > max_depth_age:
            return {}, "STALE"

        return {
            "market_type": "BINANCE_SPOT",
            "feed_mode": "RAW_EVENT_REPLAY",
            "trade_count": trade_count,
            "trade_data_age_seconds": round(trade_age, 3),
            "last_trade_at": datetime.fromtimestamp(trade_epoch, timezone.utc).isoformat(),
            "buy_volume": record.get("buy_volume"),
            "sell_volume": record.get("sell_volume"),
            "delta": record.get("delta"),
            "delta_ratio": delta_value,
            "window_cumulative_delta": record.get("cvd_value"),
            "window_delta_scope": record.get("cvd_scope"),
            "cvd_value": record.get("cvd_value"),
            "cvd_status": record.get("cvd_status"),
            "cvd_scope": record.get("cvd_scope"),
            "session_timezone": record.get("session_timezone", "UTC"),
            "session_delta": record.get("session_delta"),
            "session_delta_coverage_complete": record.get("session_delta_coverage_complete") is True,
            "session_delta_scope": record.get("session_delta_scope"),
            "depth_is_continuous": True,
            "depth_snapshot_update_id": update_id,
            "depth_observed_at": datetime.fromtimestamp(depth_epoch, timezone.utc).isoformat(),
            "order_book": dict(book_metrics),
            "data_provenance": {
                **provenance,
                "decision_clock": "RECEIVED_AT_MS",
                "capture_scope": "BOUNDED_RAW_ARCHIVE_NOT_FULL_SESSION",
                "depth_reconstruction": "REST snapshot plus sequence-applied diff-depth events",
            },
            "data_sources": {
                "stream": "RAW_BINANCE_SPOT_EVENT_ARCHIVE",
                "book": "BINANCE_SPOT_SEQUENCE_VALIDATED_DEPTH_REPLAY",
            },
            "replay_checkpoint_at": record.get("decision_at"),
            "coverage_status": record.get("coverage_status"),
            "coverage_is_complete": False,
        }, "AVAILABLE"
    except (TypeError, ValueError, OverflowError, KeyError):
        return {}, "INVALID"


def _replay_raw_order_flow_events(
    events: list[dict[str, Any]], symbol: str, replay_horizon_epoch: float
) -> list[dict[str, Any]]:
    """Rebuild causal Spot checkpoints no later than the closed-candle horizon."""
    if not isinstance(events, list):
        raise ValueError("Raw Order Flow events must be a list.")
    if not events:
        return []
    if isinstance(replay_horizon_epoch, bool) or not math.isfinite(float(replay_horizon_epoch)):
        raise ValueError("Raw Order Flow replay horizon must be a finite timestamp.")
    replay_clock = datetime.fromtimestamp(float(replay_horizon_epoch), timezone.utc)
    checkpoints = replay_spot_order_flow_events(events, symbol, now=replay_clock)
    _validate_raw_order_flow_checkpoints(checkpoints, symbol)
    return checkpoints



def _replay_execution_quotes(
    mid_price: float,
    tick_size: str,
    assumed_spread_bps: float,
) -> dict[str, float]:
    """Build an uncrossed, exchange-tick-aligned synthetic replay top of book.

    Historical candles do not contain historical bid/ask quotes. The replay
    therefore models a spread around the next candle open, rounds the bid down
    and ask up to the symbol tick, and reports the resulting (possibly wider)
    executable spread. This avoids rejecting valid replay entries merely
    because a synthetic unrounded quote is off tick.
    """
    if isinstance(mid_price, bool) or isinstance(assumed_spread_bps, bool):
        raise ValueError("Replay quote inputs must be numeric, not boolean.")
    try:
        mid = float(mid_price)
        spread = float(assumed_spread_bps)
        tick = Decimal(str(tick_size))
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        raise ValueError("Replay quote mid, spread and tick size must be valid numbers.") from None
    if (
        not math.isfinite(mid) or mid <= 0
        or not math.isfinite(spread) or spread < 0
        or not tick.is_finite() or tick <= 0
    ):
        raise ValueError("Replay quote mid/tick must be positive and spread must be finite and non-negative.")

    half_spread = spread / 20000.0
    best_bid = round_price_to_tick(mid * (1.0 - half_spread), str(tick), round_up=False)
    best_ask = round_price_to_tick(mid * (1.0 + half_spread), str(tick), round_up=True)
    if best_ask <= best_bid:
        best_ask = round_price_to_tick(best_bid + float(tick), str(tick), round_up=True)
    replay_mid = (best_bid + best_ask) / 2.0
    actual_spread_bps = (best_ask - best_bid) / replay_mid * 10000.0
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": replay_mid,
        "spread_bps": actual_spread_bps,
        "assumed_spread_bps": spread,
    }


def _limit_fill_price(side: str, limit_price: float, candle: dict[str, Any]) -> float | None:
    """Model a resting limit fill, including a favorable gap through the limit."""
    open_price = float(candle["open"])
    low = float(candle["low"])
    high = float(candle["high"])
    if side == "BUY":
        if open_price <= limit_price:
            return min(limit_price, open_price)
        if low <= limit_price:
            return limit_price
    else:
        if open_price >= limit_price:
            return max(limit_price, open_price)
        if high >= limit_price:
            return limit_price
    return None


def _stop_fill_price(side: str, stop: float, candle: dict[str, Any]) -> float:
    open_price = float(candle["open"])
    if side == "BUY" and open_price <= stop:
        return open_price
    if side == "SELL" and open_price >= stop:
        return open_price
    return stop


def _target_fill_price(side: str, target: float, candle: dict[str, Any]) -> float:
    open_price = float(candle["open"])
    if side == "BUY" and open_price >= target:
        return open_price
    if side == "SELL" and open_price <= target:
        return open_price
    return target


def _metrics(trades: list[dict[str, Any]], counters: dict[str, int], candles: list[dict[str, Any]],
             start_index: int, end_index: int, settings: dict[str, Any]) -> dict[str, Any]:
    wins = [trade for trade in trades if trade["net_pnl"] > 0]
    losses = [trade for trade in trades if trade["net_pnl"] < 0]
    gross_profit = sum(trade["net_pnl"] for trade in wins)
    gross_loss = abs(sum(trade["net_pnl"] for trade in losses))
    r_values = [trade["r_multiple"] for trade in trades]
    expectancy = sum(r_values) / len(r_values) if r_values else None
    expectancy_se = None
    expectancy_ci = None
    if len(r_values) >= 2 and expectancy is not None:
        variance = sum((value - expectancy) ** 2 for value in r_values) / (len(r_values) - 1)
        expectancy_se = math.sqrt(max(0.0, variance) / len(r_values))
        expectancy_ci = [
            round(expectancy - 1.96 * expectancy_se, 3),
            round(expectancy + 1.96 * expectancy_se, 3),
        ]

    win_rate_ci = None
    if trades:
        sample_size = len(trades)
        proportion = len(wins) / sample_size
        z_score = 1.96
        denominator = 1 + z_score * z_score / sample_size
        center = (proportion + z_score * z_score / (2 * sample_size)) / denominator
        margin = (
            z_score
            * math.sqrt(
                (proportion * (1 - proportion) + z_score * z_score / (4 * sample_size))
                / sample_size
            )
            / denominator
        )
        win_rate_ci = [
            round(max(0.0, center - margin) * 100, 2),
            round(min(1.0, center + margin) * 100, 2),
        ]

    equity = 0.0
    peak = 0.0
    max_drawdown_r = 0.0
    for value in r_values:
        equity += value
        peak = max(peak, equity)
        max_drawdown_r = max(max_drawdown_r, peak - equity)
    baseline = None
    # A decision at primary_times[start_index + 1] executes at that bar's open.
    # Compare buy-and-hold over the same execution window, not the preceding bar.
    if 0 <= start_index + 1 <= end_index < len(candles):
        first = float(candles[start_index + 1]["open"])
        last = float(candles[end_index]["close"])
        if first > 0:
            baseline = round((last / first - 1) * 100, 3)
    sample_bars = max(0, end_index - start_index)
    return {
        "sample_bars": sample_bars,
        "blocked_or_skipped_bars": max(
            0, sample_bars - counters["signals"] - counters["waits"]
        ),
        "signal_count": counters["signals"],
        "wait_count": counters["waits"],
        "trade_count": len(trades),
        "market_entries": counters["market"],
        "limit_entries": counters["limit"],
        "limit_expired": counters["limit_expired"],
        "limit_censored": counters.get("limit_censored", 0),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else None,
        "win_rate_95_ci_wilson_pct": win_rate_ci,
        "gross_pnl_quote": round(sum(trade["gross_pnl"] for trade in trades), 8),
        "estimated_cost_quote": round(sum(trade["estimated_cost"] for trade in trades), 8),
        "net_pnl_quote": round(sum(trade["net_pnl"] for trade in trades), 8),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else (
            "infinite" if gross_profit > 0 else None
        ),
        "expectancy_r": round(expectancy, 3) if expectancy is not None else None,
        "expectancy_r_standard_error": round(expectancy_se, 4) if expectancy_se is not None else None,
        "expectancy_r_95_ci_normal_approx": expectancy_ci,
        "confidence_interval_note": (
            "Win-rate interval uses the Wilson 95% method; expectancy interval is a descriptive normal approximation. "
            "Neither interval corrects for serial dependence, strategy selection or sparse/non-random order-flow coverage."
        ),
        "average_r": round(expectancy, 3) if expectancy is not None else None,
        "max_drawdown_r": round(max_drawdown_r, 3),
        "buy_and_hold_return_pct": baseline,
        "order_flow_replay_enabled": bool(counters.get("order_flow_enabled", 0)),
        "order_flow_raw_event_replay_enabled": bool(counters.get("order_flow_raw_event_replay_enabled", 0)),
        "order_flow_raw_event_checkpoint_matches": counters.get("order_flow_raw_event_checkpoint_matches", 0),
        "order_flow_decision_points": counters.get("order_flow_decision_points", 0),
        "order_flow_snapshot_matches": counters.get("order_flow_snapshot_matches", 0),
        "order_flow_missing_snapshots": counters.get("order_flow_missing_snapshots", 0),
        "order_flow_stale_snapshots": counters.get("order_flow_stale_snapshots", 0),
        "order_flow_invalid_snapshots": counters.get("order_flow_invalid_snapshots", 0),
        "order_flow_confirmed_candidates": counters.get("order_flow_confirmed_candidates", 0),
        "order_flow_rejected_candidates": counters.get("order_flow_rejected_candidates", 0),
        "order_flow_coverage_pct": round(
            counters.get("order_flow_snapshot_matches", 0)
            / counters.get("order_flow_decision_points", 1) * 100, 2
        ) if counters.get("order_flow_decision_points", 0) else None,
        "order_flow_candidate_confirmation_pct": round(
            counters.get("order_flow_confirmed_candidates", 0)
            / max(1, counters.get("order_flow_confirmed_candidates", 0) + counters.get("order_flow_rejected_candidates", 0)) * 100, 2
        ) if counters.get("order_flow_confirmed_candidates", 0) + counters.get("order_flow_rejected_candidates", 0) else None,
        "trades": trades[-200:],
    }


async def _simulate_slice(
    symbol: str,
    candles_by_tf: dict[str, list[dict[str, Any]]],
    symbol_info: dict[str, Any],
    settings: dict[str, Any],
    assumed_spread_bps: float,
    assumed_depth_usd: float,
    start_index: int,
    end_index: int,
    order_flow_observations: list[dict[str, Any]] | None = None,
    raw_order_flow_checkpoints: list[dict[str, Any]] | None = None,
    execution_end_epoch: float | None = None,
) -> dict[str, Any]:
    primary_tf = str(settings.get("primary", "5"))
    enabled = list(dict.fromkeys(
        [str(item) for item in settings.get("enabled", ["60", "30", "15", "5", "1"])]
        + [primary_tf, str(settings.get("trend", "60"))]
    ))
    if primary_tf not in TIMEFRAME_MINUTES:
        raise ValueError("Signal replay primary timeframe is unsupported.")
    primary = candles_by_tf.get(primary_tf, [])
    if len(primary) < 2:
        raise ValueError("Not enough primary timeframe history for signal replay.")

    timestamps = {
        tf: [_epoch(row["time"]) for row in rows]
        for tf, rows in candles_by_tf.items() if tf in TIMEFRAME_MINUTES
    }
    if order_flow_observations is not None and raw_order_flow_checkpoints is not None:
        raise ValueError("Choose feature snapshots or raw Order Flow checkpoints, not both.")
    observation_epochs = (
        _validate_order_flow_observations(order_flow_observations, symbol)
        if order_flow_observations is not None else None
    )
    raw_checkpoint_epochs = (
        _validate_raw_order_flow_checkpoints(raw_order_flow_checkpoints, symbol)
        if raw_order_flow_checkpoints is not None else None
    )
    counters = {
        "signals": 0, "waits": 0, "market": 0, "limit": 0,
        "limit_expired": 0, "limit_censored": 0,
        "order_flow_enabled": int(order_flow_observations is not None or raw_order_flow_checkpoints is not None),
        "order_flow_raw_event_replay_enabled": int(raw_order_flow_checkpoints is not None),
        "order_flow_raw_event_checkpoint_matches": 0,
        "order_flow_decision_points": 0, "order_flow_snapshot_matches": 0,
        "order_flow_missing_snapshots": 0, "order_flow_stale_snapshots": 0,
        "order_flow_invalid_snapshots": 0, "order_flow_confirmed_candidates": 0,
        "order_flow_rejected_candidates": 0,
    }
    trades: list[dict[str, Any]] = []
    index = max(0, start_index)
    end_index = min(end_index, len(primary) - 2)
    minute_rows = candles_by_tf.get("1", [])
    minute_times = timestamps.get("1", [])
    if not minute_rows or len(minute_rows) != len(minute_times):
        raise ValueError("One-minute execution history is required for historical fill simulation.")
    decision_end_epoch = timestamps[primary_tf][end_index + 1]
    if execution_end_epoch is None:
        execution_end_epoch = decision_end_epoch
    elif (
        isinstance(execution_end_epoch, bool)
        or not math.isfinite(float(execution_end_epoch))
        or float(execution_end_epoch) < decision_end_epoch
    ):
        raise ValueError("Replay execution end must be finite and no earlier than the decision-window end.")
    else:
        execution_end_epoch = float(execution_end_epoch)
    minute_end_index = bisect_left(minute_times, execution_end_epoch - 1e-6)
    if minute_end_index < 1:
        raise ValueError("One-minute execution history does not reach the replay decision window.")
    raw_filters = symbol_info.get("filters")
    raw_price_filter = raw_filters.get("PRICE_FILTER") if isinstance(raw_filters, dict) else None
    if not isinstance(raw_price_filter, dict):
        raise ValueError(
            "Binance Spot replay requires authoritative PRICE_FILTER metadata; no fallback tick size is allowed."
        )
    try:
        tick_value = Decimal(str(raw_price_filter.get("tickSize")))
        min_price_value = Decimal(str(raw_price_filter.get("minPrice") or "0"))
        max_price_value = Decimal(str(raw_price_filter.get("maxPrice") or "0"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Binance Spot replay received invalid PRICE_FILTER metadata.") from None
    if (
        not tick_value.is_finite() or tick_value <= 0
        or not min_price_value.is_finite() or min_price_value < 0
        or not max_price_value.is_finite() or max_price_value < 0
        or (min_price_value > 0 and max_price_value > 0 and max_price_value < min_price_value)
    ):
        raise ValueError("Binance Spot replay received invalid PRICE_FILTER bounds or tick size.")
    tick_size = str(tick_value)
    price_filter = {
        "tick_size": tick_size,
        "min_price": str(min_price_value),
        "max_price": str(max_price_value),
    }
    quote_asset = str(symbol_info.get("quote_asset") or "")
    stable_quotes = {"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "USDP", "DAI", "USDE"}

    while index <= end_index:
        as_of_epoch = timestamps[primary_tf][index + 1]
        if as_of_epoch >= decision_end_epoch:
            break
        as_of = datetime.fromtimestamp(as_of_epoch, timezone.utc)
        windows: dict[str, list[dict[str, Any]]] = {}
        enough_history = True
        for tf in enabled:
            rows = candles_by_tf.get(tf)
            tf_times = timestamps.get(tf)
            if rows is None or tf_times is None or tf not in TIMEFRAME_MINUTES:
                enough_history = False
                break
            cutoff = as_of_epoch - TIMEFRAME_MINUTES[tf] * 60
            eligible = bisect_right(tf_times, cutoff + 1e-6)
            if eligible < 210:
                enough_history = False
                break
            window_size = 3200 if tf == "1" and "50" in enabled else 320
            windows[tf] = rows[max(0, eligible - window_size):eligible]
        if not enough_history:
            index += 1
            continue

        next_bar = primary[index + 1]
        mid = float(next_bar["open"])
        if not math.isfinite(mid) or mid <= 0:
            index += 1
            continue
        modeled_quotes = _replay_execution_quotes(mid, tick_size, assumed_spread_bps)
        execution = {
            "symbol": symbol,
            "provider": "Historical Binance Spot replay",
            **modeled_quotes,
            "bid_depth_quote": assumed_depth_usd,
            "ask_depth_quote": assumed_depth_usd,
            "bid_depth_usd": assumed_depth_usd,
            "ask_depth_usd": assumed_depth_usd,
            "quote_asset": quote_asset,
            "quote_asset_usd_rate": 1.0 if quote_asset in stable_quotes else None,
            "quote_asset_usd_rate_source": "stablecoin_parity_assumption" if quote_asset in stable_quotes else "assumed_depth_usd",
            "tick_size": tick_size,
            "price_filter": price_filter,
            "tick_size_source": "BINANCE_EXCHANGEINFO_PRICE_FILTER",
            "step_size": str(symbol_info.get("filters", {}).get("LOT_SIZE", {}).get("stepSize") or ""),
            "min_quantity": str(symbol_info.get("filters", {}).get("LOT_SIZE", {}).get("minQty") or ""),
            "min_notional": str((symbol_info.get("filters", {}).get("NOTIONAL") or symbol_info.get("filters", {}).get("MIN_NOTIONAL") or {}).get("minNotional") or ""),
            "observed_at": as_of.isoformat(),
            "is_replay": True,
        }
        order_flow_override = None
        order_flow_mode = None
        if order_flow_observations is not None and observation_epochs is not None:
            order_flow_override, observation_status = _select_order_flow_snapshot(
                order_flow_observations, observation_epochs, symbol, as_of_epoch, settings
            )
            order_flow_mode = "HISTORICAL_FEATURE_SNAPSHOT_REPLAY"
        elif raw_order_flow_checkpoints is not None and raw_checkpoint_epochs is not None:
            order_flow_override, observation_status = _select_raw_order_flow_snapshot(
                raw_order_flow_checkpoints, raw_checkpoint_epochs, symbol, as_of_epoch, settings
            )
            order_flow_mode = "HISTORICAL_RAW_EVENT_REPLAY"

        if order_flow_mode is not None:
            counters["order_flow_decision_points"] += 1
            if observation_status == "AVAILABLE":
                counters["order_flow_snapshot_matches"] += 1
                if order_flow_mode == "HISTORICAL_RAW_EVENT_REPLAY":
                    counters["order_flow_raw_event_checkpoint_matches"] += 1
            elif observation_status == "MISSING":
                counters["order_flow_missing_snapshots"] += 1
            elif observation_status == "STALE":
                counters["order_flow_stale_snapshots"] += 1
            else:
                counters["order_flow_invalid_snapshots"] += 1

        build_kwargs = {
            "candles_override": windows,
            "execution_context_override": execution,
            "replay_as_of": as_of,
        }
        if order_flow_mode is not None:
            # An empty override deliberately fails the existing order-flow gate;
            # historical candidates must not silently fall back to candle-only.
            build_kwargs["order_flow_override"] = order_flow_override or {}
            build_kwargs["order_flow_mode_override"] = order_flow_mode
        result = await build_signal(settings, symbol, **build_kwargs)
        order_flow_result = result.get("order_flow") or {}
        if order_flow_result.get("data_mode") == "HISTORICAL_FEATURE_SNAPSHOT_REPLAY":
            if order_flow_result.get("accepted") is True:
                counters["order_flow_confirmed_candidates"] += 1
            elif order_flow_result.get("accepted") is False:
                counters["order_flow_rejected_candidates"] += 1
        signal = result.get("signal")
        if result.get("status") != "SIGNAL" or not signal:
            counters["waits"] += 1
            index += 1
            continue
        counters["signals"] += 1
        side = signal["side"]
        sign = 1 if side == "BUY" else -1
        entry_type = signal["entry_type"]
        minute_start = bisect_left(minute_times, as_of_epoch - 1e-6)
        if entry_type == "MARKET":
            if minute_start >= minute_end_index or abs(minute_times[minute_start] - as_of_epoch) > 1e-3:
                counters["waits"] += 1
                index += 1
                continue
            fill_index = minute_start
            entry_price = float(signal["entry"])
            counters["market"] += 1
        elif entry_type == "LIMIT":
            limit_price = float(signal["limit_price"])
            expiry_end_epoch = min(as_of_epoch + 900, execution_end_epoch)
            expiry_end_index = bisect_left(minute_times, expiry_end_epoch - 1e-6)
            fill_index = None
            entry_price = None
            for candidate_index in range(minute_start, min(expiry_end_index, minute_end_index)):
                fill_price = _limit_fill_price(side, limit_price, minute_rows[candidate_index])
                if fill_price is not None:
                    fill_index = candidate_index
                    entry_price = fill_price
                    break
            counters["limit"] += 1
            if fill_index is None:
                if as_of_epoch + 900 <= execution_end_epoch + 1e-6:
                    counters["limit_expired"] += 1
                else:
                    counters["limit_censored"] += 1
                next_signal_index = bisect_left(timestamps[primary_tf], expiry_end_epoch - 1e-6) - 1
                index = max(index + 1, next_signal_index)
                continue
        else:
            counters["waits"] += 1
            index += 1
            continue

        stop = float(signal["stop_loss"])
        target = float(signal["tp1"])
        exit_price = float(minute_rows[minute_end_index - 1]["close"])
        exit_index = minute_end_index - 1
        exit_reason = "SPLIT_END"
        for candle_index in range(fill_index, minute_end_index):
            candle = minute_rows[candle_index]
            low = float(candle["low"])
            high = float(candle["high"])
            hit_stop = low <= stop if side == "BUY" else high >= stop
            hit_target = high >= target if side == "BUY" else low <= target
            if hit_stop:
                exit_price = _stop_fill_price(side, stop, candle)
                exit_index = candle_index
                exit_reason = "STOP_LOSS_STOP_FIRST"
                break
            if hit_target and not (entry_type == "LIMIT" and candle_index == fill_index):
                exit_price = _target_fill_price(side, target, candle)
                exit_index = candle_index
                exit_reason = "TAKE_PROFIT_1"
                break

        gross_pnl = (exit_price - entry_price) * sign
        execution_quality = signal.get("execution_quality") or {}
        cost_bps = float(execution_quality.get("estimated_round_trip_cost_bps") or 0)
        estimated_cost = entry_price * cost_bps / 10000
        net_pnl = gross_pnl - estimated_cost
        risk_distance = abs(entry_price - stop)
        r_multiple = net_pnl / risk_distance if risk_distance > 0 else 0.0
        trades.append({
            "symbol": symbol, "side": side, "entry_type": entry_type,
            "signal_time": signal["signal_candle_time"],
            "fill_time": minute_rows[fill_index]["time"],
            "exit_time": minute_rows[exit_index]["time"],
            "entry": round(entry_price, 12), "stop_loss": signal["stop_loss"],
            "take_profit": signal["tp1"], "exit": round(exit_price, 12),
            "gross_pnl": round(gross_pnl, 12), "estimated_cost": round(estimated_cost, 12),
            "net_pnl": round(net_pnl, 12), "estimated_cost_bps": round(cost_bps, 3),
            "r_multiple": round(r_multiple, 4), "exit_reason": exit_reason,
            "minutes_held": exit_index - fill_index + 1,
        })
        exit_epoch = minute_times[exit_index] + 60
        if exit_epoch >= execution_end_epoch:
            index = len(primary) - 2
            break
        next_signal_index = bisect_left(timestamps[primary_tf], exit_epoch - 1e-6) - 1
        index = max(index + 1, next_signal_index)

    metrics = _metrics(trades, counters, primary, start_index, end_index, settings)
    metrics["_all_trades"] = trades
    metrics["_next_signal_index"] = index
    return metrics


def _public_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Remove internal replay state before returning metrics to API clients."""
    return {key: value for key, value in metrics.items() if not key.startswith("_")}


def _aggregate_fold_metrics(
    fold_results: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    start_index: int,
    end_index: int,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate sequential OOS folds without discarding trades beyond the UI preview."""
    counter_fields = {
        "signals": "signal_count",
        "waits": "wait_count",
        "market": "market_entries",
        "limit": "limit_entries",
        "limit_expired": "limit_expired",
        "limit_censored": "limit_censored",
        "order_flow_decision_points": "order_flow_decision_points",
        "order_flow_snapshot_matches": "order_flow_snapshot_matches",
        "order_flow_missing_snapshots": "order_flow_missing_snapshots",
        "order_flow_stale_snapshots": "order_flow_stale_snapshots",
        "order_flow_invalid_snapshots": "order_flow_invalid_snapshots",
        "order_flow_confirmed_candidates": "order_flow_confirmed_candidates",
        "order_flow_rejected_candidates": "order_flow_rejected_candidates",
    }
    counters = {key: 0 for key in counter_fields}
    counters["order_flow_enabled"] = int(any(
        result.get("order_flow_replay_enabled") is True for result in fold_results
    ))
    trades: list[dict[str, Any]] = []
    for result in fold_results:
        for counter_key, metric_key in counter_fields.items():
            counters[counter_key] += int(result.get(metric_key) or 0)
        trades.extend(result.get("_all_trades") or [])
    trades.sort(key=lambda trade: (
        str(trade.get("exit_time") or ""),
        str(trade.get("signal_time") or ""),
        str(trade.get("fill_time") or ""),
    ))
    aggregate = _metrics(trades, counters, candles, start_index, end_index, settings)
    aggregate["fold_count"] = len(fold_results)
    aggregate["folds_with_trades"] = sum(
        1 for result in fold_results if result.get("trade_count", 0) > 0
    )
    aggregate["folds_with_positive_expectancy"] = sum(
        1 for result in fold_results
        if isinstance(result.get("expectancy_r"), (int, float)) and result["expectancy_r"] > 0
    )
    return aggregate


async def run_signal_walk_forward(
    symbol: str,
    candles_by_tf: dict[str, list[dict[str, Any]]],
    symbol_info: dict[str, Any],
    settings: dict[str, Any] | None = None,
    *,
    train_ratio: float = 0.7,
    fold_count: int = 3,
    assumed_spread_bps: float = 5.0,
    assumed_depth_usd: float = 10000.0,
    order_flow_observations: list[dict[str, Any]] | None = None,
    raw_order_flow_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run fixed-rule sequential OOS folds with causal candle/Order Flow replay."""
    settings = settings or {"primary": "5", "trend": "60", "enabled": ["60", "30", "15", "5", "1"], "min_score": 7}
    if order_flow_observations is not None and raw_order_flow_events is not None:
        raise ValueError("Choose feature snapshots or raw Order Flow events, not both.")
    if not 0.5 <= train_ratio <= 0.9:
        raise ValueError("Train ratio must be between 0.5 and 0.9.")
    if isinstance(fold_count, bool) or not isinstance(fold_count, int) or not 2 <= fold_count <= 6:
        raise ValueError("Walk-forward fold_count must be an integer between 2 and 6.")
    if not math.isfinite(assumed_spread_bps) or not 0 <= assumed_spread_bps <= 100:
        raise ValueError("Assumed spread must be between 0 and 100 bps.")
    if not math.isfinite(assumed_depth_usd) or assumed_depth_usd < 1000:
        raise ValueError("Assumed replay depth must be at least 1,000 USD.")
    for key, default in (
        ("estimated_taker_fee_bps_per_side", 10.0),
        ("estimated_maker_fee_bps_per_side", 8.0),
        ("estimated_slippage_bps_per_side", 2.5),
        ("min_reward_to_cost_ratio", 1.25),
    ):
        value = float(settings.get(key, default))
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be finite and non-negative.")

    primary_tf = str(settings.get("primary", "5"))
    primary = candles_by_tf.get(primary_tf, [])
    if len(primary) < 500:
        raise ValueError("At least 500 primary timeframe candles are required for a useful signal replay.")
    enabled = list(dict.fromkeys(
        [str(item) for item in settings.get("enabled", ["60", "30", "15", "5", "1"])]
        + [primary_tf, str(settings.get("trend", "60"))]
    ))
    unsupported = [tf for tf in enabled if tf not in TIMEFRAME_MINUTES]
    if unsupported:
        raise ValueError("Unsupported replay timeframe(s): " + ", ".join(unsupported))
    missing = [tf for tf in enabled if tf not in candles_by_tf]
    if missing:
        raise ValueError("Missing historical timeframe data: " + ", ".join(missing))
    timestamps = {
        tf: [_epoch(row["time"]) for row in rows]
        for tf, rows in candles_by_tf.items() if tf in TIMEFRAME_MINUTES
    }
    for timeframe, values in timestamps.items():
        if values != sorted(values) or len(values) != len(set(values)):
            raise ValueError(f"Historical {timeframe}m candles must be unique and chronological.")
    primary_times = timestamps[primary_tf]
    if order_flow_observations is not None:
        _validate_order_flow_observations(order_flow_observations, symbol)
    minute_times = timestamps.get("1", [])
    missing_minute_bars = 0
    largest_gap_minutes = 0
    for previous, current in zip(minute_times, minute_times[1:]):
        gap_minutes = max(0, int(round((current - previous) / 60)) - 1)
        missing_minute_bars += gap_minutes
        largest_gap_minutes = max(largest_gap_minutes, gap_minutes)
    if largest_gap_minutes > 15 or missing_minute_bars > max(10, int(len(minute_times) * 0.01)):
        raise ValueError(
            f"Historical 1m data has too many missing bars ({missing_minute_bars}; largest gap {largest_gap_minutes}m)."
        )
    if not minute_times or minute_times[-1] + 60 < primary_times[-1] - 1e-6:
        raise ValueError("One-minute execution history must cover the final primary decision window.")
    first_valid = None
    for index in range(len(primary) - 1):
        as_of_epoch = primary_times[index + 1]
        if all(
            tf in timestamps and bisect_right(
                timestamps[tf], as_of_epoch - TIMEFRAME_MINUTES[tf] * 60 + 1e-6
            ) >= 210
            for tf in enabled if tf in TIMEFRAME_MINUTES
        ):
            first_valid = index
            break
    if first_valid is None:
        raise ValueError("Historical range does not contain enough closed multi-timeframe warm-up candles.")
    usable = len(primary) - 1 - first_valid
    if usable < 100:
        raise ValueError("Not enough post-warm-up candles for a meaningful train/holdout comparison.")
    split_index = first_valid + max(1, int(usable * train_ratio))
    out_of_sample_decisions = len(primary) - 1 - split_index
    if split_index - first_valid < 50 or out_of_sample_decisions < fold_count * 10:
        raise ValueError(
            "Training needs at least 50 decision bars and each out-of-sample fold needs at least 10 bars."
        )

    training_raw = await _simulate_slice(
        symbol, candles_by_tf, symbol_info, settings, assumed_spread_bps,
        assumed_depth_usd, first_valid, split_index - 1,
    )
    training = _public_metrics(training_raw)
    oos_execution_end_epoch = minute_times[-1] + 60.0

    async def _run_oos_folds(
        observations: list[dict[str, Any]] | None,
        raw_checkpoints: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        sizes = [
            out_of_sample_decisions // fold_count
            + (1 if index < out_of_sample_decisions % fold_count else 0)
            for index in range(fold_count)
        ]
        cursor = split_index
        next_start_index = split_index - 1
        raw_results: list[dict[str, Any]] = []
        public_folds: list[dict[str, Any]] = []
        for fold_number, size in enumerate(sizes, start=1):
            fold_end = cursor + size
            start_index = max(next_start_index, cursor - 1)
            end_index = fold_end - 1
            raw = await _simulate_slice(
                symbol, candles_by_tf, symbol_info, settings, assumed_spread_bps,
                assumed_depth_usd, start_index, end_index,
                order_flow_observations=observations,
                raw_order_flow_checkpoints=raw_checkpoints,
                execution_end_epoch=oos_execution_end_epoch,
            )
            raw_results.append(raw)
            public_folds.append({
                "fold": fold_number,
                "decision_start": datetime.fromtimestamp(primary_times[cursor], timezone.utc).isoformat(),
                "decision_end_exclusive": datetime.fromtimestamp(primary_times[fold_end], timezone.utc).isoformat(),
                **_public_metrics(raw),
            })
            next_start_index = max(fold_end - 1, int(raw.get("_next_signal_index", fold_end - 1)))
            cursor = fold_end
        aggregate = _aggregate_fold_metrics(
            raw_results, primary, split_index - 1, len(primary) - 2, settings
        )
        return aggregate, public_folds

    out_of_sample, out_of_sample_folds = await _run_oos_folds(None)

    raw_order_flow_checkpoints = None
    raw_event_replay_summary = None
    if raw_order_flow_events is not None:
        replay_horizon_epoch = minute_times[-1] + 60.0
        raw_order_flow_checkpoints = _replay_raw_order_flow_events(
            raw_order_flow_events, symbol, replay_horizon_epoch
        )
        raw_event_replay_summary = {
            "source": "BINANCE_SPOT_RAW_EVENT_ARCHIVE",
            "event_count": len(raw_order_flow_events),
            "checkpoint_count": len(raw_order_flow_checkpoints),
            "eligible_checkpoint_count": sum(
                row.get("eligible_for_order_flow_replay") is True
                for row in raw_order_flow_checkpoints
            ),
            "ineligible_checkpoint_count": sum(
                row.get("eligible_for_order_flow_replay") is not True
                for row in raw_order_flow_checkpoints
            ),
            "first_checkpoint_at": raw_order_flow_checkpoints[0].get("decision_at") if raw_order_flow_checkpoints else None,
            "last_checkpoint_at": raw_order_flow_checkpoints[-1].get("decision_at") if raw_order_flow_checkpoints else None,
            "decision_clock": "RECEIVED_AT_MS",
            "coverage_is_complete": False,
        }

    order_flow_replay = None
    order_flow_comparison = None
    if order_flow_observations is not None or raw_order_flow_events is not None:
        is_raw_replay = raw_order_flow_events is not None
        flow_observations = order_flow_observations
        flow_checkpoints = raw_order_flow_checkpoints if is_raw_replay else None
        flow_count = len(flow_checkpoints or []) if is_raw_replay else len(flow_observations or [])
        if flow_count == 0:
            order_flow_replay = {
                "status": (
                    "NO_COMPLETE_RAW_EVENT_CHECKPOINTS" if is_raw_replay
                    else "NO_CAPTURED_ORDER_FLOW_DATA"
                ),
                "source": "BINANCE_SPOT_RAW_EVENT_ARCHIVE" if is_raw_replay else "MINUTE_FEATURE_SNAPSHOTS",
                "observation_count": 0,
                "raw_event_count": len(raw_order_flow_events or []) if is_raw_replay else None,
                "note": (
                    "No completed receive-time raw-event checkpoint overlaps the historical candle range; "
                    "the raw archive cannot support an Order Flow performance result."
                    if is_raw_replay else
                    "No eligible sequence-validated Spot feature snapshots overlap this historical candle range; no order-flow performance result is available."
                ),
            }
        else:
            flow_kwargs = (
                {"raw_order_flow_checkpoints": flow_checkpoints}
                if is_raw_replay else {"order_flow_observations": flow_observations}
            )
            order_flow_training_raw = await _simulate_slice(
                symbol, candles_by_tf, symbol_info, settings, assumed_spread_bps,
                assumed_depth_usd, first_valid, split_index - 1,
                **flow_kwargs,
            )
            order_flow_training = _public_metrics(order_flow_training_raw)
            order_flow_out_of_sample, order_flow_out_of_sample_folds = await _run_oos_folds(
                flow_observations, flow_checkpoints
            )
            order_flow_replay = {
                "status": "EVALUATED",
                "source": "BINANCE_SPOT_RAW_EVENT_ARCHIVE" if is_raw_replay else "MINUTE_FEATURE_SNAPSHOTS",
                "observation_count": flow_count,
                "raw_event_count": len(raw_order_flow_events or []) if is_raw_replay else None,
                "eligible_checkpoint_count": (
                    raw_event_replay_summary["eligible_checkpoint_count"] if is_raw_replay else None
                ),
                "ineligible_checkpoint_count": (
                    raw_event_replay_summary["ineligible_checkpoint_count"] if is_raw_replay else None
                ),
                "first_captured_at": (
                    raw_event_replay_summary["first_checkpoint_at"] if is_raw_replay
                    else flow_observations[0].get("captured_at")
                ),
                "last_captured_at": (
                    raw_event_replay_summary["last_checkpoint_at"] if is_raw_replay
                    else flow_observations[-1].get("captured_at")
                ),
                "decision_clock": "RECEIVED_AT_MS" if is_raw_replay else "FEATURE_CAPTURE_TIMESTAMP",
                "coverage_is_complete": False if is_raw_replay else None,
                "training": order_flow_training,
                "out_of_sample": order_flow_out_of_sample,
                "out_of_sample_folds": order_flow_out_of_sample_folds,
                "method": (
                    "Same fixed candle strategy and execution model across sequential OOS folds. Raw Binance Spot "
                    "aggTrade and sequence-reconstructed L2 checkpoints are selected only when their receive-time "
                    "decision boundary is at or before the candle decision; exchange event-time freshness is "
                    "recomputed at that decision. Ineligible or missing latest checkpoints fail closed. "
                    "OOS positions remain blocked until their modeled exit."
                    if is_raw_replay else
                    "Same fixed candle strategy and execution model across sequential OOS folds, with the live Spot "
                    "order-flow gate applied only to prior, fresh, sequence-validated feature snapshots. "
                    "OOS positions remain blocked until their modeled exit, including across fold boundaries."
                ),
            }
            baseline_expectancy = out_of_sample.get("expectancy_r")
            flow_expectancy = order_flow_out_of_sample.get("expectancy_r")
            baseline_win_rate = out_of_sample.get("win_rate_pct")
            flow_win_rate = order_flow_out_of_sample.get("win_rate_pct")
            order_flow_comparison = {
                "out_of_sample_trade_count_delta": (
                    order_flow_out_of_sample["trade_count"] - out_of_sample["trade_count"]
                ),
                "out_of_sample_expectancy_r_delta": (
                    round(flow_expectancy - baseline_expectancy, 3)
                    if isinstance(flow_expectancy, (int, float)) and isinstance(baseline_expectancy, (int, float))
                    else None
                ),
                "out_of_sample_win_rate_percentage_point_delta": (
                    round(flow_win_rate - baseline_win_rate, 2)
                    if isinstance(flow_win_rate, (int, float)) and isinstance(baseline_win_rate, (int, float))
                    else None
                ),
                "out_of_sample_profit_factor_baseline": out_of_sample["profit_factor"],
                "out_of_sample_profit_factor_order_flow": order_flow_out_of_sample["profit_factor"],
                "out_of_sample_net_pnl_quote_delta": round(
                    order_flow_out_of_sample["net_pnl_quote"] - out_of_sample["net_pnl_quote"], 8
                ),
                "out_of_sample_estimated_cost_quote_delta": round(
                    order_flow_out_of_sample["estimated_cost_quote"] - out_of_sample["estimated_cost_quote"], 8
                ),
                "out_of_sample_max_drawdown_r_delta": round(
                    order_flow_out_of_sample["max_drawdown_r"] - out_of_sample["max_drawdown_r"], 3
                ),
                "interpretation": "Descriptive ablation only. Snapshot coverage is sparse and non-random; this comparison is not a calibrated causal estimate of order-flow edge.",
            }
    return {
        "symbol": symbol,
        "market_type": "BINANCE_SPOT",
        "quote_asset": symbol_info.get("quote_asset"),
        "pnl_unit": "quote-currency PnL per 1 unit of the base asset; no account position size is assumed",
        "data_quality": {
            "one_minute_candles": len(minute_times),
            "missing_minute_bars": missing_minute_bars,
            "largest_gap_minutes": largest_gap_minutes,
            "incomplete_aggregated_bars_are_discarded": True,
        },
        "settings": settings,
        "train_ratio": train_ratio,
        "fold_count": fold_count,
        "training": training,
        "out_of_sample": out_of_sample,
        "out_of_sample_folds": out_of_sample_folds,
        "order_flow_replay": order_flow_replay,
        "order_flow_comparison": order_flow_comparison,
        "assumptions": {
            "spread_bps": assumed_spread_bps,
            "top_book_depth_usd": assumed_depth_usd,
            "taker_fee_bps_per_side": float(settings.get("estimated_taker_fee_bps_per_side", 10.0)),
            "maker_fee_bps_per_side": float(settings.get("estimated_maker_fee_bps_per_side", 8.0)),
            "slippage_bps_per_side": float(settings.get("estimated_slippage_bps_per_side", 2.5)),
            "fees_and_slippage": "Uses estimated fee/slippage assumptions; not historical exchange order-book or account fee data.",
            "market_fill": "Next primary candle open using the modeled bid/ask spread.",
            "limit_fill": "Filled only if a 1m candle touches the limit within the 15-minute signal expiry; gap-through fills use the better opening price.",
            "intrabar_ambiguity": "If stop-loss and TP1 are both touched in one candle, stop-loss is assumed first.",
            "exit_policy": "Full position exits at stop-loss or TP1; TP2/TP3 partial exits are not modeled. Open positions are carried across OOS fold boundaries and prevent overlapping new entries.",
            "order_flow_replay": (
                "Raw-event mode reconstructs receive-time checkpoints from archived Binance Spot aggTrades and "
                "sequence-applied depth diffs. Only the latest checkpoint at or before each candle decision is "
                "eligible; trade/depth event-time ages are recomputed at that decision. Missing, stale, gapped, "
                "truncated or malformed data fails closed. Bounded archives never claim full-session completeness."
                if raw_order_flow_events is not None else
                "Feature-snapshot mode selects only the latest stored Spot feature snapshot captured at or before "
                "each decision; source ages are recomputed at that decision timestamp. Missing, stale, future, "
                "malformed or non-sequenced snapshots fail closed; no stale forward-fill is allowed."
            ),
        },
        "method": "Fixed-rule sequential walk-forward: one initial in-sample segment followed by non-overlapping OOS decision windows. No parameters are fit on the OOS windows; open positions are carried across fold boundaries.",
        "limitations": [
            "Historical order-book depth and bid/ask are unavailable; spread and depth are modeled assumptions.",
            "Fee estimates may differ from the user's Binance fee tier.",
            "No partial fills, funding, position sizing, contract multiplier, taxes or broker execution latency.",
            "Spot SELL is a sell signal only, not a short position.",
            "Confidence intervals are descriptive only and do not correct for serial dependence or strategy selection.",
            "A historical holdout is not proof of future profitability.",
            "Order-flow snapshots are retained for seven days, sampled at most once per symbol per minute, and only exist for symbols with active managed streams.",
            "Captured feature snapshots are summaries, not raw AggTrade/depth-diff archives; CVD is bounded since the stream seed and UTC session delta may be incomplete.",
            "Raw-event replay is bounded to the supplied archive window and its first captured trade is only a CVD seed; UTC session delta is not available without a proven session-start anchor.",
            "Raw-event archives may be sparse, non-random or truncated; this replay does not establish complete exchange-event capture.",
            "The order-flow replay comparison is subject to sparse, non-random stream coverage and must not be interpreted as proof of incremental predictive value.",
        ],
    }

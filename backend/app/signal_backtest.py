"""Chronological, paper-only replay of the QUANTNEX multi-timeframe signal engine."""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .signal_engine import build_signal

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
    equity = 0.0
    peak = 0.0
    max_drawdown_r = 0.0
    for value in r_values:
        equity += value
        peak = max(peak, equity)
        max_drawdown_r = max(max_drawdown_r, peak - equity)
    baseline = None
    if 0 <= start_index < end_index < len(candles):
        first = float(candles[start_index]["open"])
        last = float(candles[end_index]["close"])
        if first > 0:
            baseline = round((last / first - 1) * 100, 3)
    return {
        "sample_bars": max(0, end_index - start_index + 1),
        "signal_count": counters["signals"],
        "wait_count": counters["waits"],
        "trade_count": len(trades),
        "market_entries": counters["market"],
        "limit_entries": counters["limit"],
        "limit_expired": counters["limit_expired"],
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else None,
        "gross_pnl_quote": round(sum(trade["gross_pnl"] for trade in trades), 8),
        "estimated_cost_quote": round(sum(trade["estimated_cost"] for trade in trades), 8),
        "net_pnl_quote": round(sum(trade["net_pnl"] for trade in trades), 8),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else (
            "infinite" if gross_profit > 0 else None
        ),
        "expectancy_r": round(sum(r_values) / len(r_values), 3) if r_values else None,
        "average_r": round(sum(r_values) / len(r_values), 3) if r_values else None,
        "max_drawdown_r": round(max_drawdown_r, 3),
        "buy_and_hold_return_pct": baseline,
        "order_flow_replay_enabled": bool(counters.get("order_flow_enabled", 0)),
        "order_flow_decision_points": counters.get("order_flow_decision_points", 0),
        "order_flow_snapshot_matches": counters.get("order_flow_snapshot_matches", 0),
        "order_flow_missing_snapshots": counters.get("order_flow_missing_snapshots", 0),
        "order_flow_stale_snapshots": counters.get("order_flow_stale_snapshots", 0),
        "order_flow_invalid_snapshots": counters.get("order_flow_invalid_snapshots", 0),
        "order_flow_confirmed_candidates": counters.get("order_flow_confirmed_candidates", 0),
        "order_flow_rejected_candidates": counters.get("order_flow_rejected_candidates", 0),
        "order_flow_coverage_pct": round(
            counters.get("order_flow_snapshot_matches", 0) / counters.get("order_flow_decision_points", 1) * 100, 2
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
    observation_epochs = (
        _validate_order_flow_observations(order_flow_observations, symbol)
        if order_flow_observations is not None else None
    )
    counters = {
        "signals": 0, "waits": 0, "market": 0, "limit": 0, "limit_expired": 0,
        "order_flow_enabled": int(order_flow_observations is not None),
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
    slice_end_epoch = timestamps[primary_tf][end_index + 1]
    minute_end_index = bisect_left(minute_times, slice_end_epoch)
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
        if as_of_epoch >= slice_end_epoch:
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
        half_spread = assumed_spread_bps / 20000
        execution = {
            "symbol": symbol,
            "provider": "Historical Binance Spot replay",
            "best_bid": mid * (1 - half_spread),
            "best_ask": mid * (1 + half_spread),
            "mid_price": mid,
            "spread_bps": assumed_spread_bps,
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
        result = await build_signal(
            settings, symbol, candles_override=windows,
            execution_context_override=execution, replay_as_of=as_of,
        )
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
            expiry_end_epoch = min(as_of_epoch + 900, slice_end_epoch)
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
                counters["limit_expired"] += 1
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
        if exit_epoch >= slice_end_epoch:
            break
        next_signal_index = bisect_left(timestamps[primary_tf], exit_epoch - 1e-6) - 1
        index = max(index + 1, next_signal_index)

    return _metrics(trades, counters, primary, start_index, end_index, settings)


async def run_signal_walk_forward(
    symbol: str,
    candles_by_tf: dict[str, list[dict[str, Any]]],
    symbol_info: dict[str, Any],
    settings: dict[str, Any] | None = None,
    *,
    train_ratio: float = 0.7,
    assumed_spread_bps: float = 5.0,
    assumed_depth_usd: float = 10000.0,
) -> dict[str, Any]:
    """Evaluate the actual signal rules on chronological training and unseen holdout slices."""
    settings = settings or {"primary": "5", "trend": "60", "enabled": ["60", "30", "15", "5", "1"], "min_score": 7}
    if not 0.5 <= train_ratio <= 0.9:
        raise ValueError("Train ratio must be between 0.5 and 0.9.")
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
    if split_index - first_valid < 50 or len(primary) - 1 - split_index < 30:
        raise ValueError("Training and out-of-sample windows are too small after indicator warm-up.")

    training = await _simulate_slice(
        symbol, candles_by_tf, symbol_info, settings, assumed_spread_bps,
        assumed_depth_usd, first_valid, split_index - 1,
    )
    out_of_sample = await _simulate_slice(
        symbol, candles_by_tf, symbol_info, settings, assumed_spread_bps,
        assumed_depth_usd, split_index, len(primary) - 2,
    )
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
        "training": training,
        "out_of_sample": out_of_sample,
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
            "exit_policy": "Full position exits at stop-loss or TP1; TP2/TP3 partial exits are not modeled.",
        },
        "method": "Chronological holdout. Each signal uses only candles closed by the next primary bar open; the holdout is not used for parameter fitting.",
        "limitations": [
            "Historical order-book depth and bid/ask are unavailable; spread and depth are modeled assumptions.",
            "Fee estimates may differ from the user's Binance fee tier.",
            "No partial fills, funding, position sizing, contract multiplier, taxes or broker execution latency.",
            "Spot SELL is a sell signal only, not a short position.",
            "A historical holdout is not proof of future profitability.",
        ],
    }

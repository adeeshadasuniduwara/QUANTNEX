"""Chronological, paper-only replay of the QUANTNEX multi-timeframe signal engine."""
from __future__ import annotations

import math
from bisect import bisect_right
from datetime import datetime, timezone
from typing import Any

from .signal_engine import build_signal

TIMEFRAME_MINUTES = {"1": 1, "5": 5, "15": 15, "30": 30, "50": 50, "60": 60, "240": 240}


def _epoch(value: str) -> float:
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


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
    counters = {"signals": 0, "waits": 0, "market": 0, "limit": 0, "limit_expired": 0}
    trades: list[dict[str, Any]] = []
    index = max(0, start_index)
    end_index = min(end_index, len(primary) - 2)
    primary_seconds = TIMEFRAME_MINUTES[primary_tf] * 60
    tick_size = str(symbol_info.get("filters", {}).get("PRICE_FILTER", {}).get("tickSize") or "0.00000001")
    quote_asset = str(symbol_info.get("quote_asset") or "")
    stable_quotes = {"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "USDP", "DAI", "USDE"}

    while index <= end_index:
        as_of_epoch = timestamps[primary_tf][index + 1]
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
        if entry_type == "MARKET":
            fill_index = index + 1
            entry_price = float(signal["entry"])
            counters["market"] += 1
        elif entry_type == "LIMIT":
            limit_price = float(signal["limit_price"])
            expiry_bars = max(1, math.ceil(900 / primary_seconds))
            fill_index = None
            entry_price = None
            for candidate_index in range(index + 1, min(end_index + 1, index + 1 + expiry_bars)):
                candle = primary[candidate_index]
                fill_price = _limit_fill_price(side, limit_price, candle)
                if fill_price is not None:
                    fill_index = candidate_index
                    entry_price = fill_price
                    break
            counters["limit"] += 1
            if fill_index is None:
                counters["limit_expired"] += 1
                index += 1
                continue
        else:
            counters["waits"] += 1
            index += 1
            continue

        stop = float(signal["stop_loss"])
        target = float(signal["tp1"])
        exit_price = float(primary[end_index]["close"])
        exit_index = end_index
        exit_reason = "SPLIT_END"
        for candle_index in range(fill_index, end_index + 1):
            candle = primary[candle_index]
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
            "fill_time": primary[fill_index]["time"],
            "exit_time": primary[exit_index]["time"],
            "entry": round(entry_price, 12), "stop_loss": signal["stop_loss"],
            "take_profit": signal["tp1"], "exit": round(exit_price, 12),
            "gross_pnl": round(gross_pnl, 12), "estimated_cost": round(estimated_cost, 12),
            "net_pnl": round(net_pnl, 12), "estimated_cost_bps": round(cost_bps, 3),
            "r_multiple": round(r_multiple, 4), "exit_reason": exit_reason,
            "bars_held": exit_index - fill_index + 1,
        })
        index = max(index + 1, exit_index + 1)

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
            "limit_fill": "Filled only if a later candle touches the limit within the 15-minute signal expiry; gap-through fills use the better opening price.",
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

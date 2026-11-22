"""Observed-event Binance Spot footprint and conservative microstructure context."""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import math
from typing import Any

MAX_FOOTPRINT_EVENTS = 5000
MAX_FOOTPRINT_LEVELS = 1000

class OrderFlowFootprintError(ValueError):
    """Raised when footprint inputs or limits are invalid."""

def _positive_decimal(value: Any, name: str) -> Decimal:
    try: number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError): raise OrderFlowFootprintError(f"{name} must be a positive decimal.") from None
    if not number.is_finite() or number <= 0: raise OrderFlowFootprintError(f"{name} must be a positive decimal.")
    return number

def build_order_flow_footprint(events: list[dict[str, Any]], *, price_step: str | float | Decimal, interval_ms: int = 60_000, max_levels: int = 250, imbalance_ratio: float = 3.0) -> dict[str, Any]:
    """Aggregate archived aggTrade data; context flags are candidates, never trade instructions.

    Binance aggTrade m=True means buyer is maker (seller aggressor); m=False
    means buyer aggressor. Price levels are floored to the explicit tick size.
    Depth updates are used only for observed liquidity-pull context, never executed volume.
    """
    step = _positive_decimal(price_step, "price_step")
    if not isinstance(events, list) or len(events) > MAX_FOOTPRINT_EVENTS: raise OrderFlowFootprintError(f"events must be a list of at most {MAX_FOOTPRINT_EVENTS} rows.")
    if isinstance(interval_ms, bool) or not isinstance(interval_ms, int) or interval_ms not in {60_000, 300_000, 900_000}: raise OrderFlowFootprintError("interval_ms must be 60000, 300000 or 900000.")
    if isinstance(max_levels, bool) or not isinstance(max_levels, int) or not 1 <= max_levels <= MAX_FOOTPRINT_LEVELS: raise OrderFlowFootprintError(f"max_levels must be between 1 and {MAX_FOOTPRINT_LEVELS}.")
    if isinstance(imbalance_ratio, bool) or not isinstance(imbalance_ratio, (int, float)) or not math.isfinite(float(imbalance_ratio)) or imbalance_ratio < 1: raise OrderFlowFootprintError("imbalance_ratio must be a finite number greater than or equal to 1.")
    buckets: dict[int, dict[Decimal, dict[str, Any]]] = defaultdict(dict)
    depth_changes: dict[Decimal, dict[str, int]] = defaultdict(lambda: {"updates": 0, "pulls": 0, "adds": 0})
    accepted = ignored = depth_rows = 0
    for event in events:
        if not isinstance(event, dict): ignored += 1; continue
        if event.get("event_type") == "depthUpdate":
            payload = event.get("payload")
            if not isinstance(payload, dict): continue
            for side, key in (("bid", "b"), ("ask", "a")):
                for level in payload.get(key, []) if isinstance(payload.get(key, []), list) else []:
                    if not isinstance(level, (list, tuple)) or len(level) < 2: continue
                    try: price = _positive_decimal(level[0], "depth price"); qty = Decimal(str(level[1]))
                    except (InvalidOperation, TypeError, ValueError): continue
                    if not qty.is_finite() or qty < 0: continue
                    bucket = depth_changes[price]; bucket["updates"] += 1
                    if qty == 0: bucket["pulls"] += 1
                    else: bucket["adds"] += 1
                    depth_rows += 1
            continue
        if event.get("event_type") != "aggTrade": ignored += 1; continue
        payload = event.get("payload")
        if not isinstance(payload, dict): raise OrderFlowFootprintError("aggTrade payload must be an object.")
        try:
            event_ms = int(event["event_time_ms"]); price = _positive_decimal(payload["p"], "trade price")
            quantity = _positive_decimal(payload["q"], "trade quantity"); buyer_is_maker = payload["m"]
        except (KeyError, TypeError, ValueError, OverflowError): raise OrderFlowFootprintError("aggTrade row is missing valid time, price or quantity.") from None
        if event_ms <= 0 or not isinstance(buyer_is_maker, bool): raise OrderFlowFootprintError("aggTrade timestamp or aggressor side is invalid.")
        level = (price / step).to_integral_value(rounding=ROUND_FLOOR) * step
        bucket_ms = (event_ms // interval_ms) * interval_ms
        row = buckets[bucket_ms].setdefault(level, {"buy_volume": Decimal("0"), "sell_volume": Decimal("0"), "trade_count": 0})
        row["sell_volume" if buyer_is_maker else "buy_volume"] += quantity; row["trade_count"] += 1; accepted += 1
    candles = []
    for bucket_ms in sorted(buckets):
        levels = buckets[bucket_ms]; ordered = sorted(levels, reverse=True)[:max_levels]; rows = []
        for price in ordered:
            data = levels[price]; buy, sell = data["buy_volume"], data["sell_volume"]
            lower_sell = levels.get(price-step, {}).get("sell_volume", Decimal("0"))
            higher_buy = levels.get(price+step, {}).get("buy_volume", Decimal("0"))
            rows.append({"price":format(price,"f"),"buy_volume":format(buy,"f"),"sell_volume":format(sell,"f"),
                "delta":format(buy-sell,"f"),"total_volume":format(buy+sell,"f"),"trade_count":data["trade_count"],
                "buy_imbalance":bool(lower_sell>0 and buy>=lower_sell*Decimal(str(imbalance_ratio))),
                "sell_imbalance":bool(higher_buy>0 and sell>=higher_buy*Decimal(str(imbalance_ratio)))})
        candles.append({"open_time_ms":bucket_ms,"interval_ms":interval_ms,"levels":rows,"level_count":len(rows),
            "trades_aggregated":sum(levels[p]["trade_count"] for p in ordered),"levels_truncated":len(levels)>len(ordered),
            "total_buy_volume":format(sum(x["buy_volume"] for x in levels.values()),"f"),
            "total_sell_volume":format(sum(x["sell_volume"] for x in levels.values()),"f"),
            "delta":format(sum(x["buy_volume"]-x["sell_volume"] for x in levels.values()),"f")})
    stacked = []
    for candle in candles:
        for side in ("buy_imbalance","sell_imbalance"):
            run = []
            for row in sorted(candle["levels"], key=lambda x: Decimal(x["price"])):
                if row[side]:
                    price = Decimal(row["price"])
                    if run and price - Decimal(run[-1]["price"]) != step:
                        if len(run) >= 3: stacked.append({"open_time_ms":candle["open_time_ms"],"side":side.replace("_imbalance","").upper(),"levels":[x["price"] for x in run],"count":len(run)})
                        run = []
                    run.append(row)
                else:
                    if len(run) >= 3: stacked.append({"open_time_ms":candle["open_time_ms"],"side":side.replace("_imbalance","").upper(),"levels":[x["price"] for x in run],"count":len(run)})
                    run=[]
            if len(run) >= 3: stacked.append({"open_time_ms":candle["open_time_ms"],"side":side.replace("_imbalance","").upper(),"levels":[x["price"] for x in run],"count":len(run)})
    divergence = {"status":"INSUFFICIENT_DATA","signal":"NONE","note":"At least three observed footprint intervals are required."}
    if len(candles) >= 3:
        recent=candles[-3:]; delta_values=[Decimal(x["delta"]) for x in recent]
        net_prices=[Decimal(x["levels"][0]["price"]) if x["levels"] else Decimal("0") for x in recent]
        if all(x>0 for x in net_prices):
            price_up=net_prices[-1]>net_prices[0]; price_down=net_prices[-1]<net_prices[0]
            delta_down=delta_values[-1]<delta_values[0]; delta_up=delta_values[-1]>delta_values[0]
            signal="BEARISH" if price_up and delta_down else "BULLISH" if price_down and delta_up else "NONE"
            divergence={"status":"OBSERVED","signal":signal,"price_direction":"UP" if price_up else "DOWN" if price_down else "FLAT","delta_direction":"UP" if delta_up else "DOWN" if delta_down else "FLAT","note":"Three-interval comparison of highest traded price level and observed delta; not OHLC price divergence."}
    absorption=[]; iceberg_candidates=[]
    for candle in candles:
        totals=[Decimal(row["total_volume"]) for row in candle["levels"]]
        peak=max(totals, default=Decimal("0"))
        for row in candle["levels"]:
            total=Decimal(row["total_volume"]); delta=abs(Decimal(row["delta"]))
            if peak>0 and total>=peak*Decimal("0.5") and delta<=total*Decimal("0.15") and int(row["trade_count"])>=3:
                absorption.append({"open_time_ms":candle["open_time_ms"],"price":row["price"],"volume":row["total_volume"],"delta":row["delta"],"type":"TWO_SIDED_HIGH_VOLUME_CANDIDATE","confidence":"LOW","note":"High two-sided traded volume with small net delta; price-response confirmation is unavailable from trade-only events."})
            if int(row["trade_count"])>=5 and total>=peak*Decimal("0.5"):
                iceberg_candidates.append({"open_time_ms":candle["open_time_ms"],"price":row["price"],"trade_count":row["trade_count"],"volume":row["total_volume"],"status":"REPEATED_EXECUTION_CANDIDATE","confidence":"LOW","note":"Repeated executions at one price do not prove hidden iceberg replenishment; order identity and synchronized queue history are unavailable."})
    liquidity_pulls=[]
    for price, data in depth_changes.items():
        if data["updates"]>=3 and data["pulls"]>=2:
            liquidity_pulls.append({"price":format(price,"f"),**data,"status":"REPEATED_ZERO_QUANTITY_UPDATES","confidence":"LOW","note":"Observed zero-quantity depth updates at this price; not proof of spoofing or participant intent."})
    return {"market_type":"BINANCE_SPOT","source":"ARCHIVED_BINANCE_SPOT_EVENTS","price_step":format(step,"f"),"interval_ms":interval_ms,
        "imbalance_ratio":float(imbalance_ratio),"accepted_trade_events":accepted,"ignored_non_trade_events":ignored,
        "depth_level_updates":depth_rows,"candles":candles,"stacked_imbalances":stacked,"delta_divergence":divergence,
        "absorption_candidates":absorption,"iceberg_candidates":iceberg_candidates,"liquidity_pull_context":liquidity_pulls,
        "spoofing_detection":{"status":"NOT_PROVEN","note":"Spoofing intent cannot be determined from public aggregated depth updates; displayed pull context is descriptive only."},
        "coverage":"OBSERVED_EVENTS_ONLY_NOT_PROVEN_COMPLETE"}

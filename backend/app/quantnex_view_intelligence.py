"""QUANTNEX VIEW strategy intelligence, signal scoring and deterministic research backtests.

Scores are confluence rankings, never win-probability estimates. Backtests use closed candles
only, one open position per symbol, conservative stop-first intrabar ordering and partial exits.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .signal_engine import ema, rsi, atr, adx, macd, structure, fetch_candles, MarketDataError

# Ten transparent strategy families x ten context profiles = a 100-setup research catalogue.
# The context profiles are explicit filters, not claims that 100 independent edges exist.
_FAMILIES = [
    ("Liquidity Sweep + MSS", "ICT", "sweep then close through a recent opposing swing"),
    ("FVG Pullback", "ICT", "retracement into a fresh fair-value gap with directional displacement"),
    ("Order Block Retest", "SMC", "retest of the last opposing candle before a structure break"),
    ("Breaker Block Retest", "SMC", "failed order block flips polarity and is retested"),
    ("BOS Continuation", "SMC", "confirmed break of structure with trend alignment"),
    ("CHoCH Reversal", "SMC", "character change after a liquidity run"),
    ("Premium / Discount Reversal", "ICT", "discount buys or premium sells with momentum confirmation"),
    ("EMA Trend Pullback", "Trend", "20/50/200 EMA stack with pullback and momentum recovery"),
    ("VWAP Reclaim / Reject", "Volume", "price reclaims or rejects rolling session VWAP"),
    ("Silver Bullet Window", "ICT", "time-window context plus displacement and FVG retest"),
]
_CONTEXTS = [
    ("trend", "trend-aligned"), ("countertrend", "counter-trend"), ("high_adx", "ADX above 22"),
    ("low_adx", "ADX below 22"), ("bull_regime", "bullish EMA regime"),
    ("bear_regime", "bearish EMA regime"), ("high_volume", "relative volume expansion"),
    ("low_volume", "normalised volume"), ("discount", "discount-side location"),
    ("premium", "premium-side location"),
]
STRATEGY_CATALOG = [
    {"id": f"QX-{i+1:03d}", "name": f"{family[0]} · {ctx[1].title()}",
     "family": family[0], "category": family[1], "rule": family[2],
     "context_filter": ctx[1], "research_only": False}
    for i, (family, ctx) in enumerate((f, c) for f in _FAMILIES for c in _CONTEXTS)
]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _features(candles: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [float(x["close"]) for x in candles]
    volumes = [float(x.get("volume", 0) or 0) for x in candles]
    last = candles[-1]
    e20, e50, e200 = ema(closes, 20)[-1], ema(closes, 50)[-1], ema(closes, 200)[-1]
    m, ms, mh = macd(closes)
    rv, av, dx = rsi(closes), atr(candles), adx(candles)
    st = structure(candles)
    recent = candles[-30:]
    vwap_num = sum(float(x["close"]) * float(x.get("volume", 0) or 0) for x in recent)
    vwap_den = sum(float(x.get("volume", 0) or 0) for x in recent)
    vwap = vwap_num / vwap_den if vwap_den > 0 else _mean(closes[-30:])
    avg_vol = _mean(volumes[-20:])
    rel_vol = volumes[-1] / avg_vol if avg_vol > 0 else 1.0
    bullish = closes[-1] > e20 > e50 and closes[-1] > e200
    bearish = closes[-1] < e20 < e50 and closes[-1] < e200
    return {"close": closes[-1], "ema20": e20, "ema50": e50, "ema200": e200,
            "macd": m, "macd_signal": ms, "macd_histogram": mh, "rsi": rv,
            "atr": av, "adx": dx, "structure": st, "vwap": vwap,
            "relative_volume": rel_vol, "bullish_regime": bullish, "bearish_regime": bearish,
            "volume": volumes[-1], "time": last["time"]}


def _near_zone(price: float, zone: dict | None, tolerance: float) -> bool:
    return bool(zone and zone.get("low") - tolerance <= price <= zone.get("high") + tolerance)


def _family_votes(c: list[dict[str, Any]], f: dict[str, Any]) -> list[dict[str, Any]]:
    st, price, av = f["structure"], f["close"], max(f["atr"], 1e-12)
    bull, bear = [], []
    if st["liquidity_sweep"] == "BULLISH" and st["bos_mss"] == "BULLISH": bull.append(("Liquidity Sweep + MSS", 4, "Sell-side sweep followed by bullish structure shift"))
    if st["liquidity_sweep"] == "BEARISH" and st["bos_mss"] == "BEARISH": bear.append(("Liquidity Sweep + MSS", 4, "Buy-side sweep followed by bearish structure shift"))
    if _near_zone(price, st.get("bullish_fvg"), av * .25) and f["macd_histogram"] > 0: bull.append(("FVG Pullback", 3, "Price is trading in bullish FVG with positive MACD"))
    if _near_zone(price, st.get("bearish_fvg"), av * .25) and f["macd_histogram"] < 0: bear.append(("FVG Pullback", 3, "Price is trading in bearish FVG with negative MACD"))
    if _near_zone(price, st.get("bullish_order_block"), av * .2) and f["bullish_regime"]: bull.append(("Order Block Retest", 3, "Bullish order-block retest in aligned regime"))
    if _near_zone(price, st.get("bearish_order_block"), av * .2) and f["bearish_regime"]: bear.append(("Order Block Retest", 3, "Bearish order-block retest in aligned regime"))
    if _near_zone(price, st.get("bullish_breaker_block"), av * .2): bull.append(("Breaker Block Retest", 3, "Bullish breaker block retest"))
    if _near_zone(price, st.get("bearish_breaker_block"), av * .2): bear.append(("Breaker Block Retest", 3, "Bearish breaker block retest"))
    if st["bos_mss"] == "BULLISH" and f["bullish_regime"]: bull.append(("BOS Continuation", 3, "Bullish BOS aligned with EMA regime"))
    if st["bos_mss"] == "BEARISH" and f["bearish_regime"]: bear.append(("BOS Continuation", 3, "Bearish BOS aligned with EMA regime"))
    if st["bos_mss"] == "BULLISH" and st["liquidity_sweep"] == "BULLISH": bull.append(("CHoCH Reversal", 3, "Bullish character change after downside liquidity run"))
    if st["bos_mss"] == "BEARISH" and st["liquidity_sweep"] == "BEARISH": bear.append(("CHoCH Reversal", 3, "Bearish character change after upside liquidity run"))
    if st["premium_discount"] == "DISCOUNT" and f["macd_histogram"] > 0 and f["rsi"] < 65: bull.append(("Premium / Discount Reversal", 2, "Discount-side momentum recovery"))
    if st["premium_discount"] == "PREMIUM" and f["macd_histogram"] < 0 and f["rsi"] > 35: bear.append(("Premium / Discount Reversal", 2, "Premium-side momentum rollover"))
    if f["bullish_regime"] and f["close"] >= f["ema20"] and f["macd_histogram"] > 0: bull.append(("EMA Trend Pullback", 2, "Bullish EMA stack with positive momentum"))
    if f["bearish_regime"] and f["close"] <= f["ema20"] and f["macd_histogram"] < 0: bear.append(("EMA Trend Pullback", 2, "Bearish EMA stack with negative momentum"))
    if price > f["vwap"] and f["macd_histogram"] > 0 and f["relative_volume"] >= 1.1: bull.append(("VWAP Reclaim / Reject", 2, "Above rolling VWAP with relative-volume expansion"))
    if price < f["vwap"] and f["macd_histogram"] < 0 and f["relative_volume"] >= 1.1: bear.append(("VWAP Reclaim / Reject", 2, "Below rolling VWAP with relative-volume expansion"))
    # Silver Bullet is represented as a time-window filter; only UTC windows are evaluated here.
    try:
        hour = datetime.fromisoformat(str(f["time"]).replace("Z", "+00:00")).hour
    except ValueError:
        hour = -1
    if hour in {10, 14, 15}:
        if f["relative_volume"] >= 1.2 and st.get("bullish_fvg") and f["macd_histogram"] > 0: bull.append(("Silver Bullet Window", 2, "UTC time-window displacement with bullish FVG"))
        if f["relative_volume"] >= 1.2 and st.get("bearish_fvg") and f["macd_histogram"] < 0: bear.append(("Silver Bullet Window", 2, "UTC time-window displacement with bearish FVG"))
    return [{"side": "BUY", "family": name, "weight": weight, "reason": reason} for name, weight, reason in bull] + [
        {"side": "SELL", "family": name, "weight": weight, "reason": reason} for name, weight, reason in bear]


def analyze_candles(candles: list[dict[str, Any]], symbol: str, interval: str,
                    min_score: int = 6, risk_multiple: float = 1.5) -> dict[str, Any]:
    if len(candles) < 210:
        raise MarketDataError("At least 210 candles are required for QUANTNEX VIEW analysis.")
    f = _features(candles)
    votes = _family_votes(candles, f)
    buy = [x for x in votes if x["side"] == "BUY"]
    sell = [x for x in votes if x["side"] == "SELL"]
    bscore, sscore = sum(x["weight"] for x in buy), sum(x["weight"] for x in sell)
    side = "BUY" if bscore >= min_score and bscore > sscore else "SELL" if sscore >= min_score and sscore > bscore else None
    winning = buy if side == "BUY" else sell if side == "SELL" else (buy if bscore >= sscore else sell)
    # Confidence is a transparent confluence score, not a probability or claimed accuracy.
    confirmations = list(dict.fromkeys(x["family"] for x in winning))
    score = max(bscore, sscore)
    signal = None
    if side:
        swing = f["structure"]["swing_low"] if side == "BUY" else f["structure"]["swing_high"]
        structural = abs(f["close"] - swing)
        risk = max(f["atr"] * risk_multiple, structural if 0 < structural <= f["atr"] * 4 else 0)
        sign = 1 if side == "BUY" else -1
        entry = f["close"]
        stop = entry - sign * risk
        signal = {"symbol": symbol, "side": side, "timeframe": interval, "entry": round(entry, 8),
                  "stop_loss": round(stop, 8), "tp1": round(entry + sign*risk, 8),
                  "tp2": round(entry + sign*risk*2, 8), "tp3": round(entry + sign*risk*3, 8),
                  "risk_distance": round(risk, 8), "score": score, "score_out_of": 20,
                  "confidence_label": "HIGH CONFLUENCE" if score >= 10 else "MODERATE CONFLUENCE",
                  "confirmations": confirmations, "reasons": [x["reason"] for x in winning]}
    return {"symbol": symbol, "interval": interval, "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "SIGNAL" if signal else "WAIT", "signal": signal, "confluence_score": score,
            "score_out_of": 20, "score_note": "Confluence ranking only; not a measured win probability.",
            "strategies_evaluated": len(STRATEGY_CATALOG), "active_family_votes": len(votes),
            "features": {k: round(v, 6) if isinstance(v, float) else v for k, v in f.items()},
            "votes": votes, "strategy_catalog": STRATEGY_CATALOG}


def backtest_candles(candles: list[dict[str, Any]], symbol: str, interval: str,
                     initial_balance: float = 10000.0, risk_percent: float = 1.0,
                     min_score: int = 6) -> dict[str, Any]:
    if len(candles) < 260:
        raise MarketDataError("Backtest requires at least 260 candles.")
    if not 100 <= initial_balance <= 10_000_000 or not 0.05 <= risk_percent <= 2:
        raise ValueError("Balance must be $100–$10,000,000 and risk 0.05%–2%.")
    balance, peak, max_dd = initial_balance, initial_balance, 0.0
    trades, active = [], None
    # Walk forward: each decision sees only candles up to that closed bar.
    for i in range(210, len(candles)):
        row = candles[i]
        if active:
            side, entry, stop, t1, t2, t3 = (active[k] for k in ("side","entry","stop","tp1","tp2","tp3"))
            hit_sl = row["low"] <= stop if side == "BUY" else row["high"] >= stop
            if hit_sl:
                # Conservative ordering: if SL and TP are both inside one candle, SL wins.
                pnl = active["risk_cash"] * (-1.0 if not active["be"] else 0.0)
                balance += pnl
                trades.append({**active, "exit": stop, "pnl": round(pnl, 2), "result": "LOSS" if pnl < 0 else "BREAKEVEN", "exit_time": row["time"]})
                active = None
            else:
                targets = [t1,t2,t3]
                for n, target in enumerate(targets):
                    key = f"tp{n+1}_hit"
                    if not active[key] and (row["high"] >= target if side == "BUY" else row["low"] <= target):
                        active[key] = True
                        # Three equal partials; after TP1 the remaining stop is moved to entry.
                        gain = active["risk_cash"] * (1/3) * (n+1)
                        balance += gain
                        if n == 0:
                            active["be"] = True
                            active["stop"] = entry
                        if n == 2:
                            trades.append({**active, "exit": target, "pnl": round(active["realized"], 2) if "realized" in active else round(active["risk_cash"] * 2, 2), "result": "WIN", "exit_time": row["time"]})
                            active = None
                        else:
                            active["realized"] = active.get("realized", 0.0) + gain
                if active and active["be"] and not (active["tp1_hit"] or active["tp2_hit"] or active["tp3_hit"]):
                    pass
            peak = max(peak, balance)
            max_dd = max(max_dd, (peak-balance)/peak*100 if peak else 0)
            continue
        try:
            result = analyze_candles(candles[:i+1], symbol, interval, min_score)
        except (ValueError, KeyError, IndexError):
            continue
        sig = result.get("signal")
        if not sig:
            continue
        risk_cash = balance * risk_percent / 100
        active = {"symbol": symbol, "side": sig["side"], "entry": sig["entry"], "stop": sig["stop_loss"],
                  "tp1": sig["tp1"], "tp2": sig["tp2"], "tp3": sig["tp3"], "risk_cash": risk_cash,
                  "be": False, "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
                  "signal_time": row["time"], "families": sig["confirmations"]}
    if active:
        # Close the final open trade at the last candle close; no future candle is assumed.
        close = float(candles[-1]["close"])
        sign = 1 if active["side"] == "BUY" else -1
        remaining = sum(not active[f"tp{x}_hit"] for x in (1,2,3))/3
        pnl = active.get("realized", 0.0) + max(-active["risk_cash"], min(active["risk_cash"]*3, (close-active["entry"])*sign/active["risk_distance"]*active["risk_cash"]))*remaining
        balance += pnl
        trades.append({**active, "exit": close, "pnl": round(pnl,2), "result": "WIN" if pnl>0 else "LOSS" if pnl<0 else "BREAKEVEN", "exit_time": candles[-1]["time"]})
    wins = sum(t["pnl"] > 0 for t in trades)
    losses = sum(t["pnl"] < 0 for t in trades)
    gross_profit = sum(max(0,t["pnl"]) for t in trades)
    gross_loss = abs(sum(min(0,t["pnl"]) for t in trades))
    return {"symbol":symbol,"interval":interval,"initial_balance":round(initial_balance,2),"final_balance":round(balance,2),
            "net_pnl":round(balance-initial_balance,2),"trades":len(trades),"wins":wins,"losses":losses,
            "breakeven":len(trades)-wins-losses,"win_rate":round(wins/len(trades)*100,2) if trades else 0.0,
            "profit_factor":round(gross_profit/gross_loss,3) if gross_loss else None,
            "max_drawdown_percent":round(max_dd,2),"one_position_per_symbol":True,
            "risk_percent":risk_percent,"execution":"historical simulation only","trade_history":trades[-200:]}

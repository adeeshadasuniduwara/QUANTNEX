"""Phase 10 deterministic market-data validation and execution safety gates."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from math import isfinite
from typing import Any

TIMEFRAME_SECONDS={"5m":300,"15m":900,"1h":3600,"4h":14400}

def parse_provider_time(value: Any) -> datetime | None:
    if value is None: return None
    try:
        if isinstance(value,(int,float)):
            stamp=float(value)
            if not isfinite(stamp): return None
            if stamp>10_000_000_000: stamp/=1000
            return datetime.fromtimestamp(stamp,tz=timezone.utc)
        raw=str(value).strip()
        if not raw: return None
        if raw.isdigit():
            return parse_provider_time(int(raw))
        parsed=datetime.fromisoformat(raw.replace("Z","+00:00"))
        if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError,TypeError,OverflowError,OSError):
        return None

def assess_quote(quote: dict, now: datetime | None=None) -> dict:
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issues=[]; warnings=[]
    try: price=float(quote.get("price"))
    except (TypeError,ValueError): price=float("nan")
    if not isfinite(price) or price<=0: issues.append("INVALID_PRICE")
    source_time=parse_provider_time(quote.get("source_timestamp"))
    if source_time is None:
        issues.append("MISSING_PROVIDER_TIMESTAMP")
        age=None
    else:
        age=(now-source_time).total_seconds()
        if age < -30: issues.append("FUTURE_PROVIDER_TIMESTAMP")
        max_age=180 if quote.get("kind")=="crypto" else 1800
        if age>max_age: issues.append("STALE_QUOTE")
        elif age>max_age*0.6: warnings.append("QUOTE_NEAR_STALE_LIMIT")
    status="UNSAFE" if issues else "DEGRADED" if warnings else "HEALTHY"
    return {"status":status,"trading_safe":not issues,"issues":issues,"warnings":warnings,
            "age_seconds":round(age,2) if age is not None else None,
            "max_age_seconds":180 if quote.get("kind")=="crypto" else 1800,
            "provider_timestamp":source_time.isoformat() if source_time else None}

def assess_candles(candles: list[dict], timeframe: str, now: datetime | None=None) -> dict:
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError("Unsupported timeframe. Choose 5m, 15m, 1h or 4h.")
    issues=[];warnings=[];seen=set();previous=None;gaps=0
    seconds=TIMEFRAME_SECONDS[timeframe]
    if not isinstance(candles,list) or not candles:
        return {"status":"UNSAFE","trading_safe":False,"issues":["NO_CANDLES"],"warnings":[],"count":0,"gap_count":0}
    for index,row in enumerate(candles):
        stamp=parse_provider_time(row.get("time"))
        if stamp is None:
            issues.append("INVALID_CANDLE_TIMESTAMP");continue
        key=stamp.isoformat()
        if key in seen: issues.append("DUPLICATE_CANDLE")
        seen.add(key)
        if stamp>now+timedelta(seconds=30): issues.append("FUTURE_CANDLE")
        if previous is not None:
            delta=(stamp-previous).total_seconds()
            if delta<=0: issues.append("NON_MONOTONIC_CANDLES")
            elif delta>seconds*3:
                gaps+=1
        previous=stamp
        try:
            o,h,l,c=[float(row[k]) for k in ("open","high","low","close")]
            if not all(isfinite(x) and x>0 for x in (o,h,l,c)): raise ValueError()
            if h<max(o,c,l) or l>min(o,c,h): issues.append("INVALID_OHLC_RANGE")
            if "volume" in row and row["volume"] is not None:
                v=float(row["volume"])
                if not isfinite(v) or v<0: issues.append("INVALID_VOLUME")
        except (KeyError,TypeError,ValueError):
            issues.append("INVALID_CANDLE_VALUES")
    if gaps: warnings.append("CANDLE_TIME_GAPS")
    latest=parse_provider_time(candles[-1].get("time"))
    if latest and (now-latest).total_seconds()>seconds*4:
        issues.append("STALE_CANDLE_SERIES")
    status="UNSAFE" if issues else "DEGRADED" if warnings else "HEALTHY"
    return {"status":status,"trading_safe":not issues,"issues":sorted(set(issues)),
            "warnings":warnings,"count":len(candles),"gap_count":gaps,
            "latest_candle_timestamp":latest.isoformat() if latest else None,
            "expected_interval_seconds":seconds}

def assess_market_snapshot(quote: dict, candles: list[dict] | None=None,
                           timeframe: str="15m", now: datetime | None=None) -> dict:
    q=assess_quote(quote,now)
    c=assess_candles(candles,timeframe,now) if candles is not None else None
    issues=list(q["issues"])+(c["issues"] if c else [])
    warnings=list(q["warnings"])+(c["warnings"] if c else [])
    status="UNSAFE" if issues else "DEGRADED" if warnings else "HEALTHY"
    return {"symbol":quote.get("symbol"),"provider":quote.get("provider"),"status":status,
            "trading_safe":not issues,"quote":q,"candles":c,"issues":issues,"warnings":warnings}

def execution_gate(quote: dict, now: datetime | None=None) -> dict:
    health=assess_quote(quote,now)
    return {"allowed":health["trading_safe"],"reason":None if health["trading_safe"] else
            "Paper entry blocked by Market Data Guardian: "+", ".join(health["issues"]),
            "health":health}

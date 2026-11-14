"""XAUUSD multi-timeframe confluence engine using a configured Twelve Data feed.

Scores are rule-based confluence counts, never estimated win probabilities.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone, timedelta
import math
import time
from typing import Any
import httpx
from .config import TWELVE_DATA_API_KEY, QUANTNEX_MT5_ENABLED, QUANTNEX_MT5_GOLD_SYMBOL

BASE = "https://api.twelvedata.com/time_series"
INTERVALS = {"1": "1min", "5": "5min", "15": "15min", "30": "30min", "60": "1h", "240": "4h"}

class MarketDataError(RuntimeError):
    pass

CRYPTO_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "BCHUSDT", "DOTUSDT", "TRXUSDT", "TONUSDT", "SUIUSDT", "NEARUSDT", "UNIUSDT", "AAVEUSDT", "SHIBUSDT", "PEPEUSDT"}
BINANCE_INTERVALS = {"1min":"1m", "5min":"5m", "15min":"15m", "30min":"30m", "1h":"1h", "4h":"4h"}
INTERVAL_SECONDS = {"1min":60, "5min":300, "15min":900, "30min":1800,
                    "1h":3600, "4h":14400, "50min":3000}


def closed_candles(candles: list[dict[str, Any]], interval: str,
                   now: datetime | None = None) -> list[dict[str, Any]]:
    """Keep only candles whose full interval has elapsed at the supplied UTC time."""
    seconds = INTERVAL_SECONDS.get(interval)
    if seconds is None:
        raise MarketDataError(f"Unsupported candle interval for close validation: {interval}.")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    result = []
    for candle in candles:
        try:
            stamp = datetime.fromisoformat(str(candle["time"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if stamp.astimezone(timezone.utc).timestamp() + seconds <= current.timestamp():
                result.append(candle)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return result
_GOLD_CANDLE_CACHE: dict[tuple[str, str, int], tuple[float, list[dict[str, Any]]]] = {}
_GOLD_CANDLE_CACHE_TTL = 15.0


def _normalize_gold_candles(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and normalize provider OHLC rows into unique ascending UTC candles."""
    normalized: dict[int, dict[str, Any]] = {}
    for row in values:
        try:
            raw_time = str(row["datetime"]).replace("Z", "+00:00")
            stamp = datetime.fromisoformat(raw_time)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamp = stamp.astimezone(timezone.utc)
            prices = [float(row[key]) for key in ("open", "high", "low", "close")]
            if not all(math.isfinite(value) and value > 0 for value in prices):
                continue
            op, high, low, close = prices
            if high < max(op, close, low) or low > min(op, close, high):
                continue
            volume = float(row.get("volume", 0.0) or 0.0)
            if not math.isfinite(volume) or volume < 0:
                volume = 0.0
            normalized[int(stamp.timestamp())] = {
                "time": stamp.isoformat(), "open": op, "high": high,
                "low": low, "close": close, "volume": volume,
            }
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return [normalized[key] for key in sorted(normalized)]

async def _fetch_coinbase_candles(symbol: str, interval: str, requested: int) -> list[dict[str, Any]]:
    """Public BTC/ETH/SOL USD candles used only when Binance history is unreachable."""
    products = {"BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD", "SOLUSDT": "SOL-USD"}
    product = products.get(symbol)
    granularities = {"1min": 60, "5min": 300, "15min": 900, "1h": 3600}
    granularity = granularities.get(interval)
    if not product or granularity is None:
        raise MarketDataError("Coinbase fallback supports BTCUSDT, ETHUSDT and SOLUSDT at 1m, 5m, 15m or 1h.")
    count = min(max(int(requested), 210), 300)
    end = datetime.now(timezone.utc)
    begin = end - timedelta(seconds=granularity * (count + 2))
    params = {
        "granularity": granularity,
        "start": begin.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "end": end.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(18, connect=5), follow_redirects=True,
                                 headers={"User-Agent": "QUANTNEX-Market-Data"}) as client:
        response = await client.get(f"https://api.exchange.coinbase.com/products/{product}/candles", params=params)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        raise MarketDataError("Coinbase returned an unexpected candle response.")
    candles = []
    for row in payload:
        try:
            # Coinbase Exchange order: [time, low, high, open, close, volume].
            stamp = datetime.fromtimestamp(int(row[0]), timezone.utc).isoformat()
            low, high, op, close, volume = (float(row[i]) for i in (1, 2, 3, 4, 5))
            if not all(math.isfinite(value) for value in (low, high, op, close, volume)):
                continue
            if min(low, high, op, close) <= 0 or volume < 0 or high < max(op, close, low) or low > min(op, close, high):
                continue
            candles.append({"time": stamp, "open": op, "high": high, "low": low,
                            "close": close, "volume": volume})
        except (IndexError, TypeError, ValueError, OverflowError):
            continue
    candles.sort(key=lambda item: item["time"])
    candles = closed_candles(candles, interval)
    if len(candles) < 210:
        raise MarketDataError(f"Coinbase returned only {len(candles)} valid closed {interval} candles; 210 are required.")
    return candles[-count:]


async def fetch_candles_with_provider(interval: str, outputsize: int = 320,
                                      symbol: str = "XAUUSD") -> tuple[list[dict[str, Any]], str]:
    """Fetch validated candles and return the actual provider used for the chart."""
    symbol = str(symbol).upper()
    if symbol in CRYPTO_SYMBOLS:
        binance_interval = BINANCE_INTERVALS.get(interval)
        if not binance_interval:
            raise MarketDataError(f"Unsupported Binance candle interval: {interval}.")
        requested = min(max(int(outputsize), 210), 3200)
        try:
            rows = []
            end_time = None
            async with httpx.AsyncClient(timeout=httpx.Timeout(18, connect=5)) as client:
                while len(rows) < requested:
                    limit = min(1000, requested - len(rows))
                    params = {"symbol":symbol,"interval":binance_interval,"limit":limit}
                    if end_time is not None:
                        params["endTime"] = end_time
                    response = await client.get("https://api.binance.com/api/v3/klines", params=params)
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, list) or not payload:
                        raise MarketDataError("Binance returned no candle rows.")
                    rows = payload + rows
                    end_time = int(payload[0][0]) - 1
                    if len(payload) < limit:
                        break
            candles=[]
            for row in rows[-requested:]:
                try:
                    stamp=datetime.fromtimestamp(int(row[0])/1000, timezone.utc).isoformat()
                    op, high, low, close, volume = (float(row[i]) for i in (1, 2, 3, 4, 5))
                    if not all(math.isfinite(value) for value in (op, high, low, close, volume)):
                        continue
                    if min(op, high, low, close) <= 0 or volume < 0 or high < max(op, close, low) or low > min(op, close, high):
                        continue
                    candles.append({"time":stamp,"open":op,"high":high,"low":low,"close":close,"volume":volume})
                except (IndexError,TypeError,ValueError,OverflowError):
                    continue
            candles = closed_candles(candles, interval)
            if len(candles) < 210:
                raise MarketDataError(f"Not enough CLOSED {symbol} {interval} Binance candles ({len(candles)} received).")
            return candles, "Binance Spot"
        except (httpx.HTTPError, MarketDataError, ValueError, TypeError, IndexError) as binance_error:
            try:
                candles = await _fetch_coinbase_candles(symbol, interval, requested)
                return candles, "Coinbase Exchange fallback"
            except (httpx.HTTPError, MarketDataError, ValueError, TypeError) as coinbase_error:
                raise MarketDataError(
                    f"Binance candles unavailable ({binance_error}); Coinbase fallback unavailable ({coinbase_error})."
                ) from coinbase_error

    if symbol != "XAUUSD":
        raise MarketDataError("Supported crypto markets: "+", ".join(sorted(CRYPTO_SYMBOLS))+"; gold: XAUUSD.")
    mt5_error = None
    if QUANTNEX_MT5_ENABLED:
        from .mt5_feed import get_candles as get_mt5_candles, MT5FeedError
        try:
            candles = await get_mt5_candles(QUANTNEX_MT5_GOLD_SYMBOL, interval.replace("min", "m"), min(max(outputsize, 210), 1000))
            candles = closed_candles(candles, interval)
            if len(candles) < 210:
                raise MarketDataError(f"Not enough CLOSED MT5 {interval} XAUUSD candles ({len(candles)} received).")
            return candles, "MetaTrader 5 local terminal"
        except (MT5FeedError, MarketDataError) as exc:
            mt5_error = str(exc)
    if not TWELVE_DATA_API_KEY:
        detail = "Gold historical candles require a connected MT5 terminal with QUANTNEX_MT5_ENABLED=true or a TWELVE_DATA_API_KEY in backend/.env."
        if mt5_error:
            detail += " MT5 detail: " + mt5_error
        raise MarketDataError(detail)
    requested = min(max(int(outputsize), 210), 5000)
    cache_key = (symbol, interval, requested)
    cached = _GOLD_CANDLE_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < _GOLD_CANDLE_CACHE_TTL:
        return [dict(row) for row in cached[1]], "Twelve Data (cached)"
    async with httpx.AsyncClient(timeout=18) as client:
        response = await client.get(BASE, params={"symbol":"XAU/USD","interval":interval,
            "outputsize":requested,"timezone":"UTC","apikey":TWELVE_DATA_API_KEY})
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or payload.get("status") == "error" or not isinstance(payload.get("values"), list):
        detail = payload.get("message") or payload.get("code") if isinstance(payload, dict) else "Provider returned an invalid candle response."
        raise MarketDataError(str(detail or "Provider returned no candle data."))
    candles = _normalize_gold_candles(payload["values"])
    candles = closed_candles(candles, interval)
    if len(candles) < 210:
        raise MarketDataError(f"Not enough valid CLOSED {interval} XAUUSD candles for stable indicator calculations ({len(candles)} received).")
    candles = candles[-requested:]
    _GOLD_CANDLE_CACHE[cache_key] = (time.monotonic(), candles)
    return [dict(row) for row in candles], "Twelve Data"


async def fetch_candles(interval: str, outputsize: int = 320, symbol: str = "XAUUSD") -> list[dict[str, Any]]:
    candles, _provider = await fetch_candles_with_provider(interval, outputsize, symbol)
    return candles

def aggregate_minutes(candles: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
    """Aggregate 1-minute UTC candles into fixed minute bars."""
    from datetime import datetime
    buckets={}
    for c in candles:
        try:
            stamp=datetime.fromisoformat(c["time"].replace("Z","+00:00"))
            if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
            epoch=int(stamp.timestamp())
        except (ValueError,TypeError):
            continue
        key=epoch//(minutes*60)
        b=buckets.get(key)
        if b is None:
            bucket_start = datetime.fromtimestamp(key * minutes * 60, timezone.utc).isoformat()
            buckets[key]={"time":bucket_start,"open":c["open"],"high":c["high"],"low":c["low"],"close":c["close"]}
        else:
            b["high"]=max(b["high"],c["high"]);b["low"]=min(b["low"],c["low"]);b["close"]=c["close"]
    return [buckets[k] for k in sorted(buckets)]

def ema(values: list[float], period: int) -> list[float]:
    if not values: return []
    alpha=2/(period+1); out=[values[0]]
    for value in values[1:]: out.append(alpha*value+(1-alpha)*out[-1])
    return out

def rsi(values: list[float], period: int=14) -> float:
    changes=[values[i]-values[i-1] for i in range(1,len(values))]
    if len(changes)<period: return 50.0
    gains=[max(x,0) for x in changes]; losses=[max(-x,0) for x in changes]
    avg_gain=sum(gains[:period])/period; avg_loss=sum(losses[:period])/period
    for i in range(period,len(changes)):
        avg_gain=(avg_gain*(period-1)+gains[i])/period
        avg_loss=(avg_loss*(period-1)+losses[i])/period
    if avg_loss==0: return 100.0
    rs=avg_gain/avg_loss
    return 100-(100/(1+rs))

def atr(c: list[dict[str,Any]], period: int=14) -> float:
    trs=[]
    for i in range(1,len(c)):
        prev=c[i-1]["close"]; row=c[i]
        trs.append(max(row["high"]-row["low"],abs(row["high"]-prev),abs(row["low"]-prev)))
    return sum(trs[-period:])/min(period,len(trs)) if trs else 0.0

def adx(c: list[dict[str,Any]], period: int=14) -> float:
    if len(c)<period*2+1:return 0.0
    trs=[]; plus=[]; minus=[]
    for i in range(1,len(c)):
        cur,prev=c[i],c[i-1]
        up=cur["high"]-prev["high"]; down=prev["low"]-cur["low"]
        plus.append(up if up>down and up>0 else 0.0)
        minus.append(down if down>up and down>0 else 0.0)
        trs.append(max(cur["high"]-cur["low"],abs(cur["high"]-prev["close"]),abs(cur["low"]-prev["close"])))
    dx=[]
    for i in range(period-1,len(trs)):
        tr=sum(trs[i-period+1:i+1]); p=sum(plus[i-period+1:i+1]); m=sum(minus[i-period+1:i+1])
        if tr<=0: continue
        pdi=100*p/tr; mdi=100*m/tr
        dx.append(100*abs(pdi-mdi)/max(pdi+mdi,1e-9))
    return sum(dx[-period:])/len(dx[-period:]) if dx else 0.0

def macd(values: list[float]) -> tuple[float,float,float]:
    fast=ema(values,12); slow=ema(values,26)
    line=[a-b for a,b in zip(fast,slow)]
    signal=ema(line,9)
    return line[-1],signal[-1],line[-1]-signal[-1]

def structure(c: list[dict[str,Any]]) -> dict[str,Any]:
    """Return confirmed two-sided swing structure and the latest BOS/MSS event.

    Swing points use a 2-left/2-right confirmation window, so the newest two
    candles are never treated as confirmed pivots. The event is emitted only
    when the latest candle closes through a previously confirmed swing.
    """
    recent=c[-120:]
    if len(recent)<8:
        raise ValueError("At least eight candles are required for structure analysis.")
    highs=[];lows=[]
    for i in range(2,len(recent)-2):
        row=recent[i]
        if row["high"]>=max(x["high"] for x in recent[i-2:i]) and row["high"]>max(x["high"] for x in recent[i+1:i+3]):
            highs.append((i,row))
        if row["low"]<=min(x["low"] for x in recent[i-2:i]) and row["low"]<min(x["low"] for x in recent[i+1:i+3]):
            lows.append((i,row))
    fallback=recent[-32:-2]
    swing_high=highs[-1][1]["high"] if highs else max(x["high"] for x in fallback)
    swing_low=lows[-1][1]["low"] if lows else min(x["low"] for x in fallback)
    trend="NEUTRAL"
    if len(highs)>=2 and len(lows)>=2:
        hh=highs[-1][1]["high"]>highs[-2][1]["high"]
        hl=lows[-1][1]["low"]>lows[-2][1]["low"]
        lh=highs[-1][1]["high"]<highs[-2][1]["high"]
        ll=lows[-1][1]["low"]<lows[-2][1]["low"]
        if hh and hl: trend="BULLISH"
        elif lh and ll: trend="BEARISH"
    last=recent[-1];prev=recent[-2]
    bullish_break=prev["close"]<=swing_high and last["close"]>swing_high
    bearish_break=prev["close"]>=swing_low and last["close"]<swing_low
    event="NONE"
    if bullish_break:
        event="BULLISH_MSS" if trend=="BEARISH" else "BULLISH_BOS"
    elif bearish_break:
        event="BEARISH_MSS" if trend=="BULLISH" else "BEARISH_BOS"
    direction="BULLISH" if event.startswith("BULLISH") else "BEARISH" if event.startswith("BEARISH") else "NONE"
    sweep="BULLISH" if last["low"]<swing_low and last["close"]>swing_low else "BEARISH" if last["high"]>swing_high and last["close"]<swing_high else "NONE"
    bull_fvg=None;bear_fvg=None
    for i in range(max(2,len(recent)-40),len(recent)):
        a,b,d=recent[i-2],recent[i-1],recent[i]
        if a["high"]<d["low"]: bull_fvg={"low":a["high"],"high":d["low"]}
        if a["low"]>d["high"]: bear_fvg={"low":d["high"],"high":a["low"]}
    bull_ob=None;bear_ob=None
    if direction=="BULLISH":
        for row in reversed(recent[-12:-1]):
            if row["close"]<row["open"]: bull_ob={"low":row["low"],"high":row["high"]};break
    if direction=="BEARISH":
        for row in reversed(recent[-12:-1]):
            if row["close"]>row["open"]: bear_ob={"low":row["low"],"high":row["high"]};break
    bull_ifvg={"low":bull_fvg["low"],"high":bull_fvg["high"]} if bull_fvg and last["close"]<bull_fvg["low"] else None
    bear_ifvg={"low":bear_fvg["low"],"high":bear_fvg["high"]} if bear_fvg and last["close"]>bear_fvg["high"] else None
    bear_breaker={"low":bull_ob["low"],"high":bull_ob["high"]} if bull_ob and last["close"]<bull_ob["low"] else None
    bull_breaker={"low":bear_ob["low"],"high":bear_ob["high"]} if bear_ob and last["close"]>bear_ob["high"] else None
    volatility=atr(recent,14)
    pad=max(volatility*0.12,abs(last["close"])*0.00001)
    support={"low":swing_low-pad,"high":swing_low+pad}
    resistance={"low":swing_high-pad,"high":swing_high+pad}
    equilibrium=(swing_high+swing_low)/2
    premium_discount="DISCOUNT" if last["close"]<equilibrium else "PREMIUM"
    return {"bos_mss":direction,"structure_event":event,"structure_trend":trend,
            "liquidity_sweep":sweep,"bullish_fvg":bull_fvg,"bearish_fvg":bear_fvg,
            "bullish_ifvg":bull_ifvg,"bearish_ifvg":bear_ifvg,
            "bullish_order_block":bull_ob,"bearish_order_block":bear_ob,
            "bullish_breaker_block":bull_breaker,"bearish_breaker_block":bear_breaker,
            "support_zone":support,"resistance_zone":resistance,
            "premium_discount":premium_discount,"equilibrium":equilibrium,
            "swing_high":swing_high,"swing_low":swing_low}

def inspect_tf(c: list[dict[str,Any]]) -> dict[str,Any]:
    close=[x["close"] for x in c]; e20=ema(close,20)[-1];e50=ema(close,50)[-1];e200=ema(close,200)[-1] if len(close)>=200 else None
    m,ms,mh=macd(close); rv=rsi(close); av=atr(c); dx=adx(c); last=close[-1]
    bias="BULLISH" if last>e20 and e20>e50 and (e200 is None or last>e200) else "BEARISH" if last<e20 and e20<e50 and (e200 is None or last<e200) else "NEUTRAL"
    return {"bias":bias,"close":last,"ema20":e20,"ema50":e50,"ema200":e200,"macd":m,"macd_signal":ms,
            "macd_histogram":mh,"rsi":rv,"atr":av,"adx":dx,"structure":structure(c)}

async def build_signal(settings: dict[str,Any], symbol: str = "XAUUSD") -> dict[str,Any]:
    symbol = str(symbol).upper()
    if symbol not in CRYPTO_SYMBOLS and symbol != "XAUUSD":
        raise MarketDataError("Supported signal markets: BTCUSDT, ETHUSDT, SOLUSDT and XAUUSD.")
    enabled=[str(x) for x in settings.get("enabled",["60","30","15","5","1"])]
    if not enabled: enabled=["60","30","15","5","1"]
    needed=set(enabled+[str(settings.get("primary","5")),str(settings.get("trend","60"))])
    if "50" in needed: needed.add("1")
    tasks={}
    for tf in needed:
        if tf in INTERVALS: tasks[tf]=fetch_candles(INTERVALS[tf],3200 if tf=="1" and "50" in needed else 320,symbol)
    results=await asyncio.gather(*tasks.values(),return_exceptions=True)
    candles={}
    errors=[]
    for tf,result in zip(tasks,results):
        if isinstance(result,Exception):
            errors.append(f"{tf}m: {str(result)}")
        else: candles[tf]=result
    if "50" in needed and "1" in candles:
        candles["50"] = closed_candles(aggregate_minutes(candles["1"], 50), "50min")
        if len(candles["50"]) < 50:
            raise MarketDataError("Not enough fully closed M50 candles for stable indicator calculations.")
    if errors: raise MarketDataError("; ".join(errors))
    analysis={tf:inspect_tf(candles[tf]) for tf in needed if tf in candles and len(candles[tf])>=(50 if tf=="50" else 210)}
    primary=str(settings.get("primary","5")); trend=str(settings.get("trend","60"))
    if primary not in analysis or trend not in analysis: raise MarketDataError("Selected primary/trend timeframe does not have enough candles.")
    p=analysis[primary]; t=analysis[trend]; side=None
    # Score ten transparent rule checks, rather than claiming a probability of winning.
    close=p["close"]; st=p["structure"]; buy=[];sell=[]
    for tf in ["60","30","15"]:
        if tf in analysis:
            (buy if analysis[tf]["bias"]=="BULLISH" else sell if analysis[tf]["bias"]=="BEARISH" else []).append(f"{tf}m EMA trend")
    (buy if p["macd_histogram"]>0 else sell if p["macd_histogram"]<0 else []).append("Primary MACD momentum")
    if 50<=p["rsi"]<=70: buy.append("RSI bullish range")
    elif 30<=p["rsi"]<=50: sell.append("RSI bearish range")
    if p["adx"]>=18: (buy if p["macd_histogram"]>0 else sell if p["macd_histogram"]<0 else []).append("ADX trend strength")
    if st["bos_mss"]=="BULLISH":buy.append("Bullish BOS / MSS")
    elif st["bos_mss"]=="BEARISH":sell.append("Bearish BOS / MSS")
    if st["liquidity_sweep"]=="BULLISH":buy.append("Sell-side liquidity sweep")
    elif st["liquidity_sweep"]=="BEARISH":sell.append("Buy-side liquidity sweep")
    zone=(st["bullish_fvg"] or st["bullish_order_block"] or st["bullish_breaker_block"] or st["bullish_ifvg"]) if p["macd_histogram"]>0 else (st["bearish_fvg"] or st["bearish_order_block"] or st["bearish_breaker_block"] or st["bearish_ifvg"])
    in_zone=bool(zone and zone["low"]<=close<=zone["high"])
    discount_buy=st.get("premium_discount")=="DISCOUNT" and p["macd_histogram"]>0
    premium_sell=st.get("premium_discount")=="PREMIUM" and p["macd_histogram"]<0
    if in_zone or discount_buy or premium_sell:
        (buy if p["macd_histogram"]>0 else sell).append("OB / FVG / breaker or premium-discount zone")
    # Count directional timeframe alignment as the tenth confluence.
    if t["bias"]=="BULLISH":buy.append("Trend timeframe aligned")
    elif t["bias"]=="BEARISH":sell.append("Trend timeframe aligned")
    bscore=min(10,len(buy));sscore=min(10,len(sell))
    threshold=int(settings.get("min_score",7))
    if bscore>=threshold and bscore>sscore: side="BUY";checks=buy;score=bscore
    elif sscore>=threshold and sscore>bscore: side="SELL";checks=sell;score=sscore
    else: checks=buy if bscore>=sscore else sell;score=max(bscore,sscore)
    # Directional quality gate: no signal against the selected primary/trend bias,
    # with weak ADX or an overextended RSI. Enabled higher timeframes must broadly agree.
    quality_filters={"primary_bias_aligned":False,"trend_bias_aligned":False,"adx_strength":False,
                     "rsi_not_extreme":False,"macd_direction":False,"timeframe_consensus":False}
    if side:
        primary_aligned=p["bias"]==("BULLISH" if side=="BUY" else "BEARISH")
        trend_aligned=t["bias"]==("BULLISH" if side=="BUY" else "BEARISH")
        adx_ok=p["adx"]>=18
        rsi_ok=(45<=p["rsi"]<=68) if side=="BUY" else (32<=p["rsi"]<=55)
        macd_ok=(p["macd_histogram"]>0) if side=="BUY" else (p["macd_histogram"]<0)
        directional=[analysis[x]["bias"] for x in enabled if x in analysis and x!=primary]
        aligned=sum(x==("BULLISH" if side=="BUY" else "BEARISH") for x in directional)
        consensus_ok=not directional or aligned/len(directional)>=0.60
        quality_filters={"primary_bias_aligned":primary_aligned,"trend_bias_aligned":trend_aligned,
                         "adx_strength":adx_ok,"rsi_not_extreme":rsi_ok,"macd_direction":macd_ok,
                         "timeframe_consensus":consensus_ok}
        if not all(quality_filters.values()):
            side=None
    signal=None
    if side:
        risk=max(p["atr"]*1.5,abs(close-(st["swing_low"] if side=="BUY" else st["swing_high"])))
        risk=max(risk,p["atr"]*0.8)
        sl=close-risk if side=="BUY" else close+risk
        sign=1 if side=="BUY" else -1
        signal={"symbol":symbol,"side":side,"timeframe":primary,"trend_timeframe":trend,
                "entry":round(close,2),"signal_candle_time":candles[primary][-1]["time"],"stop_loss":round(sl,2),"tp1":round(close+sign*risk,2),
                "tp2":round(close+sign*risk*2,2),"tp3":round(close+sign*risk*3,2),
                "score":score,"out_of":10,"confirmations":checks,"risk_distance":round(risk,2)}
    return {"symbol":symbol,"provider":"Binance Spot" if symbol in CRYPTO_SYMBOLS else "Twelve Data","generated_at":datetime.now(timezone.utc).isoformat(),
            "signal":signal,"confluence_score":score,"score_out_of":10,"score_note":"Rule-based confluence count, not a measured win probability.",
            "timeframes":{tf:{"bias":v["bias"],"close":round(v["close"],2),"ema20":round(v["ema20"],2),
                "ema50":round(v["ema50"],2),"ema200":round(v["ema200"],2) if v["ema200"] is not None else None,"macd_histogram":round(v["macd_histogram"],4),
                "rsi":round(v["rsi"],1),"adx":round(v["adx"],1),"atr":round(v["atr"],3),
                "structure":v["structure"]} for tf,v in analysis.items()},
            "quality_filters":quality_filters,"status":"SIGNAL" if signal else "WAIT","message":"Confluence threshold and directional quality filters met." if signal else "WAIT — confluence threshold or directional quality filters not met."}

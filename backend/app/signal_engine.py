"""XAUUSD multi-timeframe confluence engine using a configured Twelve Data feed.

Scores are rule-based confluence counts, never estimated win probabilities.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any
import httpx
from .config import TWELVE_DATA_API_KEY, QUANTNEX_MT5_ENABLED, QUANTNEX_MT5_GOLD_SYMBOL

BASE = "https://api.twelvedata.com/time_series"
INTERVALS = {"1": "1min", "5": "5min", "15": "15min", "30": "30min", "60": "1h", "240": "4h"}

class MarketDataError(RuntimeError):
    pass

CRYPTO_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "BCHUSDT", "DOTUSDT", "TRXUSDT", "TONUSDT", "SUIUSDT", "NEARUSDT", "UNIUSDT", "AAVEUSDT", "SHIBUSDT", "PEPEUSDT"}
BINANCE_INTERVALS = {"1min":"1m", "5min":"5m", "15min":"15m", "30min":"30m", "1h":"1h", "4h":"4h"}

async def fetch_candles(interval: str, outputsize: int = 320, symbol: str = "XAUUSD") -> list[dict[str, Any]]:
    symbol = str(symbol).upper()
    if symbol in CRYPTO_SYMBOLS:
        binance_interval = BINANCE_INTERVALS.get(interval)
        if not binance_interval:
            raise MarketDataError(f"Unsupported Binance candle interval: {interval}.")
        requested = min(max(outputsize, 210), 3200)
        interval_ms = {"1m":60000,"5m":300000,"15m":900000,"30m":1800000,"1h":3600000,"4h":14400000}[binance_interval]
        rows = []
        end_time = None
        async with httpx.AsyncClient(timeout=18) as client:
            while len(rows) < requested:
                limit = min(1000, requested - len(rows))
                params = {"symbol":symbol,"interval":binance_interval,"limit":limit}
                if end_time is not None:
                    params["endTime"] = end_time
                response = await client.get("https://api.binance.com/api/v3/klines", params=params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list) or not payload:
                    break
                rows = payload + rows
                end_time = int(payload[0][0]) - 1
                if len(payload) < limit:
                    break
        candles=[]
        for row in rows[-requested:]:
            try:
                stamp=datetime.fromtimestamp(int(row[0])/1000, timezone.utc).isoformat()
                candles.append({"time":stamp,"open":float(row[1]),"high":float(row[2]),
                                "low":float(row[3]),"close":float(row[4]),"volume":float(row[5])})
            except (IndexError,TypeError,ValueError,OverflowError):
                continue
        if len(candles) < 210:
            raise MarketDataError(f"Not enough {symbol} {interval} Binance candles for stable indicator calculations ({len(candles)} received).")
        return candles
    if symbol != "XAUUSD":
        raise MarketDataError("Supported crypto markets: "+", ".join(sorted(CRYPTO_SYMBOLS))+"; gold: XAUUSD.")
    if QUANTNEX_MT5_ENABLED:
        from .mt5_feed import get_candles as get_mt5_candles, MT5FeedError
        try:
            return await get_mt5_candles(QUANTNEX_MT5_GOLD_SYMBOL, interval.replace("min", "m"), min(max(outputsize, 210), 1000))
        except MT5FeedError as exc:
            raise MarketDataError(str(exc)) from exc
    if not TWELVE_DATA_API_KEY:
        raise MarketDataError("Gold market data is not configured. Enable QUANTNEX_MT5_ENABLED or add TWELVE_DATA_API_KEY to backend/.env.")
    async with httpx.AsyncClient(timeout=18) as client:
        response = await client.get(BASE, params={"symbol":"XAU/USD","interval":interval,
            "outputsize":min(outputsize, 5000),"timezone":"UTC","apikey":TWELVE_DATA_API_KEY})
        response.raise_for_status()
        payload = response.json()
    if payload.get("status") == "error" or not isinstance(payload.get("values"), list):
        raise MarketDataError(str(payload.get("message") or payload.get("code") or "Provider returned no candle data."))
    candles=[]
    for row in reversed(payload["values"]):
        try:
            candles.append({"time":row["datetime"],"open":float(row["open"]),"high":float(row["high"]),
                            "low":float(row["low"]),"close":float(row["close"])})
        except (KeyError,TypeError,ValueError):
            continue
    if len(candles) < 210:
        raise MarketDataError(f"Not enough {interval} candles for stable indicator calculations ({len(candles)} received).")
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
            buckets[key]={"time":c["time"],"open":c["open"],"high":c["high"],"low":c["low"],"close":c["close"]}
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
    if "50" in needed and "1" in candles: candles["50"]=aggregate_minutes(candles["1"],50)
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

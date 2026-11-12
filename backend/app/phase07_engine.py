"""Phase 07 market adapters and transparent multi-timeframe analysis.

Crypto prices/candles/order books are public Binance spot data.
XAUUSD and FX quotes/candles require the configured Twelve Data key.
Missing providers are reported as unavailable; no synthetic prices are generated.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone, date, timedelta
from typing import Any
import httpx
from .config import TWELVE_DATA_API_KEY, FINNHUB_API_KEY
from .signal_engine import inspect_tf

BINANCE = "https://api.binance.com"
TWELVE = "https://api.twelvedata.com"
MARKETS = {
    "BTCUSDT": {"kind":"crypto","provider":"Binance","label":"Bitcoin / USDT","base":"BTC","quote":"USDT"},
    "ETHUSDT": {"kind":"crypto","provider":"Binance","label":"Ethereum / USDT","base":"ETH","quote":"USDT"},
    "SOLUSDT": {"kind":"crypto","provider":"Binance","label":"Solana / USDT","base":"SOL","quote":"USDT"},
    "XAUUSD": {"kind":"gold","provider":"Twelve Data","label":"Gold / US Dollar","twelve":"XAU/USD"},
    "EURUSD": {"kind":"forex","provider":"Twelve Data","label":"Euro / US Dollar","twelve":"EUR/USD"},
    "GBPUSD": {"kind":"forex","provider":"Twelve Data","label":"Pound / US Dollar","twelve":"GBP/USD"},
    "USDJPY": {"kind":"forex","provider":"Twelve Data","label":"US Dollar / Yen","twelve":"USD/JPY"},
}
TIMEFRAMES = {"5m":"5min","15m":"15min","1h":"1h","4h":"4h"}

class IntelligenceDataError(RuntimeError):
    pass

def market_info(symbol: str) -> dict:
    key=symbol.upper().replace("/","").replace(":","")
    if key not in MARKETS:
        raise ValueError("Unsupported symbol. Choose BTCUSDT, ETHUSDT, SOLUSDT, XAUUSD, EURUSD, GBPUSD or USDJPY.")
    return {"symbol":key,**MARKETS[key]}

async def _get_json(client: httpx.AsyncClient, url: str, params: dict | None=None):
    response=await client.get(url,params=params)
    response.raise_for_status()
    data=response.json()
    if not isinstance(data,dict) and not isinstance(data,list):
        raise IntelligenceDataError("Market provider returned an invalid payload.")
    if isinstance(data,dict) and data.get("status")=="error":
        raise IntelligenceDataError(str(data.get("message") or "Market provider returned an error."))
    return data

async def get_quote(symbol: str) -> dict:
    info=market_info(symbol)
    async with httpx.AsyncClient(timeout=httpx.Timeout(12,connect=5)) as client:
        if info["kind"]=="crypto":
            data=await _get_json(client,BINANCE+"/api/v3/ticker/24hr",{"symbol":info["symbol"]})
            price=float(data["lastPrice"]); change=float(data["priceChangePercent"])
            high=float(data["highPrice"]); low=float(data["lowPrice"]); volume=float(data["quoteVolume"])
        else:
            if not TWELVE_DATA_API_KEY:
                raise IntelligenceDataError("Add TWELVE_DATA_API_KEY to backend/.env to enable Gold and Forex quotes.")
            data=await _get_json(client,TWELVE+"/quote",{"symbol":info["twelve"],"apikey":TWELVE_DATA_API_KEY})
            price=float(data["close"]); change=float(data.get("percent_change") or 0)
            high=float(data.get("high") or price); low=float(data.get("low") or price); volume=None
    if price<=0: raise IntelligenceDataError("Provider returned a non-positive price.")
    return {"symbol":info["symbol"],"label":info["label"],"kind":info["kind"],"provider":info["provider"],
            "price":price,"change_percent":change,"high_24h":high,"low_24h":low,"quote_volume":volume,
            "timestamp":datetime.now(timezone.utc).isoformat(),"indicative":True}

async def get_market_board() -> dict:
    symbols=list(MARKETS)
    results=await asyncio.gather(*(get_quote(x) for x in symbols),return_exceptions=True)
    items=[]
    for symbol,result in zip(symbols,results):
        if isinstance(result,Exception):
            items.append({"symbol":symbol,"label":MARKETS[symbol]["label"],"kind":MARKETS[symbol]["kind"],
                          "status":"unavailable","reason":"Provider request failed; check the API key, provider quota or network connection."})
        else:
            items.append({"status":"ok",**result})
    return {"items":items,"timestamp":datetime.now(timezone.utc).isoformat(),
            "note":"Indicative provider quotes; execution prices and spreads may differ at your broker."}

async def get_candles(symbol: str, timeframe: str="15m", limit: int=250) -> list[dict]:
    info=market_info(symbol)
    if timeframe not in TIMEFRAMES: raise ValueError("Timeframe must be 5m, 15m, 1h or 4h.")
    limit=max(210,min(int(limit),500))
    async with httpx.AsyncClient(timeout=httpx.Timeout(18,connect=5)) as client:
        if info["kind"]=="crypto":
            data=await _get_json(client,BINANCE+"/api/v3/klines",{"symbol":info["symbol"],"interval":timeframe,"limit":limit})
            candles=[{"time":datetime.fromtimestamp(row[0]/1000,timezone.utc).isoformat(),
                      "open":float(row[1]),"high":float(row[2]),"low":float(row[3]),"close":float(row[4]),
                      "volume":float(row[5])} for row in data]
        else:
            if not TWELVE_DATA_API_KEY:
                raise IntelligenceDataError("Add TWELVE_DATA_API_KEY to backend/.env to enable Gold and Forex candles.")
            data=await _get_json(client,TWELVE+"/time_series",{"symbol":info["twelve"],"interval":TIMEFRAMES[timeframe],
                "outputsize":limit,"timezone":"UTC","apikey":TWELVE_DATA_API_KEY})
            values=data.get("values",[]) if isinstance(data,dict) else []
            candles=[]
            for row in reversed(values):
                try:
                    candles.append({"time":row["datetime"],"open":float(row["open"]),"high":float(row["high"]),
                                    "low":float(row["low"]),"close":float(row["close"]),"volume":float(row.get("volume") or 0)})
                except (KeyError,TypeError,ValueError): continue
    if len(candles)<210:
        raise IntelligenceDataError(f"Not enough {timeframe} candles for stable analysis ({len(candles)} received; 210 required).")
    return candles

async def scan_market_signal(symbol: str, threshold: int=6) -> dict:
    info=market_info(symbol)
    frames=["15m","1h","4h"]
    results=await asyncio.gather(*(get_candles(info["symbol"],tf,250) for tf in frames))
    analysis={tf:inspect_tf(results[i]) for i,tf in enumerate(frames)}
    sides=[]
    for tf,data in analysis.items():
        sides.append("BUY" if data["bias"]=="BULLISH" else "SELL" if data["bias"]=="BEARISH" else "WAIT")
    latest=analysis["15m"]; trend=analysis["1h"]; close=latest["close"]; atr=latest["atr"]
    buy_checks=[];sell_checks=[]
    for tf,data in analysis.items():
        if data["bias"]=="BULLISH": buy_checks.append(tf+" EMA structure")
        elif data["bias"]=="BEARISH": sell_checks.append(tf+" EMA structure")
    if latest["macd_histogram"]>0: buy_checks.append("15m MACD momentum")
    elif latest["macd_histogram"]<0: sell_checks.append("15m MACD momentum")
    if 50<=latest["rsi"]<=68: buy_checks.append("RSI bullish range")
    elif 32<=latest["rsi"]<=50: sell_checks.append("RSI bearish range")
    if latest["adx"]>=18:
        (buy_checks if latest["macd_histogram"]>0 else sell_checks).append("ADX trend strength")
    structure=latest["structure"]
    if structure["bos_mss"]=="BULLISH": buy_checks.append("Bullish BOS / MSS")
    elif structure["bos_mss"]=="BEARISH": sell_checks.append("Bearish BOS / MSS")
    if structure["liquidity_sweep"]=="BULLISH": buy_checks.append("Sell-side liquidity sweep")
    elif structure["liquidity_sweep"]=="BEARISH": sell_checks.append("Buy-side liquidity sweep")
    bscore=min(10,len(buy_checks));sscore=min(10,len(sell_checks))
    side="BUY" if bscore>=threshold and bscore>sscore else "SELL" if sscore>=threshold and sscore>bscore else None
    filters={}
    if side:
        wanted="BULLISH" if side=="BUY" else "BEARISH"
        filters={"15m_bias":latest["bias"]==wanted,"1h_bias":trend["bias"]==wanted,
                 "4h_bias":analysis["4h"]["bias"]==wanted,"adx":latest["adx"]>=18,
                 "macd":(latest["macd_histogram"]>0 if side=="BUY" else latest["macd_histogram"]<0)}
        if not all(filters.values()): side=None
    score=max(bscore,sscore)
    signal=None
    if side:
        risk=max(float(atr)*1.5,0.00000001)
        sign=1 if side=="BUY" else -1
        signal={"symbol":info["symbol"],"side":side,"timeframe":"15m","trend_timeframe":"1h",
                "entry":round(close,8),"stop_loss":round(close-sign*risk,8),
                "tp1":round(close+sign*risk,8),"tp2":round(close+sign*risk*2,8),
                "tp3":round(close+sign*risk*3,8),"risk_distance":round(risk,8),
                "score":score,"out_of":10,"confirmations":buy_checks if side=="BUY" else sell_checks,
                "generated_at":datetime.now(timezone.utc).isoformat()}
    return {"symbol":info["symbol"],"provider":info["provider"],"status":"SIGNAL" if signal else "WAIT",
            "signal":signal,"confluence_score":score,"score_out_of":10,
            "score_note":"Transparent rule-based confluence count, not a win probability.",
            "timeframes":{tf:{"bias":v["bias"],"close":v["close"],"ema20":v["ema20"],"ema50":v["ema50"],
                "rsi":v["rsi"],"adx":v["adx"],"atr":v["atr"],"macd_histogram":v["macd_histogram"],
                "structure":v["structure"]} for tf,v in analysis.items()},
            "quality_filters":filters,"timeframe_alignment":sides,
            "message":"All directional filters passed." if signal else "WAIT — no sufficiently aligned setup. No trade is recommended."}

async def get_order_book(symbol: str, limit: int=20) -> dict:
    info=market_info(symbol)
    if info["kind"]!="crypto":
        return {"symbol":info["symbol"],"supported":False,"status":"unavailable",
                "reason":"This configured provider does not expose executable order-book depth for Gold/Forex. No synthetic depth is shown."}
    async with httpx.AsyncClient(timeout=12) as client:
        data=await _get_json(client,BINANCE+"/api/v3/depth",{"symbol":info["symbol"],"limit":min(max(limit,5),100)})
    bids=[{"price":float(x[0]),"quantity":float(x[1])} for x in data.get("bids",[])]
    asks=[{"price":float(x[0]),"quantity":float(x[1])} for x in data.get("asks",[])]
    bid_total=sum(x["quantity"] for x in bids);ask_total=sum(x["quantity"] for x in asks)
    total=bid_total+ask_total
    return {"symbol":info["symbol"],"supported":True,"provider":"Binance Spot","bids":bids,"asks":asks,
            "bid_quantity":bid_total,"ask_quantity":ask_total,
            "imbalance":(bid_total-ask_total)/total if total else 0,
            "timestamp":datetime.now(timezone.utc).isoformat(),
            "note":"Snapshot depth only; not full exchange-wide liquidity or executed volume."}

async def get_economic_calendar(days: int=7) -> dict:
    if not FINNHUB_API_KEY:
        return {"configured":False,"provider":"Finnhub","events":[],
                "note":"Add FINNHUB_API_KEY to backend/.env to enable the economic calendar. No events are fabricated."}
    today=date.today()
    async with httpx.AsyncClient(timeout=15) as client:
        data=await _get_json(client,"https://finnhub.io/api/v1/calendar/economic",
            {"from":today.isoformat(),"to":(today+timedelta(days=max(1,min(days,30)))).isoformat(),"token":FINNHUB_API_KEY})
    events=data.get("economicCalendar",[]) if isinstance(data,dict) else []
    return {"configured":True,"provider":"Finnhub","events":events[:500],
            "timestamp":datetime.now(timezone.utc).isoformat(),"note":"Provider calendar data; verify event time and impact before trading."}

def calculate_risk(equity: float, risk_percent: float, entry: float, stop_loss: float) -> dict:
    if equity<=0 or not 0<risk_percent<=5 or entry<=0 or stop_loss<=0 or entry==stop_loss:
        raise ValueError("Equity and prices must be positive; risk percentage must be above 0 and at most 5%.")
    risk_amount=equity*risk_percent/100
    distance=abs(entry-stop_loss)
    return {"equity":equity,"risk_percent":risk_percent,"risk_amount":round(risk_amount,2),
            "entry":entry,"stop_loss":stop_loss,"price_distance":distance,
            "estimated_units":risk_amount/distance,
            "note":"Estimated base units only. Broker lot size, contract multiplier, tick value, fees and slippage are not included."}

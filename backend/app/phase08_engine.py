"""Phase 08 deterministic strategy research tools. No broker execution."""
from __future__ import annotations
from math import isfinite
from statistics import mean

def validate_strategy(strategy: dict) -> dict:
    fast=int(strategy.get("fast_ema",9)); slow=int(strategy.get("slow_ema",21))
    rr=float(strategy.get("risk_reward",2.0))
    if not (2 <= fast <= 50 and fast < slow <= 200):
        raise ValueError("EMA settings must satisfy 2 <= fast EMA < slow EMA <= 200.")
    if not (0.5 <= rr <= 8 and isfinite(rr)):
        raise ValueError("Risk/reward must be between 0.5 and 8.")
    return {"name":str(strategy.get("name","EMA Trend Cross"))[:60],
            "fast_ema":fast,"slow_ema":slow,"risk_reward":rr}

def ema(values: list[float], period: int) -> list[float | None]:
    alpha=2/(period+1); result=[]; current=None
    for value in values:
        current=value if current is None else alpha*value+(1-alpha)*current
        result.append(current)
    return result

def run_backtest(candles: list[dict], raw_strategy: dict) -> dict:
    cfg=validate_strategy(raw_strategy)
    if len(candles) < max(cfg["slow_ema"]+5, 60):
        raise ValueError("At least 60 candles and enough warm-up history are required.")
    closes=[float(x["close"]) for x in candles]
    highs=[float(x["high"]) for x in candles]; lows=[float(x["low"]) for x in candles]
    if any(not isfinite(x) or x <= 0 for x in closes):
        raise ValueError("Candles contain invalid prices.")
    fast=ema(closes,cfg["fast_ema"]); slow=ema(closes,cfg["slow_ema"])
    trades=[]; equity=0.0; peak=0.0; max_dd=0.0; i=cfg["slow_ema"]+1
    while i < len(candles)-1:
        prev_up=fast[i-1] > slow[i-1]; now_up=fast[i] > slow[i]
        side="BUY" if now_up and not prev_up else "SELL" if prev_up and not now_up else None
        if not side:
            i+=1; continue
        atr_values=[max(highs[j]-lows[j],abs(highs[j]-closes[j-1]),abs(lows[j]-closes[j-1])) for j in range(max(1,i-14),i+1)]
        risk=max(mean(atr_values)*1.5, closes[i]*0.0001)
        entry=closes[i]; sign=1 if side=="BUY" else -1
        stop=entry-sign*risk; target=entry+sign*risk*cfg["risk_reward"]
        exit_price=closes[-1]; reason="DATA_END"; exit_index=len(candles)-1
        for j in range(i+1,len(candles)):
            hit_stop=(lows[j] <= stop if side=="BUY" else highs[j] >= stop)
            hit_target=(highs[j] >= target if side=="BUY" else lows[j] <= target)
            if hit_stop:
                exit_price=stop; reason="STOP_LOSS"; exit_index=j; break
            if hit_target:
                exit_price=target; reason="TAKE_PROFIT"; exit_index=j; break
        pnl=(exit_price-entry)*sign
        equity+=pnl; peak=max(peak,equity); max_dd=max(max_dd,peak-equity)
        trades.append({"side":side,"entry_time":candles[i].get("time"),"exit_time":candles[exit_index].get("time"),
                       "entry":round(entry,8),"stop_loss":round(stop,8),"take_profit":round(target,8),
                       "exit":round(exit_price,8),"pnl":round(pnl,8),"r_multiple":round(pnl/risk,3),
                       "exit_reason":reason})
        i=exit_index+1
    wins=[x for x in trades if x["pnl"]>0]; losses=[x for x in trades if x["pnl"]<0]
    gross_profit=sum(x["pnl"] for x in wins); gross_loss=abs(sum(x["pnl"] for x in losses))
    return {"strategy":cfg,"candle_count":len(candles),"trade_count":len(trades),"wins":len(wins),
            "losses":len(losses),"win_rate":round(len(wins)/len(trades)*100,2) if trades else None,
            "net_pnl":round(sum(x["pnl"] for x in trades),8),
            "profit_factor":round(gross_profit/gross_loss,3) if gross_loss else (None if not gross_profit else "infinite"),
            "max_drawdown":round(max_dd,8),"trades":trades[-100:],
            "limitations":"Educational simulation only. No spread, fees, slippage, funding, broker contract size or execution latency. Same-bar stop is prioritized over target. Historical results do not predict future results."}

def optimize(candles: list[dict]) -> dict:
    results=[]
    for fast in (5,9,12):
        for slow in (20,26,34):
            if fast >= slow: continue
            for rr in (1.5,2.0,3.0):
                result=run_backtest(candles,{"fast_ema":fast,"slow_ema":slow,"risk_reward":rr})
                results.append({k:v for k,v in result.items() if k!="trades"})
    results.sort(key=lambda x:(x["net_pnl"],x["profit_factor"] if isinstance(x["profit_factor"],float) else 0),reverse=True)
    return {"tested":len(results),"ranked":results[:10],
            "warning":"In-sample parameter search can overfit. Validate the selected settings on unseen data and forward paper observations."}

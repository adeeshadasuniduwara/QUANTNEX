"""Phase 11 advanced performance analytics for the local paper ledger."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite

def _value(raw, default=0.0):
    try:
        value=float(raw if raw is not None else default)
        return value if isfinite(value) else default
    except (TypeError,ValueError):
        return default

def _time(value):
    if value is None: return None
    if value.tzinfo is None: return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def advanced_performance(trades, period_days=0, now=None):
    """Return transparent paper-only metrics; period_days=0 includes all history."""
    if not isinstance(period_days,int) or period_days not in {0,7,30,90,365}:
        raise ValueError("period_days must be one of 0, 7, 30, 90 or 365.")
    now=_time(now or datetime.now(timezone.utc))
    closed=[]
    for trade in trades:
        if getattr(trade,"status",None)!="CLOSED" or getattr(trade,"realized_pnl",None) is None:
            continue
        stamp=_time(getattr(trade,"closed_at",None) or getattr(trade,"created_at",None))
        if stamp is None: continue
        if period_days and (now-stamp).total_seconds()>period_days*86400: continue
        pnl=_value(trade.realized_pnl)
        risk=abs(_value(trade.entry_price)*0 + (_value(trade.entry_price)-_value(trade.stop_loss))*_value(trade.quantity))
        r_multiple=pnl/risk if risk>0 else None
        opened=_time(getattr(trade,"created_at",None))
        duration=max(0.0,(stamp-opened).total_seconds()/60) if opened else None
        closed.append({"id":getattr(trade,"id",None),"symbol":str(getattr(trade,"symbol","UNKNOWN")),
                       "side":str(getattr(trade,"side","")),"pnl":pnl,"risk":risk,
                       "r_multiple":r_multiple,"closed_at":stamp,"duration_minutes":duration})
    closed.sort(key=lambda x:(x["closed_at"],x["id"] or 0))
    wins=[x for x in closed if x["pnl"]>0]
    losses=[x for x in closed if x["pnl"]<0]
    breakeven=[x for x in closed if x["pnl"]==0]
    gross_profit=sum(x["pnl"] for x in wins)
    gross_loss=abs(sum(x["pnl"] for x in losses))
    net=gross_profit-gross_loss
    pf=(gross_profit/gross_loss if gross_loss else (None if not gross_profit else "infinite"))
    avg_win=gross_profit/len(wins) if wins else None
    avg_loss=gross_loss/len(losses) if losses else None
    expectancy=net/len(closed) if closed else None
    valid_r=[x["r_multiple"] for x in closed if x["r_multiple"] is not None]
    curve=[];cumulative=0.0;peak=0.0;max_dd=0.0;max_dd_pct=None
    streak_w=streak_l=max_w=max_l=0
    for item in closed:
        cumulative+=item["pnl"];peak=max(peak,cumulative)
        dd=peak-cumulative;max_dd=max(max_dd,dd)
        streak_w=streak_w+1 if item["pnl"]>0 else 0
        streak_l=streak_l+1 if item["pnl"]<0 else 0
        max_w=max(max_w,streak_w);max_l=max(max_l,streak_l)
        curve.append({"trade_id":item["id"],"time":item["closed_at"].isoformat(),
                      "pnl":round(item["pnl"],8),"cumulative_pnl":round(cumulative,8),
                      "peak_pnl":round(peak,8),"drawdown_amount":round(dd,8)})
    if peak>0: max_dd_pct=round(max_dd/peak*100,4)
    by_symbol=defaultdict(lambda:{"trades":0,"wins":0,"losses":0,"net_pnl":0.0,"gross_profit":0.0,"gross_loss":0.0})
    daily=defaultdict(float);durations=[]
    for x in closed:
        row=by_symbol[x["symbol"]];row["trades"]+=1;row["net_pnl"]+=x["pnl"]
        if x["pnl"]>0: row["wins"]+=1;row["gross_profit"]+=x["pnl"]
        elif x["pnl"]<0: row["losses"]+=1;row["gross_loss"]+=abs(x["pnl"])
        daily[x["closed_at"].date().isoformat()]+=x["pnl"]
        if x["duration_minutes"] is not None: durations.append(x["duration_minutes"])
    symbols={}
    for symbol,row in sorted(by_symbol.items()):
        count=row["trades"]
        symbols[symbol]={**{k:round(v,6) if isinstance(v,float) else v for k,v in row.items()},
            "win_rate":round(row["wins"]/count*100,2) if count else None,
            "profit_factor":round(row["gross_profit"]/row["gross_loss"],3) if row["gross_loss"] else
                (None if not row["gross_profit"] else "infinite")}
    best=max(closed,key=lambda x:x["pnl"]) if closed else None
    worst=min(closed,key=lambda x:x["pnl"]) if closed else None
    return {
        "mode":"PAPER ONLY","period_days":period_days,"total_trades":len(closed),
        "wins":len(wins),"losses":len(losses),"breakeven":len(breakeven),
        "win_rate":round(len(wins)/len(closed)*100,2) if closed else None,
        "gross_profit":round(gross_profit,6),"gross_loss":round(gross_loss,6),
        "net_pnl":round(net,6),"profit_factor":round(pf,3) if isinstance(pf,float) else pf,
        "expectancy_per_trade":round(expectancy,6) if expectancy is not None else None,
        "average_win":round(avg_win,6) if avg_win is not None else None,
        "average_loss":round(avg_loss,6) if avg_loss is not None else None,
        "average_r_multiple":round(sum(valid_r)/len(valid_r),4) if valid_r else None,
        "r_multiple_sample":len(valid_r),
        "largest_win":round(best["pnl"],6) if best else None,
        "largest_loss":round(worst["pnl"],6) if worst else None,
        "max_drawdown_amount":round(max_dd,6),"max_drawdown_percent_of_peak_pnl":max_dd_pct,
        "max_consecutive_wins":max_w,"max_consecutive_losses":max_l,
        "average_holding_minutes":round(sum(durations)/len(durations),2) if durations else None,
        "equity_curve":curve,
        "daily_pnl":[{"date":k,"pnl":round(v,6)} for k,v in sorted(daily.items())],
        "by_symbol":symbols,
        "best_trade":({"id":best["id"],"symbol":best["symbol"],"pnl":round(best["pnl"],6)} if best else None),
        "worst_trade":({"id":worst["id"],"symbol":worst["symbol"],"pnl":round(worst["pnl"],6)} if worst else None),
        "methodology":{
            "source":"Closed QUANTNEX paper trades only; live/broker trades and browser-only journal rows are excluded.",
            "r_multiple":"Estimated realized P&L / (absolute entry-to-stop distance × quantity). It is approximate and may not match broker R because contract multipliers, quote-currency conversion, fees and slippage are not modeled.",
            "drawdown":"Peak-to-trough decline of cumulative realized P&L within the selected period, starting at zero. Percentage is relative to the highest positive cumulative P&L, not account equity.",
            "holding_time":"Closed timestamp minus opened timestamp; timestamps are normalized to UTC.",
            "limitations":"Metrics are descriptive, not a forecast, guarantee, or evidence of statistical significance. Strategy attribution is unavailable because paper trades do not store a strategy identifier."
        }
    }

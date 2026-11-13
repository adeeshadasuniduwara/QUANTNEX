"""Phase 09 risk and portfolio intelligence. Pure calculations; never routes broker orders."""
from __future__ import annotations
from math import isfinite
from statistics import mean

def _num(value, name, minimum=None, maximum=None):
    try: x=float(value)
    except (TypeError,ValueError): raise ValueError(f"{name} must be numeric.")
    if not isfinite(x): raise ValueError(f"{name} must be finite.")
    if minimum is not None and x<minimum: raise ValueError(f"{name} must be at least {minimum}.")
    if maximum is not None and x>maximum: raise ValueError(f"{name} must be at most {maximum}.")
    return x

def calculate_position_size(equity, risk_percent, entry, stop_loss, contract_multiplier):
    equity=_num(equity,"equity",0.01); risk_percent=_num(risk_percent,"risk_percent",0.01,5)
    entry=_num(entry,"entry",0.00000001); stop_loss=_num(stop_loss,"stop_loss",0.00000001)
    multiplier=_num(contract_multiplier,"contract_multiplier",0.00000001)
    distance=abs(entry-stop_loss)
    if distance<=0: raise ValueError("Entry and stop loss must differ.")
    risk_amount=equity*risk_percent/100
    units=risk_amount/(distance*multiplier)
    return {"risk_amount":round(risk_amount,8),"price_distance":round(distance,10),
            "estimated_units":round(units,8),"contract_multiplier":multiplier,
            "formula":"risk_amount / (abs(entry - stop_loss) * contract_multiplier)",
            "note":"Units are estimates only. Confirm each broker's contract size, quote currency, pip value, fees and margin before use; this is not a universal forex lot calculator."}

def portfolio_snapshot(trades):
    open_trades=[t for t in trades if t.status=="OPEN"]
    rows=[]; gross=0.0; risk=0.0; by_symbol={}
    for t in open_trades:
        notional=abs(float(t.quantity)*float(t.entry_price))
        planned=abs(float(t.entry_price)-float(t.stop_loss))*float(t.quantity)
        gross+=notional; risk+=planned
        by_symbol[t.symbol]=by_symbol.get(t.symbol,0.0)+notional
        rows.append({"id":t.id,"symbol":t.symbol,"side":t.side,"quantity":t.quantity,
                     "entry_price":t.entry_price,"notional_estimate":round(notional,6),
                     "planned_stop_risk_estimate":round(planned,6)})
    concentration={k:round(v/gross*100,2) if gross else 0 for k,v in by_symbol.items()}
    return {"open_positions":len(rows),"gross_notional_estimate":round(gross,6),
            "planned_stop_risk_estimate":round(risk,6),"by_symbol_notional":{k:round(v,6) for k,v in by_symbol.items()},
            "symbol_concentration_percent":concentration,"positions":rows,
            "limitations":"Notional assumes price × quantity in a common quote currency. Cross-currency conversion, contract multipliers and true correlations are not inferred; correlation is not measured from live data."}

def drawdown_guard(trades, equity, daily_loss_limit_percent=3.0, max_drawdown_percent=8.0, max_consecutive_losses=4):
    equity=_num(equity,"equity",0.01)
    daily=_num(daily_loss_limit_percent,"daily_loss_limit_percent",0.1,20)
    maxdd=_num(max_drawdown_percent,"max_drawdown_percent",0.1,50)
    if not isinstance(max_consecutive_losses,int) or not 1<=max_consecutive_losses<=20:
        raise ValueError("max_consecutive_losses must be an integer from 1 to 20.")
    closed=sorted([t for t in trades if t.status=="CLOSED" and t.realized_pnl is not None],
                  key=lambda t:(t.closed_at or t.created_at,t.id))
    from datetime import datetime, timezone
    today=datetime.now(timezone.utc).date()
    todays=[t for t in closed if (t.closed_at or t.created_at).date()==today]
    daily_loss=sum(min(0.0,float(t.realized_pnl)) for t in todays)
    # The UI supplies current account equity (also used for position sizing).
    # Reconstruct the historical starting balance by reversing all recorded
    # closed-trade P&L before walking the curve forward. Starting the curve at
    # current equity and adding historical P&L double-counted past gains/losses.
    starting_equity = equity - sum(float(t.realized_pnl) for t in closed)
    if not isfinite(starting_equity) or starting_equity <= 0:
        raise ValueError("Recorded trade history cannot be reconciled with the supplied current equity.")
    peak=starting_equity; curve=starting_equity; worst=0.0; streak=0; max_streak=0
    for t in closed:
        pnl=float(t.realized_pnl); curve+=pnl; peak=max(peak,curve)
        if peak>0: worst=max(worst,(peak-curve)/peak*100)
        if pnl<0: streak+=1; max_streak=max(max_streak,streak)
        elif pnl>0: streak=0
    triggers=[]
    if abs(daily_loss)>=equity*daily/100: triggers.append("DAILY_LOSS_LIMIT")
    if worst>=maxdd: triggers.append("MAX_DRAWDOWN")
    if streak>=max_consecutive_losses: triggers.append("LOSS_STREAK")
    return {"trading_allowed":not triggers,"cooldown_required":bool(triggers),"triggers":triggers,
            "daily_realized_loss":round(daily_loss,6),"daily_loss_limit_amount":round(equity*daily/100,6),
            "historical_max_drawdown_percent":round(worst,4),"max_drawdown_limit_percent":maxdd,
            "current_loss_streak":streak,"max_consecutive_losses":max_consecutive_losses,
            "note":"UTC calendar-day realized losses and closed-paper-trade equity curve only. Equity is current user-supplied account equity; starting equity is reconstructed by reversing recorded closed-trade P&L. Open P&L and deposits/withdrawals are excluded."}

def stress_test(trades, shocks=None):
    shocks=shocks or {"risk_off":-0.05,"risk_on":0.05,"volatility_spike":-0.10}
    scenarios=[]
    for name,raw in shocks.items():
        shock=_num(raw,f"shock {name}",-0.5,0.5)
        pnl=0.0
        for t in trades:
            if t.status!="OPEN": continue
            direction=1 if t.side=="BUY" else -1
            pnl+=float(t.entry_price)*float(t.quantity)*shock*direction
        scenarios.append({"scenario":str(name)[:40],"assumed_price_shock_percent":round(shock*100,2),
                          "estimated_pnl_impact":round(pnl,6)})
    return {"scenarios":scenarios,"note":"Hypothetical parallel percentage price shocks applied independently to each position. No historical covariance, volatility calibration, FX conversion, liquidation or gap model."}

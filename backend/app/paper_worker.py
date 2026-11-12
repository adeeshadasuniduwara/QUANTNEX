"""Local-only paper trade SL/TP monitor. Never sends broker orders."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from .database import SessionLocal
from .models import AuditEvent, PaperTrade
from .events import event_hub
from .phase07_engine import get_quote

logger=logging.getLogger("quantnex.paper")

def exit_reason(trade, price: float) -> str | None:
    if trade.side=="BUY":
        if price<=trade.stop_loss: return "STOP_LOSS"
        if price>=trade.take_profit: return "TAKE_PROFIT"
    else:
        if price>=trade.stop_loss: return "STOP_LOSS"
        if price<=trade.take_profit: return "TAKE_PROFIT"
    return None

async def paper_trade_monitor() -> None:
    while True:
        try:
            with SessionLocal() as db:
                snapshot=[{"id":x.id,"symbol":x.symbol,"side":x.side,"quantity":x.quantity,
                           "entry_price":x.entry_price,"stop_loss":x.stop_loss,"take_profit":x.take_profit}
                          for x in db.scalars(select(PaperTrade).where(PaperTrade.status=="OPEN"))]
            if snapshot:
                symbols=sorted({x["symbol"] for x in snapshot})
                quotes=await asyncio.gather(*(get_quote(symbol) for symbol in symbols),return_exceptions=True)
                prices={symbol:float(result["price"]) for symbol,result in zip(symbols,quotes) if isinstance(result,dict)}
                closed_events = []
                with SessionLocal() as db:
                    for row in snapshot:
                        if row["symbol"] not in prices: continue
                        price=prices[row["symbol"]]
                        reason=exit_reason(row,price)
                        if not reason: continue
                        trade=db.scalar(select(PaperTrade).where(PaperTrade.id==row["id"],PaperTrade.status=="OPEN"))
                        if trade is None: continue
                        pnl=(price-trade.entry_price)*trade.quantity*(1 if trade.side=="BUY" else -1)
                        trade.exit_price=price
                        trade.realized_pnl=round(pnl,8)
                        trade.status="CLOSED"
                        trade.closed_at=datetime.now(timezone.utc)
                        db.add(AuditEvent(event_type="paper_trade.auto_closed",severity="warning",
                            details='{"trade_id":%d,"symbol":"%s","reason":"%s","exit_price":%.10f,"realized_pnl":%.8f}' %
                                    (trade.id,trade.symbol,reason,price,trade.realized_pnl)))
                        closed_events.append({"trade_id":trade.id,"symbol":trade.symbol,"reason":reason,
                                              "exit_price":price,"realized_pnl":trade.realized_pnl})
                    db.commit()
                # Publish only after the close transaction commits so all workspace
                # views refresh from a durable, committed paper-ledger state.
                for payload in closed_events:
                    event_hub.publish("paper_trade.changed","paper_trade","auto_closed",payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Paper monitor cycle failed: %s",type(exc).__name__)
        await asyncio.sleep(10)

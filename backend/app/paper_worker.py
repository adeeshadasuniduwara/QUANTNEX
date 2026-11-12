"""Local-only paper trade SL/TP monitor. Never sends broker orders."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from .database import SessionLocal
from .models import AuditEvent, PaperTrade, User
from .phase07_engine import get_quote

logger=logging.getLogger("quantnex.paper")

def exit_reason(trade: PaperTrade, price: float) -> str | None:
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
                owner=db.scalar(select(User).order_by(User.id))
                open_trades=list(db.scalars(select(PaperTrade).where(PaperTrade.status=="OPEN")))
                if owner and open_trades:
                    symbols=sorted({trade.symbol for trade in open_trades})
                    quotes=await asyncio.gather(*(get_quote(symbol) for symbol in symbols),return_exceptions=True)
                    prices={symbol:result["price"] for symbol,result in zip(symbols,quotes) if isinstance(result,dict)}
                    for trade in open_trades:
                        if trade.symbol not in prices: continue
                        price=float(prices[trade.symbol])
                        reason=exit_reason(trade,price)
                        if not reason: continue
                        pnl=(price-trade.entry_price)*trade.quantity*(1 if trade.side=="BUY" else -1)
                        trade.exit_price=price
                        trade.realized_pnl=round(pnl,8)
                        trade.status="CLOSED"
                        trade.closed_at=datetime.now(timezone.utc)
                        db.add(AuditEvent(event_type="paper_trade.auto_closed",severity="warning",
                            details='{"trade_id":%d,"symbol":"%s","reason":"%s","exit_price":%.10f,"realized_pnl":%.8f}' %
                                    (trade.id,trade.symbol,reason,price,trade.realized_pnl)))
                    db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Paper monitor cycle failed: %s",type(exc).__name__)
        await asyncio.sleep(10)

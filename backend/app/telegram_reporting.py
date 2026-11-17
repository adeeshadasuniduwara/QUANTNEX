"""A4 portrait daily Telegram PDF for the QUANTNEX paper-trade ledger."""
from __future__ import annotations

from datetime import date, datetime, timezone
from io import BytesIO
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

COLOMBO = ZoneInfo("Asia/Colombo")


def _local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(COLOMBO)


def build_daily_paper_pdf(db, user_id: int, report_day: date | None = None) -> tuple[bytes, dict]:
    """Build a report from persisted PaperTrade rows only; never reads manual journal."""
    from sqlalchemy import select
    from .models import PaperTrade, PaperTradeEvent

    day = report_day or datetime.now(COLOMBO).date()
    rows = list(db.scalars(select(PaperTrade).where(PaperTrade.user_id == user_id).order_by(PaperTrade.created_at)))
    opened_today, closed_today, open_at_cutoff = [], [], []
    cutoff = datetime.combine(day, datetime.max.time(), tzinfo=COLOMBO)
    for trade in rows:
        created = _local(trade.created_at)
        closed = _local(trade.closed_at)
        if created and created.date() == day:
            opened_today.append(trade)
        if closed and closed.date() == day:
            closed_today.append(trade)
        if created and created <= cutoff and (closed is None or closed > cutoff):
            open_at_cutoff.append(trade)

    event_rows = list(db.scalars(select(PaperTradeEvent).where(
        PaperTradeEvent.user_id == user_id).order_by(PaperTradeEvent.created_at)))
    events_today = [event for event in event_rows
                    if _local(event.created_at) and _local(event.created_at).date() == day]
    pnl_values = [float(t.realized_pnl or 0) for t in closed_today]
    wins = sum(1 for value in pnl_values if value > 0)
    losses = sum(1 for value in pnl_values if value < 0)
    breakeven = sum(1 for value in pnl_values if value == 0)
    gross_profit = sum(value for value in pnl_values if value > 0)
    total_loss = abs(sum(value for value in pnl_values if value < 0))
    net = sum(pnl_values)
    win_rate = (wins / len(pnl_values) * 100) if pnl_values else 0.0
    stats = {
        "date": day.isoformat(), "opened": len(opened_today), "closed": len(closed_today),
        "open_at_cutoff": len(open_at_cutoff), "wins": wins, "losses": losses,
        "breakeven": breakeven, "gross_profit": round(gross_profit, 2),
        "total_loss": round(total_loss, 2), "net": round(net, 2),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(gross_profit / total_loss, 2) if total_loss > 0 else ("infinite" if gross_profit > 0 else None),
        "event_count": len(events_today),
        "automatic_entries": sum(1 for event in events_today if event.event_type == "AUTO_OPENED"),
    }

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=14*mm, leftMargin=14*mm,
                            topMargin=23*mm, bottomMargin=14*mm, title=f"QUANTNEX Paper Report {day}")
    def decorate(canvas, _doc):
        from .goal_certificates import draw_quantnex_mark
        draw_quantnex_mark(canvas,14*mm,A4[1]-18*mm,9*mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("QXTitle", parent=styles["Title"], fontName="Helvetica-Bold",
                           fontSize=21, leading=25, alignment=TA_CENTER, textColor=colors.black)
    subtitle = ParagraphStyle("QXSub", parent=styles["Normal"], fontSize=9,
                              alignment=TA_CENTER, textColor=colors.HexColor("#555555"))
    heading = ParagraphStyle("QXHead", parent=styles["Heading2"], fontSize=11, leading=14,
                             textColor=colors.black, spaceBefore=7, spaceAfter=5)
    story = [Paragraph("QUANTNEX", title),
             Paragraph("DAILY PAPER TRADING REPORT · LOCAL WORKSPACE", subtitle),
             Paragraph(day.strftime("%d %B %Y") + " · Asia/Colombo", subtitle), Spacer(1, 7*mm)]
    summary = [
        ["TRADES OPENED", "TRADES CLOSED", "OPEN AT CUTOFF", "WIN RATE"],
        [str(stats["opened"]), str(stats["closed"]), str(stats["open_at_cutoff"]), f'{stats["win_rate"]:.2f}%'],
        ["GROSS PROFIT", "TOTAL LOSSES", "RECORDED P&L", "W / L / BE"],
        [f'${stats["gross_profit"]:.2f}', f'-${stats["total_loss"]:.2f}',
         f'${stats["net"]:.2f}', f'{wins} / {losses} / {breakeven}'],
    ]
    table = Table(summary, colWidths=[44*mm]*4, rowHeights=[8*mm, 11*mm, 8*mm, 11*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#111111")),
        ("BACKGROUND",(0,2),(-1,2),colors.HexColor("#111111")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),("TEXTCOLOR",(0,2),(-1,2),colors.white),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),("GRID",(0,0),(-1,-1),0.5,colors.HexColor("#777777")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("BACKGROUND",(0,1),(-1,1),colors.HexColor("#F0F0F0")),
        ("BACKGROUND",(0,3),(-1,3),colors.HexColor("#F0F0F0")),
    ]))
    story += [table,
              Paragraph("Profit factor: "+(str(stats["profit_factor"]) if stats["profit_factor"] is not None else "—")
                        +" · Current ledger does not store fees, spread or slippage; P&L below is the recorded realized amount.",
                        ParagraphStyle("scope", parent=styles["Normal"], fontSize=7, textColor=colors.HexColor("#555555"))),
              Paragraph("Closed paper trades", heading)]
    data = [["Symbol","Side","Qty","Entry","SL","TP","Exit","Opened","Exited","Recorded P&L"]]
    for trade in closed_today:
        exit_time = _local(trade.closed_at)
        open_time = _local(trade.created_at)
        data.append([trade.symbol, trade.side, f"{trade.quantity:g}", f"{trade.entry_price:g}",
                     f"{trade.stop_loss:g}", f"{trade.take_profit:g}",
                     f"{trade.exit_price:g}" if trade.exit_price is not None else "—",
                     open_time.strftime("%H:%M:%S") if open_time else "—",
                     exit_time.strftime("%H:%M:%S") if exit_time else "—",
                     "$"+format(float(trade.realized_pnl or 0),".2f")])
    if len(data) == 1:
        data.append(["No closed paper trades today","","","","","","","","",""])
    trade_table = Table(data, repeatRows=1, colWidths=[17*mm,11*mm,10*mm,16*mm,16*mm,16*mm,16*mm,21*mm,21*mm,20*mm])
    trade_table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#111111")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),
        ("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#999999")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ALIGN",(2,1),(-1,-1),"RIGHT"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F4F4F4")]),
    ]))
    story += [trade_table, Paragraph("Paper execution event ledger", heading)]
    event_data = [["Time", "Trade", "Event", "Price", "Qty", "Recorded P&L"]]
    for event in events_today:
        event_time = _local(event.created_at)
        event_data.append([
            event_time.strftime("%H:%M:%S") if event_time else "—",
            str(event.trade_id), event.event_type, f"{event.price:g}", f"{event.quantity:g}",
            "$" + format(float(event.pnl or 0), ".2f"),
        ])
    if len(event_data) == 1:
        event_data.append(["No paper events today", "", "", "", "", ""])
    event_table = Table(event_data, repeatRows=1,
        colWidths=[24*mm, 16*mm, 42*mm, 28*mm, 25*mm, 36*mm])
    event_table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#111111")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),
        ("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#999999")),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F4F4F4")]),
    ]))
    story += [event_table, Paragraph("Open positions at report cutoff", heading)]
    open_data = [["Symbol","Side","Qty","Entry","SL","TP","Opened"]]
    for trade in open_at_cutoff:
        opened = _local(trade.created_at)
        open_data.append([trade.symbol, trade.side, f"{trade.quantity:g}", f"{trade.entry_price:g}",
                          f"{trade.stop_loss:g}", f"{trade.take_profit:g}",
                          opened.strftime("%d %b %H:%M") if opened else "—"])
    if len(open_data) == 1:
        open_data.append(["No open paper positions","","","","","",""])
    open_table = Table(open_data, repeatRows=1, colWidths=[26*mm,18*mm,18*mm,25*mm,25*mm,25*mm,38*mm])
    open_table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#111111")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
        ("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#999999")),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F4F4F4")]),
    ]))
    story += [open_table, Spacer(1,5*mm),
              Paragraph("Source: QUANTNEX local PaperTrade ledger. Simulated results only; recorded P&L may exclude fees, spread and slippage. Not broker execution or real-account profit.",
                        ParagraphStyle("foot", parent=styles["Normal"], fontSize=7, textColor=colors.HexColor("#555555")))]
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue(), stats


def build_daily_signal_pdf(db, user_id: int, report_day: date | None = None) -> tuple[bytes, dict]:
    """Create a vector-quality daily PDF from confirmed SignalTrade outcomes and pair history."""
    from collections import defaultdict
    from sqlalchemy import select
    from .models import SignalTrade, SignalTradeEvent
    from reportlab.lib.pagesizes import landscape
    from reportlab.lib import colors as c
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

    day = report_day or datetime.now(COLOMBO).date()
    rows = list(db.scalars(select(SignalTrade).where(
        SignalTrade.user_id == user_id).order_by(SignalTrade.signal_time.desc())))
    terminal = {"SL_HIT", "STOPPED", "PROTECTED_EXIT", "LOCKED_PROFIT_EXIT", "TARGETS_COMPLETE"}
    def closed_at(trade):
        return trade.stopped_at or trade.tp3_at or (trade.updated_at if trade.status in terminal else None)
    opened_today, closed_today, open_at_cutoff = [], [], []
    cutoff = datetime.combine(day, datetime.max.time(), tzinfo=COLOMBO)
    for trade in rows:
        opened = _local(trade.created_at or trade.signal_time)
        closed = _local(closed_at(trade))
        if opened and opened.date() == day:
            opened_today.append(trade)
        if trade.status in terminal and closed and closed.date() == day:
            closed_today.append(trade)
        if opened and opened <= cutoff and (trade.status not in terminal) and trade.status != "EXPIRED":
            open_at_cutoff.append(trade)

    def outcome_value(trade):
        return float(trade.realized_r or 0)
    wins = sum(outcome_value(t) > 0 for t in closed_today)
    losses = sum(outcome_value(t) < 0 for t in closed_today)
    breakeven = sum(outcome_value(t) == 0 for t in closed_today)
    net_r = sum(outcome_value(t) for t in closed_today)
    gross_win_r = sum(outcome_value(t) for t in closed_today if outcome_value(t) > 0)
    gross_loss_r = abs(sum(outcome_value(t) for t in closed_today if outcome_value(t) < 0))
    pair_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "be": 0, "r": 0.0})
    for trade in rows:
        if trade.status not in terminal:
            continue
        stats = pair_stats[trade.symbol]
        stats["trades"] += 1
        value = outcome_value(trade)
        stats["wins"] += value > 0
        stats["losses"] += value < 0
        stats["be"] += value == 0
        stats["r"] += value
    stats = {
        "date": day.isoformat(), "opened": len(opened_today), "closed": len(closed_today),
        "open_at_cutoff": len(open_at_cutoff), "wins": wins, "losses": losses,
        "breakeven": breakeven, "win_rate": round(wins / len(closed_today) * 100, 2) if closed_today else 0.0,
        "net_r": round(net_r, 3), "gross_win_r": round(gross_win_r, 3),
        "gross_loss_r": round(gross_loss_r, 3),
        "profit_factor": round(gross_win_r / gross_loss_r, 2) if gross_loss_r else ("infinite" if gross_win_r else None),
        "pairs": {symbol: {**value, "win_rate": round(value["wins"] / value["trades"] * 100, 2),
                           "net_r": round(value["r"], 3)}
                  for symbol, value in sorted(pair_stats.items())},
    }

    page = landscape(A4)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=page, rightMargin=12*mm, leftMargin=12*mm,
                            topMargin=20*mm, bottomMargin=13*mm,
                            title=f"QUANTNEX Signal Performance {day}")
    styles = getSampleStyleSheet()
    title = ParagraphStyle("QXSigTitle", parent=styles["Title"], fontName="Helvetica-Bold",
                           fontSize=24, leading=28, alignment=TA_CENTER, textColor=c.HexColor("#111827"))
    sub = ParagraphStyle("QXSigSub", parent=styles["Normal"], fontSize=9,
                         alignment=TA_CENTER, textColor=c.HexColor("#64748b"))
    head = ParagraphStyle("QXSigHead", parent=styles["Heading2"], fontSize=12, leading=15,
                          textColor=c.HexColor("#0f172a"), spaceBefore=9, spaceAfter=5)
    small = ParagraphStyle("QXSigSmall", parent=styles["Normal"], fontSize=7,
                           textColor=c.HexColor("#64748b"), leading=9)
    def decorate(canvas, _doc):
        canvas.saveState()
        width, height = page
        canvas.setFillColor(c.HexColor("#0b1220"))
        canvas.rect(0, height-13*mm, width, 13*mm, fill=1, stroke=0)
        canvas.setFillColor(c.HexColor("#e2e8f0"))
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(12*mm, height-8.5*mm, "QUANTNEX  /  SIGNAL PERFORMANCE")
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(width-12*mm, height-8.5*mm, "CONFIRMED SIGNAL LEDGER  ·  ASIA/COLOMBO")
        canvas.setStrokeColor(c.HexColor("#cbd5e1"))
        canvas.line(12*mm, 9*mm, width-12*mm, 9*mm)
        canvas.setFillColor(c.HexColor("#64748b"))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(12*mm, 5.5*mm, "Simulated signal outcomes · Not broker execution or guaranteed future performance")
        canvas.drawRightString(width-12*mm, 5.5*mm, f"Page {_doc.page}")
        canvas.restoreState()

    story = [Spacer(1, 2*mm), Paragraph("DAILY SIGNAL REPORT", title),
             Paragraph(day.strftime("%A · %d %B %Y") + "  |  21:00 scheduled snapshot  |  All figures in R-multiples",
                       sub), Spacer(1, 7*mm)]
    summary = [
        ["CLOSED SIGNALS", "WIN RATE", "WINS / LOSSES / BE", "NET RESULT", "OPEN AT CUTOFF"],
        [str(stats["closed"]), f'{stats["win_rate"]:.2f}%', f'{wins} / {losses} / {breakeven}',
         f'{net_r:+.2f}R', str(stats["open_at_cutoff"])],
        ["GROSS WIN R", "GROSS LOSS R", "PROFIT FACTOR", "NEW SIGNALS", "MARKETS TRACKED"],
        [f'{gross_win_r:.2f}R', f'{gross_loss_r:.2f}R',
         str(stats["profit_factor"] or "—"), str(stats["opened"]), str(len(pair_stats))],
    ]
    summary_table = Table(summary, colWidths=[(page[0]-24*mm)/5]*5,
                          rowHeights=[8*mm, 12*mm, 8*mm, 12*mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),c.HexColor("#172554")),
        ("BACKGROUND",(0,2),(-1,2),c.HexColor("#172554")),
        ("TEXTCOLOR",(0,0),(-1,0),c.white),("TEXTCOLOR",(0,2),(-1,2),c.white),
        ("BACKGROUND",(0,1),(-1,1),c.HexColor("#eff6ff")),
        ("BACKGROUND",(0,3),(-1,3),c.HexColor("#eff6ff")),
        ("TEXTCOLOR",(0,1),(-1,1),c.HexColor("#0f172a")),
        ("TEXTCOLOR",(0,3),(-1,3),c.HexColor("#0f172a")),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),9),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("GRID",(0,0),(-1,-1),0.4,c.HexColor("#cbd5e1")),
    ]))
    story += [summary_table, Paragraph("PAIR-BY-PAIR WIN RATE · ALL RECORDED CLOSED SIGNALS", head)]
    pair_data = [["PAIR", "CLOSED", "WINS", "LOSSES", "BREAKEVEN", "WIN RATE", "NET RESULT"]]
    for symbol, item in stats["pairs"].items():
        pair_data.append([symbol, str(item["trades"]), str(item["wins"]), str(item["losses"]),
                          str(item["be"]), f'{item["win_rate"]:.2f}%', f'{item["net_r"]:+.2f}R'])
    if len(pair_data) == 1:
        pair_data.append(["No completed signal outcomes yet", "0", "0", "0", "0", "0.00%", "0.00R"])
    pair_table = Table(pair_data, repeatRows=1,
                       colWidths=[42*mm,25*mm,25*mm,25*mm,30*mm,35*mm,40*mm])
    pair_table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),c.HexColor("#0f172a")),("TEXTCOLOR",(0,0),(-1,0),c.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
        ("GRID",(0,0),(-1,-1),0.35,c.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[c.white,c.HexColor("#f8fafc")]),
        ("ALIGN",(1,1),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    story += [pair_table, Paragraph("SIGNALS CLOSED TODAY", head)]
    detail = [["PAIR", "SIDE", "ENTRY", "ORIGINAL SL", "ACTIVE SL", "TP1 / TP2 / TP3", "OUTCOME", "RESULT"]]
    for trade in closed_today:
        status = {"STOPPED":"SL HIT", "SL_HIT":"SL HIT", "PROTECTED_EXIT":"PROTECTED EXIT",
                  "LOCKED_PROFIT_EXIT":"PROFIT LOCKED", "TARGETS_COMPLETE":"TP3 COMPLETED"}.get(trade.status, trade.status)
        detail.append([trade.symbol, trade.side, f'{trade.entry_price:g}', f'{trade.stop_loss:g}',
                       f'{trade.active_stop_loss:g}', f'{trade.tp1:g} / {trade.tp2:g} / {trade.tp3:g}',
                       status, f'{outcome_value(trade):+.2f}R'])
    if len(detail) == 1:
        detail.append(["No signals closed today", "", "", "", "", "", "", ""])
    detail_table = Table(detail, repeatRows=1,
                         colWidths=[29*mm,20*mm,27*mm,27*mm,27*mm,63*mm,43*mm,24*mm])
    detail_table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),c.HexColor("#0f172a")),("TEXTCOLOR",(0,0),(-1,0),c.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),
        ("GRID",(0,0),(-1,-1),0.35,c.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[c.white,c.HexColor("#f8fafc")]),
        ("ALIGN",(2,1),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
    ]))
    story += [detail_table, Spacer(1, 4*mm),
              Paragraph("Outcome rules: only closed signals count in win rate. TP1/TP2 partials, protected exits and profit-lock exits use the persisted realized R value. Open signals remain active and are excluded until SL/TP resolution. R results are simulated level-based estimates and exclude fees, spread and slippage unless separately modelled.", small)]
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue(), stats

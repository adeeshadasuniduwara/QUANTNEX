"""A4 portrait daily Telegram PDF for the QUANTNEX paper-trade ledger."""
from __future__ import annotations

from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.graphics import renderPDF
from svglib.svglib import svg2rlg
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
    from .models import PaperTrade

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
    }

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=14*mm, leftMargin=14*mm,
                            topMargin=23*mm, bottomMargin=14*mm, title=f"QUANTNEX Paper Report {day}")
    logo_path = Path(__file__).resolve().parents[2] / "apps" / "web" / "quantnex-mark.svg"
    try:
        logo = svg2rlg(str(logo_path))
    except Exception:
        logo = None

    def decorate(canvas, _doc):
        if logo and logo.width and logo.height:
            canvas.saveState()
            scale=(9*mm)/max(logo.width,logo.height)
            canvas.translate(14*mm, A4[1]-18*mm)
            canvas.scale(scale,scale)
            renderPDF.draw(logo,canvas,0,0)
            canvas.restoreState()
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
    story += [trade_table, Paragraph("Open positions at report cutoff", heading)]
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

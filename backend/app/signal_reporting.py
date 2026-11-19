"""QUANTNEX chart-signal performance PDF reports."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from io import BytesIO
from zoneinfo import ZoneInfo
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
COLOMBO=ZoneInfo("Asia/Colombo")
PERIODS={"daily":"Daily","weekly":"Weekly","monthly":"Monthly","yearly":"Yearly","total":"All-time"}
ACTIVE={"OPEN","PENDING"}
IGNORED={"EXPIRED","SUPERSEDED","PENDING"}
def _local(v):
    if v is None:return None
    if v.tzinfo is None:v=v.replace(tzinfo=timezone.utc)
    return v.astimezone(COLOMBO)
def _start(p,n):
    x=_local(n)
    if p=="daily":return x.replace(hour=0,minute=0,second=0,microsecond=0)
    if p=="weekly":
        x=x.replace(hour=0,minute=0,second=0,microsecond=0)
        return x-timedelta(days=x.weekday())
    if p=="monthly":return x.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    if p=="yearly":return x.replace(month=1,day=1,hour=0,minute=0,second=0,microsecond=0)
    return None
def _stats(rows):
    done=[t for t in rows if t.status not in ACTIVE and t.status not in IGNORED]
    win=sum(float(t.realized_r or 0)>1e-9 for t in done)
    loss=sum(float(t.realized_r or 0)<-1e-9 for t in done)
    return {"signals":len(rows),"resolved":len(done),"open":sum(t.status in ACTIVE for t in rows),
      "wins":win,"losses":loss,"breakeven":len(done)-win-loss,
      "win_rate":round(win/len(done)*100,2) if done else 0.0,
      "realized_r":round(sum(float(t.realized_r or 0) for t in done),3)}
def build_signal_performance_pdf(db,user_id,period="daily",symbol=None,now=None):
    from sqlalchemy import select
    from .models import SignalTrade
    period=str(period or "daily").lower()
    if period not in PERIODS:raise ValueError("Unsupported report period.")
    instant=now or datetime.now(timezone.utc); start=_start(period,instant)
    q=select(SignalTrade).where(SignalTrade.user_id==user_id)
    if start is not None:q=q.where(SignalTrade.signal_time>=start.astimezone(timezone.utc))
    if symbol:
        symbol=symbol.strip().upper();q=q.where(SignalTrade.symbol==symbol)
    rows=list(db.scalars(q.order_by(SignalTrade.signal_time.desc())))
    stats=_stats(rows); groups={}
    for t in rows:groups.setdefault(t.symbol,[]).append(t)
    by=[(k,_stats(v)) for k,v in sorted(groups.items())]
    local=_local(instant)
    date_label="All recorded history" if start is None else start.strftime("%d %b %Y %H:%M")+" to "+local.strftime("%d %b %Y %H:%M")+" · Asia/Colombo"
    buf=BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=landscape(A4),rightMargin=12*mm,leftMargin=12*mm,topMargin=14*mm,bottomMargin=12*mm)
    styles=getSampleStyleSheet()
    title=ParagraphStyle("QXT",parent=styles["Title"],fontName="Helvetica-Bold",fontSize=20,alignment=1)
    sub=ParagraphStyle("QXS",parent=styles["Normal"],fontSize=8,alignment=1,textColor=colors.grey)
    head=ParagraphStyle("QXH",parent=styles["Heading2"],fontSize=11,spaceBefore=7,spaceAfter=5)
    story=[Paragraph("QUANTNEX",title),Paragraph(PERIODS[period].upper()+" CHART SIGNAL PERFORMANCE",sub),Paragraph(date_label+(" · "+symbol if symbol else ""),sub),Spacer(1,5*mm)]
    summary=[["SIGNALS","RESOLVED","OPEN","WINS","LOSSES","BREAKEVEN","WIN RATE","REALIZED P&L"],
      [str(stats["signals"]),str(stats["resolved"]),str(stats["open"]),str(stats["wins"]),str(stats["losses"]),str(stats["breakeven"]),f'{stats["win_rate"]:.2f}%',f'{stats["realized_r"]:+.3f} R']]
    t=Table(summary,colWidths=[31*mm,31*mm,25*mm,23*mm,25*mm,30*mm,30*mm,34*mm])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.black),("TEXTCOLOR",(0,0),(-1,0),colors.white),("BACKGROUND",(0,1),(-1,1),colors.whitesmoke),("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),("ALIGN",(0,0),(-1,-1),"CENTER"),("GRID",(0,0),(-1,-1),.4,colors.grey)]))
    story += [t,Paragraph("Performance by coin",head)]
    data=[["Symbol","Signals","Resolved","Open","Wins","Losses","BE","Win rate","Realized P&L"]]
    for k,s in by:data.append([k,str(s["signals"]),str(s["resolved"]),str(s["open"]),str(s["wins"]),str(s["losses"]),str(s["breakeven"]),f'{s["win_rate"]:.2f}%',f'{s["realized_r"]:+.3f} R'])
    if len(data)==1:data.append(["No signal trades in this period","","","","","","","",""])
    t=Table(data,repeatRows=1,colWidths=[35*mm,25*mm,25*mm,22*mm,22*mm,22*mm,20*mm,30*mm,34*mm])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.black),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),("GRID",(0,0),(-1,-1),.35,colors.grey),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.whitesmoke])]))
    story += [t,Paragraph("Latest signal trades (up to 100)",head)]
    data=[["Date/time","Symbol","Side","TF","Entry","SL","TP1 / TP2 / TP3","Status","P&L"]]
    for x in rows[:100]:
        d=_local(x.signal_time)
        data.append([d.strftime("%d %b %H:%M") if d else "—",x.symbol,x.side,str(x.timeframe),f"{x.entry_price:g}",f"{x.stop_loss:g}",f"{x.tp1:g} / {x.tp2:g} / {x.tp3:g}",x.status,f'{float(x.realized_r or 0):+.3f} R'])
    if len(data)==1:data.append(["No signal trades in this period","","","","","","","",""])
    t=Table(data,repeatRows=1,colWidths=[27*mm,22*mm,16*mm,14*mm,22*mm,22*mm,52*mm,38*mm,28*mm])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.black),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),("GRID",(0,0),(-1,-1),.3,colors.grey)]))
    story += [t,Spacer(1,4*mm),Paragraph("Win rate = wins / resolved trades. Open and pending trades are excluded. Expired and superseded plans are excluded. P&L is shown in R from the signal lifecycle ledger, not USD; these are simulated chart-signal outcomes, not broker fills.",styles["Normal"])]
    doc.build(story)
    stats.update({"period":period,"symbol":symbol,"by_symbol":{k:v for k,v in by}})
    return buf.getvalue(),stats

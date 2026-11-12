"""Print-ready monochrome QUANTNEX personal achievement certificate."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def build_goal_certificate_pdf(*, display_name: str, goal_title: str,
                               created_at: datetime, achieved_at: datetime,
                               elapsed_days: int, certificate_id: str,
                               integrity_fingerprint: str, target_amount: float,
                               saved_amount: float, currency: str) -> bytes:
    buffer = BytesIO()
    page_w, page_h = A4
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=24*mm, leftMargin=24*mm,
                            topMargin=36*mm, bottomMargin=32*mm,
                            title="QUANTNEX Achievement Certificate")

    def decorate(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#111111"))
        canvas.setLineWidth(1.4)
        canvas.rect(10*mm, 10*mm, page_w-20*mm, page_h-20*mm)
        canvas.setLineWidth(0.45)
        canvas.rect(13*mm, 13*mm, page_w-26*mm, page_h-26*mm)
        draw_quantnex_mark(canvas,page_w/2-7.5*mm,page_h-33*mm,15*mm)
        canvas.setFillColor(colors.black)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawCentredString(page_w/2, 20*mm, "QUANTNEX  ·  PERSONAL DISCIPLINE SERIES")
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawCentredString(page_w/2, 16*mm, "LOCAL CERTIFICATE · NOT A FINANCIAL LICENSE OR TRADING PERFORMANCE GUARANTEE")
        canvas.restoreState()

    styles = getSampleStyleSheet()
    brand = ParagraphStyle("Brand", parent=styles["Normal"], fontName="Helvetica-Bold",
                           fontSize=12, leading=15, alignment=TA_CENTER, tracking=3)
    title = ParagraphStyle("TitleQX", parent=styles["Title"], fontName="Times-Bold",
                           fontSize=30, leading=36, alignment=TA_CENTER, textColor=colors.black,
                           spaceAfter=6*mm)
    lead = ParagraphStyle("LeadQX", parent=styles["Normal"], fontName="Helvetica",
                          fontSize=11, leading=17, alignment=TA_CENTER, textColor=colors.HexColor("#333333"))
    name = ParagraphStyle("NameQX", parent=styles["Heading1"], fontName="Times-BoldItalic",
                          fontSize=25, leading=31, alignment=TA_CENTER, textColor=colors.black,
                          spaceBefore=7*mm, spaceAfter=5*mm)
    goal = ParagraphStyle("GoalQX", parent=styles["Heading2"], fontName="Helvetica-Bold",
                          fontSize=18, leading=24, alignment=TA_CENTER, textColor=colors.black,
                          spaceBefore=4*mm, spaceAfter=4*mm)
    small = ParagraphStyle("SmallQX", parent=styles["Normal"], fontName="Helvetica",
                           fontSize=8, leading=12, alignment=TA_CENTER, textColor=colors.HexColor("#444444"))
    story = [
        Paragraph("Q U A N T N E X", brand),
        Spacer(1, 10*mm),
        Paragraph("CERTIFICATE OF ACHIEVEMENT", title),
        Paragraph("PROUDLY PRESENTED TO", lead),
        Paragraph(display_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), name),
        Paragraph("For achieving the personal goal", lead),
        Paragraph(goal_title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), goal),
        Spacer(1, 5*mm),
        Paragraph("A meaningful result built through patience, consistency and self-discipline.", lead),
        Spacer(1, 4*mm),
        Paragraph(f"GOAL VALUE  ·  {currency} {target_amount:,.2f}  ·  RECORDED SAVINGS {currency} {saved_amount:,.2f}", small),
        Spacer(1, 8*mm),
        Paragraph(f"GOAL STARTED  ·  {created_at.strftime('%d %B %Y')}", small),
        Spacer(1, 2*mm),
        Paragraph(f"ACHIEVED  ·  {achieved_at.strftime('%d %B %Y')}", small),
        Spacer(1, 2*mm),
        Paragraph(f"TIME INVESTED  ·  {elapsed_days} days", small),
        Spacer(1, 13*mm),
        Paragraph("Presented by the QUANTNEX Support Team", lead),
        Spacer(1, 3*mm),
        Paragraph("QUANTNEX", ParagraphStyle("Signature", parent=styles["Normal"],
            fontName="Times-Italic", fontSize=20, leading=24, alignment=TA_CENTER)),
        Spacer(1, 2*mm),
        Paragraph("PERSONAL GOAL MILESTONE", small),
        Spacer(1, 11*mm),
        Paragraph(f"Certificate ID: {certificate_id}", small),
        Paragraph(f"Local integrity fingerprint: {integrity_fingerprint[:24]}", small),
    ]
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def draw_quantnex_mark(canvas, x: float, y: float, size: float) -> None:
    """Draw a compact monochrome vector approximation of the repository Q mark."""
    canvas.saveState()
    scale=size/64.0
    canvas.translate(x,y)
    canvas.scale(scale,scale)
    canvas.setFillColor(colors.HexColor("#0B0B0B"))
    canvas.roundRect(0,0,64,64,16,fill=1,stroke=0)
    canvas.setStrokeColor(colors.HexColor("#F5F5F5"))
    canvas.setLineWidth(5.5)
    canvas.setLineCap(1)
    canvas.arc(10,10,54,54,45,285)
    path=canvas.beginPath()
    path.moveTo(34,34)
    path.lineTo(48,48)
    canvas.drawPath(path,stroke=1,fill=0)
    canvas.setFillColor(colors.HexColor("#F5F5F5"))
    canvas.circle(50.5,13.5,5.5,fill=1,stroke=0)
    canvas.restoreState()

"""Print-ready A4 QUANTNEX achievement certificates with a gold ornamental design."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from urllib.parse import urlsplit
import ipaddress
import socket

import httpx

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer


GOLD = colors.HexColor("#B58A28")
LIGHT_GOLD = colors.HexColor("#E8D79B")
DARK = colors.HexColor("#262116")


def build_goal_certificate_pdf(*, display_name: str, goal_title: str,
                               created_at: datetime, achieved_at: datetime,
                               elapsed_days: int, certificate_id: str,
                               integrity_fingerprint: str, target_amount: float,
                               saved_amount: float, currency: str, demo_only: bool = False,
                               achievement_text: str = "A meaningful result built through patience, consistency and self-discipline.",
                               goal_image_url: str = "", elapsed_hours: int | None = None) -> bytes:
    """Build a self-contained PDF; demo certificates are prominently non-valid."""
    buffer = BytesIO()
    page_w, page_h = A4
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=25*mm, leftMargin=25*mm,
        topMargin=38*mm, bottomMargin=28*mm,
        title=("QUANTNEX Demo Certificate — NOT VALID" if demo_only else "QUANTNEX Achievement Certificate"),
        author="QUANTNEX",
    )

    def star(canvas, cx, cy, outer, inner):
        path = canvas.beginPath()
        for i in range(10):
            import math
            angle = math.pi / 2 + i * math.pi / 5
            radius = outer if i % 2 == 0 else inner
            x, y = cx + math.cos(angle)*radius, cy + math.sin(angle)*radius
            (path.moveTo if i == 0 else path.lineTo)(x, y)
        path.close()
        canvas.drawPath(path, fill=1, stroke=0)

    def decorate(canvas, _doc):
        canvas.saveState()
        # Warm ivory sheet and layered metallic-gold frame.
        canvas.setFillColor(colors.HexColor("#FFFEFA"))
        canvas.rect(0, 0, page_w, page_h, fill=1, stroke=0)
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(2.2)
        canvas.rect(9*mm, 9*mm, page_w-18*mm, page_h-18*mm, fill=0, stroke=1)
        canvas.setStrokeColor(LIGHT_GOLD)
        canvas.setLineWidth(0.8)
        canvas.rect(13*mm, 13*mm, page_w-26*mm, page_h-26*mm, fill=0, stroke=1)
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(0.6)
        canvas.line(28*mm, page_h-39*mm, page_w-28*mm, page_h-39*mm)
        canvas.line(28*mm, 34*mm, page_w-28*mm, 34*mm)
        # Decorative corner stars and central Q emblem.
        canvas.setFillColor(GOLD)
        for x in (19*mm, page_w-19*mm):
            for y in (19*mm, page_h-19*mm):
                star(canvas, x, y, 3.0*mm, 1.2*mm)
        draw_quantnex_mark(canvas, page_w/2-8*mm, page_h-34*mm, 16*mm, gold=True)
        if demo_only:
            canvas.saveState()
            canvas.translate(page_w/2, page_h/2)
            canvas.rotate(32)
            canvas.setFillColor(colors.Color(0.72, 0.57, 0.25, alpha=0.20))
            canvas.setFont("Helvetica-Bold", 31)
            canvas.drawCentredString(0, 0, "DEMO ONLY — NOT VALID")
            canvas.setFont("Helvetica-Bold", 12)
            canvas.drawCentredString(0, -13*mm, "FOR DISPLAY PURPOSES ONLY")
            canvas.restoreState()
        canvas.setFillColor(DARK)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawCentredString(page_w/2, 24*mm, "QUANTNEX  ·  PERSONAL DISCIPLINE SERIES")
        canvas.setFillColor(GOLD)
        canvas.setFont("Helvetica", 6.5)
        footer = ("DEMO SAMPLE · NOT VALID · FOR DISPLAY PURPOSES ONLY" if demo_only
                  else "LOCAL CERTIFICATE · NOT A FINANCIAL LICENSE OR TRADING PERFORMANCE GUARANTEE")
        canvas.drawCentredString(page_w/2, 20*mm, footer)
        canvas.restoreState()

    styles = getSampleStyleSheet()
    brand = ParagraphStyle("BrandGold", parent=styles["Normal"], fontName="Helvetica-Bold",
                           fontSize=9, leading=11, alignment=TA_CENTER, textColor=GOLD, tracking=3)
    title = ParagraphStyle("TitleGold", parent=styles["Title"], fontName="Times-Bold",
                           fontSize=24, leading=28, alignment=TA_CENTER, textColor=DARK,
                           spaceAfter=5*mm)
    lead = ParagraphStyle("LeadGold", parent=styles["Normal"], fontName="Helvetica",
                         fontSize=9, leading=12, alignment=TA_CENTER, textColor=DARK)
    name = ParagraphStyle("NameGold", parent=styles["Heading1"], fontName="Times-BoldItalic",
                          fontSize=22, leading=26, alignment=TA_CENTER, textColor=GOLD,
                          spaceBefore=7*mm, spaceAfter=5*mm)
    goal = ParagraphStyle("GoalGold", parent=styles["Heading2"], fontName="Helvetica-Bold",
                          fontSize=15, leading=18, alignment=TA_CENTER, textColor=DARK,
                          spaceBefore=4*mm, spaceAfter=4*mm)
    small = ParagraphStyle("SmallGold", parent=styles["Normal"], fontName="Helvetica",
                           fontSize=7, leading=9, alignment=TA_CENTER, textColor=colors.HexColor("#5B513C"))
    story = [
        Paragraph("Q U A N T N E X", brand),
        Spacer(1, 4*mm),
        Paragraph("DEMO CERTIFICATE PREVIEW" if demo_only else "CERTIFICATE OF ACHIEVEMENT", title),
        Paragraph("SAMPLE ONLY · NOT VALID · PROUDLY PRESENTED TO" if demo_only else "PROUDLY PRESENTED TO", lead),
        Paragraph(_escape(display_name), name),
        Paragraph("PERSONAL GOAL ACHIEVED", lead),
        Paragraph(_escape(goal_title), goal),
        Spacer(1, 2*mm),
        Paragraph(_escape(achievement_text), lead),
        Spacer(1, 3*mm),
        Paragraph(f"GOAL VALUE  ·  {currency} {target_amount:,.2f}  ·  RECORDED SAVINGS {currency} {saved_amount:,.2f}", small),
        Spacer(1, 4*mm),
        Paragraph(f"GOAL STARTED  ·  {created_at.strftime('%d %B %Y')}", small),
        Spacer(1, 2*mm),
        Paragraph(f"ACHIEVED  ·  {achieved_at.strftime('%d %B %Y')}", small),
        Spacer(1, 2*mm),
        Paragraph(f"TIME INVESTED  ·  {elapsed_days} days · {elapsed_hours if elapsed_hours is not None else elapsed_days * 24} hours", small),
        Spacer(1, 6*mm),
        Paragraph("Presented by the QUANTNEX Support Team", lead),
        Spacer(1, 3*mm),
        Paragraph("QUANTNEX", ParagraphStyle("SignatureGold", parent=styles["Normal"],
            fontName="Times-Italic", fontSize=19, leading=23, alignment=TA_CENTER, textColor=GOLD)),
        Spacer(1, 2*mm),
        Paragraph("PERSONAL GOAL MILESTONE", small),
        Spacer(1, 8*mm),
        Paragraph(f"Certificate ID: {certificate_id}", small),
        Paragraph(f"Local integrity fingerprint: {integrity_fingerprint[:24]}", small),
    ]
    if goal_image_url:
        image_data = _fetch_public_goal_image(goal_image_url)
        if image_data:
            try:
                photo = Image(BytesIO(image_data), width=70*mm, height=36*mm, kind="proportional")
                photo.hAlign = "CENTER"
                story.insert(8, photo)
                story.insert(9, Spacer(1, 3*mm))
            except Exception:
                pass
    if demo_only:
        story.insert(0, Paragraph("DEMO ONLY — NOT VALID · FOR DISPLAY PURPOSES ONLY", small))
        story.insert(1, Spacer(1, 3*mm))
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def _escape(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def draw_quantnex_mark(canvas, x: float, y: float, size: float, gold: bool = False) -> None:
    """Draw the QUANTNEX Q emblem in a black or gold medallion."""
    canvas.saveState()
    scale=size/64.0
    canvas.translate(x,y)
    canvas.scale(scale,scale)
    canvas.setFillColor(GOLD if gold else colors.HexColor("#0B0B0B"))
    canvas.roundRect(0,0,64,64,16,fill=1,stroke=0)
    canvas.setStrokeColor(colors.HexColor("#FFFEFA"))
    canvas.setLineWidth(5.5)
    canvas.setLineCap(1)
    canvas.arc(10,10,54,54,45,285)
    path=canvas.beginPath()
    path.moveTo(34,34)
    path.lineTo(48,48)
    canvas.drawPath(path,stroke=1,fill=0)
    canvas.setFillColor(colors.HexColor("#FFFEFA"))
    canvas.circle(50.5,13.5,5.5,fill=1,stroke=0)
    canvas.restoreState()


def _fetch_public_goal_image(url: str) -> bytes | None:
    """Fetch only small public HTTPS JPEG/PNG images; reject local/private hosts and redirects."""
    try:
        parsed = urlsplit(str(url))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return None
        host = parsed.hostname
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(addr).is_global for addr in addresses):
            return None
        with httpx.Client(timeout=4.0, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", url, headers={"Accept": "image/png,image/jpeg"}) as response:
                if response.status_code != 200:
                    return None
                media_type = response.headers.get("content-type", "").split(";")[0].lower()
                if media_type not in {"image/png", "image/jpeg"}:
                    return None
                length = int(response.headers.get("content-length", "0") or 0)
                if length > 3 * 1024 * 1024:
                    return None
                chunks = bytearray()
                for chunk in response.iter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > 3 * 1024 * 1024:
                        return None
                return bytes(chunks) if chunks else None
    except Exception:
        return None

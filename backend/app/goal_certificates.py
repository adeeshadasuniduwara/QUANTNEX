"""Print-ready, selectable QUANTNEX achievement certificate PDFs."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from urllib.parse import urlsplit
import ipaddress
import socket
import math

import httpx
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from .certificate_designs import get_certificate_design

GOLD = colors.HexColor("#B58A28")
LIGHT_GOLD = colors.HexColor("#E8D79B")
DARK = colors.HexColor("#262116")


def build_goal_certificate_pdf(*, display_name: str, goal_title: str,
                               created_at: datetime, achieved_at: datetime,
                               elapsed_days: int, certificate_id: str,
                               integrity_fingerprint: str, target_amount: float,
                               saved_amount: float, currency: str, demo_only: bool = False,
                               achievement_text: str = "A meaningful result built through patience, consistency and self-discipline.",
                               goal_image_url: str = "", elapsed_hours: int | None = None,
                               design_id: str = "P-01", orientation: str | None = None) -> bytes:
    """Build a self-contained A4 PDF using one of 100 selectable unique designs."""
    design = get_certificate_design(design_id, orientation)
    is_landscape = design["orientation"] == "landscape"
    page_size = landscape(A4) if is_landscape else portrait(A4)
    page_w, page_h = page_size
    accent = colors.HexColor(design["accent"])
    light = colors.HexColor(design["light"])
    ink = colors.HexColor(design["ink"])
    paper = colors.HexColor(design["paper"])
    buffer = BytesIO()
    margin = 18 * mm if is_landscape else 22 * mm
    doc = SimpleDocTemplate(
        buffer, pagesize=page_size, rightMargin=margin, leftMargin=margin,
        topMargin=(27 if is_landscape else 32) * mm,
        bottomMargin=(22 if is_landscape else 25) * mm,
        title=("QUANTNEX Demo Certificate — NOT VALID" if demo_only else "QUANTNEX Achievement Certificate"),
        author="QUANTNEX",
    )

    def star(canvas, cx, cy, outer, inner):
        path = canvas.beginPath()
        for i in range(10):
            angle = math.pi / 2 + i * math.pi / 5
            radius = outer if i % 2 == 0 else inner
            x, y = cx + math.cos(angle) * radius, cy + math.sin(angle) * radius
            (path.moveTo if i == 0 else path.lineTo)(x, y)
        path.close()
        canvas.drawPath(path, fill=1, stroke=0)

    def decorate(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(paper)
        canvas.rect(0, 0, page_w, page_h, fill=1, stroke=0)
        motif = design["motif"]
        canvas.setStrokeColor(accent)
        canvas.setFillColor(accent)
        if motif == "double":
            canvas.setLineWidth(2.0)
            canvas.rect(8*mm, 8*mm, page_w-16*mm, page_h-16*mm, fill=0, stroke=1)
            canvas.setStrokeColor(light); canvas.setLineWidth(0.8)
            canvas.rect(13*mm, 13*mm, page_w-26*mm, page_h-26*mm, fill=0, stroke=1)
        elif motif == "deco":
            canvas.setLineWidth(1.5)
            inset = 10*mm
            canvas.rect(inset, inset, page_w-2*inset, page_h-2*inset, fill=0, stroke=1)
            for x in (inset, page_w-inset):
                for y in (inset, page_h-inset):
                    p=canvas.beginPath(); p.moveTo(x,y); p.lineTo(x+(12*mm if x<page_w/2 else -12*mm),y)
                    p.lineTo(x+(12*mm if x<page_w/2 else -12*mm),y+(12*mm if y<page_h/2 else -12*mm))
                    p.lineTo(x,y+(12*mm if y<page_h/2 else -12*mm)); p.close()
                    canvas.drawPath(p,fill=0,stroke=1)
        elif motif == "laurel":
            canvas.setLineWidth(1.1)
            canvas.roundRect(9*mm,9*mm,page_w-18*mm,page_h-18*mm,8*mm,fill=0,stroke=1)
            for side in (1,-1):
                for i in range(7):
                    x=page_w/2 + side*(26+i*2.5)*mm
                    y=page_h-31*mm if is_landscape else page_h/2 + (i-3)*7*mm
                    canvas.saveState(); canvas.translate(x,y); canvas.rotate(side*35)
                    canvas.ellipse(-2*mm,-4*mm,2*mm,4*mm,fill=0,stroke=1); canvas.restoreState()
        elif motif == "corner":
            canvas.setLineWidth(2.2)
            length=24*mm
            for xdir in (0,1):
                for ydir in (0,1):
                    x=10*mm if xdir==0 else page_w-10*mm
                    y=10*mm if ydir==0 else page_h-10*mm
                    sx=1 if xdir==0 else -1; sy=1 if ydir==0 else -1
                    p=canvas.beginPath(); p.moveTo(x+sx*length,y); p.lineTo(x,y); p.lineTo(x,y+sy*length)
                    canvas.drawPath(p,stroke=1,fill=0)
                    canvas.setFillColor(light); canvas.circle(x+sx*4*mm,y+sy*4*mm,1.5*mm,fill=1,stroke=0)
        elif motif == "medallion":
            canvas.setLineWidth(1.0)
            canvas.rect(10*mm,10*mm,page_w-20*mm,page_h-20*mm,fill=0,stroke=1)
            cx,cy=page_w/2,page_h-20*mm
            canvas.circle(cx,cy,8*mm,fill=0,stroke=1)
            canvas.circle(cx,cy,6*mm,fill=0,stroke=1)
            star(canvas,cx,cy,3.2*mm,1.3*mm)
            canvas.setStrokeColor(light)
            for y in (18*mm,page_h-18*mm):
                canvas.line(28*mm,y,page_w/2-18*mm,y)
                canvas.line(page_w/2+18*mm,y,page_w-28*mm,y)
        elif motif == "ribbon":
            canvas.setLineWidth(1.5)
            canvas.roundRect(10*mm,10*mm,page_w-20*mm,page_h-20*mm,5*mm,fill=0,stroke=1)
            for xdir in (0,1):
                x=10*mm if xdir==0 else page_w-10*mm
                sign=1 if xdir==0 else -1
                p=canvas.beginPath(); p.moveTo(x, page_h-10*mm)
                p.lineTo(x+sign*25*mm,page_h-10*mm); p.lineTo(x+sign*19*mm,page_h-24*mm)
                p.lineTo(x+sign*12*mm,page_h-17*mm); p.close()
                canvas.setFillColor(light); canvas.drawPath(p,fill=1,stroke=1)
            canvas.setStrokeColor(accent)
            canvas.line(32*mm,28*mm,page_w-32*mm,28*mm)
        elif motif == "wave":
            canvas.setLineWidth(1.6)
            for offset, color in ((0,accent),(4*mm,light),(8*mm,accent)):
                canvas.setStrokeColor(color)
                p=canvas.beginPath(); p.moveTo(12*mm,22*mm+offset)
                p.curveTo(page_w*0.28,8*mm+offset,page_w*0.42,38*mm+offset,page_w*0.58,22*mm+offset)
                p.curveTo(page_w*0.74,7*mm+offset,page_w*0.86,36*mm+offset,page_w-12*mm,22*mm+offset)
                canvas.drawPath(p,stroke=1,fill=0)
            canvas.setStrokeColor(light); canvas.line(12*mm,page_h-22*mm,page_w-12*mm,page_h-22*mm)
        elif motif == "sidepanel":
            canvas.setFillColor(colors.Color(accent.red,accent.green,accent.blue,alpha=0.10))
            panel=canvas.beginPath(); panel.moveTo(10*mm,10*mm); panel.lineTo(55*mm,10*mm)
            panel.lineTo(55*mm,page_h-10*mm); panel.lineTo(10*mm,page_h-10*mm); panel.close()
            canvas.drawPath(panel,fill=1,stroke=0)
            canvas.setStrokeColor(accent); canvas.setLineWidth(1.8)
            canvas.line(58*mm,14*mm,58*mm,page_h-14*mm)
            for y in (22*mm,page_h-22*mm):
                canvas.line(65*mm,y,page_w-14*mm,y)
            canvas.setStrokeColor(light); canvas.rect(14*mm,14*mm,37*mm,page_h-28*mm,fill=0,stroke=1)
        elif motif == "sunburst":
            cx,cy=page_w/2,page_h-22*mm
            canvas.setLineWidth(0.8)
            for angle in range(0,360,15):
                rad=math.radians(angle)
                canvas.setStrokeColor(light if angle%30 else accent)
                canvas.line(cx+math.cos(rad)*10*mm,cy+math.sin(rad)*10*mm,
                            cx+math.cos(rad)*17*mm,cy+math.sin(rad)*17*mm)
            canvas.setStrokeColor(accent); canvas.circle(cx,cy,9*mm,fill=0,stroke=1)
            canvas.circle(cx,cy,6*mm,fill=0,stroke=1); star(canvas,cx,cy,3.5*mm,1.4*mm)
            canvas.rect(10*mm,10*mm,page_w-20*mm,page_h-20*mm,fill=0,stroke=1)
        else:  # architectural grid
            canvas.setLineWidth(0.7); canvas.setStrokeColor(light)
            inset=13*mm
            canvas.rect(inset,inset,page_w-2*inset,page_h-2*inset,fill=0,stroke=1)
            for x in (page_w*0.25,page_w*0.75):
                canvas.line(x,14*mm,x,page_h-14*mm)
            for y in (page_h*0.22,page_h*0.78):
                canvas.line(14*mm,y,page_w-14*mm,y)
            canvas.setStrokeColor(accent); canvas.setLineWidth(2.0)
            canvas.line(14*mm,14*mm,38*mm,14*mm)
            canvas.line(page_w-38*mm,page_h-14*mm,page_w-14*mm,page_h-14*mm)
        if motif not in {"medallion","sunburst"}:
            canvas.setFillColor(accent)
            for x in (18*mm,page_w-18*mm):
                for y in (18*mm,page_h-18*mm):
                    star(canvas,x,y,2.6*mm,1.0*mm)
        draw_quantnex_mark(canvas,page_w/2-7*mm,page_h-(23 if is_landscape else 29)*mm,14*mm,gold_color=accent)
        if demo_only:
            canvas.saveState(); canvas.translate(page_w/2,page_h/2); canvas.rotate(28 if is_landscape else 32)
            canvas.setFillColor(colors.Color(0.55,0.42,0.18,alpha=0.19))
            canvas.setFont("Helvetica-Bold",27 if is_landscape else 30)
            canvas.drawCentredString(0,0,"DEMO ONLY — NOT VALID")
            canvas.setFont("Helvetica-Bold",10); canvas.drawCentredString(0,-11*mm,"FOR DISPLAY PURPOSES ONLY")
            canvas.restoreState()
        canvas.setFillColor(ink); canvas.setFont("Helvetica-Bold",7.5)
        canvas.drawCentredString(page_w/2,15*mm,"QUANTNEX  ·  PERSONAL DISCIPLINE SERIES")
        canvas.setFillColor(accent); canvas.setFont("Helvetica",6.2)
        footer=("DEMO SAMPLE · NOT VALID · FOR DISPLAY PURPOSES ONLY" if demo_only
                else "LOCAL CERTIFICATE · NOT A FINANCIAL LICENSE OR TRADING PERFORMANCE GUARANTEE")
        canvas.drawCentredString(page_w/2,11*mm,footer)
        canvas.restoreState()

    styles=getSampleStyleSheet()
    compact = is_landscape
    title_size = 21 if compact else 24
    name_size = 20 if compact else 22
    brand=ParagraphStyle("Brand",parent=styles["Normal"],fontName="Helvetica-Bold",
        fontSize=8,leading=10,alignment=TA_CENTER,textColor=accent,tracking=2.5)
    title=ParagraphStyle("CertTitle",parent=styles["Title"],fontName="Times-Bold",
        fontSize=title_size,leading=title_size+4,alignment=TA_CENTER,textColor=ink,spaceAfter=3*mm)
    lead=ParagraphStyle("Lead",parent=styles["Normal"],fontName="Helvetica",
        fontSize=8.5,leading=11,alignment=TA_CENTER,textColor=ink)
    name=ParagraphStyle("Name",parent=styles["Heading1"],fontName="Times-BoldItalic",
        fontSize=name_size,leading=name_size+4,alignment=TA_CENTER,textColor=accent,
        spaceBefore=4*mm,spaceAfter=3*mm)
    goal=ParagraphStyle("Goal",parent=styles["Heading2"],fontName="Helvetica-Bold",
        fontSize=13 if compact else 15,leading=16,alignment=TA_CENTER,textColor=ink,
        spaceBefore=3*mm,spaceAfter=3*mm)
    small=ParagraphStyle("Small",parent=styles["Normal"],fontName="Helvetica",
        fontSize=6.5,leading=8,alignment=TA_CENTER,textColor=ink)
    story=[
        Paragraph("Q U A N T N E X",brand),Spacer(1,2*mm),
        Paragraph("DEMO CERTIFICATE PREVIEW" if demo_only else "CERTIFICATE OF ACHIEVEMENT",title),
        Paragraph("SAMPLE ONLY · NOT VALID · PROUDLY PRESENTED TO" if demo_only else "PROUDLY PRESENTED TO",lead),
        Paragraph(_escape(display_name),name),
        Paragraph("PERSONAL GOAL ACHIEVED",lead),
        Paragraph(_escape(goal_title),goal),
        Paragraph(_escape(achievement_text),lead),Spacer(1,3*mm),
        Paragraph(f"GOAL VALUE · {currency} {target_amount:,.2f} · RECORDED SAVINGS {currency} {saved_amount:,.2f}",small),
        Spacer(1,3*mm),
        Paragraph(f"GOAL STARTED · {created_at.strftime('%d %B %Y')}   |   ACHIEVED · {achieved_at.strftime('%d %B %Y')}",small),
        Paragraph(f"TIME INVESTED · {elapsed_days} days · {elapsed_hours if elapsed_hours is not None else elapsed_days*24} hours",small),
        Spacer(1,4*mm),Paragraph("Presented by the QUANTNEX Support Team",lead),
        Paragraph("QUANTNEX",ParagraphStyle("Signature",parent=styles["Normal"],fontName="Times-Italic",
            fontSize=17,leading=20,alignment=TA_CENTER,textColor=accent)),
        Paragraph("PERSONAL GOAL MILESTONE",small),Spacer(1,4*mm),
        Paragraph(f"Certificate ID: {certificate_id}",small),
        Paragraph(f"Local integrity fingerprint: {integrity_fingerprint[:24]}",small),
    ]
    if goal_image_url:
        image_data=_fetch_public_goal_image(goal_image_url)
        if image_data:
            try:
                photo=Image(BytesIO(image_data),width=(54 if compact else 62)*mm,height=25*mm,kind="proportional")
                photo.hAlign="CENTER"; story.insert(7,photo); story.insert(8,Spacer(1,2*mm))
            except Exception:
                pass
    if demo_only:
        story.insert(0,Paragraph("DEMO ONLY — NOT VALID · FOR DISPLAY PURPOSES ONLY",small))
        story.insert(1,Spacer(1,2*mm))
    doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
    return buffer.getvalue()


def _escape(value: str) -> str:
    return str(value).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")


def draw_quantnex_mark(canvas,x:float,y:float,size:float,gold_color=None) -> None:
    canvas.saveState(); scale=size/64.0; canvas.translate(x,y); canvas.scale(scale,scale)
    canvas.setFillColor(gold_color or GOLD); canvas.roundRect(0,0,64,64,16,fill=1,stroke=0)
    canvas.setStrokeColor(colors.HexColor("#FFFEFA")); canvas.setLineWidth(5.5); canvas.setLineCap(1)
    canvas.arc(10,10,54,54,45,285); path=canvas.beginPath(); path.moveTo(34,34); path.lineTo(48,48)
    canvas.drawPath(path,stroke=1,fill=0); canvas.setFillColor(colors.HexColor("#FFFEFA"))
    canvas.circle(50.5,13.5,5.5,fill=1,stroke=0); canvas.restoreState()


def _fetch_public_goal_image(url: str) -> bytes | None:
    """Fetch only small public HTTPS JPEG/PNG images; reject local/private hosts and redirects."""
    try:
        parsed=urlsplit(str(url))
        if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password: return None
        host=parsed.hostname
        addresses={item[4][0] for item in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(addr).is_global for addr in addresses): return None
        with httpx.Client(timeout=4.0,follow_redirects=False,trust_env=False) as client:
            with client.stream("GET",url,headers={"Accept":"image/png,image/jpeg"}) as response:
                if response.status_code!=200: return None
                media_type=response.headers.get("content-type","").split(";")[0].lower()
                if media_type not in {"image/png","image/jpeg"}: return None
                length=int(response.headers.get("content-length","0") or 0)
                if length>3*1024*1024: return None
                chunks=bytearray()
                for chunk in response.iter_bytes():
                    chunks.extend(chunk)
                    if len(chunks)>3*1024*1024: return None
                return bytes(chunks) if chunks else None
    except Exception:
        return None

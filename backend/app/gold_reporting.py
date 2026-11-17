"""QUANTNEX 4K Sri Lankan gold-price image reports for Telegram."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

COLOMBO = ZoneInfo("Asia/Colombo")
GRAMS = (1, 2, 4, 8, 10, 100)
TROY_OUNCE_GRAMS = 31.1034768
HISTORY_LIMIT = 12


def _font(size: int, bold: bool = False):
    candidates = (
        [r"C:\Windows\Fonts\arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        [r"C:\Windows\Fonts\arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _money(value: float) -> str:
    return "LKR " + format(value, ",.2f")


def gold_snapshot_from_overview(overview: dict[str, Any], captured_at: datetime | None = None) -> dict[str, Any]:
    """Convert a validated XAU/USD spot and USD/LKR reference into indicative 24K/22K LKR/gram."""
    gold_per_gram = overview.get("gold_lkr_gram")
    fx = overview.get("usd_lkr")
    if gold_per_gram is None or fx is None:
        raise ValueError("Gold spot or USD/LKR reference feed is unavailable.")
    gold_per_gram = float(gold_per_gram)
    fx = float(fx)
    if not (gold_per_gram > 0 and fx > 0):
        raise ValueError("Gold price and USD/LKR must be positive.")
    stamp = captured_at or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return {
        "timestamp": stamp.astimezone(timezone.utc).isoformat(),
        "gold_usd_oz": float(overview["gold_usd_oz"]),
        "usd_lkr": fx,
        "24k_per_gram": gold_per_gram,
        "22k_per_gram": gold_per_gram * 22 / 24,
        "source": str((overview.get("sources") or {}).get("gold", "XAU/USD spot"))
                  + " · " + str((overview.get("sources") or {}).get("fx", "USD/LKR reference")),
    }


def append_gold_snapshot(raw_history: str, snapshot: dict[str, Any]) -> str:
    """Append a deduplicated user snapshot history for honest 24-hour comparisons."""
    try:
        history = json.loads(raw_history or "[]")
    except (TypeError, ValueError):
        history = []
    if not isinstance(history, list):
        history = []
    stamp = datetime.fromisoformat(snapshot["timestamp"])
    history = [row for row in history if isinstance(row, dict)
               and row.get("timestamp") != snapshot["timestamp"]]
    history.append(snapshot)
    history.sort(key=lambda row: str(row.get("timestamp", "")))
    cutoff = stamp - timedelta(days=7)
    kept = []
    for row in history:
        try:
            when = datetime.fromisoformat(row["timestamp"])
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when >= cutoff:
                kept.append(row)
        except (KeyError, TypeError, ValueError):
            continue
    return json.dumps(kept[-HISTORY_LIMIT:], separators=(",", ":"))


def find_24h_reference(raw_history: str, now: datetime) -> dict[str, Any] | None:
    """Find a sample 23–25 hours old; never fabricate a 24h return from unrelated data."""
    try:
        history = json.loads(raw_history or "[]")
    except (TypeError, ValueError):
        return None
    if not isinstance(history, list):
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    target = now.astimezone(timezone.utc) - timedelta(hours=24)
    candidates = []
    for row in history:
        try:
            stamp = datetime.fromisoformat(row["timestamp"])
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamp = stamp.astimezone(timezone.utc)
            age = (now.astimezone(timezone.utc) - stamp).total_seconds()
            if 23 * 3600 <= age <= 25 * 3600:
                candidates.append((abs((stamp - target).total_seconds()), row))
        except (KeyError, TypeError, ValueError):
            continue
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def build_gold_report_image(snapshot: dict[str, Any], previous_24h: dict[str, Any] | None = None,
                            generated_at: datetime | None = None) -> bytes:
    """Render a black/white 2160×3840 branded report; prices are indicative spot conversions."""
    width, height = 2160, 3840
    image = Image.new("RGB", (width, height), (7, 7, 7))
    draw = ImageDraw.Draw(image)
    white, soft, muted, line = (246, 246, 246), (194, 194, 194), (132, 132, 132), (57, 57, 57)
    margin = 140
    now = generated_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(COLOMBO)
    captured = datetime.fromisoformat(snapshot["timestamp"]).astimezone(COLOMBO)

    def centered(y: int, text: str, font, fill=white):
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((width - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)

    # Quiet technical texture and double frame.
    for x in range(100, width, 180):
        draw.line((x, 0, x - 240, 500), fill=(15, 15, 15), width=3)
    draw.rounded_rectangle((42, 42, width-42, height-42), radius=42, outline=(82, 82, 82), width=3)
    draw.rounded_rectangle((64, 64, width-64, height-64), radius=34, outline=(28, 28, 28), width=2)

    centered(135, "QUANTNEX", _font(112, True))
    centered(270, "SRI LANKA  ·  GOLD MARKET REPORT", _font(36, True), soft)
    draw.line((margin, 365, width-margin, 365), fill=line, width=3)
    centered(430, "LIVE GOLD PRICE", _font(78, True))
    centered(535, "INDICATIVE SPOT CONVERSION  ·  LKR PER GRAM", _font(30), muted)

    # Main 24K / 22K panels.
    panel_top, panel_h, gap = 680, 470, 54
    panel_w = (width - 2*margin - gap) // 2
    cards = [
        ("24K", "PURE GOLD", float(snapshot["24k_per_gram"])),
        ("22K", "91.67% PURITY", float(snapshot["22k_per_gram"])),
    ]
    for index, (karat, label, price) in enumerate(cards):
        x = margin + index * (panel_w + gap)
        draw.rounded_rectangle((x, panel_top, x+panel_w, panel_top+panel_h),
                               radius=34, fill=(17, 17, 17), outline=(105, 105, 105), width=3)
        draw.text((x+54, panel_top+48), karat, font=_font(72, True), fill=white)
        draw.text((x+58, panel_top+145), label, font=_font(28, True), fill=muted)
        draw.text((x+54, panel_top+250), _money(price), font=_font(51, True), fill=white)
        draw.text((x+58, panel_top+355), "PER 1 GRAM", font=_font(27), fill=soft)

    # 24-hour change is shown only when a sufficiently close historical sample exists.
    change_top = 1230
    draw.rounded_rectangle((margin, change_top, width-margin, change_top+340),
                           radius=30, fill=(13, 13, 13), outline=line, width=3)
    centered(change_top+40, "24-HOUR MARKET CHANGE", _font(38, True), soft)
    if previous_24h:
        for row_index, key in enumerate(("24k_per_gram", "22k_per_gram")):
            old = float(previous_24h[key])
            current = float(snapshot[key])
            pct = ((current - old) / old * 100) if old else 0.0
            label = "24K" if row_index == 0 else "22K"
            sign = "+" if pct > 0 else ""
            value = f"{label}   {sign}{pct:.2f}%"
            centered(change_top+125+row_index*92, value, _font(58, True),
                     white if pct >= 0 else soft)
    else:
        centered(change_top+145, "24H COMPARISON BUILDING", _font(42, True), white)
        centered(change_top+220, "A full 24-hour saved price history is not available yet.",
                 _font(25), muted)

    # Multi-weight table.
    table_top = 1660
    centered(table_top, "PRICE BY GOLD WEIGHT", _font(52, True))
    centered(table_top+80, "INDICATIVE VALUE  ·  EXCLUDES JEWELLER PREMIUMS / TAXES", _font(24), muted)
    table_y = table_top + 165
    col_x = [margin, 660, 1370]
    headers = ["WEIGHT", "24K GOLD", "22K GOLD"]
    draw.rounded_rectangle((margin, table_y, width-margin, table_y+104),
                           radius=18, fill=(28, 28, 28))
    for x, title in zip(col_x, headers):
        draw.text((x+24, table_y+28), title, font=_font(28, True), fill=white)
    row_h = 150
    for i, grams in enumerate(GRAMS):
        y = table_y + 104 + i*row_h
        if i % 2 == 0:
            draw.rounded_rectangle((margin, y, width-margin, y+row_h-12),
                                   radius=14, fill=(13, 13, 13))
        draw.text((col_x[0]+24, y+40), f"{grams:g} g", font=_font(38, True), fill=white)
        draw.text((col_x[1]+24, y+44), _money(float(snapshot["24k_per_gram"])*grams),
                  font=_font(31, True), fill=soft)
        draw.text((col_x[2]+24, y+44), _money(float(snapshot["22k_per_gram"])*grams),
                  font=_font(31, True), fill=soft)

    foot_y = table_y + 104 + len(GRAMS)*row_h + 50
    draw.line((margin, foot_y, width-margin, foot_y), fill=line, width=3)
    centered(foot_y+45, "MARKET SNAPSHOT", _font(30, True), soft)
    centered(foot_y+105, "Report time: " + local.strftime("%d %b %Y  ·  %I:%M %p") + " (Sri Lanka)",
             _font(27), muted)
    centered(foot_y+155, "Price feed updated: " + captured.strftime("%d %b %Y  ·  %I:%M %p"),
             _font(25), muted)
    centered(foot_y+225, "USD/LKR reference: " + format(float(snapshot["usd_lkr"]), ",.2f"),
             _font(26), soft)
    centered(foot_y+295, "Source: " + str(snapshot.get("source", "XAU/USD and USD/LKR reference"))[:90],
             _font(22), muted)
    centered(foot_y+380, "Indicative international spot conversion — not a jeweller's retail quote.",
             _font(22), muted)
    centered(foot_y+420, "Local taxes, workmanship and dealer premiums may differ.",
             _font(22), muted)
    centered(height-175, "QUANTNEX  ·  PLAN  /  ANALYZE  /  REVIEW", _font(29, True), soft)

    output = BytesIO()
    image.save(output, format="JPEG", quality=92, optimize=True, progressive=True)
    return output.getvalue()

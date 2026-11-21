"""Personal QUANTNEX Telegram onboarding artwork."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import unicodedata

from PIL import Image, ImageDraw, ImageFont, ImageFilter

SIZE = 1024
BG = (8, 8, 8)
WHITE = (245, 245, 245)
SILVER = (185, 185, 185)
MUTED = (112, 112, 112)
LINE = (41, 41, 41)


def normalise_telegram_name(value: str) -> str | None:
    """Accept a short display name, not commands, links, or control characters."""
    name = " ".join(str(value or "").strip().split())
    if not 2 <= len(name) <= 32:
        return None
    for char in name:
        category = unicodedata.category(char)
        if category.startswith(("L", "M", "N")) or char in " ._'-":
            continue
        return None
    if not any(unicodedata.category(char).startswith("L") for char in name):
        return None
    return name


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    root = Path("/usr/share/fonts/truetype")
    candidates = (
        [
            root / "dejavu/DejaVuSans-Bold.ttf",
            root / "liberation2/LiberationSans-Bold.ttf",
            root / "lato/Lato-Bold.ttf",
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/segoeuib.ttf"),
        ]
        if bold else [
            root / "dejavu/DejaVuSans.ttf",
            root / "liberation2/LiberationSans-Regular.ttf",
            root / "lato/Lato-Regular.ttf",
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/segoeui.ttf"),
        ]
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int, bold: bool = True):
    for size in range(start, 27, -2):
        font = _font(size, bold)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return font
    return _font(28, bold)


def _name_lines(name: str, draw: ImageDraw.ImageDraw, max_width: int) -> list[str]:
    words = name.split()
    if len(words) == 1:
        return [name]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if draw.textbbox((0, 0), candidate, font=_font(90, True))[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > 2:
        return [" ".join(words[:-1]), words[-1]]
    return lines


def build_personal_logo_png(display_name: str, user_id: int = 0) -> bytes:
    """Render a polished 1:1 QUANTNEX personal mark as a PNG."""
    name = normalise_telegram_name(display_name)
    if name is None:
        raise ValueError("Please provide a valid display name between 2 and 32 characters.")

    seed = sha256((str(user_id) + "|" + name.casefold()).encode("utf-8")).digest()
    design = seed[0] % 4
    image = Image.new("RGB", (SIZE, SIZE), BG)

    # Subtle monochrome radial glow and fine technical rings.
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for radius, alpha in ((430, 10), (350, 9), (270, 8)):
        gd.ellipse((512-radius, 512-radius, 512+radius, 512+radius),
                   outline=(245, 245, 245, alpha), width=2)
    gd.ellipse((170, 130, 854, 814), fill=(245, 245, 245, 7))
    glow = glow.filter(ImageFilter.GaussianBlur(42))
    image = Image.alpha_composite(image.convert("RGBA"), glow)
    draw = ImageDraw.Draw(image)

    # Outer frame and the QUANTNEX orbit mark.
    draw.rounded_rectangle((42, 42, 982, 982), radius=76, outline=(55, 55, 55, 255), width=3)
    draw.ellipse((390, 120, 634, 364), outline=WHITE, width=13)
    draw.arc((390, 120, 634, 364), 215, 325, fill=SILVER, width=13)
    draw.line((548, 282, 656, 390), fill=WHITE, width=13)
    draw.ellipse((625, 110, 662, 147), fill=WHITE)

    q_font = _font(43, True)
    draw.text((512, 430), "QUANTNEX", font=q_font, fill=SILVER, anchor="mm")
    draw.line((290, 474, 734, 474), fill=LINE, width=3)

    # Four understated layouts make each member's logo feel individually composed.
    initials = "".join(part[0] for part in name.split()[:2]).upper()
    if design == 0:
        draw.ellipse((412, 510, 612, 710), outline=(105, 105, 105), width=4)
        monogram = _fit_font(draw, initials, 160, 112)
        draw.text((512, 610), initials, font=monogram, fill=WHITE, anchor="mm")
        lines = _name_lines(name, draw, 800)
        font = _fit_font(draw, max(lines, key=len), 800, 86)
        y = 790 if len(lines) == 1 else 770
        for line in lines:
            draw.text((512, y), line, font=font, fill=WHITE, anchor="mm")
            y += 82
    elif design == 1:
        ghost = _fit_font(draw, initials, 720, 500)
        draw.text((512, 660), initials, font=ghost, fill=(43, 43, 43), anchor="mm")
        lines = _name_lines(name, draw, 800)
        font = _fit_font(draw, max(lines, key=len), 800, 92)
        y = 720 if len(lines) == 1 else 690
        for line in lines:
            draw.text((512, y), line, font=font, fill=WHITE, anchor="mm")
            y += 84
        draw.line((340, 850, 684, 850), fill=SILVER, width=4)
    elif design == 2:
        draw.rounded_rectangle((115, 535, 909, 790), radius=34, outline=(95, 95, 95), width=3)
        badge = _fit_font(draw, initials, 160, 115)
        draw.text((512, 610), initials, font=badge, fill=WHITE, anchor="mm")
        lines = _name_lines(name, draw, 750)
        font = _fit_font(draw, max(lines, key=len), 750, 82)
        y = 710 if len(lines) == 1 else 690
        for line in lines:
            draw.text((512, y), line, font=font, fill=SILVER, anchor="mm")
            y += 75
    else:
        draw.arc((180, 500, 844, 1164), 205, 335, fill=(90, 90, 90), width=4)
        draw.arc((220, 520, 804, 1104), 205, 335, fill=(55, 55, 55), width=3)
        lines = _name_lines(name, draw, 800)
        font = _fit_font(draw, max(lines, key=len), 800, 96)
        y = 650 if len(lines) == 1 else 620
        for line in lines:
            draw.text((512, y), line, font=font, fill=WHITE, anchor="mm")
            y += 88
        draw.text((512, 835), "PERSONAL TRADING IDENTITY",
                  font=_font(22, True), fill=MUTED, anchor="mm")

    # Fine footer line and a compact brand signature.
    draw.line((250, 910, 774, 910), fill=LINE, width=2)
    draw.text((512, 940), "LEARN  ·  ANALYSE  ·  EXECUTE",
              font=_font(20, True), fill=MUTED, anchor="mm")

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()

"""Curated catalog of 100 visually distinct goal-certificate compositions."""
from __future__ import annotations

PORTRAIT_PALETTES = [
    ("Royal Gold", "#B58A28", "#E8D79B", "#262116", "#FFFEFA"),
    ("Midnight Blue", "#315B91", "#A9C8EE", "#14243A", "#F7FAFF"),
    ("Emerald", "#26745A", "#A9DCC5", "#17372D", "#F7FFFB"),
    ("Burgundy", "#8D354B", "#E6AAB7", "#3C1721", "#FFF9FA"),
    ("Platinum", "#68717D", "#D5DCE5", "#252B33", "#FCFCFD"),
    ("Royal Purple", "#7250A4", "#C9B2E8", "#2D1D42", "#FCFAFF"),
    ("Ocean Teal", "#187D83", "#A1D9D8", "#12383A", "#F5FFFF"),
    ("Copper", "#A65F35", "#E8B99A", "#3C2418", "#FFFAF5"),
    ("Sapphire", "#244FA8", "#A9BDF0", "#17264D", "#F8FAFF"),
    ("Rose Gold", "#A96E72", "#E8C0B9", "#3C2528", "#FFFAF9"),
]
LANDSCAPE_PALETTES = [
    ("Obsidian Silver", "#59616D", "#C9D0D9", "#202630", "#FBFCFE"),
    ("Crimson Luxe", "#A52F43", "#F0A7B3", "#40151F", "#FFF8F9"),
    ("Pine & Ivory", "#3C6845", "#C3D9A9", "#1D3523", "#FCFFF8"),
    ("Amber Crown", "#B47720", "#F1D18A", "#3D2A0E", "#FFFCF3"),
    ("Arctic Glacier", "#367C9E", "#B8E3F0", "#183442", "#F7FDFF"),
    ("Amethyst Night", "#8051B5", "#D6B7F0", "#2D1744", "#FCF8FF"),
    ("Jade Dynasty", "#147A69", "#A5D9C8", "#123A33", "#F5FFFC"),
    ("Antique Bronze", "#8B653A", "#DCC39B", "#332416", "#FFFBF3"),
    ("Indigo Velvet", "#3D438F", "#B9B9EB", "#20214D", "#FAFAFF"),
    ("Champagne Pearl", "#A88A54", "#E8D9B6", "#3B3325", "#FFFEF8"),
]
PORTRAIT_MOTIFS = [
    ("Classic Double Frame", "double"),
    ("Art Deco Geometry", "deco"),
    ("Laurel Achievement", "laurel"),
    ("Modern Cornerwork", "corner"),
    ("Medallion & Lines", "medallion"),
]
LANDSCAPE_MOTIFS = [
    ("Ribbon Crest", "ribbon"),
    ("Wave Horizon", "wave"),
    ("Side Panel Luxe", "sidepanel"),
    ("Sunburst Seal", "sunburst"),
    ("Architectural Grid", "grid"),
]


def certificate_design_catalog():
    """Return 50 portrait + 50 landscape designs with disjoint composition families."""
    result = []
    groups = (
        ("portrait", "Portrait", "P", PORTRAIT_PALETTES, PORTRAIT_MOTIFS),
        ("landscape", "Landscape", "L", LANDSCAPE_PALETTES, LANDSCAPE_MOTIFS),
    )
    for orientation, label, prefix, palettes, motifs in groups:
        for palette_index, palette in enumerate(palettes, 1):
            palette_name, accent, light, ink, paper = palette
            for motif_index, (motif_name, motif) in enumerate(motifs, 1):
                number = (palette_index - 1) * len(motifs) + motif_index
                result.append({
                    "id": f"{prefix}-{number:02d}",
                    "name": f"{palette_name} · {motif_name} · {label}",
                    "orientation": orientation,
                    "orientation_label": label,
                    "palette": palette_name,
                    "motif": motif,
                    "accent": accent,
                    "light": light,
                    "ink": ink,
                    "paper": paper,
                    "description": f"{palette_name} finish with {motif_name.lower()} detailing.",
                })
    return result


DESIGN_BY_ID = {item["id"]: item for item in certificate_design_catalog()}


def get_certificate_design(design_id: str | None, orientation: str | None = None):
    """Resolve a requested design; keep old callers compatible with a default portrait."""
    if not design_id:
        design_id = "P-01"
    design = DESIGN_BY_ID.get(str(design_id).upper())
    if design is None:
        raise ValueError("Choose one of the 100 available certificate designs.")
    if orientation and orientation != design["orientation"]:
        raise ValueError("The selected certificate design does not match the chosen page orientation.")
    return design

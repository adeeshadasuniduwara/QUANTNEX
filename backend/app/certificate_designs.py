"""Curated, deterministic catalog of 100 distinct goal-certificate designs."""
from __future__ import annotations

PALETTES = [
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
MOTIFS = [
    ("Classic Double Frame", "double"),
    ("Art Deco Geometry", "deco"),
    ("Laurel Achievement", "laurel"),
    ("Modern Cornerwork", "corner"),
    ("Medallion & Lines", "medallion"),
]


def certificate_design_catalog():
    """Return 50 portrait and 50 landscape options; each id and composition is unique."""
    result = []
    for orientation, label in (("portrait", "Portrait"), ("landscape", "Landscape")):
        for palette_index, palette in enumerate(PALETTES, 1):
            palette_name, accent, light, ink, paper = palette
            for motif_index, (motif_name, motif) in enumerate(MOTIFS, 1):
                number = (palette_index - 1) * len(MOTIFS) + motif_index
                result.append({
                    "id": f"{'P' if orientation == 'portrait' else 'L'}-{number:02d}",
                    "name": f"{palette_name} · {motif_name}",
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

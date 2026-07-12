"""
Bildbearbeitung für pictures/: Zuschnitt auf Kartenratio, Wertekurven, Sättigung.
Wird vom Panel als Subprocess-losen Inplace-Aufruf genutzt (direkt importiert).
"""

from pathlib import Path
from PIL import Image, ImageEnhance


def edit_image(
    src_path: Path,
    dst_path: Path,
    lut_r: list,           # 256 int-Werte (bereits RGB×Kanal-komponiert)
    lut_g: list,
    lut_b: list,
    saturation: float,     # 1.0 = unverändert
    crop_offset_x: float,  # -1..1, Anteil des horizontalen Überschusses
    crop_offset_y: float,  # -1..1, Anteil des vertikalen Überschusses
    crop_scale: float,     # 0..1, Anteil des maximalen Ausschnitts (1 = maximal)
    card_ratio: float,     # Breite/Höhe des Kartenformats
    card_width_mm: float = 180.0,
    card_height_mm: float = 80.0,
) -> dict:
    try:
        img = Image.open(src_path).convert("RGB")
    except Exception as e:
        return {"ok": False, "error": f"Bild nicht lesbar: {e}"}

    img_w, img_h = img.size
    img_ratio    = img_w / img_h
    scale        = max(0.05, min(1.0, crop_scale))

    # Maximaler Ausschnitt mit Kartenratio
    if img_ratio > card_ratio:
        max_w = img_h * card_ratio
        max_h = float(img_h)
    else:
        max_w = float(img_w)
        max_h = img_w / card_ratio

    # Skalierter Ausschnitt
    crop_w = max(1, int(round(max_w * scale)))
    crop_h = max(1, int(round(max_h * scale)))

    # Versatz innerhalb des Überschusses
    slack_x = img_w - crop_w
    slack_y = img_h - crop_h
    x0 = int(round(slack_x / 2 * (1 + crop_offset_x)))
    y0 = int(round(slack_y / 2 * (1 + crop_offset_y)))
    x0 = max(0, min(slack_x, x0))
    y0 = max(0, min(slack_y, y0))

    img = img.crop((x0, y0, x0 + crop_w, y0 + crop_h))

    # Auf Kartenmaß bei 200 PPI resampeln
    target_w = max(1, int(round(card_width_mm  / 25.4 * 200)))
    target_h = max(1, int(round(card_height_mm / 25.4 * 200)))
    img = img.resize((target_w, target_h), Image.LANCZOS)

    # Sättigung
    if abs(saturation - 1.0) > 0.001:
        img = ImageEnhance.Color(img).enhance(saturation)

    # Wertekurve per Kanal
    r_band, g_band, b_band = img.split()
    r_band = r_band.point(lut_r)
    g_band = g_band.point(lut_g)
    b_band = b_band.point(lut_b)
    img = Image.merge("RGB", (r_band, g_band, b_band))

    try:
        img.save(str(dst_path))
    except Exception as e:
        return {"ok": False, "error": f"Speichern fehlgeschlagen: {e}"}

    return {"ok": True}

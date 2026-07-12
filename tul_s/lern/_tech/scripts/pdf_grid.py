"""
Druckraster-Logik: Setzt Lernkarten-PDFs in ein Druckraster um.

Logik:
- Quelldatei: PDF mit abwechselnd Frage/Antwort-Seiten (Seite 1=Frage, 2=Antwort, ...)
- Ziel: Druck-PDF mit Vorderseiten-Blatt + Rückseiten-Blatt (Duplex)
- Raster: cols × rows Karten pro Blatt, skaliert auf Papierformat
- Duplex-Versatz: Rückseiten horizontal gespiegelt, damit nach dem Wenden Karte auf Karte trifft
- Zellgröße wird aus dem Kartenverhältnis der Quelldatei berechnet (kein Strecken/Stauchen).
  Der Rand ergibt sich als Restfläche (Grid zentriert auf dem Blatt).

Papierformate in Punkten (1 pt = 1/72 inch):
  A4 hoch: 595 × 842
  A4 quer: 842 × 595
  A3 hoch: 842 × 1191
  A3 quer: 1191 × 842
"""

from pathlib import Path
import fitz  # PyMuPDF


PAPER_SIZES = {
    "A4 hoch":  (595.28, 841.89),
    "A4 quer":  (841.89, 595.28),
    "A3 hoch":  (841.89, 1190.55),
    "A3 quer":  (1190.55, 841.89),
}


def build_print_pdf(
    source_pdf: Path,
    output_pdf: Path,
    paper: str = "A4 quer",
    cols: int = 3,
    rows: int = 5,
    margin_pt: float = 0.0,   # Seitenrand (alle vier Seiten gleich) in pt
    gutter_pt: float = 2.83,  # Abstand zwischen Karten in pt
    crop_marks: bool = True,
    page_range: tuple[int, int] | None = None,
) -> dict:
    """
    Erzeugt ein druckfertiges PDF mit Vorder- und Rückseiten-Rastern.

    Zellgröße wird proportionserhaltend aus dem Kartenverhältnis der Quelldatei berechnet.
    margin_pt ist der Seitenrand (zieht von allen vier Seiten ab); gutter_pt ist der
    Abstand zwischen den Karten. Das Grid wird innerhalb der verbleibenden Fläche zentriert.

    page_range: (start, end) 1-basiert inklusive; None = alles
    Gibt {"ok": True, "pages": n, "cards": n} oder {"ok": False, "error": "..."} zurück.
    """
    if paper not in PAPER_SIZES:
        return {"ok": False, "error": f"Unbekanntes Papierformat: {paper}"}

    paper_w, paper_h = PAPER_SIZES[paper]

    try:
        src = fitz.open(str(source_pdf))
    except Exception as e:
        return {"ok": False, "error": f"PDF nicht lesbar: {e}"}

    # Kartenverhältnis aus erster Seite der Quelldatei
    card_ratio = src[0].rect.width / src[0].rect.height

    # Verfügbare Fläche nach Abzug des Seitenrands
    avail_w = paper_w - 2 * margin_pt
    avail_h = paper_h - 2 * margin_pt

    # Maximale Zellhöhe die ins Raster passt, Seitenverhältnis erhalten
    cell_h = min(
        (avail_w - (cols - 1) * gutter_pt) / (cols * card_ratio),
        (avail_h - (rows - 1) * gutter_pt) / rows,
    )
    cell_w = cell_h * card_ratio

    # Grid zentriert innerhalb verfügbarer Fläche
    margin_x = margin_pt + (avail_w - cols * cell_w - (cols - 1) * gutter_pt) / 2
    margin_y = margin_pt + (avail_h - rows * cell_h - (rows - 1) * gutter_pt) / 2

    total_pages = len(src)
    # Frage-Seiten: 0, 2, 4, ... (0-basiert)
    question_indices = list(range(0, total_pages, 2))

    if page_range:
        start, end = page_range
        start = max(1, start)
        end = min(len(question_indices), end)
        question_indices = question_indices[start - 1:end]

    cards_per_sheet = cols * rows
    out = fitz.open()
    card_count = 0

    for sheet_start in range(0, len(question_indices), cards_per_sheet):
        batch = question_indices[sheet_start:sheet_start + cards_per_sheet]

        # Seiten anlegen, dann per Index ansprechen (PyMuPDF invalidiert Referenzen)
        out.new_page(width=paper_w, height=paper_h)  # Vorderseite
        front_idx = len(out) - 1
        out.new_page(width=paper_w, height=paper_h)  # Rückseite
        back_idx = len(out) - 1

        for slot, q_idx in enumerate(batch):
            col = slot % cols
            row = slot // cols

            # Vorderseite: links→rechts, oben→unten
            x0 = margin_x + col * (cell_w + gutter_pt)
            y0 = margin_y + row * (cell_h + gutter_pt)
            front_rect = fitz.Rect(x0, y0, x0 + cell_w, y0 + cell_h)

            # Rückseite: Spalte horizontal spiegeln für Duplex-Wenden (lange Seite)
            back_col = (cols - 1) - col
            bx0 = margin_x + back_col * (cell_w + gutter_pt)
            back_rect = fitz.Rect(bx0, y0, bx0 + cell_w, y0 + cell_h)

            out[front_idx].show_pdf_page(front_rect, src, q_idx, keep_proportion=True)

            a_idx = q_idx + 1
            if a_idx < total_pages:
                out[back_idx].show_pdf_page(back_rect, src, a_idx, keep_proportion=True)

            if crop_marks:
                _draw_crop_marks(out[front_idx], front_rect, margin_x, margin_y)
                _draw_crop_marks(out[back_idx], back_rect, margin_x, margin_y)

            card_count += 1

    out.save(str(output_pdf))
    src.close()
    out.close()

    return {"ok": True, "cards": card_count, "pages": len(out) if not out.is_closed else card_count // cards_per_sheet * 2}


def _draw_crop_marks(page: fitz.Page, rect: fitz.Rect, margin_x: float, margin_y: float):
    """Zeichnet kleine Schnittmarken an den vier Ecken eines Rasters."""
    mark_len = 6.0
    gap = 2.0
    color = (0.6, 0.6, 0.6)

    corners = [
        (rect.x0, rect.y0),
        (rect.x1, rect.y0),
        (rect.x0, rect.y1),
        (rect.x1, rect.y1),
    ]
    for cx, cy in corners:
        dx = -mark_len if cx > margin_x else mark_len
        dy = -mark_len if cy > margin_y else mark_len
        # Horizontale Linie
        page.draw_line(
            fitz.Point(cx + (gap if dx > 0 else -gap), cy),
            fitz.Point(cx + dx, cy),
            color=color, width=0.4
        )
        # Vertikale Linie
        page.draw_line(
            fitz.Point(cx, cy + (gap if dy > 0 else -gap)),
            fitz.Point(cx, cy + dy),
            color=color, width=0.4
        )

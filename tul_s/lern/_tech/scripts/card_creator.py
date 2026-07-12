"""
Erzeugt Lernkarten-PDFs aus CSV + Template.

Layout-System (alle Maße in mm, intern in pt):
  margin_mm     – Abstand rundum: Rand zu Karte, und zwischen Thema- und Fragefeld
  topic_width_mm – Breite des Thema-Streifens links
  Daraus berechnet:
    Fragekarte:  Thema-Feld | Frage-Feld
    Antwortkarte: Antwort-Feld (Vollbreite - 2×margin)
    Frage-Wiederholung: direkt unter Antwort, Abstand repeat_gap_mm

Level-Marker: winzige, fast transparente Schrift ganz unten links auf der Fragekarte.
Format: "lev: <Name> | =" – identisch zum learncard_viewer-Format.
"""

import json
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Optional
import fitz

from .csv_loader import Card, LoadResult

MM = 2.8346  # 1 mm in pt
MIN_FONT_SIZE = 6.0


# ── Datenklassen ──────────────────────────────────────────────────────────────

@dataclass
class TextStyle:
    font: str = "helv"
    font_path: str = ""
    size: float = 14.0
    color: tuple = (1.0, 1.0, 1.0)
    shadow_offset: tuple = (0.0, 0.0)
    shadow_color: tuple = (0.0, 0.0, 0.0)
    bg_color: tuple = (0.0, 0.0, 0.0)
    bg_alpha: float = 0.0


@dataclass
class CardTemplate:
    # Geometrie
    card_width_mm: float  = 180.0
    card_height_mm: float = 80.0
    margin_mm: float      = 4.0    # Rand + Abstand zwischen Feldern
    topic_width_mm: float = 10.0   # Breite Thema-Streifen
    line_spacing: float   = 1.2    # Zeilenabstand Frage + Thema
    answer_line_spacing: float = 1.2  # Zeilenabstand Antwort (separat einstellbar)
    repeat_gap_mm: float  = 4.0    # Abstand Frage-Wiederholung unter Antwort

    # Hintergründe
    front_bg:       str   = ""
    back_bg:        str   = ""
    front_bg_alpha: float = 1.0
    back_bg_alpha:  float = 1.0

    # Textstile
    topic_style:    TextStyle = dc_field(default_factory=TextStyle)
    question_style: TextStyle = dc_field(default_factory=TextStyle)
    answer_style:   TextStyle = dc_field(default_factory=TextStyle)
    repeat_style:   TextStyle = dc_field(default_factory=TextStyle)


# ── Template I/O ──────────────────────────────────────────────────────────────

def _style_from_dict(d: dict) -> TextStyle:
    return TextStyle(
        font=d.get("font", "helv"),
        font_path=d.get("font_path", ""),
        size=float(d.get("size", 14)),
        color=tuple(d.get("color", [1, 1, 1])),
        shadow_offset=tuple(d.get("shadow_offset", [0.0, 0.0])),
        shadow_color=tuple(d.get("shadow_color", [0.0, 0.0, 0.0])),
        bg_color=tuple(d.get("bg_color", [0.0, 0.0, 0.0])),
        bg_alpha=float(d.get("bg_alpha", 0.0)),
    )

def _style_to_dict(s: TextStyle) -> dict:
    return {
        "font": s.font, "font_path": s.font_path, "size": s.size,
        "color": list(s.color),
        "shadow_offset": list(s.shadow_offset),
        "shadow_color": list(s.shadow_color),
        "bg_color": list(s.bg_color),
        "bg_alpha": s.bg_alpha,
    }

def load_template(path: Path) -> CardTemplate:
    d = json.loads(path.read_text(encoding="utf-8"))
    ls = d.get("line_spacing", 1.2)
    return CardTemplate(
        card_width_mm       = d.get("card_width_mm",  180.0),
        card_height_mm      = d.get("card_height_mm", 80.0),
        margin_mm           = d.get("margin_mm",      4.0),
        topic_width_mm      = d.get("topic_width_mm", 10.0),
        line_spacing        = ls,
        answer_line_spacing = d.get("answer_line_spacing", ls),
        repeat_gap_mm       = d.get("repeat_gap_mm",  4.0),
        front_bg            = d.get("front_bg", ""),
        back_bg             = d.get("back_bg",  ""),
        front_bg_alpha      = float(d.get("front_bg_alpha", 1.0)),
        back_bg_alpha       = float(d.get("back_bg_alpha",  1.0)),
        topic_style         = _style_from_dict(d.get("topic_style",    {})),
        question_style      = _style_from_dict(d.get("question_style", {})),
        answer_style        = _style_from_dict(d.get("answer_style",   {})),
        repeat_style        = _style_from_dict(d.get("repeat_style",   {})),
    )

def save_template(template: CardTemplate, path: Path):
    d = {
        "card_width_mm":       template.card_width_mm,
        "card_height_mm":      template.card_height_mm,
        "margin_mm":           template.margin_mm,
        "topic_width_mm":      template.topic_width_mm,
        "line_spacing":        template.line_spacing,
        "answer_line_spacing": template.answer_line_spacing,
        "repeat_gap_mm":       template.repeat_gap_mm,
        "front_bg":            template.front_bg,
        "back_bg":             template.back_bg,
        "front_bg_alpha":      template.front_bg_alpha,
        "back_bg_alpha":       template.back_bg_alpha,
        "topic_style":         _style_to_dict(template.topic_style),
        "question_style":      _style_to_dict(template.question_style),
        "answer_style":        _style_to_dict(template.answer_style),
        "repeat_style":        _style_to_dict(template.repeat_style),
    }
    path.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Geometrie-Berechnung ──────────────────────────────────────────────────────

@dataclass
class _Rect:
    x: float; y: float; w: float; h: float

    def to_fitz(self) -> fitz.Rect:
        return fitz.Rect(self.x, self.y, self.x + self.w, self.y + self.h)


def _compute_rects(t: CardTemplate) -> dict:
    """Berechnet alle Feldrects in pt aus den mm-Parametern."""
    W  = t.card_width_mm  * MM
    H  = t.card_height_mm * MM
    m  = t.margin_mm      * MM
    tw = t.topic_width_mm * MM

    topic    = _Rect(m,         m, tw,              H - 2*m)
    question = _Rect(m + tw + m, m, W - 3*m - tw,  H - 2*m)
    answer   = _Rect(m,         m, W - 2*m,         H - 2*m)

    return {"card_w": W, "card_h": H,
            "topic": topic, "question": question, "answer": answer}


# ── Haupt-Erzeugungsfunktion ──────────────────────────────────────────────────

def create_cards_pdf(
    load_result: LoadResult,
    template: CardTemplate,
    output_path: Path,
    pictures_dir: Path,
) -> dict:
    if not load_result.ok:
        return {"ok": False, "error": "CSV hat Fehler."}

    rects = _compute_rects(template)
    doc   = fitz.open()
    current_level = None

    for card in load_result.cards:
        level_changed = card.level != current_level
        if level_changed:
            current_level = card.level
        _add_question_page(doc, card, template, rects, pictures_dir, level_changed)
        _add_answer_page(doc, card, template, rects, pictures_dir)

    doc.save(str(output_path))
    doc.close()
    return {"ok": True, "cards": len(load_result.cards)}


# ── Seiten aufbauen ───────────────────────────────────────────────────────────

def _resolve_image(bg: str, pictures_dir: Path) -> Optional[Path]:
    if not bg:
        return None
    p = Path(bg)
    if p.is_absolute() and p.exists():
        return p
    c = pictures_dir / bg
    return c if c.exists() else None


def _insert_bg(page: fitz.Page, bg: str, pics: Path, w: float, h: float, img_alpha: float = 1.0):
    img = _resolve_image(bg, pics)
    if img:
        page.insert_image(fitz.Rect(0, 0, w, h), filename=str(img))
        if img_alpha < 1.0:
            page.draw_rect(fitz.Rect(0, 0, w, h),
                           color=None, fill=(1, 1, 1),
                           fill_opacity=max(0.0, 1.0 - img_alpha))


def _add_question_page(doc, card: Card, t: CardTemplate,
                        rects: dict, pics: Path, level_changed: bool):
    W, H = rects["card_w"], rects["card_h"]
    page = doc.new_page(width=W, height=H)
    _insert_bg(page, t.front_bg, pics, W, H, t.front_bg_alpha)

    _render_rotated(page, card.thema,  rects["topic"],    t.topic_style,    t.line_spacing)
    _render_normal( page, card.frage,  rects["question"], t.question_style, t.line_spacing, pad=2.0 * MM)

    # Level-Marker: winzig, fast unsichtbar, unten links
    if level_changed and card.level:
        m = t.margin_mm * MM
        _render_level_marker(page, card.level, W, H, m)


def _add_answer_page(doc, card: Card, t: CardTemplate, rects: dict, pics: Path):
    W, H = rects["card_w"], rects["card_h"]
    page = doc.new_page(width=W, height=H)
    _insert_bg(page, t.back_bg, pics, W, H, t.back_bg_alpha)

    ans_rect = rects["answer"]
    gap_pt   = t.repeat_gap_mm * MM
    ans_ls   = t.answer_line_spacing
    rep_ls   = t.line_spacing

    field_bottom = ans_rect.y + ans_rect.h

    # Innerer Text-Bereich: 2 mm Innenabstand links, rechts, oben
    IPAD     = 2.0 * MM
    inner_x  = ans_rect.x + IPAD
    inner_w  = ans_rect.w - 2 * IPAD
    inner_y  = ans_rect.y + IPAD
    inner_h  = ans_rect.h - IPAD          # ab inner_y bis field_bottom

    # Wiederholung zuerst fitten (max 25% des inneren Feldes)
    rep_fs = _fit_size(card.frage, t.repeat_style, inner_w, inner_h * 0.25, rep_ls)
    rep_h  = _measure_text_height(card.frage, t.repeat_style, inner_w, rep_ls, rep_fs)

    # Antwort auf verbleibende Höhe fitten
    ans_max = inner_h - gap_pt - rep_h
    ans_fs  = _fit_size(card.antwort, t.answer_style, inner_w, max(ans_max, MIN_FONT_SIZE), ans_ls)
    ans_h   = _measure_text_height(card.antwort, t.answer_style, inner_w, ans_ls, ans_fs)

    # Trailing-Zeilenabstand abziehen → visuelle Höhe für Positionierung
    visual_ans_h = ans_h - ans_fs * (ans_ls - 1.0)
    visual_rep_h = rep_h - rep_fs * (rep_ls - 1.0)

    total = visual_ans_h + gap_pt + visual_rep_h
    y0    = inner_y + max(0.0, (inner_h - total) / 2)

    rep_top = y0 + visual_ans_h + gap_pt
    # Hintergrund: voller ans_rect, Wiederholung überlagert unten
    _draw_field_bg(page, fitz.Rect(ans_rect.x, ans_rect.y, ans_rect.x + ans_rect.w, field_bottom), t.answer_style)
    _draw_field_bg(page, fitz.Rect(ans_rect.x, rep_top,    ans_rect.x + ans_rect.w, field_bottom), t.repeat_style)
    _render_in_rect(page, card.antwort,
                    fitz.Rect(inner_x, y0, inner_x + inner_w, field_bottom),
                    t.answer_style, ans_ls, ans_fs)
    _render_in_rect(page, card.frage,
                    fitz.Rect(inner_x, rep_top, inner_x + inner_w, field_bottom),
                    t.repeat_style, rep_ls, rep_fs)


# ── Text-Rendering ────────────────────────────────────────────────────────────

def _font_kw(style: TextStyle) -> dict:
    fp = style.font_path
    if fp and Path(fp).exists():
        # Eindeutiger Name pro Font-Datei – verhindert Alias-Konflikt wenn zwei
        # verschiedene TTFs auf derselben Seite beide "f0" nutzen würden.
        fname = "f" + format(hash(fp) & 0xFFFFFF, "x")
        return {"fontfile": fp, "fontname": fname}
    return {"fontname": style.font or "helv"}


_PROBE_H = 10000.0  # Höhe der Probe-Seite für Höhenmessung


def _measure_text_height(text: str, style: TextStyle, width: float,
                          line_spacing: float = 1.2,
                          size: Optional[float] = None) -> float:
    """
    Tatsächliche Höhe die insert_textbox verwendet – inkl. Zeilenabstand.
    Berechnung: probe_h - remaining (= was insert_textbox zurückgibt).
    Glyph-Bounding-Box unterschätzt bei lineheight > 1.
    """
    fs  = size if size is not None else style.size
    kw  = _font_kw(style)
    tmp = fitz.open()
    p   = tmp.new_page(width=max(width, 10), height=_PROBE_H)
    ret = p.insert_textbox(
        fitz.Rect(0, 0, max(width, 10), _PROBE_H), text,
        fontsize=fs, lineheight=line_spacing, align=1, **kw,
    )
    tmp.close()
    if ret < 0:
        return _PROBE_H  # sollte bei 10000pt nicht vorkommen
    return _PROBE_H - ret


def _fit_size(text: str, style: TextStyle, width: float, max_height: float,
              line_spacing: float) -> float:
    """
    Größte Schriftgröße bei der der Text in max_height passt.
    Nutzt insert_textbox-Rückgabewert (< 0 = Überlauf).
    """
    if not text:
        return style.size
    kw   = _font_kw(style)
    size = style.size
    tmp  = fitz.open()
    p    = tmp.new_page(width=max(width, 10), height=max(max_height, 10))
    rect = fitz.Rect(0, 0, max(width, 10), max(max_height, 10))
    while size > MIN_FONT_SIZE:
        ret = p.insert_textbox(rect, text, fontsize=size,
                               lineheight=line_spacing, align=1, **kw)
        if ret >= 0:
            break
        size -= 1.0
    tmp.close()
    return size


def _draw_field_bg(page: fitz.Page, rect: fitz.Rect, style: TextStyle):
    if style.bg_alpha > 0.0:
        page.draw_rect(rect, color=None, fill=style.bg_color, fill_opacity=style.bg_alpha)


def _render_in_rect(page: fitz.Page, text: str, rect: fitz.Rect,
                    style: TextStyle, line_spacing: float,
                    size: Optional[float] = None):
    """Rendert Text in rect mit Shadow falls konfiguriert."""
    if not text or rect.is_empty or rect.width < 1 or rect.height < 1:
        return
    fs = size if size is not None else style.size
    kw = _font_kw(style)
    has_shadow = style.shadow_offset[0] or style.shadow_offset[1]
    if has_shadow:
        dx, dy = style.shadow_offset
        page.insert_textbox(
            rect + (dx, dy, dx, dy), text,
            fontsize=fs, lineheight=line_spacing,
            color=style.shadow_color, align=1, **kw,
        )
    page.insert_textbox(rect, text,
                        fontsize=fs, lineheight=line_spacing,
                        color=style.color, align=1, **kw)


def _render_normal(page: fitz.Page, text: str, r: _Rect,
                   style: TextStyle, line_spacing: float, pad: float = 0.0):
    """Nicht-rotiert, vertikal + horizontal zentriert. pad = Innenabstand in pt."""
    if not text:
        return
    _draw_field_bg(page, fitz.Rect(r.x, r.y, r.x + r.w, r.y + r.h), style)
    iw = r.w - 2 * pad
    ih = r.h - 2 * pad
    ix = r.x + pad
    iy = r.y + pad
    fs = _fit_size(text, style, iw, ih, line_spacing)
    mh = _measure_text_height(text, style, iw, line_spacing, fs)
    # mh enthält Trailing-Zeilenabstand nach letzter Zeile (fs × (ls-1)); für
    # Zentrierung nur die visuelle Höhe verwenden, sonst sitzt Text zu hoch.
    visual_h = mh - fs * (line_spacing - 1.0)
    y0 = iy + max(0.0, (ih - visual_h) / 2)
    _render_in_rect(page, text, fitz.Rect(ix, y0, ix + iw, iy + ih), style, line_spacing, fs)


def _render_rotated(page: fitz.Page, text: str, r: _Rect,
                    style: TextStyle, line_spacing: float):
    """
    90°-rotiert (Thema-Feld). align=1 zentriert in physischer Y-Richtung (= vertikal nach
    Rotation). Zusätzlich: Text-Block wird in physischer X-Richtung zentriert mit 2mm Padding
    (= Abstand oben/unten am Streifenrand).
    """
    if not text:
        return
    kw  = _font_kw(style)
    PAD = 2.0 * MM

    # Schrift wie bisher auf volle Streifenbreite fitten – PAD nur durch x0-Versatz.
    fs       = _fit_size(text, style, r.h, r.w, line_spacing)
    mh       = _measure_text_height(text, style, r.h, line_spacing, fs)
    visual_h = mh - fs * (line_spacing - 1.0)
    # Zentrieren in physischer X: symmetrisch, mindestens PAD vom linken Rand.
    x0       = r.x + max(PAD, (r.w - visual_h) / 2)

    full_rect = fitz.Rect(r.x, r.y, r.x + r.w, r.y + r.h)
    text_rect = fitz.Rect(x0, r.y, r.x + r.w, r.y + r.h)
    _draw_field_bg(page, full_rect, style)

    has_shadow = style.shadow_offset[0] or style.shadow_offset[1]
    if has_shadow:
        dx, dy = style.shadow_offset
        sh = text_rect + (dx, dy, dx, dy)
        page.insert_textbox(sh, text, fontsize=fs, lineheight=line_spacing,
                            color=style.shadow_color, align=1, rotate=90, **kw)
    page.insert_textbox(text_rect, text, fontsize=fs, lineheight=line_spacing,
                        color=style.color, align=1, rotate=90, **kw)


def _render_level_marker(page: fitz.Page, level: str, W: float, H: float, m: float):
    """Winziger, fast unsichtbarer Level-Marker unten links. Format wie learncard_viewer."""
    text = f"lev: {level} | ="
    rect = fitz.Rect(m, H - m - 6, W / 3, H - m)
    page.insert_textbox(rect, text, fontsize=3.5,
                        color=(0.92, 0.92, 0.92), align=0, fontname="helv")

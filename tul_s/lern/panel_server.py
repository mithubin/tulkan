#!/usr/bin/env python3
"""
Lernkarten Panel – Flask-Server (Panel-Fork für tools_nuc/lern)
Start: python3 panel_server.py [--port 5007] [--no-browser]
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

import fitz
from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for, Response, make_response
from werkzeug.middleware.proxy_fix import ProxyFix

_tools_nuc = str(Path(__file__).resolve().parent.parent)
if _tools_nuc not in sys.path:
    sys.path.insert(0, _tools_nuc)
from tul_auth.db import init_db, get_conn
from tul_auth.auth import get_current_user, is_json_request, clear_token_cookie
from tul_auth.files_routes import make_files_blueprint

# ── Pfade ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
TECH_DIR = BASE_DIR / "_tech"

_SUBPATH    = os.environ.get('SUBPATH', '')
_DOCKER     = os.environ.get('DOCKER', '')
_FILES_ROOT = os.environ.get('FILES_ROOT', '/data/tul_files')

# Datenpfade: im Docker via DATA_DIR-Volume, lokal relativ zu BASE_DIR
_DATA = Path(os.environ.get('DATA_DIR', str(BASE_DIR)))

CARDS_PDF_DIR = _DATA / "karten-pdfs"
PRINT_PDF_DIR = _DATA / "druck_pdf"
PICTURES_DIR  = _DATA / "bilder"
CSV_DIR       = _DATA / "csv"
FONTS_DIR     = _DATA / "fonts"

TEMPLATES_DIR = TECH_DIR / "card_templates"
TMP_DIR       = TECH_DIR / "_tmp"
THEME_FILE    = _DATA / "panel_theme.json"  # legacy, kept for reference
_TOOL_NAME    = 'lern'

for d in (TMP_DIR, CARDS_PDF_DIR, PRINT_PDF_DIR):
    d.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(TECH_DIR))
from scripts.csv_loader import load_csv
from scripts.pdf_grid import build_print_pdf, PAPER_SIZES
from scripts.card_creator import load_template, save_template, create_cards_pdf, CardTemplate
from scripts.image_editor import edit_image
from scripts.viewer_config import (
    list_pdfs as vc_list_pdfs, detect_levels as vc_detect_levels,
    save_levels as vc_save_levels, save_session as vc_save_session,
    select_cards as vc_select_cards, pdf_hash as vc_pdf_hash,
)

app = Flask(
    __name__,
    template_folder=str(TECH_DIR / "templates"),
    static_folder=str(TECH_DIR / "static"),
    static_url_path="/static",
)

if _SUBPATH:
    app.config['APPLICATION_ROOT'] = _SUBPATH
    app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1)

init_db()
app.register_blueprint(make_files_blueprint(_TOOL_NAME, _FILES_ROOT))

@app.before_request
def _tul_auth():
    user = get_current_user()
    if not user:
        if is_json_request():
            return jsonify({'error': 'Not authenticated'}), 401
        return redirect('/?next=' + request.path)
    request.tul_user = user

@app.after_request
def _inject_tul_user(resp):
    if 'text/html' in resp.content_type:
        user = getattr(request, 'tul_user', None)
        snip = f'<script>window.TUL_USER={json.dumps(user)};</script>'
        body = resp.get_data(as_text=True)
        if '</head>' in body:
            resp.set_data(body.replace('</head>', snip + '\n</head>', 1))
    return resp

@app.context_processor
def _inject_base():
    return {'_base': _SUBPATH}


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def list_pdfs() -> list[dict]:
    if not CARDS_PDF_DIR.exists():
        return []
    result = []
    for p in sorted(CARDS_PDF_DIR.glob("*.pdf")):
        try:
            doc   = fitz.open(str(p))
            total = len(doc)
            levels = []
            for i in range(0, total, 2):
                for line in doc[i].get_text().splitlines():
                    if line.startswith("lev: ") and " | =" in line:
                        name = line[5:line.index(" | =")].strip()
                        if name not in levels:
                            levels.append(name)
            doc.close()
            result.append({"filename": p.name, "cards": total // 2, "levels": levels})
        except Exception:
            result.append({"filename": p.name, "cards": "?", "levels": []})
    return result


def list_templates() -> list[str]:
    return [p.stem for p in sorted(TEMPLATES_DIR.glob("*.json"))]


def list_images() -> list[str]:
    if not PICTURES_DIR.exists():
        return []
    exts = {".png", ".jpg", ".jpeg", ".webp", ".avif"}
    return sorted(p.name for p in PICTURES_DIR.iterdir() if p.suffix.lower() in exts)


def list_csvfiles() -> list[str]:
    if not CSV_DIR.exists():
        return []
    return sorted(p.name for p in CSV_DIR.glob("*.csv"))


def list_fonts() -> list[dict]:
    if not FONTS_DIR.exists():
        return []
    return sorted(
        [{"name": p.name, "path": str(p)} for p in FONTS_DIR.iterdir()
         if p.suffix.lower() == ".ttf"],
        key=lambda d: d["name"].lower(),
    )


def template_path(name: str) -> Path:
    return TEMPLATES_DIR / f"{name}.json"


def card_template_from_dict(data: dict) -> CardTemplate:
    tmp = TMP_DIR / "_browser_template.json"
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return load_template(tmp)


# ── HTML-Seiten ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for('page_viewer'))


@app.route("/print")
def print_page():
    selected = request.args.get("pdf", "")
    return render_template("print.html", active="print",
                           pdfs=list_pdfs(),
                           selected=selected,
                           paper_formats=list(PAPER_SIZES.keys()),
                           default_paper="A4 quer")


@app.route("/create")
def create_page():
    return render_template("create.html", active="create",
                           templates=list_templates() or ["default"],
                           images=list_images(),
                           fonts=list_fonts(),
                           csvfiles=list_csvfiles())


# ── API: Druck-PDF ────────────────────────────────────────────────────────────

@app.route("/api/print/build", methods=["POST"])
def api_print_build():
    d = request.get_json()
    pdf_name = d.get("pdf", "")
    source   = CARDS_PDF_DIR / pdf_name
    if not source.exists():
        return jsonify({"ok": False, "error": f"PDF nicht gefunden: {pdf_name}"})

    out_name = "druck_" + pdf_name
    out_path = PRINT_PDF_DIR / out_name

    r_start = d.get("range_start")
    r_end   = d.get("range_end")
    page_range = (int(r_start), int(r_end)) if r_start and r_end else None

    result = build_print_pdf(
        source_pdf=source,
        output_pdf=out_path,
        paper=d.get("paper", "A4 quer"),
        cols=int(d.get("cols", 3)),
        rows=int(d.get("rows", 5)),
        margin_pt=float(d.get("margin", 0)),
        gutter_pt=float(d.get("gutter", 2.83)),
        crop_marks=bool(d.get("crop_marks", True)),
        page_range=page_range,
    )
    if result["ok"]:
        result["filename"] = out_name
    return jsonify(result)


@app.route("/api/print/download/<filename>")
def api_print_download(filename: str):
    path = PRINT_PDF_DIR / filename
    if not path.exists():
        return "Nicht gefunden", 404
    return send_file(str(path), as_attachment=True, download_name=filename)


# ── API: CSV ──────────────────────────────────────────────────────────────────

def _preview_cards(result) -> list[dict]:
    return [
        {"level": c.level, "thema": c.thema,
         "frage": c.frage[:80], "antwort": c.antwort[:80]}
        for c in result.cards
    ]


@app.route("/api/csv/validate", methods=["POST"])
def api_csv_validate():
    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "errors": ["Keine Datei erhalten."]})
    tmp = TMP_DIR / "_active.csv"
    file.save(str(tmp))
    result = load_csv(tmp)
    return jsonify({"ok": result.ok, "cards": len(result.cards),
                    "levels": result.levels, "errors": result.errors,
                    "warnings": result.warnings, "preview": _preview_cards(result)})


@app.route("/api/csv/load-server", methods=["POST"])
def api_csv_load_server():
    name = (request.get_json() or {}).get("name", "")
    path = CSV_DIR / name
    if not path.exists() or path.suffix.lower() != ".csv":
        return jsonify({"ok": False, "errors": [f"Nicht gefunden: {name}"]})
    tmp = TMP_DIR / "_active.csv"
    shutil.copy2(str(path), str(tmp))
    result = load_csv(tmp)
    return jsonify({"ok": result.ok, "cards": len(result.cards),
                    "levels": result.levels, "errors": result.errors,
                    "warnings": result.warnings, "name": name,
                    "preview": _preview_cards(result)})


# ── API: Template ─────────────────────────────────────────────────────────────

@app.route("/api/template/load/<name>")
def api_template_load(name: str):
    path = template_path(name)
    if not path.exists():
        return jsonify({"error": "Nicht gefunden"}), 404
    return jsonify(json.loads(path.read_text(encoding="utf-8")))


@app.route("/api/template/save/<name>", methods=["POST"])
def api_template_save(name: str):
    try:
        data = request.get_json()
        path = template_path(name)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── API: Vorschau ─────────────────────────────────────────────────────────────

@app.route("/api/print/preview", methods=["POST"])
def api_print_preview():
    """Rendert das erste Druckblatt (Vorderseiten) als PNG – für die Live-Vorschau."""
    d        = request.get_json() or {}
    pdf_name = d.get("pdf", "")
    source   = CARDS_PDF_DIR / pdf_name
    if not source.exists():
        return jsonify({"ok": False, "error": f"PDF nicht gefunden: {pdf_name}"})
    if d.get("paper", "A4 quer") not in PAPER_SIZES:
        return jsonify({"ok": False, "error": "Unbekanntes Papierformat"})

    paper_w, paper_h = PAPER_SIZES[d.get("paper", "A4 quer")]
    cols      = max(1, int(d.get("cols", 3)))
    rows      = max(1, int(d.get("rows", 5)))
    MM        = 2.8346
    margin_pt = float(d.get("margin_mm", 0)) * MM
    gutter_pt = float(d.get("gutter",    2.83))

    try:
        src        = fitz.open(str(source))
        card_ratio = src[0].rect.width / src[0].rect.height
        avail_w    = paper_w - 2 * margin_pt
        avail_h    = paper_h - 2 * margin_pt
        cell_h     = min(
            (avail_w - (cols - 1) * gutter_pt) / (cols * card_ratio),
            (avail_h - (rows - 1) * gutter_pt) / rows,
        )
        cell_w  = cell_h * card_ratio
        off_x   = margin_pt + (avail_w - cols * cell_w - (cols - 1) * gutter_pt) / 2
        off_y   = margin_pt + (avail_h - rows * cell_h - (rows - 1) * gutter_pt) / 2

        out  = fitz.open()
        out.new_page(width=paper_w, height=paper_h)
        page = out[0]
        for slot, qi in enumerate(list(range(0, len(src), 2))[: cols * rows]):
            col = slot % cols
            row = slot // cols
            x0  = off_x + col * (cell_w + gutter_pt)
            y0  = off_y + row * (cell_h + gutter_pt)
            page.show_pdf_page(fitz.Rect(x0, y0, x0 + cell_w, y0 + cell_h),
                               src, qi, keep_proportion=True)

        pix  = page.get_pixmap(dpi=80)
        data = base64.b64encode(pix.tobytes("png")).decode()
        src.close(); out.close()
        return jsonify({"ok": True, "image": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/preview/card", methods=["POST"])
def api_preview_card():
    try:
        tmpl = card_template_from_dict(request.get_json())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

    from scripts.csv_loader import Card
    from scripts.card_creator import _add_question_page, _add_answer_page, _compute_rects

    sample = Card(level="Basics", thema="Thema",
                  frage="Beispiel-Frage: Was ist das hier genau?",
                  antwort="Das ist die Antwort, etwas ausführlicher formuliert.")
    rects = _compute_rects(tmpl)
    doc   = fitz.open()
    _add_question_page(doc, sample, tmpl, rects, PICTURES_DIR, True)
    _add_answer_page(doc, sample, tmpl, rects, PICTURES_DIR)

    def to_b64(idx):
        pix = doc[idx].get_pixmap(dpi=96)
        return base64.b64encode(pix.tobytes("png")).decode()

    result = {"ok": True, "front": to_b64(0), "back": to_b64(1)}
    doc.close()
    return jsonify(result)


# ── API: PDF erstellen ────────────────────────────────────────────────────────

@app.route("/api/create/pdf", methods=["POST"])
def api_create_pdf():
    tmpl_json = request.form.get("template", "{}")
    out_name  = request.form.get("output_name", "karten_neu.pdf")
    if not out_name.endswith(".pdf"):
        out_name += ".pdf"

    file            = request.files.get("file")
    csv_server_name = request.form.get("csv_server_name", "")
    tmp_csv         = TMP_DIR / "_active.csv"
    if file and file.filename:
        file.save(str(tmp_csv))
    elif csv_server_name:
        src = CSV_DIR / csv_server_name
        if not src.exists() or src.suffix.lower() != ".csv":
            return jsonify({"ok": False, "error": f"CSV nicht gefunden: {csv_server_name}"})
        shutil.copy2(str(src), str(tmp_csv))
    elif not tmp_csv.exists():
        return jsonify({"ok": False, "error": "Keine CSV geladen."})

    load_result = load_csv(tmp_csv)
    if not load_result.ok:
        return jsonify({"ok": False, "error": "; ".join(load_result.errors)})

    try:
        tmpl = card_template_from_dict(json.loads(tmpl_json))
    except Exception as e:
        return jsonify({"ok": False, "error": f"Template-Fehler: {e}"})

    out_path = CARDS_PDF_DIR / out_name
    try:
        result = create_cards_pdf(load_result, tmpl, out_path, PICTURES_DIR)
    except Exception as e:
        return jsonify({"ok": False, "error": f"PDF-Fehler: {e}"})
    if result["ok"]:
        result["filename"] = out_name
    return jsonify(result)


@app.route("/api/create/download/<filename>")
def api_create_download(filename: str):
    path = CARDS_PDF_DIR / filename
    if not path.exists():
        return "Nicht gefunden", 404
    return send_file(str(path), as_attachment=True, download_name=filename)


@app.route("/api/cards/download/<filename>")
def api_cards_download(filename: str):
    path = CARDS_PDF_DIR / filename
    if not path.exists():
        return "Nicht gefunden", 404
    return send_file(str(path), as_attachment=True, download_name=filename)


# ── API: Theme ───────────────────────────────────────────────────────────────

@app.route("/api/theme", methods=["GET"])
def api_theme_load():
    uid = request.tul_user['id']
    with get_conn() as conn:
        row = conn.execute(
            'SELECT settings FROM user_themes WHERE user_id=? AND tool=?', (uid, _TOOL_NAME)
        ).fetchone()
    if row:
        try:
            return jsonify({"ok": True, **json.loads(row['settings'])})
        except Exception:
            pass
    return jsonify({"ok": False})


@app.route("/api/theme", methods=["POST"])
def api_theme_save():
    uid = request.tul_user['id']
    d = request.get_json() or {}
    data = json.dumps(d)
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO user_themes(user_id,tool,settings) VALUES(?,?,?) '
            'ON CONFLICT(user_id,tool) DO UPDATE SET settings=excluded.settings',
            (uid, _TOOL_NAME, data)
        )
    return jsonify({"ok": True})


@app.route("/theme", methods=["GET"])
def theme_get():
    uid = request.tul_user['id']
    with get_conn() as conn:
        row = conn.execute(
            'SELECT settings FROM user_themes WHERE user_id=? AND tool=?', (uid, _TOOL_NAME)
        ).fetchone()
    return (Response(row['settings'], mimetype='application/json') if row else ('', 404))

@app.route("/theme", methods=["POST"])
def theme_post():
    uid = request.tul_user['id']
    data = request.get_data(as_text=True)
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO user_themes(user_id,tool,settings) VALUES(?,?,?) '
            'ON CONFLICT(user_id,tool) DO UPDATE SET settings=excluded.settings',
            (uid, _TOOL_NAME, data)
        )
    return ('', 204)


# ── API: Bildbearbeitung ──────────────────────────────────────────────────────


@app.route("/api/pictures/list")
def api_pictures_list():
    return jsonify({"ok": True, "images": list_images()})



@app.route("/api/pictures/serve/<path:filename>")
def api_pictures_serve(filename: str):
    path = PICTURES_DIR / filename
    if not path.exists():
        return "Nicht gefunden", 404
    return send_file(str(path))


@app.route("/api/pictures/edit", methods=["POST"])
def api_pictures_edit():
    d        = request.get_json()
    src_name = d.get("filename", "")
    save_as  = d.get("save_as", "").strip()
    if not src_name or not save_as:
        return jsonify({"ok": False, "error": "Dateiname fehlt"})

    src_path = PICTURES_DIR / src_name
    dst_path = PICTURES_DIR / save_as
    if not src_path.exists():
        return jsonify({"ok": False, "error": f"Bild nicht gefunden: {src_name}"})

    luts     = d.get("luts", {})
    identity = list(range(256))
    result   = edit_image(
        src_path=src_path, dst_path=dst_path,
        lut_r=luts.get("r", identity),
        lut_g=luts.get("g", identity),
        lut_b=luts.get("b", identity),
        saturation=float(d.get("saturation", 1.0)),
        crop_offset_x=float(d.get("crop_offset_x", 0.0)),
        crop_offset_y=float(d.get("crop_offset_y", 0.0)),
        crop_scale=float(d.get("crop_scale", 1.0)),
        card_ratio=float(d.get("card_ratio", 2.25)),
        card_width_mm=float(d.get("card_w_mm", 180.0)),
        card_height_mm=float(d.get("card_h_mm", 80.0)),
    )
    if result["ok"]:
        result["saved_as"] = save_as
    return jsonify(result)


# ── Viewer: Seiten ────────────────────────────────────────────────────────────

@app.route("/viewer")
def page_viewer():
    return render_template("viewer.html", active="viewer")


@app.route("/viewer/play")
def page_viewer_play():
    return render_template("viewer_play.html")


# ── Viewer: API ───────────────────────────────────────────────────────────────

@app.route("/api/viewer/pdfs")
def api_viewer_pdfs():
    return jsonify({"ok": True, "pdfs": vc_list_pdfs(CARDS_PDF_DIR)})


@app.route("/api/viewer/detect-levels", methods=["POST"])
def api_viewer_detect_levels():
    pdf_name = request.get_json().get("pdf", "")
    pdf_path = CARDS_PDF_DIR / pdf_name
    if not pdf_path.exists():
        return jsonify({"ok": False, "error": "PDF nicht gefunden"})
    levels = vc_detect_levels(pdf_path)
    return jsonify({"ok": True, "levels": levels})


@app.route("/api/viewer/save-levels", methods=["POST"])
def api_viewer_save_levels():
    d = request.get_json()
    vc_save_levels(CARDS_PDF_DIR, d["hash"], d.get("levels"))
    return jsonify({"ok": True})


@app.route("/api/viewer/session", methods=["POST"])
def api_viewer_session():
    d = request.get_json()
    pdf_path = CARDS_PDF_DIR / d.get("pdf", "")
    if not pdf_path.exists():
        return jsonify({"ok": False, "error": "PDF nicht gefunden"})
    h = vc_pdf_hash(pdf_path)
    with fitz.open(str(pdf_path)) as doc:
        page_count = doc.page_count
    # Aktuelle Level aus Config holen
    from scripts.viewer_config import _load as vc_load
    stored = vc_load(CARDS_PDF_DIR)["pdfs"].get(h, {})
    levels = stored.get("levels")
    level_filter = d.get("level_filter", [])
    randomize = bool(d.get("randomize", False))
    cards = vc_select_cards(page_count, levels, level_filter, randomize)
    vc_save_session(CARDS_PDF_DIR, h, pdf_path.name, pdf_path.stat().st_size,
                    levels, {"level_filter": level_filter, "randomize": randomize})
    return jsonify({"ok": True, "cards": cards, "page_count": page_count, "levels": levels})


@app.route("/api/viewer/page/<path:pdf_name>/<int:page_num>")
def api_viewer_page(pdf_name: str, page_num: int):
    from flask import Response
    pdf_path = CARDS_PDF_DIR / pdf_name
    if not pdf_path.exists():
        return "Nicht gefunden", 404
    with fitz.open(str(pdf_path)) as doc:
        if page_num < 1 or page_num > doc.page_count:
            return "Ungültige Seite", 400
        pix = doc[page_num - 1].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        img_bytes = pix.tobytes("png")
    resp = Response(img_bytes, mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/api/viewer/score", methods=["POST"])
def api_viewer_score():
    from datetime import datetime
    d      = request.get_json()
    pdf    = d.get("pdf", "unbekannt")
    name   = (d.get("name") or "Anonym").strip() or "Anonym"
    rounds = d.get("rounds", [])
    scores_dir = CARDS_PDF_DIR / "scores"
    scores_dir.mkdir(exist_ok=True)
    safe = "".join(c for c in name if c.isalnum() or c in " -_").strip().replace(" ", "_") or "Anonym"
    log  = scores_dir / f"{Path(pdf).stem}_{datetime.now():%Y-%m-%d_%H-%M}_{safe}.log"
    with open(log, "w", encoding="utf-8") as f:
        f.write(f"=== {pdf} ===\n")
        f.write(f"Datum: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"Name: {name}\n\n")
        for i, r in enumerate(rounds, 1):
            lvl = ", ".join(r.get("level_filter", [])) or "Alle Level"
            mod = "Zufällig" if r.get("randomize") else "Reihenfolge"
            f.write(f"Runde {i} (Level: {lvl}, Modus: {mod})\n")
            total = r.get("richtig", 0) + r.get("falsch", 0) + r.get("neutral", 0)
            if total:
                for key in ("richtig", "falsch", "neutral"):
                    v = r.get(key, 0)
                    f.write(f"  {key.capitalize()}: {v}/{total} ({v*100//total}%)\n")
            dur = int(r.get("duration", 0))
            f.write(f"  Dauer: {dur//60}m {dur%60}s\n\n")
    return jsonify({"ok": True, "file": log.name})


@app.route("/api/viewer/scores")
def api_viewer_scores():
    scores_dir = CARDS_PDF_DIR / "scores"
    if not scores_dir.exists():
        return jsonify({"ok": True, "scores": []})
    files = sorted(scores_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsonify({"ok": True, "scores": [
        {"name": f.name, "mtime": f.stat().st_mtime} for f in files[:30]
    ]})


@app.route("/api/viewer/score-read/<path:filename>")
def api_viewer_score_read(filename: str):
    p = CARDS_PDF_DIR / "scores" / filename
    if not p.exists() or p.suffix != ".log":
        return "Nicht gefunden", 404
    return p.read_text("utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}


# ── Tkinter-Viewer ───────────────────────────────────────────────────────────

@app.route("/api/viewer/tkinter-open", methods=["POST"])
def api_viewer_tkinter_open():
    if _DOCKER:
        return jsonify({"ok": False, "error": "Tkinter-Viewer nicht verfügbar im Docker-Container."})
    d        = request.get_json() or {}
    pdf_name = d.get("pdf", "")
    dpi      = max(50, min(600, int(d.get("dpi", 150))))
    mode     = d.get("mode", "manual")
    timing   = d.get("timing", "10,16,12,20")
    randomize = bool(d.get("randomize", False))
    level_filter = d.get("level_filter", [])
    fullscreen   = bool(d.get("fullscreen", True))

    pdf_path = CARDS_PDF_DIR / pdf_name
    if not pdf_path.exists():
        return jsonify({"ok": False, "error": f"PDF nicht gefunden: {pdf_name}"})

    doc = fitz.open(str(pdf_path))
    page_count = doc.page_count
    doc.close()

    levels_data = vc_detect_levels(pdf_path) or []
    cards = vc_select_cards(page_count, levels_data, level_filter, randomize)

    viewer = TECH_DIR / "scripts" / "tkinter_viewer.py"
    cmd = [
        sys.executable, str(viewer),
        "--pdf",        str(pdf_path),
        "--dpi",        str(dpi),
        "--cards",      json.dumps(cards),
        "--levels",     json.dumps(levels_data),
        "--total",      str(page_count // 2),
        "--mode",       "autopilot" if mode == "auto" else "manual",
        "--timing",     timing,
    ]
    if fullscreen:
        cmd.append("--fullscreen")
    subprocess.Popen(cmd, stdout=None, stderr=None)
    return jsonify({"ok": True})


@app.route('/logout', methods=['POST'])
def logout():
    return clear_token_cookie(make_response(jsonify({'ok': True})))


# ── Start ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get('PORT', 5007)))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://localhost:{args.port}"
    print(f"Lernkarten Panel → {url}")
    if not args.no_browser:
        webbrowser.open(url)
    app.run(host='0.0.0.0', port=args.port, debug=False)

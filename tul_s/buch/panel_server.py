#!/usr/bin/env python3
"""
buch – PDF-Seiten-Editor: Tiles mit Vorschau, Reorder, Rotate, Merge
Quellen: bild-DV (read-only) + eigene Uploads via tul-files DV-Modal
"""
import io
import json
import os
from pathlib import Path

from flask import Flask, Response, abort, jsonify, make_response, request, redirect

import sys as _sys
_tools_nuc = str(Path(__file__).resolve().parent.parent)
if _tools_nuc not in _sys.path:
    _sys.path.insert(0, _tools_nuc)
from tul_auth.db import init_db, get_conn, uid, now
from tul_auth.auth import get_current_user, is_json_request, clear_token_cookie
from tul_auth.files_routes import make_files_blueprint

app = Flask(__name__)
_HERE = Path(__file__).parent

_SUBPATH     = os.environ.get('SUBPATH', '')
_TOOL_NAME   = 'buch'
_FILES_ROOT  = os.environ.get('FILES_ROOT', '/data/tul_files')
_BILD_DIR    = Path(os.environ.get('BILD_FILES_DIR', '/data/bild_files'))

init_db()
app.register_blueprint(make_files_blueprint(_TOOL_NAME, _FILES_ROOT))

# ── Thumbnail-Cache ───────────────────────────────────────────────────────────
_thumb_cache: dict = {}   # (str(path), page_n, size, rotate) → bytes

def _render_thumb(path: Path, page_n: int, size: int, rotate: int = 0) -> bytes:
    key = (str(path), page_n, size, rotate)
    if key not in _thumb_cache:
        import fitz
        doc  = fitz.open(str(path))
        if page_n >= doc.page_count:
            doc.close()
            raise IndexError(f'page {page_n} out of range')
        page = doc[page_n]
        w, h = page.rect.width, page.rect.height
        if rotate in (90, 270):
            w, h = h, w
        scale = size / max(w, h)
        mat   = fitz.Matrix(scale, scale).prerotate(-rotate)
        pix   = page.get_pixmap(matrix=mat, alpha=False)
        data  = pix.tobytes('jpeg', jpg_quality=82)
        doc.close()
        if len(_thumb_cache) > 800:
            _thumb_cache.pop(next(iter(_thumb_cache)))
        _thumb_cache[key] = data
    return _thumb_cache[key]


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────
def _safe_name(name: str) -> str:
    return Path(name).name

def _safe_rel(base: Path, rel: str) -> Path | None:
    try:
        p = (base / rel).resolve()
        if base.resolve() in p.parents or p == base.resolve():
            return p
        return None
    except Exception:
        return None

def _pdf_info_bild(p: Path) -> dict:
    stem   = p.stem
    parts  = stem.split('_', 1)
    att_id = parts[0] if len(parts) > 1 else None
    display = (parts[1] if len(parts) > 1 else stem) + p.suffix

    file_id, listed = None, 1
    if att_id:
        with get_conn() as conn:
            row = conn.execute(
                'SELECT id, listed FROM files WHERE id=? AND tool=?',
                (att_id, 'bild')
            ).fetchone()
        if row:
            file_id = row['id']
            listed  = 1 if row['listed'] is None else int(row['listed'])

    return {
        'rel':     str(p.relative_to(_BILD_DIR)),
        'display': display,
        'size':    p.stat().st_size,
        'file_id': file_id,
        'listed':  listed,
    }

def _resolve_own_path(file_id: str, user_id: str) -> Path | None:
    with get_conn() as conn:
        row = conn.execute(
            'SELECT path FROM files WHERE id=? AND user_id=? AND tool=?',
            (file_id, user_id, _TOOL_NAME)
        ).fetchone()
    return Path(row['path']) if row else None


# ── Auth ──────────────────────────────────────────────────────────────────────
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


# ── Panel ─────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    html = (_HERE / 'panel.html').read_text(encoding='utf-8')
    if _SUBPATH:
        html = html.replace(
            "<script>\nconst _B = window._B||'';",
            f"<script>\nconst _B = '{_SUBPATH}';",
        )
    uid = request.tul_user['id']
    with get_conn() as conn:
        row = conn.execute(
            'SELECT settings FROM user_themes WHERE user_id=? AND tool=?',
            (uid, _TOOL_NAME)
        ).fetchone()
    if row:
        try:
            theme    = json.loads(row['settings'])
            css_vars = {k: v for k, v in theme.items() if k.startswith('--')}
            if css_vars:
                style = ':root{' + ''.join(f'{k}:{v};' for k, v in css_vars.items()) + '}'
                html  = html.replace('</head>', f'<style>{style}</style>\n</head>', 1)
        except Exception:
            pass
    return Response(html, mimetype='text/html', headers={'Cache-Control': 'no-store'})


# ── Theme ─────────────────────────────────────────────────────────────────────
@app.route('/theme')
def theme_get():
    uid = request.tul_user['id']
    with get_conn() as conn:
        row = conn.execute(
            'SELECT settings FROM user_themes WHERE user_id=? AND tool=?',
            (uid, _TOOL_NAME)
        ).fetchone()
    return (Response(row['settings'], mimetype='application/json') if row else ('', 404))

@app.route('/theme', methods=['POST'])
def theme_post():
    uid  = request.tul_user['id']
    data = request.get_data(as_text=True)
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO user_themes(user_id,tool,settings) VALUES(?,?,?) '
            'ON CONFLICT(user_id,tool) DO UPDATE SET settings=excluded.settings',
            (uid, _TOOL_NAME, data)
        )
    return ('', 204)


# ── bild-listed Toggle ───────────────────────────────────────────────────────
@app.route('/api/bild-listed', methods=['PATCH'])
def api_bild_listed():
    data    = request.get_json(silent=True) or {}
    file_id = data.get('file_id')
    listed  = int(bool(data.get('listed', True)))
    if not file_id:
        return jsonify({'error': 'file_id fehlt'}), 400
    with get_conn() as conn:
        conn.execute(
            'UPDATE files SET listed=? WHERE id=? AND tool=?',
            (listed, file_id, 'bild')
        )
    return ('', 204)


# ── Quellen-Liste ─────────────────────────────────────────────────────────────
@app.route('/api/bild-files')
def api_bild_files():
    if not _BILD_DIR.exists():
        return jsonify([])
    files = [_pdf_info_bild(p)
             for p in sorted(_BILD_DIR.rglob('*.pdf'))
             if p.is_file()]
    return jsonify(files)


# ── Thumbnail ─────────────────────────────────────────────────────────────────
@app.route('/thumb')
def thumb():
    source  = request.args.get('source', '')
    page_n  = max(0, int(request.args.get('page', 0)))
    size    = max(60, min(400, int(request.args.get('size', 240))))
    rotate  = int(request.args.get('rotate', 0)) % 360
    user_id = request.tul_user['id']

    if source == 'bild':
        path = _safe_rel(_BILD_DIR, request.args.get('path', ''))
        if not path or not path.is_file():
            abort(404)
    elif source == 'own':
        path = _resolve_own_path(request.args.get('id', ''), user_id)
        if not path or not path.is_file():
            abort(404)
    else:
        abort(400)

    try:
        data = _render_thumb(path, page_n, size, rotate)
    except Exception:
        abort(404)
    return Response(data, mimetype='image/jpeg',
                    headers={'Cache-Control': 'max-age=3600, private'})


# ── Import: alle Seiten eines PDFs laden ─────────────────────────────────────
@app.route('/api/import')
def api_import():
    source  = request.args.get('source', '')
    user_id = request.tul_user['id']

    if source == 'bild':
        rel  = request.args.get('path', '')
        path = _safe_rel(_BILD_DIR, rel)
        if not path or not path.is_file():
            return jsonify({'error': 'Nicht gefunden'}), 404
        ref = rel
    elif source == 'own':
        fid  = request.args.get('id', '')
        path = _resolve_own_path(fid, user_id)
        if not path or not path.is_file():
            return jsonify({'error': 'Nicht gefunden'}), 404
        ref = fid
    else:
        return jsonify({'error': 'Ungültige Quelle'}), 400

    try:
        import fitz
        doc   = fitz.open(str(path))
        pages = [{'page': i, 'w': round(doc[i].rect.width), 'h': round(doc[i].rect.height),
                  'source': source, 'ref': ref}
                 for i in range(doc.page_count)]
        doc.close()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'pages': pages})


# ── Merge ─────────────────────────────────────────────────────────────────────
@app.route('/merge', methods=['POST'])
def merge():
    data    = request.get_json(silent=True) or {}
    title   = (data.get('title') or 'buch').strip()
    pages   = data.get('pages') or []
    user_id = request.tul_user['id']

    if not pages:
        return jsonify({'error': 'Keine Seiten'}), 400

    try:
        import fitz
    except ImportError:
        return jsonify({'error': 'PyMuPDF nicht verfügbar'}), 500

    merged = fitz.open()
    for pg in pages:
        source = pg.get('source')
        ref    = pg.get('ref', '')
        page_n = int(pg.get('page', 0))
        rotate = int(pg.get('rotate', 0)) % 360

        if source == 'blank':
            merged.new_page(width=595, height=842)
            continue

        if source == 'bild':
            path = _safe_rel(_BILD_DIR, ref)
            if not path or not path.is_file():
                continue
        elif source == 'own':
            path = _resolve_own_path(ref, user_id)
            if not path or not path.is_file():
                continue
        else:
            continue

        try:
            doc = fitz.open(str(path))
            if page_n < doc.page_count:
                rot = rotate if rotate in (0, 90, 180, 270) else -1
                merged.insert_pdf(doc, from_page=page_n, to_page=page_n,
                                  rotate=rot if rot != 0 else -1)
            doc.close()
        except Exception:
            continue

    if merged.page_count == 0:
        merged.close()
        return jsonify({'error': 'Keine Seiten gemergt'}), 400

    buf = io.BytesIO()
    merged.save(buf)
    merged.close()
    safe = ''.join(c for c in title if c.isalnum() or c in ' -_äöüÄÖÜß').strip() or 'buch'
    data = buf.getvalue()

    # DV-Ausgabe speichern
    try:
        file_id = uid()
        out_dir = Path(_FILES_ROOT) / 'output' / user_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f'{file_id}_{safe}.pdf'
        out_path.write_bytes(data)
        with get_conn() as conn:
            conn.execute(
                'INSERT OR IGNORE INTO files '
                '(id, user_id, tool, filename, path, size, mime, category, file_type, retention, listed, created_at) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (file_id, user_id, _TOOL_NAME, safe + '.pdf', str(out_path),
                 len(data), 'application/pdf', 'output', None, '1mo', 1, now())
            )
    except Exception:
        pass  # Speicherfehler → trotzdem Download

    return Response(data, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{safe}.pdf"'})


# ── Logout ───────────────────────────────────────────────────────────────────
@app.route('/logout', methods=['POST'])
def logout():
    return clear_token_cookie(make_response(jsonify({'ok': True})))


# ── Start ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', 5011)))
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not args.no_browser:
        import webbrowser
        webbrowser.open(f'http://localhost:{args.port}')
    app.run(host='0.0.0.0', port=args.port, threaded=True)

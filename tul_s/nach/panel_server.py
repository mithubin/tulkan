#!/usr/bin/env python3
"""
nach – Nachschlagen-Archiv
Singles: .html direkt in _FILES_DIR
Sets:    .zip → Unterordner <stem>/; Einstieg via index_*.html
Serve:   /files/<path> — injiziert ← nach Floating-Button in alle HTML-Seiten
"""
import json
import mimetypes
import os
import re
import shutil
import zipfile
from pathlib import Path

from flask import Flask, Response, jsonify, make_response, request, redirect

import sys as _sys
_tools_nuc = str(Path(__file__).resolve().parent.parent)
if _tools_nuc not in _sys.path:
    _sys.path.insert(0, _tools_nuc)
from tul_auth.db import init_db, get_conn
from tul_auth.auth import get_current_user, is_json_request, clear_token_cookie

app   = Flask(__name__)
_HERE = Path(__file__).parent

_SUBPATH   = os.environ.get('SUBPATH', '')
_TOOL_NAME = 'nach'
_FILES_DIR = Path(os.environ.get('FILES_DIR', '/mnt/tul/nach/files'))
_FILES_DIR.mkdir(parents=True, exist_ok=True)

_HTML_EXT   = {'.html', '.htm'}
_ASSET_EXT  = {'.html', '.htm', '.css', '.js',
               '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
               '.woff', '.woff2', '.ico'}
_RE_TITLE   = re.compile(r'<title[^>]*>(.*?)</title>', re.IGNORECASE | re.DOTALL)

init_db()


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _extract_title(path: Path) -> str:
    try:
        m = _RE_TITLE.search(path.read_text(encoding='utf-8', errors='replace')[:4096])
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return path.stem


def _safe_name(name: str) -> str:
    return Path(name).name


def _inject_back(content: str) -> str:
    btn = (
        f'<a href="{_SUBPATH}/" '
        'style="position:fixed;bottom:1.2rem;right:1.2rem;z-index:9999;'
        'background:rgba(15,15,30,.92);backdrop-filter:blur(6px);'
        'color:#8899cc;border:1px solid #2a2a4a;padding:6px 16px;'
        'border-radius:20px;text-decoration:none;'
        'font:600 12px/22px sans-serif;'
        'box-shadow:0 2px 10px rgba(0,0,0,.5)">← nach</a>'
    )
    if '</body>' in content:
        return content.replace('</body>', btn + '\n</body>', 1)
    return content + btn


def _scan_items():
    items = []

    # Singles: HTML-Dateien direkt in _FILES_DIR
    for p in sorted(_FILES_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in _HTML_EXT:
            items.append({
                'type':       'single',
                'name':       p.name,
                'title':      _extract_title(p),
                'entry':      p.name,
                'page_count': 1,
                'size':       p.stat().st_size,
            })

    # Sets: Unterordner mit mind. einer HTML-Datei
    for d in sorted(_FILES_DIR.iterdir()):
        if not d.is_dir():
            continue
        html_files = sorted(f for f in d.iterdir() if f.suffix.lower() in _HTML_EXT)
        if not html_files:
            continue
        index_file = next(
            (f for f in html_files if f.name.lower().startswith('index_')),
            html_files[0]
        )
        stem = index_file.stem
        title = stem[len('index_'):] if stem.lower().startswith('index_') else d.name
        total_size = sum(f.stat().st_size for f in d.rglob('*') if f.is_file())
        items.append({
            'type':       'set',
            'name':       d.name,
            'title':      title,
            'entry':      d.name + '/' + index_file.name,
            'page_count': len(html_files),
            'size':       total_size,
        })

    return items


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


# ── Panel-Index ───────────────────────────────────────────────────────────────

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
            theme = json.loads(row['settings'])
            css_vars = {k: v for k, v in theme.items() if k.startswith('--')}
            if css_vars:
                style = ':root{' + ''.join(f'{k}:{v};' for k, v in css_vars.items()) + '}'
                html = html.replace('</head>', f'<style>{style}</style>\n</head>', 1)
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
    uid = request.tul_user['id']
    data = request.get_data(as_text=True)
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO user_themes(user_id,tool,settings) VALUES(?,?,?) '
            'ON CONFLICT(user_id,tool) DO UPDATE SET settings=excluded.settings',
            (uid, _TOOL_NAME, data)
        )
    return ('', 204)


# ── Prefs (Tile-Reihenfolge + Paneltitel) ─────────────────────────────────────

@app.route('/prefs')
def prefs_get():
    uid = request.tul_user['id']
    with get_conn() as conn:
        row = conn.execute(
            'SELECT settings FROM user_themes WHERE user_id=? AND tool=?', (uid, 'nach-prefs')
        ).fetchone()
    return (Response(row['settings'], mimetype='application/json') if row else ('{}', 200))


@app.route('/prefs', methods=['POST'])
def prefs_post():
    uid = request.tul_user['id']
    data = request.get_data(as_text=True)
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO user_themes(user_id,tool,settings) VALUES(?,?,?) '
            'ON CONFLICT(user_id,tool) DO UPDATE SET settings=excluded.settings',
            (uid, 'nach-prefs', data)
        )
    return ('', 204)


# ── API: Liste ────────────────────────────────────────────────────────────────

@app.route('/api/list')
def api_list():
    return jsonify(_scan_items())


# ── Upload ────────────────────────────────────────────────────────────────────

@app.route('/upload', methods=['POST'])
def upload():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'Keine Datei'}), 400

    name = _safe_name(f.filename)
    ext  = Path(name).suffix.lower()

    if ext in _HTML_EXT:
        dest = _FILES_DIR / name
        f.save(str(dest))
        return jsonify({'ok': True, 'type': 'single', 'name': name})

    elif ext == '.zip':
        folder_name = Path(name).stem
        dest_dir    = _FILES_DIR / folder_name
        dest_dir.mkdir(exist_ok=True)
        try:
            with zipfile.ZipFile(f.stream) as zf:
                html_count = 0
                for member in zf.namelist():
                    mp  = Path(member)
                    mex = mp.suffix.lower()
                    if mex not in _ASSET_EXT:
                        continue
                    target = dest_dir / mp.name   # flat: Unterordner ignorieren
                    with zf.open(member) as src, open(target, 'wb') as dst:
                        dst.write(src.read())
                    if mex in _HTML_EXT:
                        html_count += 1
            if html_count == 0:
                shutil.rmtree(dest_dir, ignore_errors=True)
                return jsonify({'error': 'ZIP enthält keine HTML-Dateien'}), 400
        except zipfile.BadZipFile:
            shutil.rmtree(dest_dir, ignore_errors=True)
            return jsonify({'error': 'Ungültige ZIP-Datei'}), 400
        return jsonify({'ok': True, 'type': 'set', 'folder': folder_name, 'count': html_count})

    return jsonify({'error': 'Nur .html, .htm oder .zip erlaubt'}), 400


# ── Löschen ───────────────────────────────────────────────────────────────────

@app.route('/file/<name>', methods=['DELETE'])
def delete_single(name: str):
    path = _FILES_DIR / _safe_name(name)
    if not path.is_file() or path.suffix.lower() not in _HTML_EXT:
        return jsonify({'error': 'Nicht gefunden'}), 404
    path.unlink()
    return jsonify({'ok': True})


@app.route('/set/<name>', methods=['DELETE'])
def delete_set(name: str):
    path = _FILES_DIR / _safe_name(name)
    if not path.is_dir():
        return jsonify({'error': 'Nicht gefunden'}), 404
    shutil.rmtree(path)
    return jsonify({'ok': True})


# ── Umbenennen ────────────────────────────────────────────────────────────────

@app.route('/rename', methods=['PUT'])
def rename():
    data      = request.get_json(silent=True) or {}
    item_type = data.get('type')
    old       = _safe_name(data.get('old', '').strip())
    new       = _safe_name(data.get('new', '').strip())

    if not old or not new:
        return jsonify({'error': 'Fehlende Parameter'}), 400

    if item_type == 'single':
        old_path = _FILES_DIR / old
        new_path = _FILES_DIR / new
        if not old_path.is_file():
            return jsonify({'error': 'Datei nicht gefunden'}), 404
        if new_path.exists():
            return jsonify({'error': 'Name bereits vergeben'}), 409
        old_path.rename(new_path)

    elif item_type == 'set':
        # old = Ordnername, new = neuer Stem (der * in index_*.html)
        folder = _FILES_DIR / old
        if not folder.is_dir():
            return jsonify({'error': 'Set nicht gefunden'}), 404
        html_files = sorted(f for f in folder.iterdir() if f.suffix.lower() in _HTML_EXT)
        index_file = next(
            (f for f in html_files if f.name.lower().startswith('index_')),
            None
        )
        if index_file:
            new_index = folder / f'index_{new}.html'
            if new_index.exists() and new_index != index_file:
                return jsonify({'error': 'Name bereits vergeben'}), 409
            index_file.rename(new_index)

    else:
        return jsonify({'error': 'Unbekannter Typ'}), 400

    return jsonify({'ok': True})


# ── Logout ───────────────────────────────────────────────────────────────────

@app.route('/logout', methods=['POST'])
def logout():
    return clear_token_cookie(make_response(jsonify({'ok': True})))


# ── Serve ─────────────────────────────────────────────────────────────────────

@app.route('/files/<path:name>')
def serve_file(name: str):
    parts = Path(name).parts
    if any(p in ('..', '.') for p in parts):
        return 'Ungültiger Pfad', 400
    path = _FILES_DIR / name
    if not path.is_file():
        return 'Nicht gefunden', 404
    if path.suffix.lower() in _HTML_EXT:
        content = path.read_text(encoding='utf-8', errors='replace')
        return Response(_inject_back(content), mimetype='text/html')
    mime, _ = mimetypes.guess_type(str(path))
    return Response(path.read_bytes(), mimetype=mime or 'application/octet-stream')


# ── Start ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', 5009)))
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not args.no_browser:
        import webbrowser
        webbrowser.open(f'http://localhost:{args.port}')
    app.run(host='0.0.0.0', port=args.port, threaded=True)

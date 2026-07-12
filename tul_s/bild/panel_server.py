#!/usr/bin/env python3
"""
bild – Panel-Server
Serviert bildseiteerstellen_panel.htm unter /bild/ (oder lokal ohne Subpath).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, request, make_response

_HERE = Path(__file__).parent
_tools_nuc = str(Path(__file__).resolve().parent.parent)
if _tools_nuc not in sys.path:
    sys.path.insert(0, _tools_nuc)
from tul_auth.db import init_db, get_conn, uid as new_uid, now, retention_expires
from tul_auth.auth import get_current_user, is_json_request, clear_token_cookie
from tul_auth.files_routes import make_files_blueprint

_TOOL_NAME  = 'bild'
_FILES_ROOT = os.environ.get('FILES_ROOT', '/data/tul_files')
_JSPDF_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js'
_JSPDF_LOCAL = _HERE / 'static' / 'jspdf.umd.min.js'

app = Flask(__name__)
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


@app.route('/')
def index():
    html = (_HERE / 'bildseiteerstellen_panel.htm').read_text(encoding='utf-8')
    html = html.replace('content=""', 'content="/bild"', 1)
    if _JSPDF_LOCAL.exists():
        jspdf = _JSPDF_LOCAL.read_text(encoding='utf-8')
        html = html.replace(
            f'<script src="{_JSPDF_CDN}"></script>',
            f'<script>{jspdf}</script>',
        )
    # Gespeichertes Theme vorab als :root-Vars injizieren → kein Flash beim Laden
    uid = request.tul_user['id']
    with get_conn() as conn:
        row = conn.execute(
            'SELECT settings FROM user_themes WHERE user_id=? AND tool=?', (uid, _TOOL_NAME)
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


@app.route('/theme')
def theme_get():
    uid = request.tul_user['id']
    with get_conn() as conn:
        row = conn.execute(
            'SELECT settings FROM user_themes WHERE user_id=? AND tool=?', (uid, _TOOL_NAME)
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


@app.route('/autosave', methods=['GET'])
def autosave_get():
    uid = request.tul_user['id']
    with get_conn() as conn:
        row = conn.execute(
            "SELECT settings FROM user_themes WHERE user_id=? AND tool='bild-autosave'",
            (uid,)
        ).fetchone()
    return (Response(row['settings'], mimetype='application/json') if row else ('', 204))


@app.route('/autosave', methods=['POST'])
def autosave_post():
    uid = request.tul_user['id']
    data = request.get_data(as_text=True)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_themes(user_id,tool,settings) VALUES(?,?,?) "
            "ON CONFLICT(user_id,tool) DO UPDATE SET settings=excluded.settings",
            (uid, 'bild-autosave', data)
        )
    return ('', 204)


@app.route('/autosave', methods=['DELETE'])
def autosave_delete():
    uid = request.tul_user['id']
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM user_themes WHERE user_id=? AND tool='bild-autosave'",
            (uid,)
        )
    return ('', 204)


_OPT_PRESETS = {
    'screen':  ['-dPDFSETTINGS=/screen',  '-dColorImageResolution=72',  '-dGrayImageResolution=72',  '-dMonoImageResolution=72'],
    'ebook':   ['-dPDFSETTINGS=/ebook',   '-dColorImageResolution=150', '-dGrayImageResolution=150', '-dMonoImageResolution=150'],
    '200dpi':  ['-dPDFSETTINGS=/ebook',   '-dColorImageResolution=200', '-dGrayImageResolution=200', '-dMonoImageResolution=200'],
    'printer': ['-dPDFSETTINGS=/printer',  '-dColorImageResolution=300', '-dGrayImageResolution=300', '-dMonoImageResolution=300'],
}
_OPT_SUFFIX = {'screen': '_os', 'ebook': '_oe', '200dpi': '_o2', 'printer': '_op'}


@app.route('/optimize', methods=['POST'])
def optimize_pdf():
    f    = request.files.get('file')
    qual = request.form.get('quality', '200dpi')
    if not f:
        return jsonify({'error': 'Keine Datei'}), 400

    gs_params = _OPT_PRESETS.get(qual, _OPT_PRESETS['200dpi'])
    suffix    = _OPT_SUFFIX.get(qual, '_opt')
    user_id   = request.tul_user['id']
    stem      = Path(f.filename).stem if f.filename else 'layout'
    out_fn    = stem + suffix + '.pdf'

    dest_dir = Path(_FILES_ROOT) / 'output' / user_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    fid  = new_uid()
    dest = dest_dir / f'{fid}_{out_fn}'

    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        f.save(tmp.name)
        src = Path(tmp.name)

    try:
        cmd = ['gs', '-q', '-dNOPAUSE', '-dBATCH', '-dSAFER',
               '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.4',
               '-dAutoRotatePages=/None'] + gs_params + [
               f'-sOutputFile={dest}', str(src)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return jsonify({'error': (proc.stderr or 'gs-Fehler')[:300]}), 500

        size = dest.stat().st_size
        with get_conn() as conn:
            conn.execute(
                'INSERT INTO files(id,user_id,tool,filename,path,size,mime,'
                'category,file_type,retention,created_at,expires_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (fid, user_id, _TOOL_NAME, out_fn, str(dest), size,
                 'application/pdf', 'output', None, '1mo', now(), retention_expires('1mo'))
            )
        return jsonify({'ok': True, 'id': fid, 'filename': out_fn, 'size': size})

    except FileNotFoundError:
        dest.unlink(missing_ok=True)
        return jsonify({'error': 'Ghostscript nicht gefunden'}), 500
    except subprocess.TimeoutExpired:
        dest.unlink(missing_ok=True)
        return jsonify({'error': 'Timeout (>120s)'}), 504
    finally:
        src.unlink(missing_ok=True)


@app.route('/logout', methods=['POST'])
def logout():
    return clear_token_cookie(make_response(jsonify({'ok': True})))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', 5005)))
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()

    if not args.no_browser:
        import webbrowser
        webbrowser.open(f'http://localhost:{args.port}')

    app.run(host='0.0.0.0', port=args.port)

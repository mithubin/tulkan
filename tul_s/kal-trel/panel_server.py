#!/usr/bin/env python3
"""
kal-trel – Multi-Kanban Panel
Serviert panel.html unter /kal-trel/; Zustand als JSON-Blob in kb_state (SQLite).
"""
import json
import os
import sys
from pathlib import Path

from flask import Flask, Response, jsonify, make_response, redirect, request

_HERE = Path(__file__).parent
_tools_nuc = str(Path(__file__).resolve().parent.parent)
if _tools_nuc not in sys.path:
    sys.path.insert(0, _tools_nuc)

from tul_auth.db import init_db, get_conn
from tul_auth.auth import get_current_user, is_json_request, clear_token_cookie
from tul_auth.files_routes import make_files_blueprint

_TOOL_NAME  = 'kal-trel'
_SUBPATH    = os.environ.get('SUBPATH', '')
_FILES_ROOT = os.environ.get('FILES_ROOT', '/data/tul_files')

app = Flask(__name__)
init_db()

# kb_state Tabelle anlegen
with get_conn() as _conn:
    _conn.execute(
        'CREATE TABLE IF NOT EXISTS kb_state ('
        '  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,'
        '  state   TEXT NOT NULL DEFAULT "{}",'
        '  PRIMARY KEY (user_id)'
        ')'
    )

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
    html = (_HERE / 'panel.html').read_text(encoding='utf-8')
    if _SUBPATH:
        html = html.replace('content=""', f'content="{_SUBPATH}"', 1)
    uid = request.tul_user['id']
    # Theme-Flash-Fix: gespeichertes Theme als :root-Vars einbetten
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


@app.route('/load')
def load_state():
    uid = request.tul_user['id']
    with get_conn() as conn:
        row = conn.execute('SELECT state FROM kb_state WHERE user_id=?', (uid,)).fetchone()
    if row:
        return Response(row['state'], mimetype='application/json')
    return ('', 404)


@app.route('/save', methods=['POST'])
def save_state():
    uid = request.tul_user['id']
    data = request.get_data(as_text=True)
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO kb_state(user_id, state) VALUES(?,?) '
            'ON CONFLICT(user_id) DO UPDATE SET state=excluded.state',
            (uid, data)
        )
    return ('', 204)


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


@app.route('/logout', methods=['POST'])
def logout():
    return clear_token_cookie(make_response(jsonify({'ok': True})))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', 5010)))
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()

    if not args.no_browser:
        import webbrowser
        webbrowser.open(f'http://localhost:{args.port}')

    app.run(host='0.0.0.0', port=args.port, threaded=True)

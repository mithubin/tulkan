#!/usr/bin/env python3
import json
import os
import sys
import threading
import time
import urllib.request as _urllib_req
import urllib.error as _urllib_err
from pathlib import Path

from flask import Flask, Response, jsonify, make_response, redirect, request, send_from_directory

_HERE = Path(__file__).parent
# Python 3.11+ macht __file__ absolut: _HERE.parent wäre dann '/' statt tools_nuc/
# Daher auto-detect: im Container liegt static/ direkt neben hub_server.py
_STATIC = (_HERE / 'static') if (_HERE / 'static').is_dir() else (_HERE.parent / 'static')
_tools_nuc = str(Path(__file__).resolve().parent.parent)
if _tools_nuc not in sys.path:
    sys.path.insert(0, _tools_nuc)

from tul_auth.db import get_conn, init_db, now, uid, cleanup_expired_files
from tul_auth.auth import (
    clear_token_cookie, create_token, get_current_user, hash_pw,
    promote_admin_on_startup, require_admin, require_login,
    set_token_cookie, verify_pw,
)

app = Flask(__name__)

TOOLS = ['trskr', 'lern', 'kurv', 'popt', 'bild', 'nach', 'kal-trel', 'buch']
_TOOL_NAME = 'hub'
_MKAN_URL = os.environ.get('MKAN_URL', 'http://mkan:8000')


def _inject_user(html: str, user) -> str:
    snippet = f'<script>window.TUL_USER={json.dumps(user or None)};</script>'
    return html.replace('</head>', snippet + '\n</head>', 1)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.route('/health')
def health():
    return jsonify({'ok': True, 'tool': 'tul-hub'})


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    user = get_current_user()
    html = (_HERE / 'hub.html').read_text(encoding='utf-8')
    return Response(_inject_user(html, user), mimetype='text/html',
                    headers={'Cache-Control': 'no-store'})


# ── Auth routes ────────────────────────────────────────────────────────────────

@app.route('/login', methods=['POST'])
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get('email') or '').lower().strip()
    pw    = (body.get('password') or '').strip()
    if not email or not pw:
        return jsonify({'error': 'E-Mail und Passwort erforderlich'}), 400
    with get_conn() as conn:
        user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    if not user or not verify_pw(pw, user['pw_hash']):
        return jsonify({'error': 'Falsche E-Mail oder Passwort'}), 401
    token = create_token(user['id'])
    resp = make_response(jsonify({'ok': True, 'name': user['name'], 'role': user['global_role']}))
    return set_token_cookie(resp, token)


@app.route('/logout', methods=['POST'])
def logout():
    resp = make_response(jsonify({'ok': True}))
    return clear_token_cookie(resp)


@app.route('/me')
@require_login
def me():
    return jsonify(request.tul_user)


@app.route('/change-password', methods=['POST'])
@require_login
def change_password():
    body   = request.get_json(silent=True) or {}
    old_pw = (body.get('old_pw') or '').strip()
    new_pw = (body.get('new_pw') or '').strip()
    if not old_pw or not new_pw:
        return jsonify({'error': 'Fehlende Felder.'}), 400
    if len(new_pw) < 8:
        return jsonify({'error': 'Mindestens 8 Zeichen.'}), 400
    user_id = request.tul_user['id']
    with get_conn() as conn:
        user = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    if not user or not verify_pw(old_pw, user['pw_hash']):
        return jsonify({'error': 'Altes Passwort falsch.'}), 403
    with get_conn() as conn:
        conn.execute('UPDATE users SET pw_hash=? WHERE id=?', (hash_pw(new_pw), user_id))
    return jsonify({'ok': True})


# ── Admin: User management ─────────────────────────────────────────────────────

@app.route('/register', methods=['POST'])
@require_admin
def register():
    body  = request.get_json(silent=True) or {}
    name  = (body.get('name') or '').strip()
    email = (body.get('email') or '').lower().strip()
    pw    = (body.get('password') or '').strip()
    if not name or not email or not pw:
        return jsonify({'error': 'Name, E-Mail und Passwort erforderlich'}), 400
    if len(pw) < 8:
        return jsonify({'error': 'Passwort mindestens 8 Zeichen'}), 400
    with get_conn() as conn:
        if conn.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone():
            return jsonify({'error': 'E-Mail bereits registriert'}), 409
        new_id = uid()
        conn.execute(
            'INSERT INTO users (id, name, email, pw_hash, global_role, created_at) VALUES (?,?,?,?,?,?)',
            (new_id, name, email, hash_pw(pw), 'user', now())
        )
    return jsonify({'ok': True, 'id': new_id}), 201


@app.route('/admin/users')
@require_admin
def admin_users():
    with get_conn() as conn:
        users = [dict(r) for r in conn.execute(
            'SELECT id, name, email, global_role, created_at FROM users ORDER BY name'
        ).fetchall()]
        access_rows = conn.execute('SELECT user_id, tool, allowed FROM tool_access').fetchall()
    access_map: dict = {}
    for r in access_rows:
        access_map.setdefault(r['user_id'], {})[r['tool']] = bool(r['allowed'])
    for u in users:
        u['tool_access'] = {t: access_map.get(u['id'], {}).get(t, True) for t in TOOLS}
    return jsonify(users)


@app.route('/admin/users/<target_id>/access', methods=['POST'])
@require_admin
def admin_set_access(target_id):
    body    = request.get_json(silent=True) or {}
    tool    = body.get('tool')
    allowed = bool(body.get('allowed', True))
    if not tool or not tool.replace('-','').isalnum():
        return jsonify({'error': 'Ungültiges Tool'}), 400
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO tool_access(user_id, tool, allowed) VALUES(?,?,?) '
            'ON CONFLICT(user_id, tool) DO UPDATE SET allowed=excluded.allowed',
            (target_id, tool, int(allowed))
        )
    return jsonify({'ok': True})


@app.route('/admin/users/<target_id>/role', methods=['PATCH'])
@require_admin
def admin_set_role(target_id):
    body = request.get_json(silent=True) or {}
    role = body.get('role')
    if role not in ('admin', 'user'):
        return jsonify({'error': 'Ungültige Rolle'}), 400
    if target_id == request.tul_user['id'] and role != 'admin':
        return jsonify({'error': 'Eigene Admin-Rechte nicht entziehen'}), 400
    with get_conn() as conn:
        conn.execute('UPDATE users SET global_role=? WHERE id=?', (role, target_id))
    return jsonify({'ok': True})


@app.route('/admin/users/<target_id>', methods=['DELETE'])
@require_admin
def admin_delete_user(target_id):
    if target_id == request.tul_user['id']:
        return jsonify({'error': 'Eigenen Account nicht löschen'}), 400
    with get_conn() as conn:
        conn.execute('DELETE FROM users WHERE id=?', (target_id,))
    return jsonify({'ok': True})


# ── Setup (Bootstrap – nur wenn noch kein User existiert) ──────────────────────

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    with get_conn() as conn:
        count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    if count > 0:
        return redirect('/')
    if request.method == 'GET':
        return Response("""<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8">
<title>tul – Ersteinrichtung</title>
<style>body{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
form{background:#1e1e1e;padding:28px 32px;border-radius:8px;border:1px solid #333;width:320px}
h2{margin:0 0 20px;font-size:16px;color:#aaa}
input{width:100%;padding:8px;background:#2a2a2a;border:1px solid #444;color:#eee;border-radius:4px;margin-bottom:12px;box-sizing:border-box}
button{width:100%;padding:9px;background:#5c8fc8;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:14px}
.err{color:#f38ba8;font-size:13px;margin-bottom:10px}</style></head>
<body><form id="f"><h2>Ersteinrichtung – Admin anlegen</h2>
<div class="err" id="err"></div>
<input name="name" placeholder="Name" required>
<input name="email" type="email" placeholder="E-Mail" required>
<input name="password" type="password" placeholder="Passwort (min. 8 Zeichen)" required>
<button type="submit">Admin anlegen</button></form>
<script>document.getElementById('f').onsubmit=async e=>{e.preventDefault();
const d=Object.fromEntries(new FormData(e.target));
const r=await fetch('/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
const j=await r.json();
if(j.ok)location.href='/';else document.getElementById('err').textContent=j.error||'Fehler';}
</script></body></html>""", mimetype='text/html')
    body = request.get_json(silent=True) or {}
    name  = (body.get('name') or '').strip()
    email = (body.get('email') or '').lower().strip()
    pw    = (body.get('password') or '').strip()
    if not name or not email or not pw:
        return jsonify({'error': 'Alle Felder erforderlich'}), 400
    if len(pw) < 8:
        return jsonify({'error': 'Passwort mindestens 8 Zeichen'}), 400
    with get_conn() as conn:
        if conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] > 0:
            return jsonify({'error': 'Setup bereits abgeschlossen'}), 403
        new_id = uid()
        conn.execute(
            'INSERT INTO users (id, name, email, pw_hash, global_role, created_at) VALUES (?,?,?,?,?,?)',
            (new_id, name, email, hash_pw(pw), 'admin', now())
        )
    token = create_token(new_id)
    resp = make_response(jsonify({'ok': True}))
    return set_token_cookie(resp, token)


# ── Theme (tul-theme.js Server-Persistenz) ─────────────────────────────────────

@app.route('/theme')
@require_login
def theme_get():
    user_id = request.tul_user['id']
    with get_conn() as conn:
        row = conn.execute(
            'SELECT settings FROM user_themes WHERE user_id=? AND tool=?', (user_id, _TOOL_NAME)
        ).fetchone()
    return (Response(row['settings'], mimetype='application/json') if row else ('', 404))


@app.route('/theme', methods=['POST'])
@require_login
def theme_post():
    user_id = request.tul_user['id']
    data = request.get_data(as_text=True)
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO user_themes(user_id,tool,settings) VALUES(?,?,?) '
            'ON CONFLICT(user_id,tool) DO UPDATE SET settings=excluded.settings',
            (user_id, _TOOL_NAME, data)
        )
    return ('', 204)


# ── Prefs (Hub-Tile-Order + Namen) ────────────────────────────────────────────

@app.route('/prefs')
@require_login
def prefs_get():
    user_id = request.tul_user['id']
    with get_conn() as conn:
        row = conn.execute(
            'SELECT settings FROM user_themes WHERE user_id=? AND tool=?', (user_id, 'hub-prefs')
        ).fetchone()
    return (Response(row['settings'], mimetype='application/json') if row else ('{}', 200))


@app.route('/prefs', methods=['POST'])
@require_login
def prefs_post():
    user_id = request.tul_user['id']
    data = request.get_data(as_text=True)
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO user_themes(user_id,tool,settings) VALUES(?,?,?) '
            'ON CONFLICT(user_id,tool) DO UPDATE SET settings=excluded.settings',
            (user_id, 'hub-prefs', data)
        )
    return ('', 204)


# ── Admin: DV-Verwaltung ───────────────────────────────────────────────────────

# Pfad-Übersetzung: DB-Pfad (Tool-Container-intern) → Hub-interner Pfad
# Reihenfolge wichtig: spezifischere Präfixe zuerst (z.B. /data/tul_files/ vor /data/)
_TOOL_PATH_MAP: dict[str, list[tuple[str, str]]] = {
    'trskr':    [('/data/output/',       '/mnt/hub/trskr/output/'),
                 ('/data/tul_files/',    '/mnt/hub/trskr/files/')],
    'popt':     [('/data/tul_files/',    '/mnt/hub/popt/files/')],
    'bild':     [('/data/tul_files/',    '/mnt/hub/bild/files/')],
    'lern':     [('/data/tul_files/',    '/mnt/hub/lern/tul_files/'),
                 ('/data/',              '/mnt/hub/lern/')],
    'kurv':     [('/data/tul_files/',    '/mnt/hub/kurv/files/')],
    'nach':     [('/mnt/tul/nach/files/','/mnt/hub/nach/files/'),
                 ('/data/tul_files/',    '/mnt/hub/nach/tul_files/')],
    'kal-trel': [('/data/tul_files/',    '/mnt/hub/kal-trel/files/')],
    'buch':     [('/data/bild_files/',   '/mnt/hub/bild/files/'),
                 ('/data/tul_files/',    '/mnt/hub/buch/files/')],
}

def _hub_path(tool: str, db_path: str) -> str | None:
    """Übersetzt einen DB-Pfad (Tool-Container) in den Hub-zugänglichen Pfad."""
    for db_prefix, hub_prefix in _TOOL_PATH_MAP.get(tool, []):
        if db_path.startswith(db_prefix):
            return hub_prefix + db_path[len(db_prefix):]
    return None


_DV_OUTPUT_PHASES = {'transcription-output','toc','summary','subtitle','index','document','media'}
_DV_SPECIAL_INPUT = {'recycled','requeued'}

def _tul_mime(row: dict) -> str:
    ft   = row.get('file_type') or ''
    tool = row.get('tool') or ''
    cat  = row.get('category') or ''
    mime = row.get('mime') or ''
    if ft == 'url-ref':
        fmt = 'url-ref'
    elif ft in _DV_OUTPUT_PHASES or ft in _DV_SPECIAL_INPUT:
        fmt = 'text'
    elif mime.startswith('audio/'):
        fmt = 'audio'
    elif mime.startswith('video/'):
        fmt = 'video'
    elif mime.startswith('image/'):
        fmt = 'image'
    elif mime == 'application/pdf':
        fmt = 'pdf'
    elif 'csv' in mime:
        fmt = 'csv'
    elif mime.startswith('text/'):
        fmt = 'text'
    else:
        fmt = 'file'
    if cat == 'output' and ft in _DV_OUTPUT_PHASES:
        phase = ft
    elif ft in _DV_SPECIAL_INPUT:
        phase = ft
    else:
        phase = cat
    return f'{fmt}:{tool}:{phase}'


_ROUTING_TABLE = {
    'audio:trskr:input':                 ['trskr:transcription'],
    'video:trskr:input':                 ['trskr:transcription'],
    'url-ref:trskr:input':               ['trskr:transcription'],
    'text:trskr:transcription-output':   ['trskr:nachbearbeitung'],
    'text:trskr:nachbearbeitung-output': ['lern:input'],
    'pdf:popt:input':                    ['popt:processing'],
    'pdf:popt:output':                   ['buch:input'],
    'image:bild:input':                  ['bild:processing'],
    'pdf:bild:output':                   ['popt:input', 'buch:input'],
    'pdf:buch:input':                    ['buch:processing'],
    'pdf:buch:output':                   ['popt:input'],
    'csv:lern:input':                    ['lern:processing'],
    'image:lern:input':                  ['lern:processing'],
    'csv:kurv:input':                    ['kurv:processing'],
    'html:nach:input':                   ['nach:hosting'],
    'zip:nach:input':                    ['nach:hosting'],
    'json:kal-trel:output':              ['kal-trel:input'],
}


@app.route('/admin/dv')
@require_admin
def admin_dv():
    html = (_HERE / 'dv_admin.html').read_text(encoding='utf-8')
    return Response(_inject_user(html, request.tul_user), mimetype='text/html',
                    headers={'Cache-Control': 'no-store'})


@app.route('/api/admin/dv/files')
@require_admin
def api_admin_dv_files():
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT id,user_id,tool,filename,path,size,mime,category,'
            'file_type,retention,listed,created_at,expires_at,grp FROM files '
            'ORDER BY tool, grp, created_at DESC'
        ).fetchall()
        user_map = {r['id']: r['name'] for r in
                    conn.execute('SELECT id,name FROM users').fetchall()}
    result = []
    for r in rows:
        d = dict(r)
        d['tul_mime']  = _tul_mime(d)
        d['user_name'] = user_map.get(d['user_id'], '?')
        result.append(d)
    return jsonify(result)


@app.route('/api/admin/dv/files/<file_id>', methods=['DELETE'])
@require_admin
def api_admin_dv_delete(file_id):
    with get_conn() as conn:
        row = conn.execute('SELECT path,tool FROM files WHERE id=?', (file_id,)).fetchone()
        if not row:
            return jsonify({'error': 'Nicht gefunden'}), 404
        disk_deleted = False
        hp = _hub_path(row['tool'], row['path'])
        if hp:
            try:
                Path(hp).unlink(missing_ok=True)
                disk_deleted = True
            except Exception:
                pass
        conn.execute('DELETE FROM files WHERE id=?', (file_id,))
    return jsonify({'ok': True, 'disk_deleted': disk_deleted})


@app.route('/api/admin/dv/routing')
@require_admin
def api_admin_dv_routing():
    return jsonify(_ROUTING_TABLE)


@app.route('/api/admin/dv/zip', methods=['POST'])
@require_admin
def api_admin_dv_zip():
    import io, zipfile as _zf
    body = request.get_json(silent=True) or {}
    ids  = body.get('ids', [])
    if not ids:
        return jsonify({'error': 'Keine IDs angegeben.'}), 400
    with get_conn() as conn:
        placeholders = ','.join('?' * len(ids))
        rows = conn.execute(
            f'SELECT filename, path, tool FROM files WHERE id IN ({placeholders})', ids
        ).fetchall()
    if not rows:
        return jsonify({'error': 'Keine Dateien gefunden.'}), 404
    buf = io.BytesIO()
    with _zf.ZipFile(buf, 'w', _zf.ZIP_DEFLATED) as zf:
        for row in rows:
            hp = _hub_path(row['tool'], row['path'])
            p  = Path(hp) if hp else None
            if p and p.is_file():
                zf.write(p, row['filename'])
    buf.seek(0)
    resp = make_response(buf.read())
    resp.headers['Content-Type'] = 'application/zip'
    resp.headers['Content-Disposition'] = 'attachment; filename="tul-dv-export.zip"'
    return resp


# ── mkan DV Proxy ─────────────────────────────────────────────────────────────

def _mkan_request(path: str):
    # Eigenes Bridge-Secret, getrennt von TUL_SECRET (JWT-Signing-Key) — Fund Code-Review 2026-07-12
    secret = os.environ.get('TUL_BRIDGE_SECRET', '')
    req = _urllib_req.Request(
        _MKAN_URL + path,
        headers={'X-Tul-Secret': secret},
    )
    return req


@app.route('/api/mkan-card')
@require_login
def mkan_card():
    card_id = request.args.get('card_id', '').strip()
    if not card_id:
        return jsonify({'error': 'card_id fehlt'}), 400
    try:
        with _urllib_req.urlopen(_mkan_request(f'/attachments/dv/card/{card_id}'), timeout=10) as resp:
            data = resp.read()
        return Response(data, mimetype='application/json')
    except _urllib_err.HTTPError as e:
        return jsonify({'error': f'mkan: {e.code}'}), e.code
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/api/mkan-file')
@require_login
def mkan_file():
    att_id = request.args.get('att_id', '').strip()
    if not att_id:
        return jsonify({'error': 'att_id fehlt'}), 400
    try:
        with _urllib_req.urlopen(_mkan_request(f'/attachments/dv/file/{att_id}'), timeout=30) as resp:
            data = resp.read()
            ct = resp.headers.get('Content-Type', 'application/octet-stream')
            cd = resp.headers.get('Content-Disposition', '')
        r = Response(data, mimetype=ct)
        if cd:
            r.headers['Content-Disposition'] = cd
        return r
    except _urllib_err.HTTPError as e:
        return jsonify({'error': f'mkan: {e.code}'}), e.code
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/api/mkan-pool')
@require_login
def mkan_pool():
    try:
        with _urllib_req.urlopen(_mkan_request('/attachments/dv/pool'), timeout=10) as resp:
            data = resp.read()
        return Response(data, mimetype='application/json')
    except _urllib_err.HTTPError as e:
        return jsonify({'error': f'mkan: {e.code}'}), e.code
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/api/mkan-cards-for-tool')
@require_login
def mkan_cards_for_tool():
    tool = request.args.get('tool', '').strip()
    if not tool:
        return jsonify({'error': 'tool fehlt'}), 400
    try:
        with _urllib_req.urlopen(_mkan_request(f'/attachments/dv/cards-for-tool/{tool}'), timeout=10) as resp:
            data = resp.read()
        return Response(data, mimetype='application/json')
    except _urllib_err.HTTPError as e:
        return jsonify({'error': f'mkan: {e.code}'}), e.code
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/api/mkan-unlink-card', methods=['POST'])
@require_login
def mkan_unlink_card():
    card_id = request.args.get('card_id', '').strip()
    if not card_id:
        return jsonify({'error': 'card_id fehlt'}), 400
    # Eigenes Bridge-Secret, getrennt von TUL_SECRET (JWT-Signing-Key) — Fund Code-Review 2026-07-12
    secret = os.environ.get('TUL_BRIDGE_SECRET', '')
    try:
        req = _urllib_req.Request(
            _MKAN_URL + f'/attachments/dv/unlink-card/{card_id}',
            data=b'',
            headers={'X-Tul-Secret': secret},
        )
        with _urllib_req.urlopen(req, timeout=10) as resp:
            result = resp.read()
        return Response(result, mimetype='application/json')
    except _urllib_err.HTTPError as e:
        return jsonify({'error': f'mkan: {e.code}'}), e.code
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/api/mkan-preview-text')
@require_login
def mkan_preview_text():
    att_id = request.args.get('att_id', '').strip()
    if not att_id:
        return jsonify({'error': 'att_id fehlt'}), 400
    # Eigenes Bridge-Secret, getrennt von TUL_SECRET (JWT-Signing-Key) — Fund Code-Review 2026-07-12
    secret = os.environ.get('TUL_BRIDGE_SECRET', '')
    try:
        req = _urllib_req.Request(
            _MKAN_URL + f'/attachments/dv/preview-text/{att_id}',
            headers={'X-Tul-Secret': secret},
        )
        with _urllib_req.urlopen(req, timeout=15) as resp:
            result = resp.read()
        return Response(result, mimetype='application/json')
    except _urllib_err.HTTPError as e:
        body = e.read()
        return Response(body, status=e.code, mimetype='application/json')
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/api/mkan-push-to-card', methods=['POST'])
@require_login
def mkan_push_to_card():
    card_id = request.args.get('card_id', '').strip()
    if not card_id:
        return jsonify({'error': 'card_id fehlt'}), 400
    # Eigenes Bridge-Secret, getrennt von TUL_SECRET (JWT-Signing-Key) — Fund Code-Review 2026-07-12
    secret = os.environ.get('TUL_BRIDGE_SECRET', '')
    try:
        data = request.get_data()
        req = _urllib_req.Request(
            _MKAN_URL + f'/attachments/dv/upload-to-card/{card_id}',
            data=data,
            headers={
                'X-Tul-Secret': secret,
                'Content-Type': request.content_type,
            },
            method='POST',
        )
        with _urllib_req.urlopen(req, timeout=60) as resp:
            result = resp.read()
        return Response(result, mimetype='application/json'), 201
    except _urllib_err.HTTPError as e:
        body = e.read()
        return Response(body, status=e.code, mimetype='application/json')
    except Exception as e:
        return jsonify({'error': str(e)}), 502


# ── Static ─────────────────────────────────────────────────────────────────────

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(str(_STATIC), filename)


# ── Main ───────────────────────────────────────────────────────────────────────

def _cleanup_loop():
    """cleanup_expired_files() war implementiert, aber nie aufgerufen (Fund Code-Review 2026-07-12).
    Läuft nur im Hub-Container (zentral, immer an), nicht in jedem Tool-Container einzeln."""
    while True:
        try:
            cleanup_expired_files()
        except Exception:
            pass
        time.sleep(6 * 3600)


if __name__ == '__main__':
    init_db()
    promote_admin_on_startup()
    threading.Thread(target=_cleanup_loop, daemon=True).start()
    host = '0.0.0.0' if os.environ.get('DOCKER') else '127.0.0.1'
    port = int(os.environ.get('PORT', 5000))
    app.run(host=host, port=port)

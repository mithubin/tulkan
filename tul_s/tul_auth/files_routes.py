"""Shared Flask-Blueprint für tul-files Datei-Verwaltung.

Jedes Panel registriert:
    from tul_auth.files_routes import make_files_blueprint
    app.register_blueprint(make_files_blueprint(_TOOL_NAME, _FILES_ROOT))

Erwartet require_login aus tul_auth.auth und DB-Zugriff via tul_auth.db.
"""
import io
import mimetypes
import os
import pathlib
import re
import urllib.parse as _urlparse
import urllib.request as _urlreq
import zipfile

from flask import Blueprint, Response, jsonify, request, send_file

from .auth import require_login
from .db import get_conn, now, retention_expires, uid


def _nc_parse(share_url: str):
    m = re.match(r'(https?://[^/]+)/s/([^/?#]+)', share_url.rstrip('/'))
    if not m:
        raise ValueError(f'Ungültiger NC-Link: {share_url}')
    return m.group(1), m.group(2)


def _nc_mkcol(host: str, token: str, dir_path: str):
    """MKCOL – ignoriert Fehler wenn Verzeichnis schon existiert."""
    try:
        req = _urlreq.Request(
            f'{host}/public.php/dav/files/{token}/{_urlparse.quote(dir_path, safe="/")}',
            method='MKCOL')
        _urlreq.urlopen(req, timeout=10)
    except Exception:
        pass


def _nc_upload(share_url: str, filename: str, filepath: pathlib.Path,
               remote_subpath: str = ''):
    """PUT einer Datei in einen öffentlichen Nextcloud-Share.

    remote_subpath: optionaler Unterordner (z.B. 'job123/pdf_logs').
    """
    host, token = _nc_parse(share_url)
    if remote_subpath:
        remote = f'{remote_subpath}/{_urlparse.quote(filename, safe="")}'
    else:
        remote = _urlparse.quote(filename, safe='')
    req = _urlreq.Request(
        f'{host}/public.php/dav/files/{token}/{remote}',
        data=filepath.read_bytes(), method='PUT')
    with _urlreq.urlopen(req, timeout=120):
        pass


def make_files_blueprint(tool: str, files_root: str) -> Blueprint:
    root = pathlib.Path(files_root)
    bp = Blueprint('tul_files', __name__)

    @bp.route('/health')
    def health():
        from flask import jsonify as _j
        return _j({'ok': True, 'tool': tool})

    def _user_dir(category: str) -> pathlib.Path:
        uid_val = request.tul_user['id']
        d = root / category / uid_val
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _own_file(file_id: str):
        """Gibt DB-Row zurück wenn Datei dem aktuellen User gehört, sonst None."""
        uid_val = request.tul_user['id']
        with get_conn() as conn:
            return conn.execute(
                'SELECT * FROM files WHERE id=? AND user_id=? AND tool=?',
                (file_id, uid_val, tool)
            ).fetchone()

    # ── Liste ────────────────────────────────────────────────────────────────
    @bp.route('/files')
    @require_login
    def files_list():
        category = request.args.get('category', 'input')
        show_all = request.args.get('all', '0') == '1'
        uid_val  = request.tul_user['id']
        with get_conn() as conn:
            # Panel-Sidebar: nur listed=1; Modal (?all=1) oder Ausgabe: alles
            if show_all or category == 'output':
                rows = conn.execute(
                    'SELECT * FROM files WHERE user_id=? AND tool=? AND category=? '
                    'ORDER BY created_at DESC',
                    (uid_val, tool, category)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM files WHERE user_id=? AND tool=? AND category=? AND listed=1 '
                    'ORDER BY created_at DESC',
                    (uid_val, tool, category)
                ).fetchall()
        return jsonify([dict(r) for r in rows])

    # ── Upload ───────────────────────────────────────────────────────────────
    @bp.route('/files/upload', methods=['POST'])
    @require_login
    def files_upload():
        f = request.files.get('file')
        if not f or not f.filename:
            return jsonify({'error': 'Keine Datei'}), 400
        retention = request.form.get('retention', '1mo')
        category  = request.form.get('category', 'input')
        file_type = request.form.get('file_type', '')

        dest_dir = _user_dir(category)
        fid  = uid()
        safe = pathlib.Path(f.filename).name
        dest = dest_dir / f'{fid}_{safe}'
        f.save(str(dest))
        size = dest.stat().st_size
        mime = f.mimetype or mimetypes.guess_type(safe)[0] or 'application/octet-stream'

        with get_conn() as conn:
            conn.execute(
                'INSERT INTO files(id,user_id,tool,filename,path,size,mime,'
                'category,file_type,retention,created_at,expires_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (fid, request.tul_user['id'], tool, safe, str(dest), size,
                 mime, category, file_type or None, retention, now(),
                 retention_expires(retention))
            )
        return jsonify({'ok': True, 'id': fid, 'filename': safe, 'size': size,
                        'mime': mime, 'retention': retention,
                        'category': category, 'created_at': now()})

    # ── Download ─────────────────────────────────────────────────────────────
    @bp.route('/files/<file_id>/download')
    @require_login
    def files_download(file_id):
        row = _own_file(file_id)
        if not row:
            return jsonify({'error': 'Nicht gefunden'}), 404
        p = pathlib.Path(row['path'])
        if not p.exists():
            return jsonify({'error': 'Datei fehlt auf Disk'}), 404
        return send_file(str(p), as_attachment=True,
                         download_name=row['filename'],
                         mimetype=row['mime'] or 'application/octet-stream')

    @bp.route('/files/<file_id>/inline')
    @require_login
    def files_inline(file_id):
        row = _own_file(file_id)
        if not row:
            return jsonify({'error': 'Nicht gefunden'}), 404
        p = pathlib.Path(row['path'])
        if not p.exists():
            return jsonify({'error': 'Datei fehlt auf Disk'}), 404
        return send_file(str(p), mimetype=row['mime'] or 'application/octet-stream')

    # ── ZIP-Download ─────────────────────────────────────────────────────────
    @bp.route('/files/zip', methods=['POST'])
    @require_login
    def files_zip():
        ids = (request.get_json(silent=True) or {}).get('ids', [])
        if not ids:
            return jsonify({'error': 'Keine IDs'}), 400
        uid_val = request.tul_user['id']
        with get_conn() as conn:
            placeholders = ','.join('?' * len(ids))
            rows = conn.execute(
                f'SELECT * FROM files WHERE id IN ({placeholders}) '
                f'AND user_id=? AND tool=?',
                [*ids, uid_val, tool]
            ).fetchall()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for row in rows:
                p = pathlib.Path(row['path'])
                if p.exists():
                    zf.write(str(p), row['filename'])
        buf.seek(0)
        return send_file(buf, mimetype='application/zip',
                         as_attachment=True, download_name=f'{tool}_files.zip')

    # ── Löschen ──────────────────────────────────────────────────────────────
    @bp.route('/files/<file_id>', methods=['DELETE'])
    @require_login
    def files_delete(file_id):
        row = _own_file(file_id)
        if not row:
            return jsonify({'error': 'Nicht gefunden'}), 404
        try:
            pathlib.Path(row['path']).unlink(missing_ok=True)
        except Exception:
            pass
        with get_conn() as conn:
            conn.execute('DELETE FROM files WHERE id=?', (file_id,))
        return jsonify({'ok': True})

    # ── Batch-Löschen ────────────────────────────────────────────────────────
    @bp.route('/files/batch', methods=['DELETE'])
    @require_login
    def files_batch_delete():
        ids = (request.get_json(silent=True) or {}).get('ids', [])
        if not ids:
            return jsonify({'error': 'Keine IDs'}), 400
        uid_val = request.tul_user['id']
        placeholders = ','.join('?' * len(ids))
        with get_conn() as conn:
            rows = conn.execute(
                f'SELECT id, path FROM files WHERE id IN ({placeholders}) AND user_id=? AND tool=?',
                [*ids, uid_val, tool]
            ).fetchall()
        for row in rows:
            try:
                pathlib.Path(row['path']).unlink(missing_ok=True)
            except Exception:
                pass
        found = [r['id'] for r in rows]
        if found:
            ph2 = ','.join('?' * len(found))
            with get_conn() as conn:
                conn.execute(f'DELETE FROM files WHERE id IN ({ph2})', found)
        return jsonify({'ok': True, 'deleted': len(found)})

    # ── Retention ändern ─────────────────────────────────────────────────────
    @bp.route('/files/<file_id>/retention', methods=['PATCH'])
    @require_login
    def files_retention(file_id):
        row = _own_file(file_id)
        if not row:
            return jsonify({'error': 'Nicht gefunden'}), 404
        data = request.get_json(silent=True) or {}
        retention = data.get('retention')
        days = data.get('days')
        valid = ('task', '1w', '1mo', 'user', 'perm')
        if retention not in valid:
            return jsonify({'error': 'Ungültige Retention'}), 400
        if days is not None:
            # custom days → store as 'user' with computed expires_at
            try:
                days = int(days)
                from datetime import datetime, timedelta, timezone
                expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            except (ValueError, TypeError):
                return jsonify({'error': 'Ungültige Tagesanzahl'}), 400
            with get_conn() as conn:
                conn.execute(
                    'UPDATE files SET retention=?, expires_at=? WHERE id=?',
                    ('user', expires, file_id)
                )
        else:
            with get_conn() as conn:
                conn.execute(
                    'UPDATE files SET retention=?, expires_at=? WHERE id=?',
                    (retention, retention_expires(retention), file_id)
                )
        return jsonify({'ok': True})

    # ── Listed-Flag setzen ───────────────────────────────────────────────────
    @bp.route('/files/<file_id>/listed', methods=['PATCH'])
    @require_login
    def files_listed(file_id):
        row = _own_file(file_id)
        if not row:
            return jsonify({'error': 'Nicht gefunden'}), 404
        listed = 1 if (request.get_json(silent=True) or {}).get('listed', True) else 0
        with get_conn() as conn:
            conn.execute('UPDATE files SET listed=? WHERE id=?', (listed, file_id))
        return jsonify({'ok': True})

    # ── In Eingabe kopieren (Kopie in Eingang, Original bleibt) ─────────────────
    @bp.route('/files/<file_id>/copy-to-input', methods=['POST'])
    @require_login
    def files_copy_to_input(file_id):
        row = _own_file(file_id)
        if not row:
            return jsonify({'error': 'Nicht gefunden'}), 404
        if row['category'] != 'output':
            return jsonify({'error': 'Nur Ausgabe-Dateien können kopiert werden'}), 400
        old_path = pathlib.Path(row['path'])
        uid_val  = request.tul_user['id']
        new_dir  = root / 'input' / uid_val
        new_dir.mkdir(parents=True, exist_ok=True)
        fid      = uid()
        base     = old_path.name.split('_', 1)[-1] if '_' in old_path.name else old_path.name
        new_path = new_dir / f'{fid}_{base}'
        import shutil
        try:
            shutil.copy2(str(old_path), str(new_path))
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        size = new_path.stat().st_size
        with get_conn() as conn:
            conn.execute(
                'INSERT INTO files(id,user_id,tool,filename,path,size,mime,'
                'category,file_type,retention,created_at,expires_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (fid, uid_val, tool, row['filename'], str(new_path), size,
                 row['mime'], 'input', 'requeued', row['retention'], now(),
                 row['expires_at'])
            )
        return jsonify({'ok': True, 'id': fid})

    # ── In Eingabe recyceln ───────────────────────────────────────────────────
    @bp.route('/files/<file_id>/recycle', methods=['POST'])
    @require_login
    def files_recycle(file_id):
        row = _own_file(file_id)
        if not row:
            return jsonify({'error': 'Nicht gefunden'}), 404
        if row['category'] != 'output':
            return jsonify({'error': 'Nur Ausgabe-Dateien können recycelt werden'}), 400
        # Move file on disk: output/<uid>/... → input/<uid>/...
        old_path = pathlib.Path(row['path'])
        uid_val  = request.tul_user['id']
        new_dir  = root / 'input' / uid_val
        new_dir.mkdir(parents=True, exist_ok=True)
        new_path = new_dir / old_path.name
        try:
            if old_path.exists():
                old_path.rename(new_path)
        except Exception:
            new_path = old_path  # keep path if move fails
        with get_conn() as conn:
            conn.execute(
                "UPDATE files SET category=?, path=?, file_type='recycled' WHERE id=?",
                ('input', str(new_path), file_id)
            )
        return jsonify({'ok': True})

    # ── NC-Ziele (user-spezifisch, push + fetch) ────────────────────────────────
    @bp.route('/nc-targets')
    @require_login
    def nc_targets_list():
        uid_val   = request.tul_user['id']
        direction = request.args.get('direction')   # ?direction=fetch|push
        with get_conn() as conn:
            if direction:
                rows = conn.execute(
                    'SELECT * FROM nc_targets WHERE user_id=? AND direction=? ORDER BY created_at',
                    (uid_val, direction)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM nc_targets WHERE user_id=? ORDER BY created_at',
                    (uid_val,)
                ).fetchall()
        return jsonify([dict(r) for r in rows])

    @bp.route('/nc-targets', methods=['POST'])
    @require_login
    def nc_targets_add():
        uid_val   = request.tul_user['id']
        body      = request.get_json(silent=True) or {}
        label     = (body.get('label')     or '').strip()
        url_val   = (body.get('url')       or '').strip()
        direction = (body.get('direction') or 'push').strip()
        tool_val  = (body.get('tool')      or '').strip() or None
        if not label or not url_val:
            return jsonify({'error': 'Label und URL erforderlich.'}), 400
        if not re.match(r'https?://.+/s/\w+', url_val):
            return jsonify({'error': 'Kein gültiger NC-Share-Link (https://host/s/TOKEN).'}), 400
        if direction not in ('push', 'fetch'):
            return jsonify({'error': 'direction muss push oder fetch sein.'}), 400
        tid = uid()
        with get_conn() as conn:
            conn.execute(
                'INSERT INTO nc_targets(id,user_id,label,url,direction,tool,created_at)'
                ' VALUES(?,?,?,?,?,?,?)',
                (tid, uid_val, label, url_val, direction, tool_val, now())
            )
        return jsonify({'id': tid}), 201

    @bp.route('/nc-targets/<tid>', methods=['DELETE'])
    @require_login
    def nc_targets_delete(tid):
        uid_val = request.tul_user['id']
        with get_conn() as conn:
            conn.execute('DELETE FROM nc_targets WHERE id=? AND user_id=?', (tid, uid_val))
        return ('', 204)

    # ── NC-Fetch (CSV-Pool aus NC-Share befüllen) ────────────────────────────────
    @bp.route('/nc-fetch', methods=['POST'])
    @require_login
    def nc_fetch():
        """PROPFIND NC-Share → CSVs holen → in DB registrieren.

        Idempotenz: name+size aus PROPFIND vs. DB vergleichen.
        Gleiche size → überspringen. Andere size → Datei + DB-Eintrag aktualisieren.
        Verzeichnis: root/input/ (flach, kein user-Subdir).
        Retention: 1mo.
        """
        import mimetypes as _mt
        import xml.etree.ElementTree as _ET

        uid_val = request.tul_user['id']
        body    = request.get_json(silent=True) or {}
        tid     = body.get('target_id')
        with get_conn() as conn:
            t = conn.execute(
                "SELECT url, label FROM nc_targets WHERE id=? AND user_id=? AND direction='fetch'",
                (tid, uid_val)
            ).fetchone()
        if not t:
            return jsonify({'error': 'Fetch-Quelle nicht gefunden.'}), 404

        share_url  = t['url']
        fetch_grp  = t['label'] or 'NC-Pool'
        m = re.match(r'(https?://[^/]+)/s/([^/?#]+)', share_url)
        if not m:
            return jsonify({'error': 'Ungültiger NC-Link.'}), 400
        host, token = m.group(1), m.group(2)
        dav_base = f'{host}/public.php/dav/files/{token}'

        # 1. PROPFIND — Dateiliste + Größen holen
        try:
            req = _urlreq.Request(
                dav_base + '/',
                method='PROPFIND',
                headers={'Depth': '1', 'Content-Type': 'application/xml'})
            with _urlreq.urlopen(req, timeout=30) as resp:
                xml_bytes = resp.read()
        except Exception as e:
            return jsonify({'error': f'PROPFIND fehlgeschlagen: {e}'}), 502

        tree = _ET.fromstring(xml_bytes)
        remote_files = []  # (name, remote_size_or_None)
        for r_el in tree.findall('.//{DAV:}response'):
            href = (r_el.findtext('{DAV:}href') or '').rstrip('/')
            name = _urlparse.unquote(href.split('/')[-1])
            if not name.lower().endswith('.csv'):
                continue
            sz_el = r_el.find('.//{DAV:}getcontentlength')
            remote_size = int(sz_el.text) if sz_el is not None and sz_el.text else None
            remote_files.append((name, remote_size))

        if not remote_files:
            return jsonify({'ok': True, 'fetched': 0, 'skipped': 0, 'msg': 'Keine CSV-Dateien gefunden.'})

        # 2. Vorhandene Einträge aus DB: {filename: {id, size}}
        in_dir = root / 'input'
        in_dir.mkdir(parents=True, exist_ok=True)
        with get_conn() as conn:
            # user_id-Filter ergänzt (Fund Code-Review 2026-07-12): ohne ihn hätte ein zweiter Nutzer
            # mit gleichnamiger CSV den DB-Eintrag (und wegen der flachen root/input/-Struktur auch die
            # physische Datei) eines anderen Nutzers überschrieben, statt einen eigenen Eintrag anzulegen.
            existing = {r['filename']: {'id': r['id'], 'size': r['size']} for r in conn.execute(
                "SELECT id, filename, size FROM files WHERE tool=? AND category='input' AND user_id=?",
                (tool, uid_val)
            ).fetchall()}

        def _download(name):
            url = f'{dav_base}/{_urlparse.quote(name, safe="")}'
            req = _urlreq.Request(url)
            with _urlreq.urlopen(req, timeout=120) as resp:
                return resp.read()

        fetched = skipped = 0
        ts = now()
        with get_conn() as conn:
            for name, remote_size in remote_files:
                ex = existing.get(name)
                if ex and remote_size is not None and ex['size'] == remote_size:
                    # identisch — nicht neu herunterladen
                    skipped += 1
                    continue
                # herunterladen (neu oder andere Größe)
                try:
                    data = _download(name)
                except Exception as e:
                    return jsonify({'error': f'Download {name} fehlgeschlagen: {e}'}), 502
                dest = in_dir / name
                dest.write_bytes(data)
                actual_size = len(data)
                mime = _mt.guess_type(name)[0] or 'text/csv'
                if ex:
                    # Eintrag aktualisieren
                    conn.execute(
                        'UPDATE files SET size=?, created_at=? WHERE id=?',
                        (actual_size, ts, ex['id'])
                    )
                else:
                    conn.execute(
                        'INSERT INTO files'
                        '(id,user_id,tool,filename,path,size,mime,category,file_type,retention,created_at,grp)'
                        ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                        (uid(), uid_val, tool, name, str(dest), actual_size, mime,
                         'input', 'burn-log', '1mo', ts, fetch_grp)
                    )
                fetched += 1

        return jsonify({'ok': True, 'fetched': fetched, 'skipped': skipped})

    # ── NC-Push: gesamten Job (Gruppe) mit Vz-Struktur pushen ───────────────────
    @bp.route('/job-push', methods=['POST'])
    @require_login
    def job_push():
        """Pusht alle Output-Dateien einer Job-Gruppe zu NC; erhält Unterordner-Struktur."""
        uid_val = request.tul_user['id']
        body    = request.get_json(silent=True) or {}
        grp     = body.get('grp', '').strip()
        tid     = body.get('target_id', '').strip()
        if not grp or not tid:
            return jsonify({'error': 'grp und target_id erforderlich'}), 400
        with get_conn() as conn:
            t = conn.execute(
                "SELECT url FROM nc_targets WHERE id=? AND user_id=? AND direction='push'",
                (tid, uid_val)
            ).fetchone()
            rows = conn.execute(
                "SELECT filename, path FROM files WHERE grp=? AND tool=? AND category='output'",
                (grp, tool)
            ).fetchall()
        if not t:
            return jsonify({'error': 'NC-Ziel nicht gefunden'}), 404
        if not rows:
            return jsonify({'error': 'Keine Output-Dateien für diesen Job'}), 404
        try:
            host, token = _nc_parse(t['url'])
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

        pushed = 0
        for row in rows:
            f = pathlib.Path(row['path'])
            if not f.is_file():
                continue
            # Unterordner relativ zum grp-Verzeichnis extrahieren
            path_str = row['path'].replace('\\', '/')
            marker   = '/' + grp + '/'
            idx      = path_str.find(marker)
            if idx >= 0:
                rel = path_str[idx + len(marker):]          # z.B. pdf_logs/bericht.pdf
            else:
                rel = row['filename']
            parts = rel.split('/')
            # MKCOL für grp-Verzeichnis und alle Unterordner
            dirs = [grp] + ['/'.join([grp] + parts[:i]) for i in range(1, len(parts))]
            for d in dict.fromkeys(dirs):                   # dedupliziert, Reihenfolge erhalten
                _nc_mkcol(host, token, d)
            # PUT mit Pfad: grp/subdir/.../datei
            remote_path = grp + '/' + rel
            req = _urlreq.Request(
                f'{host}/public.php/dav/files/{token}/{_urlparse.quote(remote_path, safe="/")}',
                data=f.read_bytes(), method='PUT')
            _urlreq.urlopen(req, timeout=120)
            pushed += 1

        return jsonify({'ok': True, 'pushed': pushed})

    # ── NC-Senden (Einzeldatei) ───────────────────────────────────────────────────
    @bp.route('/files/<file_id>/nc-send', methods=['POST'])
    @require_login
    def files_nc_send(file_id):
        row = _own_file(file_id)
        if not row:
            return jsonify({'error': 'Nicht gefunden'}), 404
        body    = request.get_json(silent=True) or {}
        tid     = body.get('target_id')
        uid_val = request.tul_user['id']
        with get_conn() as conn:
            t = conn.execute(
                'SELECT url FROM nc_targets WHERE id=? AND user_id=?', (tid, uid_val)
            ).fetchone()
        if not t:
            return jsonify({'error': 'NC-Ziel nicht gefunden.'}), 404
        p = pathlib.Path(row['path'])
        if not p.exists():
            return jsonify({'error': 'Datei fehlt auf Disk.'}), 404
        try:
            grp = row['grp'] or ''
            if grp:
                host, token = _nc_parse(t['url'])
                _nc_mkcol(host, token, grp)
            _nc_upload(t['url'], row['filename'], p, remote_subpath=grp)
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ── Inhalt lesen / schreiben (für Textdateien wie Batch-Listen) ─────────────
    @bp.route('/files/<file_id>/content')
    @require_login
    def files_content_get(file_id):
        row = _own_file(file_id)
        if not row:
            return jsonify({'error': 'Nicht gefunden'}), 404
        p = pathlib.Path(row['path'])
        if not p.exists():
            return jsonify({'error': 'Datei fehlt auf Disk'}), 404
        try:
            from flask import Response as _FResp
            return _FResp(p.read_text(encoding='utf-8', errors='replace'),
                          mimetype='text/plain; charset=utf-8')
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @bp.route('/files/<file_id>/content', methods=['PUT'])
    @require_login
    def files_content_put(file_id):
        row = _own_file(file_id)
        if not row:
            return jsonify({'error': 'Nicht gefunden'}), 404
        p = pathlib.Path(row['path'])
        text = request.get_data(as_text=True)
        try:
            p.write_text(text, encoding='utf-8')
            size = p.stat().st_size
            with get_conn() as conn:
                conn.execute('UPDATE files SET size=? WHERE id=?', (size, file_id))
            return jsonify({'ok': True, 'size': size})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ── User-Prefs (generisch, pro Tool+Key) ─────────────────────────────────
    @bp.route('/prefs/<key>', methods=['GET'])
    @require_login
    def prefs_get(key):
        uid_val = request.tul_user['id']
        with get_conn() as conn:
            row = conn.execute(
                "SELECT settings FROM user_themes WHERE user_id=? AND tool=?",
                (uid_val, f'pref:{tool}:{key}')
            ).fetchone()
        return Response(row['settings'] if row else '[]', mimetype='application/json')

    @bp.route('/prefs/<key>', methods=['PUT'])
    @require_login
    def prefs_put(key):
        uid_val = request.tul_user['id']
        data = request.get_data(as_text=True)
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO user_themes(user_id,tool,settings) VALUES(?,?,?) "
                "ON CONFLICT(user_id,tool) DO UPDATE SET settings=excluded.settings",
                (uid_val, f'pref:{tool}:{key}', data)
            )
        return ('', 204)

    return bp

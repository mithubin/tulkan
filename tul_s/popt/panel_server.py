#!/usr/bin/env python3
"""
popt – PDF-Optimierung Panel-Server
Upload → Ghostscript → Download
"""
import io
import json
import os
import queue
import re as _re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error as _urllib_err
import urllib.request as _urllib_req
import uuid
import zipfile
from pathlib import Path

from flask import Flask, Response, jsonify, make_response, request, send_file, redirect

import sys as _sys
_tools_nuc = str(Path(__file__).resolve().parent.parent)
if _tools_nuc not in _sys.path:
    _sys.path.insert(0, _tools_nuc)
from tul_auth.db import init_db, get_conn, uid as _uid, now as _now, retention_expires as _ret_exp
from tul_auth.auth import get_current_user, is_json_request, clear_token_cookie
from tul_auth.files_routes import make_files_blueprint

app   = Flask(__name__)
_HERE = Path(__file__).parent

_SUBPATH    = os.environ.get('SUBPATH', '')
_TOOL_NAME  = 'popt'
_FILES_ROOT = os.environ.get('FILES_ROOT', '/data/tul_files')
_TMP_BASE   = Path(tempfile.gettempdir()) / 'popt_jobs'
_TMP_BASE.mkdir(exist_ok=True)
_MKAN_URL   = os.environ.get('MKAN_URL', 'http://mkan:8000')
_TUL_SECRET = os.environ.get('TUL_BRIDGE_SECRET', '')  # eigenes Bridge-Secret, nicht JWT-Key (Fund 2026-07-12)

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
        import json as _j
        snip = f'<script>window.TUL_USER={_j.dumps(user)};</script>'
        body = resp.get_data(as_text=True)
        if '</head>' in body:
            resp.set_data(body.replace('</head>', snip + '\n</head>', 1))
    return resp

# ── Qualitäts-Presets ─────────────────────────────────────────────────────────
PRESETS = {
    'screen':   {'suffix': '_os',  'gs': ['-dPDFSETTINGS=/screen',
                  '-dColorImageResolution=72',  '-dGrayImageResolution=72',
                  '-dMonoImageResolution=72',   '-dJPEGQ=72',
                  '-dColorConversionStrategy=/sRGB', '-dConvertCMYKImagesToRGB=true']},
    'ebook':    {'suffix': '_oe',  'gs': ['-dPDFSETTINGS=/ebook',
                  '-dColorImageResolution=150', '-dGrayImageResolution=150',
                  '-dMonoImageResolution=300',  '-dJPEGQ=80',
                  '-dColorConversionStrategy=/LeaveColorUnchanged',
                  '-dConvertCMYKImagesToRGB=false']},
    '200dpi':   {'suffix': '_o2',  'gs': ['-dPDFSETTINGS=/ebook',
                  '-dColorImageResolution=200', '-dGrayImageResolution=200',
                  '-dMonoImageResolution=400',  '-dJPEGQ=86',
                  '-dColorConversionStrategy=/LeaveColorUnchanged',
                  '-dConvertCMYKImagesToRGB=false']},
    'printer':  {'suffix': '_op',  'gs': ['-dPDFSETTINGS=/printer',
                  '-dColorImageResolution=300', '-dGrayImageResolution=300',
                  '-dMonoImageResolution=1200', '-dJPEGQ=88',
                  '-dColorConversionStrategy=/LeaveColorUnchanged',
                  '-dConvertCMYKImagesToRGB=false']},
    'prepress': {'suffix': '_opp', 'gs': ['-dPDFSETTINGS=/prepress',
                  '-dColorImageResolution=300', '-dGrayImageResolution=300',
                  '-dMonoImageResolution=1200', '-dJPEGQ=96',
                  '-dColorConversionStrategy=/LeaveColorUnchanged',
                  '-dConvertCMYKImagesToRGB=false']},
}

# ── Job-Verwaltung ────────────────────────────────────────────────────────────
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _new_job(job_dir: Path) -> dict:
    job = {
        'id':      str(uuid.uuid4())[:8],
        'q':       queue.Queue(),
        'stop':    threading.Event(),
        'done':    False,
        'dir':     job_dir,
        'out_dir': job_dir / 'out',
    }
    job['out_dir'].mkdir(exist_ok=True)
    with _jobs_lock:
        _jobs[job['id']] = job
    return job


def _get_job(jid: str) -> dict | None:
    with _jobs_lock:
        return _jobs.get(jid)


# ── Input-Cleanup nach Job ────────────────────────────────────────────────────
def _after_job_inputs_cleanup(file_ids: list, user_id: str):
    """Nach GS-Job: onetimeuse (retention='task') löschen, Rest auf listed=0."""
    if not file_ids:
        return
    placeholders = ','.join('?' * len(file_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f'SELECT id, path, retention FROM files WHERE id IN ({placeholders})'
            f' AND user_id=? AND tool=?',
            [*file_ids, user_id, _TOOL_NAME]
        ).fetchall()
        to_delete = [r for r in rows if r['retention'] == 'task']
        to_hide   = [r for r in rows if r['retention'] != 'task']
        for row in to_delete:
            try:
                Path(row['path']).unlink(missing_ok=True)
            except Exception:
                pass
        if to_delete:
            ids = [r['id'] for r in to_delete]
            conn.execute(f"DELETE FROM files WHERE id IN ({','.join('?'*len(ids))})", ids)
        if to_hide:
            ids = [r['id'] for r in to_hide]
            conn.execute(f"UPDATE files SET listed=0 WHERE id IN ({','.join('?'*len(ids))})", ids)


# ── Output in tul-files registrieren ─────────────────────────────────────────
def _register_tul_output(job: dict, user_id: str):
    """Fertige PDFs aus dem GS-Job in tul-files-Ausgabe eintragen."""
    out_dir   = job['out_dir']
    user_out  = Path(_FILES_ROOT) / 'output' / user_id
    user_out.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(out_dir.glob('*.pdf')):
        fid  = _uid()
        dest = user_out / f'{fid}_{pdf.name}'
        shutil.copy2(str(pdf), str(dest))
        size = dest.stat().st_size
        with get_conn() as conn:
            conn.execute(
                'INSERT INTO files(id,user_id,tool,filename,path,size,mime,'
                'category,retention,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (fid, user_id, _TOOL_NAME, pdf.name, str(dest), size,
                 'application/pdf', 'output', '1mo', _now(), _ret_exp('1mo'))
            )


# ── GS-Worker ────────────────────────────────────────────────────────────────
def _run(job: dict, gs_params: list[str], suffix: str, user_id: str | None = None):
    q       = job['q']
    stop    = job['stop']
    in_dir  = job['dir'] / 'in'
    out_dir = job['out_dir']

    def log(msg: str):
        q.put(msg)

    pdfs = sorted(in_dir.rglob('*.pdf'))
    if not pdfs:
        log('Keine PDFs im Upload gefunden.')
        q.put(None); job['done'] = True; return

    log(f'{len(pdfs)} PDF(s) werden verarbeitet …\n')

    processed = failed = 0
    total_in  = total_out = 0

    for pdf in pdfs:
        if stop.is_set():
            log('\n[Abgebrochen]'); break

        stem   = pdf.stem
        dst    = out_dir / f'{stem}{suffix}.pdf'
        size_in = pdf.stat().st_size
        total_in += size_in
        log(f'➤ {pdf.name}')

        cmd = ['gs', '-q', '-dNOPAUSE', '-dBATCH', '-dSAFER',
               '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.5',
               *gs_params,
               '-dEmbedAllFonts=true', '-dSubsetFonts=true',
               '-dAutoFilterColorImages=true', '-dAutoFilterGrayImages=true',
               '-dColorImageFilter=/DCTEncode', '-dGrayImageFilter=/DCTEncode',
               '-dOptimize=true', '-dUseFlateCompression=true',
               f'-sOutputFile={dst}', str(pdf)]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if proc.returncode == 0 and dst.exists():
                size_out = dst.stat().st_size
                total_out += size_out
                kb_in  = size_in  // 1024
                kb_out = size_out // 1024
                pct    = int((size_in - size_out) * 100 / size_in) if size_in else 0
                mark   = '✓' if size_out <= size_in else '⚠'
                log(f'  {mark} {kb_in} KB → {kb_out} KB ({pct}% kleiner)')
                processed += 1
            else:
                log(f'  ✗ gs-Fehler (exit {proc.returncode})')
                if proc.stderr:
                    log(f'    {proc.stderr.strip()[:200]}')
                failed += 1
        except subprocess.TimeoutExpired:
            log('  ✗ Timeout (>5 min)')
            failed += 1
        except FileNotFoundError:
            log('  ✗ ghostscript nicht gefunden — Container-Problem.')
            q.put(None); job['done'] = True; return

    log('\n' + '─' * 44)
    log(f'Verarbeitet: {processed}  │  Fehler: {failed}')
    if processed and total_in:
        saved_kb = (total_in - total_out) // 1024
        pct      = int((total_in - total_out) * 100 / total_in)
        log(f'Gesamt: {total_in//1024} KB → {total_out//1024} KB  ({saved_kb} KB / {pct}% gespart)')

    if user_id:
        try:
            _register_tul_output(job, user_id)
        except Exception:
            pass
        try:
            _after_job_inputs_cleanup(job.get('input_file_ids', []), user_id)
        except Exception:
            pass

    q.put(None)
    job['done'] = True


# ── Routes ────────────────────────────────────────────────────────────────────
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


@app.route('/upload', methods=['POST'])
def upload():
    """Nimmt eine oder mehrere PDF-Dateien (oder eine ZIP) entgegen."""
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'Keine Dateien empfangen.'}), 400

    job_dir = _TMP_BASE / str(uuid.uuid4())[:8]
    in_dir  = job_dir / 'in'
    in_dir.mkdir(parents=True)

    saved = []
    for f in files:
        if not f.filename:
            continue
        name = Path(f.filename).name
        if name.lower().endswith('.zip'):
            # ZIP entpacken, nur PDFs behalten
            buf = io.BytesIO(f.read())
            with zipfile.ZipFile(buf) as zf:
                for zi in zf.infolist():
                    if zi.filename.lower().endswith('.pdf') and not zi.is_dir():
                        zf.extract(zi, in_dir)
                        saved.append(zi.filename)
        elif name.lower().endswith('.pdf'):
            dest = in_dir / name
            f.save(str(dest))
            saved.append(name)

    if not saved:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({'error': 'Keine PDFs in den hochgeladenen Dateien gefunden.'}), 400

    return jsonify({'upload_dir': str(job_dir), 'files': saved})


def _mkan_download(att_id: str, dest_dir: Path) -> bool:
    """Lädt eine mkan-Pool-Datei per TUL_SECRET in dest_dir. Gibt True bei Erfolg zurück."""
    try:
        req = _urllib_req.Request(
            _MKAN_URL + f'/attachments/dv/file/{att_id}',
            headers={'X-Tul-Secret': _TUL_SECRET},
        )
        with _urllib_req.urlopen(req, timeout=30) as resp:
            cd = resp.headers.get('Content-Disposition', '')
            fname = att_id + '.pdf'
            m = _re.search(r'filename=["\']?([^"\';\r\n]+)', cd)
            if m:
                fname = m.group(1).strip()
            if not fname.lower().endswith('.pdf'):
                fname += '.pdf'
            with open(dest_dir / fname, 'wb') as f:
                f.write(resp.read())
        return True
    except Exception:
        return False


@app.route('/start', methods=['POST'])
def start():
    data          = request.json or {}
    file_ids      = data.get('file_ids', [])
    mkan_att_ids  = data.get('mkan_att_ids', [])
    upload_dir    = data.get('upload_dir', '').strip()
    quality       = data.get('quality', '200dpi').strip()
    user_id       = request.tul_user['id']

    if file_ids or mkan_att_ids:
        job_dir = _TMP_BASE / str(uuid.uuid4())[:8]
        in_dir  = job_dir / 'in'
        in_dir.mkdir(parents=True)

        # eigene tul-files aus DB kopieren
        if file_ids:
            with get_conn() as conn:
                placeholders = ','.join('?' * len(file_ids))
                rows = conn.execute(
                    f'SELECT * FROM files WHERE id IN ({placeholders})'
                    f' AND user_id=? AND tool=? AND category=?',
                    [*file_ids, user_id, _TOOL_NAME, 'input']
                ).fetchall()
            for row in rows:
                src = Path(row['path'])
                if src.exists() and row['filename'].lower().endswith('.pdf'):
                    shutil.copy2(str(src), str(in_dir / row['filename']))

        # mkan-Pool-Dateien direkt von mkan laden
        for att_id in mkan_att_ids:
            _mkan_download(att_id, in_dir)

        if not list(in_dir.glob('*.pdf')):
            shutil.rmtree(job_dir, ignore_errors=True)
            return jsonify({'error': ['Keine PDFs in den gewählten Dateien.']}), 400
    elif upload_dir:
        file_ids     = []  # legacy path — kein tul-files-Cleanup
        mkan_att_ids = []
        job_dir = Path(upload_dir)
        if not job_dir.is_dir():
            return jsonify({'error': ['Upload-Verzeichnis nicht gefunden.']}), 400
    else:
        return jsonify({'error': ['Keine Eingabe angegeben.']}), 400

    if quality == 'custom':
        try:
            cr = int(data.get('custom_color_res') or 200)
            gr = int(data.get('custom_gray_res')  or 200)
            mr = int(data.get('custom_mono_res')  or 400)
            jq = int(data.get('custom_jpeg_q')    or 86)
        except (ValueError, TypeError):
            return jsonify({'error': ['Ungültige Custom-Werte.']}), 400
        gs_params = [f'-dColorImageResolution={cr}', f'-dGrayImageResolution={gr}',
                     f'-dMonoImageResolution={mr}',  f'-dJPEGQ={jq}',
                     '-dColorConversionStrategy=/LeaveColorUnchanged',
                     '-dConvertCMYKImagesToRGB=false']
        suffix = '_ocm'
    else:
        preset    = PRESETS.get(quality, PRESETS['200dpi'])
        gs_params = preset['gs']
        suffix    = preset['suffix']

    job = _new_job(job_dir)
    job['input_file_ids'] = file_ids  # für onetimeuse-Cleanup
    threading.Thread(target=_run, args=(job, gs_params, suffix, user_id), daemon=True).start()
    return jsonify({'job_id': job['id']})


@app.route('/stream/<jid>')
def stream(jid: str):
    job = _get_job(jid)
    if not job:
        return 'Job nicht gefunden', 404

    def generate():
        q = job['q']
        while True:
            try:
                msg = q.get(timeout=30)
            except queue.Empty:
                yield 'data: {"t":"ping"}\n\n'
                continue
            if msg is None:
                yield 'data: {"t":"done"}\n\n'
                break
            payload = json.dumps({'t': 'log', 'm': msg + '\n'})
            yield f'data: {payload}\n\n'

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/stop/<jid>', methods=['POST'])
def stop(jid: str):
    job = _get_job(jid)
    if job:
        job['stop'].set()
    return jsonify({'ok': True})


@app.route('/download/<jid>')
def download(jid: str):
    """Liefert die optimierten PDFs: einzeln wenn nur eine, sonst als ZIP."""
    job = _get_job(jid)
    if not job or not job['done']:
        return 'Noch nicht fertig oder unbekannt', 404

    out_dir = job['out_dir']
    results = sorted(out_dir.glob('*.pdf'))
    if not results:
        return 'Keine Ausgabe-PDFs vorhanden', 404

    if len(results) == 1:
        return send_file(str(results[0]), as_attachment=True,
                         download_name=results[0].name)

    # Mehrere → ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for p in results:
            zf.write(str(p), p.name)
    buf.seek(0)
    return send_file(buf, mimetype='application/zip', as_attachment=True,
                     download_name=f'optimiert_{jid}.zip')


@app.route('/logout', methods=['POST'])
def logout():
    return clear_token_cookie(make_response(jsonify({'ok': True})))


# ── Start ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', 5006)))
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()

    if not args.no_browser:
        import webbrowser
        webbrowser.open(f'http://localhost:{args.port}')

    app.run(host='0.0.0.0', port=args.port, threaded=True)

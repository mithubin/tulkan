#!/usr/bin/env python3
"""
panel_server.py – lokales Web-Panel für whisper_transkriplate_panel.py
Start: python3 panel_server.py  →  http://localhost:7860
"""
import os, sys, re, json, queue, threading, uuid, tempfile, subprocess
from pathlib import Path
from flask import Flask, Response, stream_with_context, request, send_file, jsonify, redirect, make_response

_HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(_HERE))
import whisper_transkriplate_panel as wt

# ─── Auth ─────────────────────────────────────────────────────────────────────
_tools_nuc = str(Path(__file__).resolve().parent.parent)
if _tools_nuc not in sys.path:
    sys.path.insert(0, _tools_nuc)
from tul_auth.db import init_db, get_conn, uid as _uid, now as _now, retention_expires as _ret_exp
from tul_auth.auth import get_current_user, is_json_request, require_login, clear_token_cookie
from tul_auth.files_routes import make_files_blueprint

MODELS_PATH = _HERE / wt.MODELS_DIR
_TOOL_NAME  = 'trskr'
_FILES_ROOT = os.environ.get('FILES_ROOT', '/data/tul_files')

# ─── ANSI strippen ────────────────────────────────────────────────────────────
_ANSI = re.compile(r'\x1b\[[0-9;]*[mKABCDEFGHJKSTfilu]')
def _strip(s): return _ANSI.sub('', s)

# ─── Sprach-Mappings ──────────────────────────────────────────────────────────
LANG_MAP = {
    'Deutsch': 'de', 'Englisch': 'en', 'Französisch': 'fr',
    'Spanisch': 'es', 'Italienisch': 'it', 'Russisch': 'ru',
    'Automatisch': None, '': None,
}
# Zusammenfassungssprache: Label → LANG_NAMES-Wert (wie Transkript → None)
SUMLAN_MAP = {
    'wie Transkript': None,
    'Deutsch': 'Deutsch', 'Englisch': 'Englisch',
    'Französisch': 'Französisch', 'Spanisch': 'Spanisch',
}
ACCENT_LADDER = ['tiny', 'base', 'small', 'medium', 'large-v3']

# ─── Params-Builder ───────────────────────────────────────────────────────────
def _build_params(model, accent):
    si = wt.detect_system()
    p = dict(wt.recommend_params(si))
    p['model'] = model
    if accent == 'Standard':
        p.update(beam_size=5, condition_on_previous_text=True, temperature=None)
    elif accent == 'Mittel':
        p.update(beam_size=7, condition_on_previous_text=True, temperature=None)
    elif accent == 'Stark':
        p.update(beam_size=10, condition_on_previous_text=False, temperature=0)
        cur = ACCENT_LADDER.index(p['model']) if p['model'] in ACCENT_LADDER else 3
        p['model'] = ACCENT_LADDER[min(cur + 1, len(ACCENT_LADDER) - 1)]
    elif accent == 'Sehr stark':
        p.update(beam_size=15, condition_on_previous_text=False, temperature=0)
        cur = ACCENT_LADDER.index(p['model']) if p['model'] in ACCENT_LADDER else 3
        p['model'] = ACCENT_LADDER[min(cur + 2, len(ACCENT_LADDER) - 1)]
    return p

# ─── Job-Verwaltung ───────────────────────────────────────────────────────────
_jobs: dict = {}
_jobs_lock = threading.Lock()

class _Job:
    def __init__(self):
        self.id = str(uuid.uuid4())[:8]
        self.log_q: queue.Queue = queue.Queue()
        self.log_buf: list = []          # persistenter Log für Reload-Replay
        self.done = threading.Event()
        self.stop = threading.Event()
        self.soft_stop = threading.Event()
        self.transcript_path: str | None = None
        self.output_dir: str | None = None
        self.batch_output_dirs: list = []

class _Writer:
    """Leitet stdout/stderr in Queue + persistenten Buffer (ANSI bereits gestrippt)."""
    def __init__(self, job: '_Job'):
        self._q   = job.log_q
        self._buf = job.log_buf
    def write(self, text):
        if text:
            clean = _strip(text)
            self._q.put(clean)
            self._buf.append(clean)
    def flush(self): pass
    def fileno(self):
        import io; raise io.UnsupportedOperation('fileno')

# ─── Validierung ──────────────────────────────────────────────────────────────
def _validate(data: dict) -> list[str]:
    errs = []
    st = data.get('source_type', '')
    if st == 'url':
        u = (data.get('url') or '').strip()
        if not u:
            errs.append('URL fehlt.')
        elif not (u.startswith('http://') or u.startswith('https://')):
            errs.append('URL muss mit http(s):// beginnen.')
    elif st == 'local':
        f = (data.get('local_path') or '').strip()
        if not f:
            errs.append('Dateipfad fehlt.')
        elif not Path(f).exists():
            errs.append(f'Datei nicht gefunden: {f}')
    elif st == 'batch':
        entries = [l for l in (data.get('batch_text') or '').splitlines()
                   if l.strip() and not l.strip().startswith('#')]
        if not entries:
            errs.append('Batch-Eingabe ist leer (oder nur Kommentare).')
    else:
        errs.append(f'Unbekannter Quellentyp: {st}')
    for label, key in [('Von', 'trim_start'), ('Bis', 'trim_end')]:
        v = (data.get(key) or '').strip()
        if v and wt._parse_timecode(v) is None:
            errs.append(f'Ungültiger {label}-Zeitcode: {v}')
    bd = (data.get('base_dir') or '').strip()
    if bd:
        try:
            Path(bd).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errs.append(f'Zielverzeichnis: {e}')
    return errs

# ─── Worker ───────────────────────────────────────────────────────────────────
def _cleanup_upload_tmp(data: dict):
    """Löscht /tmp/up_*-Verzeichnisse die durch /upload entstanden sind."""
    import shutil as _shutil
    candidates = []
    if data.get('source_type') == 'local':
        candidates.append(data.get('local_path', ''))
    elif data.get('source_type') == 'batch':
        for line in (data.get('batch_text') or '').splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                candidates.append(line)
    for p in candidates:
        if p and p.startswith('/tmp/up_'):
            try:
                _shutil.rmtree(str(Path(p).parent), ignore_errors=True)
            except Exception:
                pass


def _worker(job: _Job, data: dict):
    orig_out, orig_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = _Writer(job)
    try:
        st = data['source_type']
        if st == 'batch':
            _run_batch(job, data)
        else:
            _run_single(job, data)
    except Exception:
        import traceback
        print(f'\n  FEHLER:\n{traceback.format_exc()}')
    finally:
        sys.stdout, sys.stderr = orig_out, orig_err
        _cleanup_upload_tmp(data)
        user_id = data.get('_user_id')
        if user_id:
            _register_tul_outputs(job, user_id)
            _after_job_cleanup(data.get('_input_file_ids') or [], user_id)
        job.done.set()
        job.log_q.put(None)  # Sentinel


def _run_batch(job: _Job, data: dict):
    entries = [l.strip() for l in (data.get('batch_text') or '').splitlines()
               if l.strip() and not l.strip().startswith('#')]
    params = _build_params(data.get('model', 'medium'), data.get('accent', 'Standard'))
    formats = _get_formats(data)
    lang = LANG_MAP.get(data.get('language', 'Automatisch'))
    task = data.get('task', 'transcribe')
    bd = (data.get('base_dir') or '').strip() or str(_OUTPUT_BASE)
    Path(bd).mkdir(parents=True, exist_ok=True)
    trans_tgt = LANG_MAP.get(data.get('trans_tgt') or '')
    trans_src = 'en' if task == 'translate' else lang

    sum_levels, sum_langs, do_toc, focus_kw = _get_api_params(data)

    job.output_dir = bd  # Batch-Jobs zeigen auf das Basisverzeichnis

    print(f'\n  Batch: {len(entries)} Einträge — lade Modell einmal …')
    from faster_whisper import WhisperModel
    kw = {'device': params['device'], 'compute_type': params['compute']}
    if params['threads']:
        kw['cpu_threads'] = params['threads']
    whisper_dir = str(MODELS_PATH / 'whisper')
    model_inst = WhisperModel(params['model'], download_root=whisper_dir, **kw)
    print(f'  ✓ Modell geladen\n')

    user_id = data.get('_user_id')
    for i, entry in enumerate(entries, 1):
        if job.stop.is_set():
            print('  — Batch unterbrochen.')
            break
        print(f'\n  [{i}/{len(entries)}] {entry}')
        entry_st = 'url' if entry.startswith('http') else 'local'

        def _on_output_dir(d, _job=job):
            _job.output_dir = str(d)
            _job.transcript_path = str(d / f'{d.name.rsplit("-", 1)[0]}.txt')
            _job.batch_output_dirs.append(str(d))

        wt.process_single(
            entry, entry_st, dict(params), lang, task,
            set(formats), bd, trans_src, trans_tgt,
            model_instance=model_inst, models_path=MODELS_PATH,
            live_editor=True, generate_toc_flag=do_toc,
            summary_levels=sum_levels, summary_langs=sum_langs,
            focus_keywords=focus_kw,
            stop_event=job.stop,
            on_output_dir=_on_output_dir,
        )

        # Ausgaben sofort nach Task-Abschluss registrieren
        if job.batch_output_dirs and user_id:
            _register_dir_outputs(Path(job.batch_output_dirs[-1]), user_id)


def _run_single(job: _Job, data: dict):
    st = data['source_type']
    source = (data.get('url') if st == 'url' else data.get('local_path') or '').strip()

    # Titel + Ausgabepfad vorab bestimmen
    if st == 'url':
        source = wt.clean_youtube_url(source)
        url_id = wt.extract_url_id(source)
        print('  Hole Video-Titel …')
        title_raw = wt.fetch_yt_title(source) or 'transkript'
        print(f'  Titel: {title_raw}')
    else:
        url_id = None
        title_raw = Path(source).stem

    base_name = wt.slugify(title_raw) or 'transkript'
    bd = (data.get('base_dir') or '').strip() or str(_OUTPUT_BASE)
    output_dir = Path(bd) / (f'{base_name}-{url_id}' if url_id else base_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Job bekommt Ausgabepfade — ab jetzt kann das Panel pollen
    job.output_dir = str(output_dir)
    job.transcript_path = str(output_dir / f'{base_name}.txt')

    params = _build_params(data.get('model', 'medium'), data.get('accent', 'Standard'))
    formats = _get_formats(data)
    lang = LANG_MAP.get(data.get('language', 'Automatisch'))
    task = data.get('task', 'transcribe')
    keep_src = data.get('keep_source') or None
    trim_s_str = (data.get('trim_start') or '').strip()
    trim_e_str = (data.get('trim_end') or '').strip()
    trim_s = wt._parse_timecode(trim_s_str) if trim_s_str else None
    trim_e = wt._parse_timecode(trim_e_str) if trim_e_str else None

    with tempfile.TemporaryDirectory() as tmp:
        if st == 'url':
            audio = wt.download_audio(source, tmp, keep=keep_src, output_dir=str(output_dir))
        else:
            audio = wt.extract_audio_local(source, tmp, keep=keep_src, output_dir=str(output_dir))

        if trim_s is not None or trim_e is not None:
            audio = wt.trim_audio(audio, trim_s, trim_e, tmp)

        if job.stop.is_set():
            return

        if task == 'translate':
            written_orig, detected_lang, loaded_model = wt.transcribe(
                audio, params, lang, output_dir, base_name + '_orig',
                formats, task='transcribe', models_path=MODELS_PATH, live_editor=True,
                stop_event=job.soft_stop)
            if job.stop.is_set(): return
            written_en, _, _ = wt.transcribe(
                audio, params, lang, output_dir, base_name,
                formats, task='translate', model_instance=loaded_model,
                models_path=MODELS_PATH, live_editor=True, stop_event=job.soft_stop)
            written = list(written_en) + list(written_orig)
        else:
            written, detected_lang, _ = wt.transcribe(
                audio, params, lang, output_dir, base_name,
                formats, task=task, models_path=MODELS_PATH, live_editor=True,
                stop_event=job.soft_stop)
            written = list(written)

        if job.stop.is_set() and not job.soft_stop.is_set(): return

        # Helsinki-Übersetzung
        trans_tgt = LANG_MAP.get(data.get('trans_tgt') or '')
        if trans_tgt:
            txt_files = [w for w in written if w.endswith('.txt') and '_orig' not in w]
            if txt_files:
                with open(txt_files[0], encoding='utf-8') as fh:
                    lines = [l.strip() for l in fh if l.strip()]
                trans_src = 'en' if task == 'translate' else (lang or detected_lang or 'de')
                wt.translate_text(lines, trans_src, trans_tgt, output_dir, base_name,
                                  models_path=MODELS_PATH)

        # TOC + Zusammenfassung
        sum_levels, sum_langs, do_toc, focus_kw = _get_api_params(data)
        if do_toc or sum_levels:
            wt._run_api_postprocessing(
                written, detected_lang, lang, task,
                do_toc, sum_levels, sum_langs,
                title_raw, output_dir, base_name,
                source_url=source if st == 'url' else None,
                focus_keywords=focus_kw,
            )

        wt.write_index_md(output_dir, base_name, title_raw,
                          source_url=source if st == 'url' else None)
        print('\n  ✓ Fertig.')


def _get_formats(data: dict) -> set:
    fmts = set(data.get('formats') or ['txt', 'srt'])
    fmts.add('txt')  # immer für Live-Transkript-Polling
    return fmts


def _get_api_params(data: dict):
    has_api = bool(wt.ANTHROPIC_API_KEY)
    do_toc = data.get('do_toc', False) and has_api
    sum_levels = [int(l) for l in (data.get('summary_levels') or [])] if has_api else []
    focus_kw = [k.strip() for k in (data.get('focus_kw') or '').split(',') if k.strip()]
    sum_lang = SUMLAN_MAP.get(data.get('summary_lang') or 'wie Transkript')
    sum_langs = [sum_lang] if sum_levels else []
    return sum_levels, sum_langs, do_toc, focus_kw

# ─── Flask App ────────────────────────────────────────────────────────────────
app = Flask(__name__)
init_db()
app.register_blueprint(make_files_blueprint(_TOOL_NAME, _FILES_ROOT))

_SUBPATH = os.environ.get('SUBPATH', '')

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
        html = html.replace(
            '<script>\nconst _B = window._B||\'\';',
            f'<script>\nconst _B = \'{_SUBPATH}\';'
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
    from flask import Response as _R
    resp = _R(html, mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/sysinfo')
def sysinfo():
    si = wt.detect_system()
    p = wt.recommend_params(si)
    return jsonify({
        'ram_avail': f"{si['avail_gb']:.1f}",
        'ram_total':  f"{si['ram_gb']:.1f}",
        'cpu':        si['cpu_count'],
        'gpu':        si['gpu_name'] if si['has_gpu'] else None,
        'rec_model':  p['model'],
        'device':     p['device'],
        'compute':    p['compute'],
        'api_key':    bool(wt.ANTHROPIC_API_KEY),
    })


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


@app.route('/start', methods=['POST'])
def start():
    data = request.json or {}
    data['_user_id'] = request.tul_user['id']

    # tul-files: file_id → local_path
    file_id = (data.get('file_id') or '').strip()
    if file_id:
        uid_val = request.tul_user['id']
        with get_conn() as conn:
            row = conn.execute(
                'SELECT path FROM files WHERE id=? AND user_id=? AND tool=?',
                (file_id, uid_val, _TOOL_NAME)
            ).fetchone()
        if not row:
            return jsonify({'error': ['Eingabe-Datei nicht gefunden (tul-files).']}), 400
        data['local_path']       = row['path']
        data['source_type']      = 'local'
        data['_input_file_ids']  = [file_id]

    errs = _validate(data)
    if errs:
        return jsonify({'error': errs}), 400

    _register_url_input(data, request.tul_user['id'])

    job = _Job()
    with _jobs_lock:
        _jobs[job.id] = job
    threading.Thread(target=_worker, args=(job, data), daemon=True).start()
    return jsonify({'job_id': job.id})


@app.route('/log/<job_id>')
def job_log(job_id):
    job = _jobs.get(job_id)
    if not job:
        return ('', 404)
    return Response(''.join(job.log_buf), mimetype='text/plain; charset=utf-8')


@app.route('/stream/<job_id>')
def stream_log(job_id):
    def generate():
        job = _jobs.get(job_id)
        if not job:
            yield f"data: {json.dumps({'t':'err','m':'Job nicht gefunden'})}\n\n"
            return
        while True:
            try:
                chunk = job.log_q.get(timeout=0.3)
            except queue.Empty:
                if job.done.is_set():
                    yield f"data: {json.dumps({'t':'done','od':job.output_dir})}\n\n"
                    return
                yield f"data: {json.dumps({'t':'hb'})}\n\n"
                continue
            if chunk is None:
                yield f"data: {json.dumps({'t':'done','od':job.output_dir})}\n\n"
                return
            yield f"data: {json.dumps({'t':'log','m':chunk})}\n\n"

    resp = Response(stream_with_context(generate()), mimetype='text/event-stream')
    resp.headers.update({'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
                         'Connection': 'keep-alive'})
    return resp


@app.route('/transcript/<job_id>')
def get_transcript(job_id):
    job = _jobs.get(job_id)
    if not job or not job.transcript_path:
        return ('', 200)
    p = Path(job.transcript_path)
    return (p.read_text(encoding='utf-8') if p.exists() else '', 200)


@app.route('/files/<job_id>')
def get_files(job_id):
    job = _jobs.get(job_id)
    if not job or not job.output_dir:
        return jsonify([])
    files = []
    if job.batch_output_dirs:
        dirs = [Path(d) for d in job.batch_output_dirs]
    else:
        dirs = [Path(job.output_dir)]
    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file():
                files.append({'name': f.name, 'path': str(f), 'ext': f.suffix.lstrip('.'),
                              'subdir': d.name})
    return jsonify(files)


@app.route('/posthoc', methods=['POST'])
def posthoc():
    """Nachbearbeitung für einen oder mehrere Ordner.
    Einzelordner: ph_path (string)
    Mehrere Ordner: ph_paths (JSON-Array) oder ph_paths_text (zeilengetrennt)
    """
    data = request.json or {}
    types = data.get('ph_types') or []

    # Pfade normalisieren
    _ph_tmp_dir = None
    if data.get('ph_paths'):
        paths = [p.strip() for p in data['ph_paths'] if str(p).strip()]
    elif data.get('ph_paths_text'):
        paths = [l.strip() for l in data['ph_paths_text'].splitlines()
                 if l.strip() and not l.strip().startswith('#')]
    elif (data.get('file_id') or '').strip():
        file_id = data['file_id'].strip()
        with get_conn() as conn:
            frow = conn.execute(
                'SELECT path FROM files WHERE id=? AND user_id=?',
                (file_id, request.tul_user['id'])
            ).fetchone()
        if frow:
            import shutil as _shutil
            _ph_tmp_dir = tempfile.mkdtemp()
            src = Path(frow['path'])
            _shutil.copy2(str(src), str(Path(_ph_tmp_dir) / src.name))
            paths = [_ph_tmp_dir]
        else:
            paths = []
    else:
        single = (data.get('ph_path') or '').strip()
        paths = [single] if single else []

    errs = []
    if not types:
        errs.append('Keine Aufgabe gewählt.')
    if not paths:
        errs.append('Ordnerpfad fehlt.')
    for p in paths:
        if not Path(p).is_dir():
            errs.append(f'Ordner nicht gefunden: {p}')
    if 'translate' in types and not data.get('ph_tgt'):
        errs.append('Zielsprache fehlt.')
    if any(t in types for t in ('toc', 'summary')) and not wt.ANTHROPIC_API_KEY:
        errs.append('ANTHROPIC_API_KEY nicht gesetzt.')
    if 'summary' in types and not data.get('ph_sum_levels'):
        errs.append('Keine Zusammenfassungs-Stufe gewählt.')
    if errs:
        return jsonify({'error': errs}), 400

    data = {**data, '_ph_paths_resolved': paths, '_ph_tmp_dir': _ph_tmp_dir}
    job = _Job()
    with _jobs_lock:
        _jobs[job.id] = job
    threading.Thread(target=_worker_posthoc, args=(job, data), daemon=True).start()
    return jsonify({'job_id': job.id})


def _worker_posthoc(job: _Job, data: dict):
    orig_out, orig_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = _Writer(job)
    try:
        types = data.get('ph_types') or []
        paths = data.get('_ph_paths_resolved') or []
        for i, path in enumerate(paths, 1):
            entry_data = {**data, 'ph_path': path}
            if len(paths) > 1:
                print(f'\n  [{i}/{len(paths)}] {path}')
            if 'translate' in types:
                _ph_translate(job, entry_data)
            if 'toc' in types or 'summary' in types:
                _ph_toc_summary(job, entry_data, types)
            job.output_dir = path  # letzter verarbeiteter Ordner
    except Exception:
        import traceback
        print(f'\n  FEHLER:\n{traceback.format_exc()}')
    finally:
        sys.stdout, sys.stderr = orig_out, orig_err
        job.done.set()
        job.log_q.put(None)
        td = data.get('_ph_tmp_dir')
        if td:
            import shutil as _sh
            _sh.rmtree(td, ignore_errors=True)


def _ph_translate(job: _Job, data: dict):
    folder = Path(data['ph_path'].strip())
    src = LANG_MAP.get(data.get('ph_src') or 'Deutsch') or 'de'
    tgt = LANG_MAP.get(data.get('ph_tgt') or '')
    if not tgt:
        print('  Fehler: Zielsprache ungültig.'); return
    # Haupt-.txt im Ordner finden (kein _orig, keine Sprachsuffix)
    txt_candidates = [f for f in sorted(folder.glob('*.txt'))
                      if '_orig.' not in f.name
                      and not any(f'_{c}.' in f.name
                                  for c in ('de','en','fr','es','it','ru','zh','pl','nl','pt'))]
    if not txt_candidates:
        print('  Fehler: Keine .txt-Transkriptdatei im Ordner.'); return
    txt_path = txt_candidates[0]
    with open(txt_path, encoding='utf-8') as f:
        lines = [l.strip() for l in f if l.strip()]
    if not lines:
        print(f'  Fehler: {txt_path.name} ist leer.'); return
    job.output_dir = str(folder)
    print(f'  Übersetze {txt_path.name} ({len(lines)} Zeilen) — {src} → {tgt} …')
    wt.translate_text(lines, src, tgt, folder, txt_path.stem, models_path=MODELS_PATH)
    print('\n  ✓ Übersetzung fertig.')


def _ph_toc_summary(job: _Job, data: dict, types: list):
    folder = Path(data['ph_path'].strip())
    srt = list(folder.glob('*.srt'))
    txt = [f for f in folder.glob('*.txt')
           if '_orig.' not in f.name
           and not any(f'_{c}.' in f.name for c in ('de','en','fr','es','it','ru','zh','pl','nl','pt'))]
    written = [str(f) for f in srt + txt]
    if not written:
        print('  Fehler: Keine Transkript-Datei im Ordner.'); return
    do_toc     = 'toc' in types
    sum_levels = [int(l) for l in (data.get('ph_sum_levels') or [])]
    focus_kw   = [k.strip() for k in (data.get('ph_focus_kw') or '').split(',') if k.strip()]
    lang       = data.get('ph_lang') or 'Deutsch'
    job.output_dir = str(folder)
    wt._run_api_postprocessing(
        written, None, None, 'transcribe',
        do_toc, sum_levels, [lang] if sum_levels else [],
        folder.name, folder, folder.name,
        focus_keywords=focus_kw)
    print('\n  ✓ TOC/Zusammenfassung fertig.')


def _best_source(folder: Path):
    """Bevorzugt .srt, fällt auf .txt zurück (kein _orig, keine Übersetzung)."""
    srt = sorted(folder.glob('*.srt'))
    if srt: return srt[0]
    txt = [f for f in sorted(folder.glob('*.txt'))
           if '_orig.' not in f.name
           and not any(f'_{c}.' in f.name for c in ('de','en','fr','es','it','ru','zh','pl','nl','pt'))]
    return txt[0] if txt else None


@app.route('/status/<job_id>')
def job_status(job_id):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({'state': 'unknown'})
    return jsonify({
        'state':    'done' if job.done.is_set() else 'running',
        'od':       job.output_dir,
        'tx_path':  job.transcript_path,
    })


_IMG_MIME = {'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png',
             '.gif':'image/gif','.webp':'image/webp','.svg':'image/svg+xml'}

@app.route('/file')
def read_file():
    path = request.args.get('path', '').strip()
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ('Datei nicht gefunden', 404)
    mime = _IMG_MIME.get(p.suffix.lower())
    if mime:
        return send_file(str(p), mimetype=mime)
    try:
        from flask import Response as _R
        return _R(p.read_text(encoding='utf-8', errors='replace'), mimetype='text/plain; charset=utf-8')
    except Exception as e:
        return (str(e), 500)


_OUTPUT_BASE      = Path(os.environ.get('OUTPUT_DIR', '/data/output'))
_TRSKR_FILES_ROOT = Path(os.environ.get('FILES_ROOT', '/data/tul_files'))
_NC_TARGETS_F  = _OUTPUT_BASE / 'nc_targets.json'

def _register_url_input(data: dict, user_id: str) -> None:
    """Registriert URL(s) als DV-Eingabedatei (text/plain) für späteren Reuse.
    Bleibt bis zur manuellen Löschung — wird NICHT in _input_file_ids aufgenommen."""
    import mimetypes as _mt
    st = data.get('source_type')
    if st == 'url':
        url = (data.get('url') or '').strip()
        if not url:
            return
        url_id = wt.extract_url_id(url) or wt.slugify(url)[:12] or 'url'
        filename = f'url_{url_id}.txt'
        content  = url
    elif st == 'batch':
        entries = [l.strip() for l in (data.get('batch_text') or '').splitlines()
                   if l.strip() and not l.strip().startswith('#')]
        url_entries = [e for e in entries if e.startswith('http')]
        if not url_entries:
            return
        first_id = wt.extract_url_id(url_entries[0]) or 'batch'
        filename = f'url-batch_{first_id}.txt'
        content  = '\n'.join(entries)
    else:
        return

    dest_dir = Path(_FILES_ROOT) / _TOOL_NAME / user_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    fid  = _uid()
    dest = dest_dir / f'{fid}.txt'
    dest.write_text(content, encoding='utf-8')
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO files'
            '(id,user_id,tool,filename,path,size,mime,category,file_type,retention,created_at,expires_at)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (fid, user_id, _TOOL_NAME, filename, str(dest), dest.stat().st_size,
             'text/plain', 'input', 'url-ref', '1w', _now(), _ret_exp('1w'))
        )


def _trskr_file_type(name: str) -> str:
    """Leitet file_type aus Dateiname ab (tul-mime format-Teil für trskr-Ausgaben)."""
    n = name.lower()
    if '_toc_' in n and n.endswith('.md'):
        return 'toc'
    if '_summary_' in n and n.endswith('.md'):
        return 'summary'
    if n == 'index.md':
        return 'index'
    if n.endswith('.vtt') or n.endswith('.srt'):
        return 'subtitle'
    if n.endswith('.txt'):
        return 'transcription-output'
    if n.endswith('.md'):
        return 'document'
    return 'media'


def _register_dir_outputs(out_dir: Path, user_id: str) -> None:
    """Registriert Ausgabe-Dateien eines Ordners in der DB (idempotent)."""
    import mimetypes as _mt
    if not out_dir.is_dir():
        return
    with get_conn() as conn:
        for f in sorted(out_dir.iterdir()):
            if not f.is_file():
                continue
            if conn.execute(
                'SELECT id FROM files WHERE path=? AND tool=?', (str(f), _TOOL_NAME)
            ).fetchone():
                continue
            fid       = _uid()
            mime      = _mt.guess_type(f.name)[0] or 'application/octet-stream'
            file_type = _trskr_file_type(f.name)
            conn.execute(
                'INSERT INTO files'
                '(id,user_id,tool,filename,path,size,mime,category,file_type,retention,created_at,expires_at)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (fid, user_id, _TOOL_NAME, f.name, str(f), f.stat().st_size, mime,
                 'output', file_type, '1mo', _now(), _ret_exp('1mo'))
            )


def _register_tul_outputs(job: _Job, user_id: str) -> None:
    """Catch-all nach Job-Ende: registriert alle noch nicht erfassten Ausgabe-Dateien."""
    if not job.output_dir or not user_id:
        return
    if job.batch_output_dirs:
        out_dirs = [Path(d) for d in job.batch_output_dirs]
    else:
        out_dirs = [Path(job.output_dir)]
    for d in out_dirs:
        _register_dir_outputs(d, user_id)


def _after_job_cleanup(file_ids: list, user_id: str):
    """Nach Job: task-Retention-Dateien löschen, andere auf listed=0 setzen."""
    if not file_ids or not user_id:
        return
    with get_conn() as conn:
        for fid in file_ids:
            row = conn.execute(
                'SELECT * FROM files WHERE id=? AND user_id=? AND tool=?',
                (fid, user_id, _TOOL_NAME)
            ).fetchone()
            if not row:
                continue
            if row['retention'] == 'task':
                try:
                    Path(row['path']).unlink(missing_ok=True)
                except Exception:
                    pass
                conn.execute('DELETE FROM files WHERE id=?', (fid,))
            else:
                conn.execute('UPDATE files SET listed=0 WHERE id=?', (fid,))


def _load_nc_targets():
    return json.loads(_NC_TARGETS_F.read_text()) if _NC_TARGETS_F.exists() else []

def _save_nc_targets(lst):
    _OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
    _NC_TARGETS_F.write_text(json.dumps(lst, ensure_ascii=False, indent=2))

@app.route('/nc-targets')
def nc_targets_list():
    return jsonify(_load_nc_targets())

@app.route('/nc-targets', methods=['POST'])
def nc_targets_add():
    body  = request.json or {}
    label = (body.get('label') or '').strip()
    url   = (body.get('url')   or '').strip()
    if not label or not url:
        return jsonify({'error': 'Label und URL erforderlich.'}), 400
    if not re.match(r'https?://.+/s/\w+', url):
        return jsonify({'error': 'Kein gültiger NC-Share-Link (https://host/s/TOKEN).'}), 400
    targets = _load_nc_targets()
    tid = str(uuid.uuid4())[:8]
    targets.append({'id': tid, 'label': label, 'url': url})
    _save_nc_targets(targets)
    return jsonify({'id': tid}), 201

@app.route('/nc-targets/<tid>', methods=['DELETE'])
def nc_targets_delete(tid):
    _save_nc_targets([t for t in _load_nc_targets() if t['id'] != tid])
    return ('', 204)

def _nc_upload(share_url: str, filename: str, filepath: Path):
    m = re.match(r'(https?://[^/]+)/s/([^/?#]+)', share_url.rstrip('/'))
    if not m:
        raise ValueError(f'Ungültiger NC-Link: {share_url}')
    host, token = m.group(1), m.group(2)
    import urllib.request as urlreq
    req_obj = urlreq.Request(
        f'{host}/public.php/dav/files/{token}/{filename}',
        data=filepath.read_bytes(), method='PUT')
    with urlreq.urlopen(req_obj, timeout=120):
        pass

_SRC_EXTS = {'.mp4','.mkv','.webm','.mp3','.m4a','.wav','.ogg','.opus','.flac','.aac'}

def _job_files(job, skip_src=False):
    d = Path(job.output_dir)
    return [f for f in sorted(d.iterdir())
            if f.is_file() and not (skip_src and f.suffix.lower() in _SRC_EXTS)]

@app.route('/send/<job_id>', methods=['POST'])
def send_to_nc(job_id):
    job = _jobs.get(job_id)
    if not job or not job.output_dir:
        return jsonify({'error': 'Job nicht gefunden.'}), 404
    body      = request.json or {}
    tid       = body.get('target_id')
    skip_src  = bool(body.get('skip_src'))
    targets   = {t['id']: t for t in _load_nc_targets()}
    if tid not in targets:
        return jsonify({'error': 'Ziel nicht gefunden.'}), 404
    share_url = targets[tid]['url']
    sent, errors = [], []
    for f in _job_files(job, skip_src):
        try:
            _nc_upload(share_url, f.name, f)
            sent.append(f.name)
        except Exception as e:
            errors.append(f'{f.name}: {e}')
    if errors and not sent:
        return jsonify({'error': '; '.join(errors)}), 500
    return jsonify({'sent': sent, 'errors': errors, 'share_url': share_url})

@app.route('/zip/<job_id>')
def zip_download(job_id):
    import zipfile, io
    job = _jobs.get(job_id)
    if not job or not job.output_dir:
        return ('Job nicht gefunden', 404)
    skip_src = request.args.get('skip_src') == '1'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in _job_files(job, skip_src):
            zf.write(f, f.name)
    buf.seek(0)
    dirname = Path(job.output_dir).name
    return send_file(buf, mimetype='application/zip',
                     as_attachment=True, download_name=f'{dirname}.zip')



@app.route('/open')
def open_file():
    import subprocess
    path = request.args.get('path', '').strip()
    if not path or not Path(path).exists():
        return ('Datei nicht gefunden', 404)
    subprocess.Popen(['xdg-open', path])
    return ('', 204)


@app.route('/upload', methods=['POST'])
def upload_file():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'Keine Datei.'}), 400
    orig_name = Path(f.filename).name
    safe_stem = re.sub(r'[^\w\-]', '_', Path(f.filename).stem)[:40]
    # Für Quelle-Upload: in tmp (Container verwaltet Löschung nach Job)
    tmp_dir = Path(tempfile.mkdtemp(prefix='up_', dir='/tmp'))
    filepath = tmp_dir / orig_name
    f.save(str(filepath))
    return jsonify({'path': str(filepath), 'name': orig_name})


@app.route('/stop/<job_id>', methods=['POST'])
def stop_job(job_id):
    job = _jobs.get(job_id)
    if job:
        job.stop.set()
    return ('', 204)

@app.route('/soft-stop/<job_id>', methods=['POST'])
def soft_stop_job(job_id):
    """Bricht Transkription ab, verarbeitet aber bereits gesammelte Segmente weiter."""
    job = _jobs.get(job_id)
    if job:
        job.soft_stop.set()
        job.stop.set()
    return ('', 204)


@app.route('/yt-update', methods=['POST'])
def yt_update():
    import importlib.metadata
    r = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '-q', '--upgrade', 'yt-dlp', '--break-system-packages'],
        capture_output=True, text=True, timeout=120
    )
    if r.returncode != 0:
        return jsonify({'ok': False, 'msg': (r.stderr or r.stdout).strip() or 'Update fehlgeschlagen'})
    try:
        ver = importlib.metadata.version('yt-dlp')
    except Exception:
        ver = '?'
    return jsonify({'ok': True, 'msg': f'yt-dlp → {ver}'})


@app.route('/files/cleanup', methods=['POST'])
@require_login
def files_cleanup():
    """Bereinigt verwaiste DB-Einträge und alte UUID-Kopien in tul_files/output/."""
    import shutil as _shutil
    uid_val = request.tul_user['id']
    removed_db = 0
    removed_files = 0

    with get_conn() as conn:
        rows = conn.execute(
            'SELECT id, path FROM files WHERE user_id=? AND tool=?',
            (uid_val, _TOOL_NAME)
        ).fetchall()
        for row in rows:
            if not Path(row['path']).exists():
                conn.execute('DELETE FROM files WHERE id=?', (row['id'],))
                removed_db += 1

    legacy_dir = _TRSKR_FILES_ROOT / 'output' / uid_val
    if legacy_dir.exists():
        for f in legacy_dir.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                    removed_files += 1
                except Exception:
                    pass
        try:
            legacy_dir.rmdir()
        except Exception:
            pass

    return jsonify({'ok': True, 'removed_db': removed_db, 'removed_files': removed_files,
                    'msg': f'{removed_db} DB-Einträge + {removed_files} alte Kopien entfernt'})


@app.route('/files/rescan', methods=['POST'])
@require_login
def files_rescan():
    """Registriert alle Dateien in /data/output/ die noch nicht in der DB sind."""
    import mimetypes as _mt
    uid_val = request.tul_user['id']
    added = 0
    if not _OUTPUT_BASE.exists():
        return jsonify({'ok': True, 'added': 0, 'msg': 'Output-Verzeichnis leer'})
    with get_conn() as conn:
        for subdir in sorted(_OUTPUT_BASE.iterdir()):
            if not subdir.is_dir():
                continue
            for f in sorted(subdir.iterdir()):
                if not f.is_file():
                    continue
                existing = conn.execute(
                    'SELECT id FROM files WHERE path=? AND tool=?', (str(f), _TOOL_NAME)
                ).fetchone()
                if existing:
                    continue
                fid  = _uid()
                mime = _mt.guess_type(f.name)[0] or 'application/octet-stream'
                conn.execute(
                    'INSERT INTO files'
                    '(id,user_id,tool,filename,path,size,mime,category,retention,created_at,expires_at)'
                    ' VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (fid, uid_val, _TOOL_NAME, f.name, str(f), f.stat().st_size, mime,
                     'output', '1mo', _now(), _ret_exp('1mo'))
                )
                added += 1
    return jsonify({'ok': True, 'added': added,
                    'msg': f'{added} Datei(en) nachregistriert'})


@app.route('/logout', methods=['POST'])
def logout():
    return clear_token_cookie(make_response(jsonify({'ok': True})))


if __name__ == '__main__':
    import argparse, webbrowser
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT', 7860)))
    ap.add_argument('--no-browser', action='store_true')
    args = ap.parse_args()

    threading.Thread(target=wt.update_ytdlp, daemon=True).start()
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f'http://localhost:{args.port}')).start()
    print(f'  Panel: http://localhost:{args.port}')
    host = '0.0.0.0' if os.environ.get('DOCKER') else '127.0.0.1'
    app.run(host=host, port=args.port, debug=False, threaded=True)

/* tul-files.js — Datei-Verwaltung für tul.yourdomain.example (v2)
 *
 * API:
 *   tulFiles.init(opts)  — Modal + Button einbetten
 *   tulFiles.open()      — Modal öffnen
 *   tulFiles.close()     — Modal schließen
 *
 * opts:
 *   subpath    {string}    Flask-Subpath, z.B. '/trskr'
 *   tool       {string}    'trskr'|'lern'|'kurv'|'popt'|'bild'|'nach'
 *   ncEnabled  {boolean}   NC-Abschnitt zeigen (Platzhalter, noch nicht impl.)
 *   onSelect   {function}  Callback(fileIds) bei "Übernehmen"
 */
(function (global) {
'use strict';

// ── Gruppen-Konfiguration pro Tool ────────────────────────────────────────────
// Jede Gruppe hat: label (string) + match(file→bool).
// Letzter Eintrag ist immer Catch-All.

const GROUPS = {
  trskr: {
    input: [
      { label: 'Quelldateien', match: f => /^(audio|video)/i.test(f.mime || '') },
      { label: 'Batch / URLs', match: () => true },
    ],
    output: [
      { label: 'Transkripte', match: f => /\.(txt|srt|vtt)$/i.test(f.filename || '') },
      { label: 'Sonstiges',   match: () => true },
    ],
  },
  lern: {
    input: [
      { label: 'Kartendaten',  match: f => /\.csv$/i.test(f.filename || '') },
      { label: 'Bilder',       match: f => /^image/i.test(f.mime || '') },
      { label: 'Schriftarten', match: f => /\.(ttf|otf|woff2?)$/i.test(f.filename || '') },
      { label: 'Sonstiges',    match: () => true },
    ],
    output: [
      { label: 'Karten-PDFs', match: f => /\.pdf$/i.test(f.filename || '') },
      { label: 'Sonstiges',   match: () => true },
    ],
  },
  kurv: {
    groupByGrp: true,
    input: [
      { label: 'Messdaten', match: f => /\.csv$/i.test(f.filename || '') },
      { label: 'Sonstiges', match: () => true },
    ],
    output: [
      { label: 'Diagramme', match: f => /\.(pdf|html?|svg|png)$/i.test(f.filename || '') },
      { label: 'Sonstiges', match: () => true },
    ],
  },
  popt: {
    input:  [{ label: 'PDFs (Original)',  match: () => true }],
    output: [{ label: 'PDFs (optimiert)', match: () => true }],
  },
  bild: {
    input: [
      { label: 'Bilder',    match: f => /^image/i.test(f.mime || '') },
      { label: 'Sonstiges', match: () => true },
    ],
    output: [
      { label: 'HTML-Seiten', match: f => /\.html?$/i.test(f.filename || '') },
      { label: 'Sonstiges',   match: () => true },
    ],
  },
  nach: {
    input:  [{ label: 'Dokumente', match: () => true }],
    output: [],
  },
  buch: {
    input:  [{ label: 'PDFs', match: f => /\.pdf$/i.test(f.filename||'') }, { label: 'Sonstiges', match: () => true }],
    output: [{ label: 'Assemblagen', match: () => true }],
  },
};

// ── State ─────────────────────────────────────────────────────────────────────
let _sub = '', _tool = '', _onSelect = null, _onChange = null, _ncEnabled = false, _accept = null, _recycleOutput = false, _inputAction = null;
let _inFiles = [], _outFiles = [];
let _activeIds = new Set();
let _ncTargets = [], _ncSelId = '';
let _selIn = new Set(), _selOut = new Set();
let _extSources = [];    // [{id, label, url, toEntry, _files:[]}]
let _activeExtTab = null; // null = 'Eigene', else extSource.id
let _extExcluded = {};   // {srcId: Set<entryId>}
let _onWire = null;
let _mkanMultiUrl = null; // /api/mkan-cards-for-tool — auto-discovered card tabs
let _mkanPushCards = []; // [{card_id, title}] — output push targets
let _mkanPushCardId = null; // selected push target
let _openGroups = new Set();

// ── Hover-Preview ─────────────────────────────────────────────────────────────
let _prevTimer = null;
let _prevHideTimer = null;
let _prevEl = null; // aktuell gehovertes Element

function _getHoverEl() {
  let el = document.getElementById('tlf-hover-prev');
  if (!el) {
    el = document.createElement('div');
    el.id = 'tlf-hover-prev';
    el.addEventListener('mouseenter', () => { clearTimeout(_prevHideTimer); });
    el.addEventListener('mouseleave', () => { _hidePreview(); });
    document.body.appendChild(el);
  }
  return el;
}

function _isOffice(filename) {
  return /\.(docx|odt|xlsx|ods|xls|pptx|odp|doc)$/i.test(filename || '');
}

function _isImage(mime) {
  return (mime || '').startsWith('image/');
}

function _isAudio(mime) {
  return (mime || '').startsWith('audio/');
}

function _isPdf(mime, filename) {
  return mime === 'application/pdf' || /\.pdf$/i.test(filename || '');
}

function _isText(mime) {
  return (mime || '').startsWith('text/') || mime === 'application/json';
}

function _positionPreview(targetEl) {
  const box = targetEl.getBoundingClientRect();
  const el = _getHoverEl();
  const vw = window.innerWidth, vh = window.innerHeight;
  let left = box.right + 10;
  let top = box.top;
  if (left + 380 > vw) left = Math.max(4, box.left - 380);
  if (top + 320 > vh) top = Math.max(4, vh - 320);
  el.style.left = left + 'px';
  el.style.top  = top  + 'px';
}

let _pdfJsReady = null;
function _loadPdfJs() {
  if (_pdfJsReady) return _pdfJsReady;
  _pdfJsReady = new Promise((resolve, reject) => {
    if (typeof pdfjsLib !== 'undefined') { resolve(); return; }
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3/build/pdf.min.js';
    s.onload = () => {
      pdfjsLib.GlobalWorkerOptions.workerSrc =
        'https://cdn.jsdelivr.net/npm/pdfjs-dist@3/build/pdf.worker.min.js';
      resolve();
    };
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return _pdfJsReady;
}

async function _renderPdfPreview(el, src) {
  try {
    await _loadPdfJs();
    const resp = await fetch(src);
    if (!resp.ok) { el.className = ''; return; }
    const data = await resp.arrayBuffer();
    const pdf  = await pdfjsLib.getDocument({ data }).promise;
    const page = await pdf.getPage(1);
    const vp   = page.getViewport({ scale: 1 });
    const scale = Math.min(340 / vp.width, 280 / vp.height, 1.5);
    const vps  = page.getViewport({ scale });
    const canvas = document.createElement('canvas');
    canvas.width  = vps.width;
    canvas.height = vps.height;
    await page.render({ canvasContext: canvas.getContext('2d'), viewport: vps }).promise;
    el.innerHTML = '';
    el.appendChild(canvas);
  } catch {
    el.className = '';
  }
}

async function _showPreview(targetEl, fileId, filename, mime, isMkan) {
  const el = _getHoverEl();
  el.className = 'visible';
  el.innerHTML = '<pre style="color:var(--text,#ccc);opacity:.5">…</pre>';
  _positionPreview(targetEl);

  const _mkanSrc = (id) => '/api/mkan-file?att_id=' + encodeURIComponent(id);
  const _ownSrc  = (id) => _sub + '/files/' + id + '/inline';
  try {
    if (_isImage(mime)) {
      const src = isMkan ? _mkanSrc(fileId) : _ownSrc(fileId);
      el.innerHTML = '';
      const img = document.createElement('img');
      img.src = src;
      el.appendChild(img);
    } else if (_isPdf(mime, filename)) {
      const src = isMkan ? _mkanSrc(fileId) : _ownSrc(fileId);
      await _renderPdfPreview(el, src);
    } else if (_isAudio(mime)) {
      const src = isMkan ? _mkanSrc(fileId) : _ownSrc(fileId);
      el.innerHTML = '';
      const audio = document.createElement('audio');
      audio.controls = true;
      audio.src = src;
      el.appendChild(audio);
    } else if (_isOffice(filename)) {
      if (!isMkan) { el.className = ''; return; } // office-Vorschau nur für mkan
      const resp = await fetch('/api/mkan-preview-text?att_id=' + encodeURIComponent(fileId));
      if (!resp.ok) { el.className = ''; return; }
      const data = await resp.json();
      el.innerHTML = '';
      const pre = document.createElement('pre');
      pre.textContent = data.text || '(leer)';
      el.appendChild(pre);
      if (data.truncated) {
        const trunc = document.createElement('div');
        trunc.className = 'tlf-prev-trunc';
        trunc.textContent = '… (gekürzt)';
        el.appendChild(trunc);
      }
    } else if (_isText(mime)) {
      const src = isMkan ? _mkanSrc(fileId) : _ownSrc(fileId);
      const resp = await fetch(src);
      if (!resp.ok) { el.className = ''; return; }
      const text = await resp.text();
      el.innerHTML = '';
      const pre = document.createElement('pre');
      pre.textContent = text.slice(0, 3000);
      el.appendChild(pre);
      if (text.length > 3000) {
        const trunc = document.createElement('div');
        trunc.className = 'tlf-prev-trunc';
        trunc.textContent = '… (gekürzt)';
        el.appendChild(trunc);
      }
    } else {
      el.className = ''; // kein Vorschau-Typ
    }
  } catch {
    el.className = '';
  }
}

function _hidePreview() {
  clearTimeout(_prevHideTimer);
  _prevHideTimer = setTimeout(() => {
    const el = document.getElementById('tlf-hover-prev');
    if (el) el.className = '';
  }, 120);
}

function attachPreview(rowEl, fileId, filename, mime, isMkan) {
  rowEl.addEventListener('mouseenter', () => {
    clearTimeout(_prevTimer);
    _prevEl = rowEl;
    _prevTimer = setTimeout(() => {
      if (_prevEl === rowEl) _showPreview(rowEl, fileId, filename, mime, isMkan);
    }, 300);
  });
  rowEl.addEventListener('mouseleave', () => {
    clearTimeout(_prevTimer);
    if (_prevEl === rowEl) _prevEl = null;
    _hidePreview();
  });
}
let _modalTheme = 'light';
let _grayLevel = 0;

// ── Modal-Themes (graustufen, unabhängig vom Panel-Theme) ─────────────────────
const _MODAL_THEMES = {
  light: {
    '--tlf-bg':      '#ffffff', '--tlf-hd':      '#f5f5f5', '--tlf-brd':     '#e4e4e4',
    '--tlf-text':    '#1a1a1a', '--tlf-muted':   '#888888', '--tlf-dim':     '#c0c0c0',
    '--tlf-chip-bg': '#f0f0f0', '--tlf-chip-br': '#d4d4d4', '--tlf-chip-tx': '#aaaaaa',
    '--tlf-chip-on': '#1a1a1a', '--tlf-chip-on-tx': '#ffffff',
  },
  dark: {
    '--tlf-bg':      '#1e1e1e', '--tlf-hd':      '#252525', '--tlf-brd':     '#383838',
    '--tlf-text':    '#e0e0e0', '--tlf-muted':   '#909090', '--tlf-dim':     '#555555',
    '--tlf-chip-bg': '#2a2a2a', '--tlf-chip-br': '#404040', '--tlf-chip-tx': '#666666',
    '--tlf-chip-on': '#e0e0e0', '--tlf-chip-on-tx': '#1a1a1a',
  },
};

function computeGrayTheme(L) {
  const g = v => `hsl(0,0%,${Math.min(100, Math.max(0, v))}%)`;
  if (L < 40) {
    return {
      '--tlf-bg':      g(L),      '--tlf-hd':      g(L + 3),
      '--tlf-brd':     g(L + 10), '--tlf-text':    g(88),
      '--tlf-muted':   g(60),     '--tlf-dim':     g(L + 20),
      '--tlf-chip-bg': g(L + 5),  '--tlf-chip-br': g(L + 13),
      '--tlf-chip-tx': g(42),     '--tlf-chip-on': g(85),     '--tlf-chip-on-tx': g(12),
    };
  } else {
    return {
      '--tlf-bg':      g(L),      '--tlf-hd':      g(L - 4),
      '--tlf-brd':     g(L - 12), '--tlf-text':    g(10),
      '--tlf-muted':   g(53),     '--tlf-dim':     g(L - 22),
      '--tlf-chip-bg': g(L - 6),  '--tlf-chip-br': g(L - 18),
      '--tlf-chip-tx': g(67),     '--tlf-chip-on': g(10),     '--tlf-chip-on-tx': g(92),
    };
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function isFileAccepted(f) {
  if (!_accept) return true;
  const accepts = _accept.split(',').map(s => s.trim().toLowerCase());
  return accepts.some(a => {
    if (a.startsWith('.')) return f.name.toLowerCase().endsWith(a);
    return f.type.toLowerCase() === a || f.type.toLowerCase().startsWith(a.replace('/*', ''));
  });
}

function fmtSize(b) {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
  return (b / 1048576).toFixed(1) + ' MB';
}
function fmtDate(s) {
  if (!s) return '';
  const d = new Date(typeof s === 'number' ? s * 1000 : String(s).replace(' ', 'T'));
  if (isNaN(d)) return '';
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getDate())}.${pad(d.getMonth()+1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}


// ── CSS ───────────────────────────────────────────────────────────────────────
function injectStyles() {
  if (document.getElementById('tlf-style')) return;
  const s = document.createElement('style');
  s.id = 'tlf-style';
  s.textContent = `
/* === tul-files overlay === */

/* ── Modal-eigene Graustufen — unabhängig vom Panel-Theme ────────────────── */
:root {
  --tlf-bg:      #ffffff;
  --tlf-hd:      #f5f5f5;
  --tlf-brd:     #e4e4e4;
  --tlf-text:    #1a1a1a;
  --tlf-muted:   #888888;
  --tlf-dim:     #c0c0c0;
  --tlf-chip-bg: #f0f0f0;
  --tlf-chip-br: #d4d4d4;
  --tlf-chip-tx: #aaaaaa;
  --tlf-chip-on: #1a1a1a;
  --tlf-chip-on-tx: #ffffff;
}

.tlf-overlay {
  display: none; position: fixed; inset: 0; z-index: 2000;
  background: rgba(0,0,0,.55);
  align-items: center; justify-content: center;
}
.tlf-overlay.open { display: flex; }

/* dialog */
.tlf-dialog {
  width: min(100vh, 96vw); height: min(100vh, 96vw);
  max-width: 98vw; max-height: 98vh;
  background: var(--tlf-bg); color: var(--tlf-text);
  border: 1px solid var(--tlf-brd);
  display: flex; flex-direction: column;
  font-family: "Segoe UI", system-ui, sans-serif;
  font-size: 13px; line-height: 1.4;
  overflow: hidden;
}

/* header */
.tlf-hd {
  display: flex; align-items: center; gap: 10px;
  padding: 11px 16px;
  border-bottom: 1px solid var(--tlf-brd);
  background: var(--tlf-hd);
  flex-shrink: 0;
}
.tlf-hd-title {
  flex: 1; font-size: 10px;
  text-transform: uppercase; letter-spacing: .14em;
  color: var(--tlf-dim); font-weight: 700;
}
.tlf-hd-close, .tlf-hd-theme {
  background: none; border: none;
  color: var(--tlf-dim); line-height: 1;
  cursor: pointer; padding: 2px 5px;
  transition: color .12s; border-radius: 3px;
}
.tlf-hd-close { font-size: 20px; }
.tlf-hd-theme { font-size: 13px; }
.tlf-hd-close:hover, .tlf-hd-theme:hover { color: var(--tlf-text); }

/* gray panel */
.tlf-gp {
  position: fixed; z-index: 3000;
  border: 1px solid #444; border-radius: 6px;
  padding: 12px 14px; width: 190px;
  box-shadow: 0 4px 16px rgba(0,0,0,.45);
  font-family: "Segoe UI", system-ui, sans-serif; font-size: 12px;
}
.tlf-gp-lbl { display: flex; justify-content: space-between; margin-bottom: 6px; }
.tlf-gp-sw {
  margin-top: 10px; cursor: pointer; text-align: center;
  padding: 3px 6px; border-radius: 3px; font-size: 12px;
  border: 1px solid; transition: opacity .15s;
}

/* body = two columns */
.tlf-body {
  display: flex; flex: 1;
  overflow: hidden; min-height: 0;
}

/* column */
.tlf-col {
  flex: 1; display: flex; flex-direction: column;
  overflow: hidden; min-width: 0;
}
.tlf-col-hd {
  padding: 13px 20px 6px;
  font-size: 9px; text-transform: uppercase;
  letter-spacing: .16em; color: var(--tlf-dim);
  font-weight: 700; flex-shrink: 0;
}
.tlf-col-body {
  flex: 1; overflow-y: auto;
  padding: 0 20px 16px;
  scrollbar-width: thin; scrollbar-color: var(--tlf-brd) transparent;
}
.tlf-col-body::-webkit-scrollbar { width: 3px; }
.tlf-col-body::-webkit-scrollbar-thumb { background: var(--tlf-brd); border-radius: 2px; }

/* vertical divider */
.tlf-div {
  width: 1px; background: var(--tlf-brd);
  margin: 90px 0;
  flex-shrink: 0;
  align-self: stretch;
}

/* drop zone */
.tlf-dz {
  border: 1px dashed var(--tlf-brd);
  border-radius: 4px; padding: 12px 14px;
  text-align: center; color: var(--tlf-dim);
  font-size: 11px; cursor: pointer;
  transition: border-color .15s, color .15s;
  margin-bottom: 16px; user-select: none;
}
.tlf-dz:hover, .tlf-dz.over { border-color: var(--tlf-muted); color: var(--tlf-muted); }
.tlf-dz u { color: var(--tlf-muted); }
.tlf-dz input { display: none; }

/* group */
.tlf-grp { margin-bottom: 14px; }
.tlf-grp-lbl {
  font-size: 9px; text-transform: uppercase;
  letter-spacing: .12em; color: var(--tlf-dim);
  margin-bottom: 7px; padding-bottom: 5px;
  border-bottom: 1px solid var(--tlf-brd);
}

/* file row */
.tlf-row {
  padding: 7px 0;
  border-bottom: 1px solid var(--tlf-brd);
}
.tlf-row:last-child { border-bottom: none; }
.tlf-row-top {
  display: flex; align-items: baseline; gap: 8px;
  margin-bottom: 4px;
}
.tlf-fname {
  flex: 1; min-width: 0; font-size: 12px; color: var(--tlf-text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  font-family: "Consolas", "Menlo", monospace;
}
.tlf-fsize { font-size: 10px; color: var(--tlf-dim); flex-shrink: 0; }

/* retention chips + action chips row */
.tlf-row-bot { display: flex; align-items: center; gap: 5px; }
.tlf-chips { display: flex; gap: 3px; flex: 1; }

/* ── Chip-Basis (Retention + Listing) ────────────────────────────────────── */
.tlf-chip {
  padding: 2px 6px; font-size: 10px;
  border: 1px solid var(--tlf-chip-br);
  background: var(--tlf-chip-bg);
  color: var(--tlf-chip-tx);
  border-radius: 3px; cursor: pointer;
  transition: border-color .1s, color .1s, background .1s;
  white-space: nowrap; line-height: 1.4;
}
.tlf-chip:hover { border-color: #888; color: #555; background: #e8e8e8; }
.tlf-chip.on { border-color: var(--tlf-chip-on); background: var(--tlf-chip-on); color: var(--tlf-chip-on-tx); }
.tlf-chip-list { border-style: dashed !important; }
.tlf-chip-list.on { border-style: solid !important; }

/* ── Action-Chips (recycling, NC, download, delete, edit) ────────────────── */
.tlf-chip-act {
  padding: 2px 6px; font-size: 10px;
  border: 1px solid var(--tlf-chip-br);
  background: none; color: var(--tlf-dim);
  border-radius: 3px; cursor: pointer;
  transition: border-color .1s, color .1s;
  white-space: nowrap; line-height: 1.4;
  flex-shrink: 0; text-decoration: none; display: inline-block;
}
.tlf-chip-act:hover         { border-color: var(--tlf-muted); color: var(--tlf-muted); }
.tlf-chip-act.recy:hover    { border-color: #2a882a; color: #2a882a; }
.tlf-chip-act.nc:hover      { border-color: #3a6aaa; color: #3a6aaa; }
.tlf-chip-act.del:hover     { border-color: #c03030; color: #c03030; }

/* custom days chip wrapper */
.tlf-cdays { position: relative; display: inline-flex; align-items: center; }
.tlf-dinput {
  position: absolute; left: 0; top: -1px;
  width: 46px; padding: 2px 5px;
  background: var(--tlf-bg); border: 1px solid var(--tlf-chip-on);
  color: var(--tlf-text); border-radius: 3px; font-size: 10px;
  -moz-appearance: textfield; appearance: textfield; outline: none;
}
.tlf-dinput::-webkit-inner-spin-button,
.tlf-dinput::-webkit-outer-spin-button { -webkit-appearance: none; }

/* unlisted row */
.tlf-row-unlisted .tlf-fname { color: var(--tlf-dim); }
.tlf-row-unlisted .tlf-fsize { color: var(--tlf-dim); }

/* active file row */
.tlf-row-active { background: #fafafa; }
.tlf-active-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--tlf-muted); flex-shrink: 0; margin-right: 2px;
  display: inline-block; vertical-align: middle;
}

/* empty */
.tlf-empty {
  text-align: center; color: var(--tlf-dim);
  padding: 28px 10px; font-size: 11px;
}

/* toast */
#tlf-toast {
  position: fixed; bottom: 22px; left: 50%;
  transform: translateX(-50%) translateY(8px);
  background: var(--tlf-chip-on); border: 1px solid #333;
  color: var(--tlf-chip-on-tx); border-radius: 4px;
  padding: 6px 14px; font-size: 11px;
  pointer-events: none; z-index: 3000;
  opacity: 0; transition: opacity .2s, transform .2s;
  font-family: "Segoe UI", system-ui, sans-serif;
}
#tlf-toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

/* NC bar (Ausgabe-Spalte) */
.tlf-nc-bar {
  border-top: 1px solid var(--tlf-brd); padding: 9px 0 4px;
  display: flex; align-items: center; gap: 5px; flex-wrap: wrap;
  flex-shrink: 0;
}
.tlf-nc-sel {
  flex: 1; min-width: 80px; max-width: 180px;
  padding: 3px 6px; font-size: 11px;
  border: 1px solid var(--tlf-brd); border-radius: 3px;
  background: var(--tlf-chip-bg); color: var(--tlf-text); outline: none;
}
.tlf-nc-sel:focus { border-color: var(--tlf-muted); }
.tlf-nc-btn {
  padding: 3px 9px; font-size: 11px; cursor: pointer;
  border: 1px solid var(--tlf-brd); border-radius: 3px;
  background: var(--tlf-chip-bg); color: var(--tlf-text); white-space: nowrap;
}
.tlf-nc-btn:hover { border-color: var(--tlf-muted); }
.tlf-nc-btn.send { background: var(--tlf-chip-on); color: var(--tlf-chip-on-tx); border-color: var(--tlf-chip-on); }
.tlf-nc-btn.send:hover { background: #333; }
.tlf-nc-lbl { font-size: 10px; color: var(--tlf-dim); }
.tlf-nc-status { font-size: 10px; color: var(--tlf-muted); flex-basis: 100%; min-height: 14px; }

/* mkan push bar (Ausgabe-Spalte) */
.tlf-mkan-bar {
  border-top: 1px solid var(--tlf-brd); padding: 9px 0 4px;
  display: flex; align-items: center; gap: 5px; flex-wrap: wrap;
  flex-shrink: 0;
}
.tlf-mkan-lbl { font-size: 10px; color: var(--tlf-dim); }
.tlf-mkan-name { font-size: 11px; color: var(--tlf-muted); }
.tlf-mkan-sel {
  flex: 1; min-width: 80px; max-width: 180px;
  padding: 3px 6px; font-size: 11px;
  border: 1px solid var(--tlf-brd); border-radius: 3px;
  background: var(--tlf-chip-bg); color: var(--tlf-text); outline: none;
}
.tlf-mkan-sel:focus { border-color: var(--tlf-muted); }
.tlf-mkan-status { font-size: 10px; color: var(--tlf-muted); flex-basis: 100%; min-height: 14px; }

/* mkan unlink footer (Fuß eines ext-Source-Tabs) */
.tlf-ext-footer {
  border-top: 1px solid var(--tlf-brd); padding: 7px 0 3px;
  display: flex; justify-content: flex-end;
}
.tlf-unlink-btn {
  font-size: 10px; padding: 2px 8px; cursor: pointer;
  border: 1px solid var(--tlf-brd); border-radius: 3px;
  background: none; color: var(--tlf-muted);
}
.tlf-unlink-btn:hover { color: #c44; border-color: #c44; }

/* hover file preview */
#tlf-hover-prev {
  display: none; position: fixed; z-index: 3000;
  max-width: 360px; max-height: 300px; overflow: hidden;
  background: var(--bg, #1e1e1e); border: 1px solid var(--border, #444);
  border-radius: 5px; box-shadow: 0 4px 16px rgba(0,0,0,.45);
  padding: 8px 10px; pointer-events: none;
}
#tlf-hover-prev.visible { display: block; }
#tlf-hover-prev img { max-width: 100%; max-height: 280px; object-fit: contain; display: block; }
#tlf-hover-prev audio { width: 100%; }
#tlf-hover-prev iframe { width: 320px; height: 260px; border: none; background: #fff; }
#tlf-hover-prev pre {
  margin: 0; font-size: 10px; line-height: 1.4;
  white-space: pre-wrap; word-break: break-word;
  color: var(--text, #ccc); max-height: 280px; overflow: hidden;
}
#tlf-hover-prev .tlf-prev-trunc {
  font-size: 9px; color: var(--muted, #888); text-align: right; margin-top: 4px;
}

/* NC management overlay */
#tlf-nc-overlay {
  display: none; position: fixed; inset: 0; z-index: 2100;
  background: rgba(0,0,0,.55);
  align-items: center; justify-content: center;
}
#tlf-nc-overlay.open { display: flex; }
.tlf-nc-box {
  width: min(480px, 94vw); max-height: 80vh;
  background: var(--tlf-bg); color: var(--tlf-text);
  border: 1px solid var(--tlf-brd); border-radius: 4px;
  display: flex; flex-direction: column;
  font-family: "Segoe UI", system-ui, sans-serif; font-size: 13px;
}
.tlf-nc-hd {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; border-bottom: 1px solid var(--tlf-brd);
  background: var(--tlf-hd); flex-shrink: 0;
}
.tlf-nc-hd-title { flex: 1; font-size: 12px; font-weight: 600; color: var(--tlf-text); }
.tlf-nc-body { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 14px; }
.tlf-nc-row {
  display: flex; align-items: center; gap: 7px;
  padding: 5px 0; border-bottom: 1px solid var(--tlf-brd); font-size: 12px;
}
.tlf-nc-row:last-child { border-bottom: none; }
.tlf-nc-row-lbl { font-weight: 600; white-space: nowrap; color: var(--tlf-text); }
.tlf-nc-row-url { flex: 1; color: var(--tlf-dim); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tlf-nc-add { display: flex; gap: 5px; margin-top: 10px; flex-wrap: wrap; }
.tlf-nc-add input {
  padding: 4px 8px; font-size: 12px;
  border: 1px solid var(--tlf-brd); border-radius: 3px;
  background: var(--tlf-bg); color: var(--tlf-text); outline: none;
}
.tlf-nc-add input:focus { border-color: var(--tlf-muted); }
.tlf-nc-add-lbl { width: 110px; }
.tlf-nc-add-url { flex: 1; min-width: 150px; }
.tlf-nc-add-btn { padding: 4px 12px; background: var(--tlf-chip-on); color: var(--tlf-chip-on-tx); border: none; border-radius: 3px; cursor: pointer; font-size: 12px; }
.tlf-nc-add-btn:hover { background: #333; }
.tlf-nc-add-status { font-size: 11px; color: var(--tlf-muted); flex-basis: 100%; min-height: 15px; }

/* text edit modal */
#tlf-ed-overlay {
  display: none; position: fixed; inset: 0; z-index: 2100;
  background: rgba(0,0,0,.6);
  align-items: center; justify-content: center;
}
#tlf-ed-overlay.open { display: flex; }
.tlf-ed-box {
  width: min(640px, 94vw); max-height: 86vh;
  background: var(--tlf-bg); color: var(--tlf-text);
  border: 1px solid var(--tlf-brd); border-radius: 4px;
  display: flex; flex-direction: column;
  font-family: "Segoe UI", system-ui, sans-serif; font-size: 13px;
}
.tlf-ed-hd {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; border-bottom: 1px solid var(--tlf-brd);
  background: var(--tlf-hd); flex-shrink: 0;
}
.tlf-ed-title { flex: 1; font-size: 12px; color: var(--tlf-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tlf-ed-ta {
  flex: 1; min-height: 0; resize: none;
  padding: 12px 14px; border: none; outline: none;
  font-family: "Consolas", "Menlo", monospace; font-size: 12px;
  line-height: 1.6; color: var(--tlf-text); background: var(--tlf-bg);
}
.tlf-ed-ft {
  display: flex; gap: 7px; justify-content: flex-end;
  padding: 9px 14px; border-top: 1px solid var(--tlf-brd);
  background: var(--tlf-hd); flex-shrink: 0;
}
.tlf-ed-btn {
  padding: 5px 14px; border-radius: 3px; border: 1px solid var(--tlf-brd);
  background: var(--tlf-bg); color: var(--tlf-text); font-size: 12px; cursor: pointer;
}
.tlf-ed-btn.primary { background: var(--tlf-chip-on); color: var(--tlf-chip-on-tx); border-color: var(--tlf-chip-on); }
.tlf-ed-btn:hover:not(.primary) { border-color: var(--tlf-muted); }
.tlf-ed-status { flex: 1; font-size: 11px; color: var(--tlf-muted); align-self: center; }

/* ── Ausgabe-Gruppen ──────────────────────────────────────────────────────── */
.tlf-grpout { margin-bottom: 10px; }
.tlf-grpout-hd {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 0; border-bottom: 1px solid var(--tlf-brd);
  cursor: pointer; user-select: none;
}
.tlf-grpout-hd:hover .tlf-grpout-tog { color: var(--tlf-muted); }
.tlf-grpout-tog { font-size: 9px; color: var(--tlf-dim); flex-shrink: 0; width: 10px; }
.tlf-grpout-name {
  flex: 1; min-width: 0; font-size: 12px; font-weight: 600; color: var(--tlf-text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  font-family: "Consolas", "Menlo", monospace;
}
.tlf-grpout-meta { font-size: 10px; color: var(--tlf-dim); flex-shrink: 0; white-space: nowrap; }
.tlf-grpout-acts { display: flex; gap: 3px; flex-shrink: 0; }
.tlf-grpout-body { padding-left: 12px; }
.tlf-grpout-body.tlf-collapsed { display: none; }

/* ── Externe Quellen-Tabs ────────────────────────────────────────────────── */
.tlf-srctabs {
  display: flex; gap: 0; margin: -2px -20px 10px;
  border-bottom: 1px solid var(--tlf-brd); flex-shrink: 0;
}
.tlf-srctab {
  flex: 1; padding: 6px 4px 7px; background: none; border: none;
  border-bottom: 2px solid transparent; color: var(--tlf-dim);
  cursor: pointer; font-size: 11px; text-align: center;
  transition: color .12s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.tlf-srctab:hover { color: var(--tlf-text); }
.tlf-srctab.on { color: var(--tlf-text); border-bottom-color: var(--tlf-muted); }

/* externe Quellen: kleines Onglet-Tab */
.tlf-srctab-ext {
  flex: 0 0 auto !important;
  padding: 1px 7px 2px !important;
  font-size: 9px !important;
  border: 1px solid var(--tlf-brd) !important;
  border-bottom: none !important;
  border-radius: 3px 3px 0 0 !important;
  margin: 0 2px -1px !important;
  align-self: flex-end;
  background: var(--tlf-chip-bg);
  letter-spacing: .02em;
}
.tlf-srctab-ext.on {
  background: var(--tlf-bg) !important;
  border-color: var(--tlf-muted) !important;
  color: var(--tlf-text) !important;
  border-bottom-color: transparent !important;
}

/* externe Quell-Zeile */
.tlf-ext-row {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 0; border-bottom: 1px solid var(--tlf-brd);
}
.tlf-ext-row:last-child { border-bottom: none; }
.tlf-ext-row.unlisted .tlf-ext-name { color: var(--tlf-dim); }
.tlf-ext-name {
  flex: 1; min-width: 0; font-size: 12px; color: var(--tlf-text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-family: "Consolas", "Menlo", monospace;
}
.tlf-ext-size { font-size: 10px; color: var(--tlf-dim); flex-shrink: 0; }
.tlf-wire-btn {
  padding: 2px 9px; font-size: 11px; flex-shrink: 0;
  border: 1px solid var(--tlf-brd); border-radius: 3px;
  background: none; color: var(--tlf-dim); cursor: pointer; white-space: nowrap;
}
.tlf-wire-btn:hover { border-color: var(--tlf-muted); color: var(--tlf-text); background: var(--tlf-chip-bg); }

/* checkboxen */
.tlf-cb { flex-shrink:0; width:13px; height:13px; cursor:pointer; accent-color:#555; margin-right:3px; }

/* batch bar */
.tlf-batch {
  border-top: 1px solid var(--tlf-brd); padding: 5px 20px;
  display: flex; align-items: center; gap: 6px; flex-shrink: 0;
  font-size: 11px; background: var(--tlf-hd);
}
.tlf-bat-btn {
  padding: 2px 8px; font-size: 11px; border-radius: 3px; cursor: pointer;
  border: 1px solid var(--tlf-chip-br); background: var(--tlf-chip-bg);
  color: var(--tlf-muted); white-space: nowrap;
}
.tlf-bat-btn.del { color: #c03030; border-color: #c03030; }
.tlf-bat-btn.del:hover { background: #c03030; color: #fff; }
.tlf-bat-btn.nc:hover  { background: var(--tlf-chip-on); color: var(--tlf-chip-on-tx); border-color: var(--tlf-chip-on); }
.tlf-ft { padding: 10px 16px; border-top: 1px solid var(--tlf-brd); display: flex; justify-content: flex-end; flex-shrink: 0; background: var(--tlf-hd); }
.tlf-ft-btn { background: var(--tlf-chip-on, #6366f1); color: var(--tlf-chip-on-tx, #fff); border: none; border-radius: 5px; padding: 6px 20px; font-size: .82rem; font-weight: 600; cursor: pointer; transition: opacity .14s; }
.tlf-ft-btn:hover { opacity: .82; }
`;
  document.head.appendChild(s);
}

// ── Modal HTML ────────────────────────────────────────────────────────────────
function injectModal() {
  if (document.getElementById('tlf-overlay')) return;
  const el = document.createElement('div');
  el.id = 'tlf-overlay';
  el.className = 'tlf-overlay';
  el.innerHTML =
    '<div class="tlf-dialog" id="tlf-dlg">' +
      '<div class="tlf-hd">' +
        '<span class="tlf-hd-title">Dateiverwaltung</span>' +
        '<button class="tlf-hd-theme" id="tlf-theme-chip" title="Dunkel-Modus">◑</button>' +
        '<button class="tlf-hd-close" id="tlf-cls" title="Schließen">×</button>' +
      '</div>' +
      '<div class="tlf-body">' +
        '<div class="tlf-col"><div class="tlf-col-hd">Eingabe</div><div class="tlf-col-body" id="tlf-cin"></div><div class="tlf-batch" id="tlf-in-sel" style="display:none"></div></div>' +
        '<div class="tlf-div"></div>' +
        '<div class="tlf-col"><div class="tlf-col-hd">Ausgabe</div><div class="tlf-col-body" id="tlf-cout"></div><div class="tlf-batch" id="tlf-out-sel" style="display:none"></div></div>' +
      '</div>' +
      '<div class="tlf-ft" id="tlf-ft" style="display:none"><button class="tlf-ft-btn" id="tlf-ubernehmen">Übernehmen</button></div>' +
    '</div>';
  document.body.appendChild(el);

  document.getElementById('tlf-cls').onclick = close;

  // Paste-Handler einmalig hier registrieren (nicht in makeDropZone — würde sich bei jedem Render akkumulieren)
  document.addEventListener('paste', e => {
    const overlay = document.getElementById('tlf-overlay');
    if (!overlay || !overlay.classList.contains('open')) return;
    // Paste in Input/Textarea-Felder nicht abfangen (z.B. NC-URL-Eingabe)
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
    const text = e.clipboardData.getData('text');
    if (text) {
      if (!_accept) uploadUrl(text.trim());  // URL-Upload nur für Werkzeuge ohne Typ-Filter
      return;
    }
    const items = [...(e.clipboardData.files || [])].filter(isFileAccepted);
    if (items.length) uploadFiles(items);
  });

  document.getElementById('tlf-theme-chip').onclick = function() {
    const gp = document.getElementById('tlf-gp');
    if (!gp) return;
    if (gp.style.display !== 'none' && gp.style.display !== '') { gp.style.display = 'none'; return; }
    const r = this.getBoundingClientRect();
    gp.style.top  = (r.bottom + 6) + 'px';
    gp.style.right = (window.innerWidth - r.right) + 'px';
    gp.style.display = 'block';
    document.getElementById('tlf-gp-sl').value = _grayLevel;
    document.getElementById('tlf-gp-val').textContent = _grayLevel > 0 ? _grayLevel + '%' : 'aus';
  };
  el.addEventListener('click', e => { if (e.target === el) close(); });

  // gray panel (body-level, shared across opens)
  if (!document.getElementById('tlf-gp')) {
    const gp = document.createElement('div');
    gp.id = 'tlf-gp';
    gp.className = 'tlf-gp';
    gp.style.display = 'none';
    gp.innerHTML =
      '<div class="tlf-gp-lbl">Grau-Helligkeit&ensp;<span id="tlf-gp-val">aus</span></div>' +
      '<input type="range" id="tlf-gp-sl" min="0" max="100" value="0" style="width:100%;margin:6px 0 0">' +
      '<div id="tlf-gp-sw" class="tlf-gp-sw">◑&ensp;dunkel</div>';
    document.body.appendChild(gp);
    document.getElementById('tlf-gp-sl').oninput = function() {
      _grayLevel = +this.value;
      document.getElementById('tlf-gp-val').textContent = _grayLevel > 0 ? _grayLevel + '%' : 'aus';
      applyModalTheme(_modalTheme);
      try { localStorage.setItem('tlf-gray:' + _tool, _grayLevel); } catch {}
    };
    document.getElementById('tlf-gp-sw').onclick = function() {
      if (_grayLevel > 0) return;
      applyModalTheme(_modalTheme === 'dark' ? 'light' : 'dark');
    };
    document.addEventListener('click', function(e) {
      const gp = document.getElementById('tlf-gp');
      if (gp && gp.style.display !== 'none' && !gp.contains(e.target) && e.target.id !== 'tlf-theme-chip') {
        gp.style.display = 'none';
      }
    }, true);
  }

  // toast
  const t = document.createElement('div');
  t.id = 'tlf-toast';
  document.body.appendChild(t);

  // edit modal
  if (!document.getElementById('tlf-ed-overlay')) {
    const ed = document.createElement('div');
    ed.id = 'tlf-ed-overlay';
    ed.innerHTML =
      '<div class="tlf-ed-box">' +
        '<div class="tlf-ed-hd">' +
          '<span class="tlf-ed-title" id="tlf-ed-title">Bearbeiten</span>' +
          '<button class="tlf-ed-btn" id="tlf-ed-cls">✕</button>' +
        '</div>' +
        '<textarea class="tlf-ed-ta" id="tlf-ed-ta" spellcheck="false"></textarea>' +
        '<div class="tlf-ed-ft">' +
          '<span class="tlf-ed-status" id="tlf-ed-status"></span>' +
          '<button class="tlf-ed-btn" onclick="(function(){document.getElementById(\'tlf-ed-overlay\').classList.remove(\'open\')})()">Abbrechen</button>' +
          '<button class="tlf-ed-btn primary" id="tlf-ed-save">Speichern</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(ed);
    document.getElementById('tlf-ed-cls').onclick = closeEditModal;
    ed.addEventListener('click', e => { if (e.target === ed) closeEditModal(); });
  }

  // NC management modal
  if (!document.getElementById('tlf-nc-overlay')) {
    const nc = document.createElement('div');
    nc.id = 'tlf-nc-overlay';
    nc.innerHTML =
      '<div class="tlf-nc-box">' +
        '<div class="tlf-nc-hd">' +
          '<span class="tlf-nc-hd-title">Nextcloud-Ziele</span>' +
          '<button class="tlf-ed-btn" id="tlf-nc-cls">✕</button>' +
        '</div>' +
        '<div class="tlf-nc-body">' +
          '<div id="tlf-nc-list"></div>' +
          '<div class="tlf-nc-add">' +
            '<input class="tlf-nc-add-lbl" id="tlf-nc-add-lbl" placeholder="Bezeichnung" type="text">' +
            '<input class="tlf-nc-add-url" id="tlf-nc-add-url" placeholder="https://…/s/TOKEN" type="text">' +
            '<button class="tlf-nc-add-btn" id="tlf-nc-add-btn">+ Hinzufügen</button>' +
            '<div class="tlf-nc-add-status" id="tlf-nc-add-status"></div>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(nc);
    document.getElementById('tlf-nc-cls').onclick = closeNcMgmt;
    nc.addEventListener('click', e => { if (e.target === nc) closeNcMgmt(); });
    document.getElementById('tlf-nc-add-btn').onclick = ncAdd;
    document.getElementById('tlf-nc-add-url').onkeydown = e => { if (e.key === 'Enter') ncAdd(); };
  }
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let _toastTimer;
function toast(msg) {
  const el = document.getElementById('tlf-toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), 2500);
}

// ── Ausgabe-Gruppen ───────────────────────────────────────────────────────────
function fileStem(filename) {
  const dot = filename.lastIndexOf('.');
  return dot > 0 ? filename.slice(0, dot) : filename;
}

const _STEM_FN = {
  trskr: n => {
    // Suffixe abziehen die trskr an den Job-Basisnamen anhängt
    const s = n
      .replace(/_toc_[^.]+\.md$/i, '.md')
      .replace(/_summary_[^.]+\.md$/i, '.md')
      .replace(/_index\.md$/i, '.md')
      .replace(/_(Deutsch|Englisch|Franz[eé]sisch|Spanisch|Russisch|Italienisch)\.txt$/i, '.txt')
      .replace(/_orig\.(txt|srt|vtt)$/i, '.$1');
    return fileStem(s);
  },
};

function groupOutputByGrp(files) {
  const map = new Map();
  const order = [];
  files.forEach(f => {
    const key = f.grp || '—';
    if (!map.has(key)) { map.set(key, []); order.push(key); }
    map.get(key).push(f);
  });
  return order.map(key => ({ stem: key, files: map.get(key) }));
}

function groupOutputFiles(files) {
  const stemFn = _STEM_FN[_tool] || (f => fileStem(f));
  const map = new Map();
  const order = [];
  files.forEach(f => {
    const s = stemFn(f.filename);
    if (!map.has(s)) { map.set(s, []); order.push(s); }
    map.get(s).push(f);
  });
  const singles = [], groups = [];
  order.forEach(s => {
    const gf = map.get(s);
    if (gf.length < 2) singles.push(gf[0]);
    else groups.push({ stem: s, files: gf });
  });
  return { singles, groups };
}

function makeGrpSelBtns(fileIds, cat) {
  const sel = cat === 'input' ? _selIn : _selOut;
  const colId = cat === 'input' ? 'tlf-cin' : 'tlf-cout';
  const colFiles = cat === 'input' ? _inFiles : _outFiles;
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;gap:3px;flex-shrink:0';
  const mkb = (txt, title, fn) => {
    const b = document.createElement('button');
    b.className = 'tlf-chip-act';
    b.textContent = txt; b.title = title;
    b.style.cssText = 'font-size:9px;padding:1px 5px';
    b.onclick = e => {
      e.stopPropagation();
      fn();
      renderCol(cat, colFiles, colId);
      updateBatchBar(cat);
    };
    wrap.appendChild(b);
  };
  mkb('☑', 'Alle', () => fileIds.forEach(id => sel.add(id)));
  mkb('☐', 'Keine', () => fileIds.forEach(id => sel.delete(id)));
  mkb('⇅', 'Toggle', () => fileIds.forEach(id => sel.has(id) ? sel.delete(id) : sel.add(id)));
  return wrap;
}

function makeExtSelBtns(src) {
  const fileIds = src._files.map(f => f.id);
  const saveAndRefresh = () => {
    const s = _extExcluded[src.id] || new Set();
    fetch(_sub + '/prefs/excl-' + src.id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify([...s]),
    }).catch(() => {});
    const cin = document.getElementById('tlf-cin');
    if (cin) renderInputTabbed(cin, _inFiles);
    if (_onChange) try { _onChange(); } catch {}
  };
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;gap:3px;flex-shrink:0';
  const mkb = (txt, title, fn) => {
    const b = document.createElement('button');
    b.className = 'tlf-chip-act';
    b.textContent = txt; b.title = title;
    b.style.cssText = 'font-size:9px;padding:1px 5px';
    b.onclick = e => { e.stopPropagation(); fn(); saveAndRefresh(); };
    wrap.appendChild(b);
  };
  mkb('☑', 'Alle einschließen', () => {
    const s = _extExcluded[src.id] || new Set();
    fileIds.forEach(id => s.delete(id));
    _extExcluded[src.id] = s;
  });
  mkb('☐', 'Alle ausschließen', () => {
    const s = _extExcluded[src.id] || new Set();
    fileIds.forEach(id => s.add(id));
    _extExcluded[src.id] = s;
  });
  mkb('⇅', 'Toggle', () => {
    const s = _extExcluded[src.id] || new Set();
    fileIds.forEach(id => s.has(id) ? s.delete(id) : s.add(id));
    _extExcluded[src.id] = s;
  });
  return wrap;
}

function makeGroupRow(stem, groupFiles) {
  const isOpen = _openGroups.has(stem);
  const totalSize = groupFiles.reduce((a, f) => a + (f.size || 0), 0);
  const ids = groupFiles.map(f => f.id);

  const wrapper = document.createElement('div');
  wrapper.className = 'tlf-grpout';

  const hd = document.createElement('div');
  hd.className = 'tlf-grpout-hd';

  const tog = document.createElement('span');
  tog.className = 'tlf-grpout-tog';
  tog.textContent = isOpen ? '▼' : '▶';

  const name = document.createElement('span');
  name.className = 'tlf-grpout-name';
  name.textContent = stem;
  name.title = stem;

  const meta = document.createElement('span');
  meta.className = 'tlf-grpout-meta';
  meta.textContent = groupFiles.length + '× · ' + fmtSize(totalSize);

  const acts = document.createElement('div');
  acts.className = 'tlf-grpout-acts';

  const zipBtn = document.createElement('button');
  zipBtn.className = 'tlf-chip-act';
  zipBtn.textContent = '↓ ZIP';
  zipBtn.title = 'Als ZIP herunterladen';
  zipBtn.onclick = e => { e.stopPropagation(); downloadGroupZip(ids, stem); };
  acts.appendChild(zipBtn);

  if (_ncEnabled) {
    const ncBtn = document.createElement('button');
    ncBtn.className = 'tlf-chip-act nc';
    ncBtn.textContent = '↑ NC';
    ncBtn.title = 'Alle an Nextcloud senden';
    ncBtn.onclick = e => { e.stopPropagation(); apiGroupNcSend(ids, ncBtn); };
    acts.appendChild(ncBtn);
  }

  const delBtn = document.createElement('button');
  delBtn.className = 'tlf-chip-act del';
  delBtn.textContent = '✕ alle';
  delBtn.title = 'Gruppe löschen';
  delBtn.onclick = e => { e.stopPropagation(); apiGroupDelete(ids, stem, groupFiles.length); };
  acts.appendChild(delBtn);

  hd.appendChild(tog);
  hd.appendChild(name);
  hd.appendChild(meta);
  hd.appendChild(makeGrpSelBtns(ids, 'output'));
  hd.appendChild(acts);

  const gbody = document.createElement('div');
  gbody.className = 'tlf-grpout-body' + (isOpen ? '' : ' tlf-collapsed');
  groupFiles.forEach(f => gbody.appendChild(makeFileRow(f, 'output')));

  hd.addEventListener('click', () => {
    const collapsed = gbody.classList.toggle('tlf-collapsed');
    tog.textContent = collapsed ? '▶' : '▼';
    if (collapsed) _openGroups.delete(stem);
    else _openGroups.add(stem);
  });

  wrapper.appendChild(hd);
  wrapper.appendChild(gbody);
  return wrapper;
}

async function downloadGroupZip(ids, stem) {
  try {
    const r = await fetch(_sub + '/files/zip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
    if (!r.ok) { toast('ZIP-Fehler.'); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = stem + '.zip';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch { toast('ZIP-Fehler.'); }
}

async function apiGroupNcSend(ids, btn) {
  if (!_ncSelId) { toast('Kein NC-Ziel gewählt.'); return; }
  if (btn) { btn.textContent = '…'; btn.disabled = true; }
  let sent = 0, errs = 0;
  for (const id of ids) {
    try {
      const r = await fetch(_sub + '/files/' + id + '/nc-send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_id: _ncSelId }),
      });
      if (r.ok) sent++; else errs++;
    } catch { errs++; }
  }
  toast('✓ ' + sent + ' gesendet' + (errs ? ', ' + errs + ' Fehler' : '') + '.');
  if (btn) { btn.textContent = '↑ NC'; btn.disabled = false; }
}

async function apiGroupDelete(ids, stem, count) {
  if (!confirm('Gruppe "' + stem + '" (' + count + ' Dateien) löschen?')) return;
  try {
    const r = await fetch(_sub + '/files/batch', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
    if (r.ok) {
      toast('✓ Gelöscht.');
      _openGroups.delete(stem);
      apiLoad();
    } else {
      toast('Fehler beim Löschen.');
    }
  } catch { toast('Fehler.'); }
}

// ── Externe Quellen ───────────────────────────────────────────────────────────
async function loadExtExclusions() {
  if (!_extSources.length || !_sub) return;
  for (const src of _extSources) {
    try {
      const r = await fetch(_sub + '/prefs/excl-' + src.id);
      if (r.ok) {
        const arr = await r.json();
        _extExcluded[src.id] = new Set(Array.isArray(arr) ? arr : []);
      }
    } catch {}
  }
}

async function loadExtSources() {
  // Rebuild auto-discovered card-tabs from mkan (drop stale, re-fetch)
  _extSources = _extSources.filter(s => !s._fromMulti);
  if (_mkanMultiUrl) {
    try {
      const r = await fetch(_mkanMultiUrl);
      if (r.ok) {
        const cards = await r.json();
        if (Array.isArray(cards)) {
          const urlParamSrc = _extSources.find(s => s.id === 'mkan-card');
          const urlParamCardId = urlParamSrc?.url?.match(/card_id=([^&]+)/)?.[1];
          for (const card of cards) {
            if (urlParamCardId && urlParamCardId === card.card_id) continue;
            _extSources.push({
              id: 'mkan-card-' + card.card_id,
              label: card.title,
              toEntry: f => f,
              _fromMulti: true,
              _files: card.files || [],
            });
          }
        }
      }
    } catch {}
  }

  await loadExtExclusions();
  for (const src of _extSources) {
    if (src._fromMulti) continue;
    try {
      const r = await fetch(src.url);
      const raw = r.ok ? await r.json() : [];
      let arr;
      if (Array.isArray(raw)) arr = raw;
      else if (Array.isArray(raw?.pool)) arr = raw.pool.flatMap(c => c.files || []);
      else if (Array.isArray(raw?.files)) arr = raw.files;
      else arr = [];
      if (raw?.title) src.label = raw.title;
      let entries = arr.map(src.toEntry);
      if (src.filter) entries = entries.filter(src.filter);
      src._files = entries;
    } catch {
      src._files = [];
    }
  }
  _rebuildMkanPushCards();
}

function _rebuildMkanPushCards() {
  _mkanPushCards = [];
  const paramSrc = _extSources.find(s => s.id === 'mkan-card');
  const paramCardId = paramSrc?.url?.match(/card_id=([^&]+)/)?.[1];
  if (paramSrc && paramCardId) {
    _mkanPushCards.push({ card_id: paramCardId, title: paramSrc.label });
  }
  for (const s of _extSources) {
    if (s._fromMulti) {
      _mkanPushCards.push({ card_id: s.id.replace('mkan-card-', ''), title: s.label });
    }
  }
  if (_mkanPushCards.length && !_mkanPushCardId) {
    _mkanPushCardId = _mkanPushCards[0].card_id;
  } else if (!_mkanPushCards.some(c => c.card_id === _mkanPushCardId)) {
    _mkanPushCardId = _mkanPushCards[0]?.card_id ?? null;
  }
}

function makeExtRow(srcId, entry) {
  const isListed = entry.listed !== false && entry.listed !== 0;
  const row = document.createElement('div');
  row.className = 'tlf-ext-row' + (isListed ? '' : ' unlisted');

  const name = document.createElement('span');
  name.className = 'tlf-ext-name'; name.textContent = entry.name; name.title = entry.name;

  const sz = document.createElement('span');
  sz.className = 'tlf-ext-size';
  sz.textContent = entry.size ? fmtSize(entry.size) : '';

  // ≡-Chip: listed-Toggle (nur wenn file_id + listed_url vorhanden)
  if (entry.file_id && entry.listed_url) {
    let listed = isListed;
    const lc = document.createElement('button');
    lc.className = 'tlf-chip tlf-chip-list' + (listed ? ' on' : '');
    lc.title     = listed ? 'Aus Quellen-Liste verbergen' : 'In Quellen-Liste zeigen';
    lc.textContent = '≡';
    lc.onclick = async () => {
      listed = !listed;
      entry.listed = listed;
      lc.classList.toggle('on', listed);
      lc.title = listed ? 'Aus Quellen-Liste verbergen' : 'In Quellen-Liste zeigen';
      row.classList.toggle('unlisted', !listed);
      name.style.color = listed ? '' : 'var(--tlf-dim)';
      try {
        const resp = await fetch(entry.listed_url, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file_id: entry.file_id, listed }),
        });
        if (!resp.ok) toast('Fehler beim Speichern (' + resp.status + ').');
      } catch { toast('Fehler beim Speichern.'); }
      await apiLoad();
    };
    row.appendChild(name); row.appendChild(sz); row.appendChild(lc);
  } else {
    row.appendChild(name); row.appendChild(sz);
  }

  // Ein/Ausschließen-Toggle für externe Quellen (≡ wie listed-Toggle)
  const excl = (_extExcluded[srcId] || new Set());
  const isExcl = excl.has(entry.id);
  if (isExcl) row.classList.add('unlisted');
  const xb = document.createElement('button');
  xb.className = 'tlf-chip tlf-chip-list' + (isExcl ? '' : ' on');
  xb.textContent = '≡'; xb.title = isExcl ? 'In Panel einschließen' : 'Aus Panel ausschließen';
  xb.onclick = () => {
    const s = _extExcluded[srcId] || new Set();
    if (s.has(entry.id)) s.delete(entry.id); else s.add(entry.id);
    _extExcluded[srcId] = s;
    fetch(_sub + '/prefs/excl-' + srcId, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify([...s]),
    }).catch(() => {});
    const cin = document.getElementById('tlf-cin');
    if (cin) renderInputTabbed(cin, _inFiles);
    if (_onChange) try { _onChange(); } catch {}
  };
  row.appendChild(xb);

  const wb = document.createElement('button');
  wb.className = 'tlf-wire-btn'; wb.textContent = '→';
  wb.title = 'In Werkzeug übernehmen';
  wb.onclick = () => { if (_onWire) _onWire(srcId, entry); };
  row.appendChild(wb);
  attachPreview(row, entry.id, entry.name, entry.mime, srcId.startsWith('mkan-'));
  return row;
}

function renderInputTabbed(body, files) {
  const frag = document.createDocumentFragment();

  // Tab-Leiste
  const tabBar = document.createElement('div');
  tabBar.className = 'tlf-srctabs';
  const mkTab = (id, label, isExt) => {
    const t = document.createElement('button');
    t.className = 'tlf-srctab' + (isExt ? ' tlf-srctab-ext' : '') + (_activeExtTab === id ? ' on' : '');
    t.textContent = label;
    if (isExt) t.title = label;
    t.onclick = () => { _activeExtTab = id; renderInputTabbed(body, _inFiles); updateBatchBar('input'); };
    return t;
  };
  tabBar.appendChild(mkTab(null, 'Eigene', false));
  _extSources.forEach(s => tabBar.appendChild(mkTab(s.id, s.label, true)));
  frag.appendChild(tabBar);

  if (_activeExtTab === null) {
    // Eigene: Upload-Dropzone + Gruppen
    frag.appendChild(makeDropZone());
    const toolGroups = (GROUPS[_tool] || {}).input || [{ label: 'Dateien', match: () => true }];
    let remaining = files.slice();
    toolGroups.forEach((grp, i) => {
      const isCatchAll = i === toolGroups.length - 1;
      const matched = isCatchAll ? remaining : remaining.filter(f => grp.match(f));
      if (!isCatchAll) remaining = remaining.filter(f => !grp.match(f));
      if (!matched.length) return;
      const g = document.createElement('div'); g.className = 'tlf-grp';
      const lbl = document.createElement('div'); lbl.className = 'tlf-grp-lbl';
      lbl.style.cssText = 'display:flex;align-items:center;gap:4px';
      const lblText = document.createElement('span'); lblText.style.flex = '1'; lblText.textContent = grp.label;
      lbl.appendChild(lblText);
      lbl.appendChild(makeGrpSelBtns(matched.map(f => f.id), 'input'));
      g.appendChild(lbl);
      matched.forEach(f => g.appendChild(makeFileRow(f, 'input')));
      frag.appendChild(g);
    });
    if (!files.length) {
      const em = document.createElement('div');
      em.className = 'tlf-empty'; em.textContent = 'Keine Eingabe-Dateien.';
      frag.appendChild(em);
    }
  } else {
    // Externe Quelle
    const src = _extSources.find(s => s.id === _activeExtTab);
    if (!src || !src._files.length) {
      const em = document.createElement('div');
      em.className = 'tlf-empty'; em.textContent = 'Keine Dateien in dieser Quelle.';
      frag.appendChild(em);
    } else {
      const grp = document.createElement('div'); grp.className = 'tlf-grp';
      const lbl = document.createElement('div'); lbl.className = 'tlf-grp-lbl';
      lbl.style.cssText = 'display:flex;justify-content:space-between;align-items:center';
      const txt = document.createElement('span'); txt.textContent = src.label + ' · ' + src._files.length;
      lbl.appendChild(txt);
      lbl.appendChild(makeExtSelBtns(src));
      grp.appendChild(lbl);
      src._files.forEach(entry => grp.appendChild(makeExtRow(src.id, entry)));
      frag.appendChild(grp);
    }
    if (src?._fromMulti) {
      const cardId = src.id.replace('mkan-card-', '');
      const footer = document.createElement('div');
      footer.className = 'tlf-ext-footer';
      const btn = document.createElement('button');
      btn.className = 'tlf-unlink-btn';
      btn.textContent = '⊗ Verbindung lösen';
      btn.onclick = () => mkanUnlinkCard(cardId, src.label);
      footer.appendChild(btn);
      frag.appendChild(footer);
    }
  }

  body.innerHTML = '';
  body.appendChild(frag);
}

// ── Render ────────────────────────────────────────────────────────────────────
function render() {
  renderCol('input',  _inFiles,  'tlf-cin');
  renderCol('output', _outFiles, 'tlf-cout');
  updateBatchBar('input');
  updateBatchBar('output');
}

function renderCol(cat, files, elId) {
  const body = document.getElementById(elId);
  if (!body) return;

  // Wenn externe Quellen definiert: tabbed Eingabe-Rendering
  if (cat === 'input' && _extSources.length > 0) {
    renderInputTabbed(body, files);
    return;
  }

  const frag = document.createDocumentFragment();

  if (cat === 'input') {
    frag.appendChild(makeDropZone());
  }

  if (cat === 'output') {
    if (files.length > 0) {
      const useGrp = (GROUPS[_tool] || {}).groupByGrp;
      let groups, singles;
      if (useGrp) {
        groups = groupOutputByGrp(files); singles = [];
      } else {
        const _r = groupOutputFiles(files); groups = _r.groups; singles = _r.singles;
      }
      groups.forEach(g => frag.appendChild(makeGroupRow(g.stem, g.files)));
      if (singles.length > 0) {
        const wrap = document.createElement('div');
        wrap.className = 'tlf-grp';
        singles.forEach(f => wrap.appendChild(makeFileRow(f, 'output')));
        frag.appendChild(wrap);
      }
    }
  } else {
    const toolGroups = (GROUPS[_tool] || {})[cat] || [{ label: 'Dateien', match: () => true }];
    let remaining = files.slice();
    toolGroups.forEach((grp, i) => {
      const isCatchAll = i === toolGroups.length - 1;
      const matched = isCatchAll ? remaining : remaining.filter(f => grp.match(f));
      if (!isCatchAll) remaining = remaining.filter(f => !grp.match(f));
      if (matched.length === 0) return;
      const g = document.createElement('div');
      g.className = 'tlf-grp';
      const lbl = document.createElement('div');
      lbl.className = 'tlf-grp-lbl';
      lbl.style.cssText = 'display:flex;align-items:center;gap:4px';
      const lblText = document.createElement('span');
      lblText.style.flex = '1'; lblText.textContent = grp.label;
      lbl.appendChild(lblText);
      lbl.appendChild(makeGrpSelBtns(matched.map(f => f.id), cat));
      g.appendChild(lbl);
      matched.forEach(f => g.appendChild(makeFileRow(f, cat)));
      frag.appendChild(g);
    });
  }

  if (files.length === 0) {
    const em = document.createElement('div');
    em.className = 'tlf-empty';
    em.textContent = cat === 'input' ? 'Keine Eingabe-Dateien.' : 'Keine Ausgabe-Dateien.';
    frag.appendChild(em);
  }

  body.innerHTML = '';
  body.appendChild(frag);

  if (cat === 'output' && _ncEnabled) {
    body.appendChild(makeNcBar());
  }
  if (cat === 'output' && _mkanPushCards.length) {
    body.appendChild(makeMkanBar());
  }
}

// ── Drop zone ─────────────────────────────────────────────────────────────────
function makeDropZone() {
  const dz = document.createElement('div');
  dz.className = 'tlf-dz';
  dz.id = 'tlf-dz';
  dz.innerHTML = 'Dateien hierher ziehen oder <u>auswählen</u><input type="file" id="tlf-fi" multiple>';

  dz.addEventListener('click', () => {
    const fi = document.getElementById('tlf-fi');
    if (fi) fi.click();
  });
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('over'); });
  dz.addEventListener('dragleave', e => { if (!dz.contains(e.relatedTarget)) dz.classList.remove('over'); });
  dz.addEventListener('drop', e => {
    e.preventDefault(); dz.classList.remove('over');
    const all = [...e.dataTransfer.files];
    const ok  = all.filter(isFileAccepted);
    if (all.length > ok.length) toast('Nur PDFs erlaubt (' + (all.length - ok.length) + ' ignoriert).');
    if (ok.length) uploadFiles(ok);
  });

  setTimeout(() => {
    const fi = document.getElementById('tlf-fi');
    if (fi) {
      if (_accept) fi.setAttribute('accept', _accept);
      fi.addEventListener('change', e => {
        const all = [...e.target.files];
        const ok  = all.filter(isFileAccepted);
        if (ok.length) uploadFiles(ok);
        else if (all.length) toast('Nur PDFs erlaubt.');
        e.target.value = '';
      });
    }
  }, 0);

  return dz;
}

// ── File row ──────────────────────────────────────────────────────────────────
function makeFileRow(f, cat) {
  const ret = f.retention || '1mo';
  const isCustom = ret === 'user';
  let customLabel = '_T';
  if (isCustom && f.expires_at) {
    try {
      const days = Math.max(1, Math.round((new Date(f.expires_at) - Date.now()) / 86400000));
      customLabel = days + 'T';
    } catch {}
  }
  const isActive   = _activeIds.has(f.id);
  const isUnlisted = cat === 'input' && f.listed === 0;

  const row = document.createElement('div');
  row.className = 'tlf-row'
    + (isActive   ? ' tlf-row-active'   : '')
    + (isUnlisted ? ' tlf-row-unlisted' : '');

  // top: filename + size (+ active dot)
  const top = document.createElement('div');
  top.className = 'tlf-row-top';
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.className = 'tlf-cb';
  cb.checked = (cat === 'input' ? _selIn : _selOut).has(f.id);
  cb.addEventListener('change', e => {
    e.stopPropagation();
    const s = cat === 'input' ? _selIn : _selOut;
    if (cb.checked) s.add(f.id); else s.delete(f.id);
    updateBatchBar(cat);
  });
  top.appendChild(cb);
  if (isActive) {
    const dot = document.createElement('span');
    dot.className = 'tlf-active-dot';
    dot.title = 'Aktuell in Verarbeitung';
    top.appendChild(dot);
  }
  const fname = document.createElement('span');
  fname.className = 'tlf-fname';
  fname.title = f.filename;
  fname.textContent = f.filename;
  const fts = document.createElement('span');
  fts.className = 'tlf-fsize';
  fts.textContent = fmtDate(f.created_at);
  const fsize = document.createElement('span');
  fsize.className = 'tlf-fsize';
  fsize.textContent = fmtSize(f.size);
  top.appendChild(fname);
  top.appendChild(fts);
  top.appendChild(fsize);
  row.appendChild(top);

  // bottom: chips + actions
  const bot = document.createElement('div');
  bot.className = 'tlf-row-bot';

  const chips = document.createElement('div');
  chips.className = 'tlf-chips';

  const chip = (label, val, active) => {
    const c = document.createElement('button');
    c.className = 'tlf-chip' + (active ? ' on' : '');
    c.textContent = label;
    c.onclick = () => apiSetRetention(f.id, val, null);
    return c;
  };
  chips.appendChild(chip('1×',  'task', ret === 'task'));
  chips.appendChild(chip('1W',  '1w',   ret === '1w'));
  chips.appendChild(chip('1M',  '1mo',  ret === '1mo'));
  chips.appendChild(makeDaysChip(f.id, isCustom, customLabel));
  chips.appendChild(chip('∞', 'perm', ret === 'perm'));

  // ≡ Liste-Toggle (nur wenn kein inputAction override)
  if (cat === 'input' && _inputAction !== 'load') {
    const listed = f.listed !== 0;
    const isMedia = /^(audio|video)/i.test(f.mime || '');
    const isRecycled = f.file_type === 'recycled' || f.file_type === 'requeued';
    const listLabel = isMedia ? 'Medienliste'
      : isRecycled ? 'Nachbearbeitungs-Liste'
      : 'Batch-Eingabeliste';
    const lc = document.createElement('button');
    lc.className = 'tlf-chip tlf-chip-list' + (listed ? ' on' : '');
    lc.textContent = '≡';
    lc.title = listed ? `Aus ${listLabel} verbergen` : `In ${listLabel} zeigen`;
    lc.onclick = () => apiSetListed(f.id, !listed);
    chips.appendChild(lc);
  }
  bot.appendChild(chips);

  // "laden"-Chip für Tools mit inputAction:'load' (z.B. kal-trel JSON-Import)
  if (cat === 'input' && _inputAction === 'load') {
    const lc = document.createElement('button');
    lc.className = 'tlf-chip-act load';
    lc.title = 'Board aus dieser Datei laden';
    lc.textContent = 'laden';
    lc.onclick = () => { if (_onSelect) _onSelect([f.id]); };
    bot.appendChild(lc);
  }

  // recycle/copy-to-input Chip für Ausgabe-Dateien
  if (cat === 'output') {
    if (_recycleOutput === 'copy') {
      const rb = document.createElement('button');
      rb.className = 'tlf-chip-act recy';
      rb.title = 'Kopie in Eingang legen (Original bleibt)';
      rb.textContent = '→ Eingang';
      rb.onclick = () => apiCopyToInput(f.id);
      bot.appendChild(rb);
    } else if (_recycleOutput || f.file_type === 'transcription-output') {
      const rb = document.createElement('button');
      rb.className = 'tlf-chip-act recy';
      rb.title = 'Als Eingabe recyceln (für Nachbearbeitung)';
      rb.textContent = '↥';
      rb.onclick = () => apiRecycle(f.id);
      bot.appendChild(rb);
    }
  }

  // edit button for trskr input text files (batch lists)
  if (_tool === 'trskr' && cat === 'input' && /text\/plain|\.txt$/i.test(f.mime || f.filename || '')) {
    const eb = document.createElement('button');
    eb.className = 'tlf-chip-act';
    eb.title = 'Inhalt anzeigen / bearbeiten';
    eb.textContent = '✎';
    eb.onclick = () => openEditModal(f.id, f.filename);
    bot.appendChild(eb);
  }

  // NC send (output only, when NC enabled and targets exist)
  if (_ncEnabled && cat === 'output') {
    const ns = document.createElement('button');
    ns.className = 'tlf-chip-act nc';
    ns.title = 'An Nextcloud senden';
    ns.textContent = '↑ NC';
    ns.onclick = () => ncSendFile(f.id, ns);
    bot.appendChild(ns);
  }

  // mkan push (output only, when mkan push targets exist)
  if (cat === 'output' && _mkanPushCards.length) {
    const mb = document.createElement('button');
    mb.className = 'tlf-chip-act';
    mb.title = 'An mkan-Karte senden';
    mb.textContent = '→ mkan';
    mb.onclick = () => mkanPushFile(f.id, f.filename, f.mime, mb);
    bot.appendChild(mb);
  }

  // download
  const dl = document.createElement('a');
  dl.className = 'tlf-chip-act';
  dl.title = 'Herunterladen';
  dl.textContent = '↓';
  dl.href = _sub + '/files/' + f.id + '/download';
  dl.setAttribute('download', f.filename);
  bot.appendChild(dl);

  // delete
  const xb = document.createElement('button');
  xb.className = 'tlf-chip-act del';
  xb.title = 'Löschen';
  xb.textContent = '✕';
  xb.onclick = () => apiDelete(f.id, f.filename);
  bot.appendChild(xb);

  row.appendChild(bot);
  attachPreview(row, f.id, f.filename, f.mime, false);
  return row;
}

function makeDaysChip(fileId, isActive, label) {
  const wrap = document.createElement('span');
  wrap.className = 'tlf-cdays';

  const chip = document.createElement('button');
  chip.className = 'tlf-chip' + (isActive ? ' on' : '');
  chip.textContent = label;
  chip.title = 'Tage (benutzerdefiniert)';

  const inp = document.createElement('input');
  inp.type = 'number';
  inp.min = 1; inp.max = 999;
  inp.placeholder = 'T';
  inp.className = 'tlf-dinput';
  inp.style.display = 'none';

  chip.onclick = () => {
    chip.style.visibility = 'hidden';
    inp.style.display = 'inline-block';
    inp.focus();
  };

  const confirm = () => {
    const days = parseInt(inp.value, 10);
    inp.style.display = 'none';
    chip.style.visibility = '';
    if (days >= 1) {
      chip.classList.add('on');
      chip.textContent = days + 'T';
      apiSetRetention(fileId, 'user', days);
    }
  };

  inp.onkeydown = e => {
    if (e.key === 'Enter') confirm();
    if (e.key === 'Escape') { inp.style.display = 'none'; chip.style.visibility = ''; }
  };
  inp.onblur = () => setTimeout(confirm, 120);

  wrap.appendChild(chip);
  wrap.appendChild(inp);
  return wrap;
}

// ── API calls ─────────────────────────────────────────────────────────────────
async function apiLoad() {
  try {
    const reqs = [
      fetch(_sub + '/files?category=input&all=1'),
      fetch(_sub + '/files?category=output'),
    ];
    if (_ncEnabled) reqs.push(fetch(_sub + '/nc-targets'));
    const [inR, outR, ncR] = await Promise.all(reqs);
    _inFiles  = inR.ok  ? await inR.json()  : [];
    _outFiles = outR.ok ? await outR.json() : [];
    if (ncR) {
      _ncTargets = ncR.ok ? await ncR.json() : [];
      if (_ncTargets.length && !_ncSelId) {
        try {
          const saved = localStorage.getItem('tlf-nc-sel:' + _tool);
          _ncSelId = (_ncTargets.find(t => t.id === saved) ? saved : null) || _ncTargets[0].id;
        } catch { _ncSelId = _ncTargets[0].id; }
      }
    }
  } catch {
    _inFiles = []; _outFiles = [];
  }
  const inIds  = new Set(_inFiles.map(f => f.id));
  const outIds = new Set(_outFiles.map(f => f.id));
  for (const id of [..._selIn])  if (!inIds.has(id))  _selIn.delete(id);
  for (const id of [..._selOut]) if (!outIds.has(id)) _selOut.delete(id);
  if (_extSources.length || _mkanMultiUrl) await loadExtSources();
  render();
  if (_onChange) try { _onChange(); } catch {}
}

async function uploadFiles(files) {
  for (const f of files) {
    const fd = new FormData();
    fd.append('file', f);
    fd.append('category', 'input');
    fd.append('retention', '1mo');
    try {
      const r = await fetch(_sub + '/files/upload', { method: 'POST', body: fd });
      if (!r.ok) toast('Upload fehlgeschlagen: ' + f.name);
    } catch { toast('Upload-Fehler: ' + f.name); }
  }
  await apiLoad();
}

async function uploadUrl(url) {
  if (!url.startsWith('http')) return;
  const fd = new FormData();
  const blob = new Blob([url + '\n'], { type: 'text/plain' });
  fd.append('file', blob, 'url.txt');
  fd.append('category', 'input');
  fd.append('retention', '1mo');
  fd.append('file_type', 'url');
  try {
    const r = await fetch(_sub + '/files/upload', { method: 'POST', body: fd });
    if (!r.ok) toast('URL-Upload fehlgeschlagen.');
    else toast('URL gespeichert.');
  } catch { toast('URL-Upload-Fehler.'); }
  await apiLoad();
}

async function apiDelete(id, name) {
  if (!confirm('Löschen: ' + name + '?')) return;
  try {
    await fetch(_sub + '/files/' + id, { method: 'DELETE' });
  } catch {}
  await apiLoad();
}

async function apiSetRetention(id, retention, days) {
  const body = days ? { retention, days } : { retention };
  try {
    await fetch(_sub + '/files/' + id + '/retention', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {}
  await apiLoad();
}

async function apiSetListed(id, listed) {
  try {
    await fetch(_sub + '/files/' + id + '/listed', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ listed }),
    });
  } catch {}
  await apiLoad();
}

async function apiRecycle(id) {
  try {
    await fetch(_sub + '/files/' + id + '/recycle', { method: 'POST' });
    toast('In Eingabe verschoben.');
  } catch { toast('Fehler beim Verschieben.'); }
  await apiLoad();
}

async function apiCopyToInput(id) {
  try {
    const r = await fetch(_sub + '/files/' + id + '/copy-to-input', { method: 'POST' });
    if (r.ok) { toast('Kopie in Eingang gelegt.'); }
    else { toast('Fehler beim Kopieren (' + r.status + ').'); }
  } catch { toast('Fehler beim Kopieren.'); }
  await apiLoad();
}

async function batchDelete(cat) {
  const sel = cat === 'input' ? _selIn : _selOut;
  const n = sel.size;
  if (!n || !confirm(n + ' Datei' + (n === 1 ? '' : 'en') + ' löschen?')) return;
  for (const id of [...sel]) {
    try { await fetch(_sub + '/files/' + id, { method: 'DELETE' }); } catch {}
  }
  if (cat === 'input') _selIn.clear(); else _selOut.clear();
  await apiLoad();
}

async function batchNcSend() {
  const ids = [..._selOut];
  if (!ids.length || !_ncSelId) { toast('Kein NC-Ziel oder keine Auswahl.'); return; }
  const st = document.getElementById('tlf-nc-bar-status');
  if (st) st.textContent = 'Sende …';
  let sent = 0, errs = 0;
  for (const id of ids) {
    try {
      const r = await fetch(_sub + '/files/' + id + '/nc-send', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_id: _ncSelId }),
      });
      if (r.ok) sent++; else errs++;
    } catch { errs++; }
  }
  const msg = '✓ ' + sent + ' gesendet' + (errs ? ', ' + errs + ' Fehler' : '') + '.';
  if (st) { st.textContent = msg; setTimeout(() => { if (st) st.textContent = ''; }, 4000); }
  toast(msg);
}

function updateBatchBar(cat) {
  const sel = cat === 'input' ? _selIn : _selOut;
  const barId = cat === 'input' ? 'tlf-in-sel' : 'tlf-out-sel';
  const bar = document.getElementById(barId);
  if (!bar) return;
  const n = sel.size;
  if (n === 0) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
  bar.style.display = 'flex';
  bar.innerHTML = '';
  const lbl = document.createElement('span');
  lbl.textContent = n + ' gewählt';
  lbl.style.cssText = 'color:#999;flex:1;font-size:10px';
  bar.appendChild(lbl);
  const delBtn = document.createElement('button');
  delBtn.className = 'tlf-bat-btn del';
  delBtn.textContent = '✕ Löschen (' + n + ')';
  delBtn.onclick = () => batchDelete(cat);
  bar.appendChild(delBtn);
  if (cat === 'output' && _ncEnabled && _ncSelId) {
    const ncBtn = document.createElement('button');
    ncBtn.className = 'tlf-bat-btn nc';
    ncBtn.textContent = '↑ NC (' + n + ')';
    ncBtn.onclick = () => batchNcSend();
    bar.appendChild(ncBtn);
  }
}

// ── NC ────────────────────────────────────────────────────────────────────────
async function ncLoad() {
  try {
    const r = await fetch(_sub + '/nc-targets?direction=push');
    _ncTargets = r.ok ? await r.json() : [];
  } catch { _ncTargets = []; }
  if (_ncTargets.length) {
    try {
      const saved = localStorage.getItem('tlf-nc-sel:' + _tool);
      _ncSelId = (_ncTargets.find(t => t.id === saved) ? saved : null) || _ncTargets[0].id;
    } catch { _ncSelId = _ncTargets[0].id; }
  }
}

async function ncAdd() {
  const label = (document.getElementById('tlf-nc-add-lbl').value || '').trim();
  const url   = (document.getElementById('tlf-nc-add-url').value  || '').trim();
  const st    = document.getElementById('tlf-nc-add-status');
  st.textContent = '';
  if (!label || !url) { st.textContent = 'Label und URL erforderlich.'; return; }
  try {
    const r = await fetch(_sub + '/nc-targets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label, url }),
    });
    const d = await r.json();
    if (!r.ok) { st.textContent = d.error || 'Fehler.'; return; }
    document.getElementById('tlf-nc-add-lbl').value = '';
    document.getElementById('tlf-nc-add-url').value = '';
    st.textContent = '✓ Gespeichert.';
    await ncLoad();
    renderNcList();
    render();  // NC-Bar im Modal aktualisieren
  } catch { st.textContent = 'Verbindungsfehler.'; }
}

async function ncDelete(tid) {
  try {
    await fetch(_sub + '/nc-targets/' + tid, { method: 'DELETE' });
    if (_ncSelId === tid) _ncSelId = '';
    await ncLoad();
    renderNcList();
    render();
  } catch { toast('Fehler beim Löschen.'); }
}

function renderNcList() {
  const el = document.getElementById('tlf-nc-list');
  if (!el) return;
  el.innerHTML = '';
  if (!_ncTargets.length) {
    el.innerHTML = '<div style="font-size:11px;color:#bbb;padding:4px 0">Keine Ziele gespeichert.</div>';
    return;
  }
  _ncTargets.forEach(t => {
    const row = document.createElement('div');
    row.className = 'tlf-nc-row';
    const lbl = document.createElement('span');
    lbl.className = 'tlf-nc-row-lbl'; lbl.textContent = t.label;
    const url = document.createElement('span');
    url.className = 'tlf-nc-row-url'; url.textContent = t.url; url.title = t.url;
    const del = document.createElement('button');
    del.className = 'tlf-ed-btn'; del.textContent = '×';
    del.style.cssText = 'padding:1px 7px;font-size:11px';
    del.title = 'Löschen'; del.onclick = () => ncDelete(t.id);
    row.appendChild(lbl); row.appendChild(url); row.appendChild(del);
    el.appendChild(row);
  });
}

function openNcMgmt() {
  const overlay = document.getElementById('tlf-nc-overlay');
  if (!overlay) return;
  renderNcList();
  document.getElementById('tlf-nc-add-status').textContent = '';
  overlay.classList.add('open');
}
function closeNcMgmt() {
  const overlay = document.getElementById('tlf-nc-overlay');
  if (overlay) overlay.classList.remove('open');
}

function makeNcBar() {
  const bar = document.createElement('div');
  bar.className = 'tlf-nc-bar';

  const lbl = document.createElement('span');
  lbl.className = 'tlf-nc-lbl'; lbl.textContent = 'NC:';
  bar.appendChild(lbl);

  if (_ncTargets.length) {
    const sel = document.createElement('select');
    sel.className = 'tlf-nc-sel';
    _ncTargets.forEach(t => {
      const o = document.createElement('option');
      o.value = t.id; o.textContent = t.label;
      if (t.id === _ncSelId) o.selected = true;
      sel.appendChild(o);
    });
    if (!_ncSelId && _ncTargets.length) { _ncSelId = _ncTargets[0].id; sel.value = _ncSelId; }
    sel.onchange = () => {
      _ncSelId = sel.value;
      try { localStorage.setItem('tlf-nc-sel:' + _tool, _ncSelId); } catch {}
    };
    bar.appendChild(sel);

    const sendAll = document.createElement('button');
    sendAll.className = 'tlf-nc-btn send'; sendAll.textContent = '↑ Alle';
    sendAll.onclick = () => ncSendAll(sendAll);
    bar.appendChild(sendAll);
  }

  const mgmtBtn = document.createElement('button');
  mgmtBtn.className = 'tlf-nc-btn'; mgmtBtn.textContent = '⚙ Ziele';
  mgmtBtn.onclick = openNcMgmt;
  bar.appendChild(mgmtBtn);

  const st = document.createElement('div');
  st.className = 'tlf-nc-status'; st.id = 'tlf-nc-bar-status';
  bar.appendChild(st);
  return bar;
}

async function ncSendFile(fileId, btn) {
  if (!_ncSelId) { toast('Kein NC-Ziel gewählt.'); return; }
  if (btn) { btn.textContent = '…'; btn.disabled = true; }
  const st = document.getElementById('tlf-nc-bar-status');
  if (st) st.textContent = 'Sende …';
  try {
    const r = await fetch(_sub + '/files/' + fileId + '/nc-send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_id: _ncSelId }),
    });
    const d = await r.json();
    if (r.ok) {
      if (st) st.textContent = '✓ Gesendet.';
      toast('✓ Datei gesendet.');
    } else {
      if (st) st.textContent = 'Fehler: ' + (d.error || '?');
      toast('Fehler: ' + (d.error || 'NC-Send fehlgeschlagen'));
    }
  } catch {
    if (st) st.textContent = 'Verbindungsfehler.';
    toast('Verbindungsfehler.');
  }
  if (btn) { btn.textContent = '↑ NC'; btn.disabled = false; }
  setTimeout(() => { if (st) st.textContent = ''; }, 4000);
}

async function ncSendAll(btn) {
  if (!_ncSelId) { toast('Kein NC-Ziel gewählt.'); return; }
  if (!_outFiles.length) { toast('Keine Ausgabe-Dateien.'); return; }
  if (btn) { btn.textContent = '…'; btn.disabled = true; }
  const st = document.getElementById('tlf-nc-bar-status');
  if (st) st.textContent = 'Sende …';
  let sent = 0, errs = 0;
  for (const f of _outFiles) {
    try {
      const r = await fetch(_sub + '/files/' + f.id + '/nc-send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_id: _ncSelId }),
      });
      if (r.ok) sent++; else errs++;
    } catch { errs++; }
  }
  const msg = `✓ ${sent} gesendet` + (errs ? `, ${errs} Fehler` : '') + '.';
  if (st) st.textContent = msg;
  toast(msg);
  if (btn) { btn.textContent = '↑ Alle'; btn.disabled = false; }
  setTimeout(() => { if (st) st.textContent = ''; }, 5000);
}

// ── mkan push (Ausgabe → Karte zurück) ───────────────────────────────────────

function makeMkanBar() {
  const bar = document.createElement('div');
  bar.className = 'tlf-mkan-bar';
  const lbl = document.createElement('span');
  lbl.className = 'tlf-mkan-lbl'; lbl.textContent = '→ mkan:';
  bar.appendChild(lbl);
  if (_mkanPushCards.length > 1) {
    const sel = document.createElement('select');
    sel.className = 'tlf-mkan-sel';
    _mkanPushCards.forEach(c => {
      const o = document.createElement('option');
      o.value = c.card_id; o.textContent = c.title;
      if (c.card_id === _mkanPushCardId) o.selected = true;
      sel.appendChild(o);
    });
    if (!_mkanPushCardId) { _mkanPushCardId = _mkanPushCards[0].card_id; sel.value = _mkanPushCardId; }
    sel.onchange = () => { _mkanPushCardId = sel.value; };
    bar.appendChild(sel);
  } else {
    const nm = document.createElement('span');
    nm.className = 'tlf-mkan-name'; nm.textContent = _mkanPushCards[0]?.title || '';
    bar.appendChild(nm);
  }
  const st = document.createElement('div');
  st.className = 'tlf-mkan-status'; st.id = 'tlf-mkan-bar-status';
  bar.appendChild(st);
  return bar;
}

async function mkanPushFile(fileId, filename, mime, btn) {
  if (!_mkanPushCardId) { toast('Kein mkan-Ziel gewählt.'); return; }
  if (btn) { btn.textContent = '…'; btn.disabled = true; }
  const st = document.getElementById('tlf-mkan-bar-status');
  if (st) st.textContent = 'Sende …';
  try {
    const dlResp = await fetch(_sub + '/files/' + fileId + '/download');
    if (!dlResp.ok) throw new Error('Download fehlgeschlagen (' + dlResp.status + ')');
    const blob = await dlResp.blob();
    const fd = new FormData();
    fd.append('file', blob, filename);
    const r = await fetch('/api/mkan-push-to-card?card_id=' + encodeURIComponent(_mkanPushCardId), {
      method: 'POST',
      body: fd,
    });
    if (r.ok) {
      if (st) st.textContent = '✓ Gesendet.';
      toast('✓ An mkan gesendet.');
    } else {
      const d = await r.json().catch(() => ({}));
      const msg = 'Fehler: ' + (d.error || 'mkan-Push fehlgeschlagen');
      if (st) st.textContent = msg;
      toast(msg);
    }
  } catch (e) {
    const msg = 'Fehler: ' + e.message;
    if (st) st.textContent = msg;
    toast(msg);
  }
  if (btn) { btn.textContent = '→ mkan'; btn.disabled = false; }
  setTimeout(() => { if (st) st.textContent = ''; }, 4000);
}

async function mkanUnlinkCard(cardId, title) {
  if (!confirm('Verbindung zu „' + title + '" lösen?')) return;
  try {
    const r = await fetch('/api/mkan-unlink-card?card_id=' + encodeURIComponent(cardId), { method: 'POST' });
    if (r.ok) {
      toast('✓ Verbindung gelöst.');
      _activeExtTab = null;
      await apiLoad();
    } else {
      const d = await r.json().catch(() => ({}));
      toast('Fehler: ' + (d.error || 'Unlink fehlgeschlagen'));
    }
  } catch (e) {
    toast('Fehler: ' + e.message);
  }
}

// ── Text-Edit Modal ───────────────────────────────────────────────────────────
let _editFileId = null;

async function openEditModal(id, filename) {
  _editFileId = id;
  const overlay = document.getElementById('tlf-ed-overlay');
  if (!overlay) return;
  document.getElementById('tlf-ed-title').textContent = filename;
  document.getElementById('tlf-ed-status').textContent = 'Lade …';
  document.getElementById('tlf-ed-ta').value = '';
  overlay.classList.add('open');
  try {
    const r = await fetch(_sub + '/files/' + id + '/content');
    if (r.ok) {
      document.getElementById('tlf-ed-ta').value = await r.text();
      document.getElementById('tlf-ed-status').textContent = '';
    } else {
      document.getElementById('tlf-ed-status').textContent = 'Fehler beim Laden.';
    }
  } catch {
    document.getElementById('tlf-ed-status').textContent = 'Verbindungsfehler.';
  }
  const saveBtn = document.getElementById('tlf-ed-save');
  if (saveBtn) saveBtn.onclick = saveEditModal;
}

async function saveEditModal() {
  if (!_editFileId) return;
  const text = document.getElementById('tlf-ed-ta').value;
  const st = document.getElementById('tlf-ed-status');
  st.textContent = 'Speichere …';
  try {
    const r = await fetch(_sub + '/files/' + _editFileId + '/content', {
      method: 'PUT',
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      body: text,
    });
    if (r.ok) {
      st.textContent = '✓ Gespeichert.';
      await apiLoad();
      setTimeout(() => { st.textContent = ''; }, 2000);
    } else {
      st.textContent = 'Fehler beim Speichern.';
    }
  } catch {
    st.textContent = 'Verbindungsfehler.';
  }
}

function closeEditModal() {
  const overlay = document.getElementById('tlf-ed-overlay');
  if (overlay) overlay.classList.remove('open');
  _editFileId = null;
}

// ── Modal-Theming ─────────────────────────────────────────────────────────────
function applyModalTheme(name) {
  const vars = _grayLevel > 0 ? computeGrayTheme(_grayLevel) : (_MODAL_THEMES[name] || _MODAL_THEMES.light);
  ['tlf-overlay', 'tlf-nc-overlay', 'tlf-ed-overlay'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    Object.entries(vars).forEach(([k, v]) => el.style.setProperty(k, v));
  });
  _modalTheme = name;
  try { localStorage.setItem('tlf-theme:' + _tool, name); } catch {}
  const chip = document.getElementById('tlf-theme-chip');
  if (chip) chip.title = _grayLevel > 0 ? 'Graustufen (' + _grayLevel + '%)' : (name === 'dark' ? 'Hell-Modus' : 'Dunkel-Modus');
  const gp = document.getElementById('tlf-gp');
  if (gp) {
    gp.style.background = vars['--tlf-hd'];
    gp.style.color = vars['--tlf-text'];
    gp.style.borderColor = vars['--tlf-brd'];
  }
  const sw = document.getElementById('tlf-gp-sw');
  if (sw) {
    sw.textContent = name === 'dark' ? '◑  hell' : '◑  dunkel';
    sw.style.opacity = _grayLevel > 0 ? '0.35' : '1';
    sw.style.pointerEvents = _grayLevel > 0 ? 'none' : '';
  }
}

// ── Open / Close / Refresh ────────────────────────────────────────────────────
function open() {
  const el = document.getElementById('tlf-overlay');
  if (el) { el.classList.add('open'); applyModalTheme(_modalTheme); apiLoad(); }
}

function close() {
  const el = document.getElementById('tlf-overlay');
  if (el) el.classList.remove('open');
}

function refresh() {
  const el = document.getElementById('tlf-overlay');
  if (el && el.classList.contains('open')) apiLoad();
}

function markActive(ids) {
  _activeIds = new Set(ids || []);
  const el = document.getElementById('tlf-overlay');
  if (el && el.classList.contains('open')) render();
}

// ── Header button ─────────────────────────────────────────────────────────────
function addHeaderButton() {
  const btn = document.createElement('button');
  btn.className = 'hdr-btn';
  btn.textContent = 'Dateien';
  btn.onclick = open;
  const hdrLeft = document.querySelector('.hdr-left');
  if (hdrLeft) {
    const firstBtn = hdrLeft.querySelector('.hdr-btn');
    hdrLeft.insertBefore(btn, firstBtn ? firstBtn.nextSibling : null);
  } else {
    const container = document.querySelector('header') || document.querySelector('nav');
    if (!container) return;
    container.insertBefore(btn, container.firstChild);
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
function init(opts) {
  _sub          = opts.subpath          || '';
  _tool         = opts.tool             || '';
  _onSelect     = opts.onSelect         || null;
  _onChange     = opts.onChange         || null;
  _ncEnabled      = !!opts.ncEnabled;
  _recycleOutput  = opts.recycleOutput  || false;   // false | true | 'copy'
  _inputAction    = opts.inputAction    || null;    // null | 'load'
  _accept         = opts.accept         || null;
  _extSources   = (opts.externalSources || []).map(s => ({ ...s, _files: [] }));
  _activeExtTab = null;
  _extExcluded  = {};
  _onWire       = opts.onWire           || null;
  _mkanMultiUrl = _tool ? '/api/mkan-cards-for-tool?tool=' + encodeURIComponent(_tool) : null;

  try {
    const _mkanCardId = new URLSearchParams(location.search).get('mkanCard');
    if (_mkanCardId) {
      _extSources.push({ id: 'mkan-card', label: 'mkan …', url: '/api/mkan-card?card_id=' + encodeURIComponent(_mkanCardId), toEntry: f => f, _files: [] });
      _activeExtTab = 'mkan-card';
    }
  } catch {}

  injectStyles();
  injectModal();
  if (_onSelect) {
    const ft = document.getElementById('tlf-ft');
    if (ft) ft.style.display = '';
    const ub = document.getElementById('tlf-ubernehmen');
    if (ub) ub.onclick = () => { _onSelect([..._selIn, ..._selOut]); };
  }
  addHeaderButton();

  try { _modalTheme = localStorage.getItem('tlf-theme:' + _tool) || 'light'; } catch {}
  try { _grayLevel = +(localStorage.getItem('tlf-gray:' + _tool) || 0); } catch {}
  const _gpSl = document.getElementById('tlf-gp-sl');
  if (_gpSl) _gpSl.value = _grayLevel;
  applyModalTheme(_modalTheme);
}

// ── Public ────────────────────────────────────────────────────────────────────
global.tulFiles = { init, open, close, refresh, markActive, getExtExcluded: () => _extExcluded, attachPreview };

})(window);

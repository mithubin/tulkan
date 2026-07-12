/* tul-theme.js — Shared theme engine für tul.yourdomain.example panels
 *
 * API:
 *   tulTheme.PRESETS          — vordefinierte Modul-Presets (trskr/lern/kurv/popt/bild)
 *   tulTheme.init(opts)       — panels einbetten, theme laden & anwenden
 *
 * opts:
 *   subpath   {string}   Flask-Subpath des Panels, z.B. '/trskr'
 *                        → GET/POST <subpath>/theme für Server-Persistenz
 *   preset    {object}   Default-Preset { chrome, accent } wenn kein Server-Theme
 *   labVisible {boolean} Labor-Panel beim Start sichtbar (default: false)
 *   onApply   {function} Callback(params, vars) bei Snapshot/Anwenden
 *
 * Voraussetzungen:
 *   1. tul-theme.css laden (oder inline)
 *   2. CSS-Variablen im Panel: --bg --bg2 --bg3 --border --text --muted --acc --acc2 --blur
 *   3. Flask-Routen GET+POST <subpath>/theme (liest/schreibt theme.json)
 *   4. tulTheme.init() nach DOMContentLoaded aufrufen
 */
(function (global) {
'use strict';

// ── Modul-Presets ─────────────────────────────────────────────────────────────
const MODULE_PRESETS = {
  trskr: { chrome: '#131828', accent: '#5c8fc8' },  // Blau-Violett  — ruhig, Fokus
  lern:  { chrome: '#142018', accent: '#5abf5a' },  // Waldgrün      — Wachstum
  kurv:  { chrome: '#211808', accent: '#d4882a' },  // Amber         — Feuer, Industrie
  popt:  { chrome: '#141a1f', accent: '#6ab0c8' },  // Stahlblau     — Präzision
  bild:  { chrome: '#1c1020', accent: '#bf5ab0' },  // Magenta       — visuell
};

// ── Farb-Hilfsfunktionen ──────────────────────────────────────────────────────
function hexToHsl(hex) {
  let r = parseInt(hex.slice(1,3),16)/255, g = parseInt(hex.slice(3,5),16)/255, b = parseInt(hex.slice(5,7),16)/255;
  const max = Math.max(r,g,b), min = Math.min(r,g,b); let h=0,s=0,l=(max+min)/2;
  if (max !== min) {
    const d = max - min; s = l > .5 ? d/(2-max-min) : d/(max+min);
    switch (max) { case r: h=((g-b)/d+(g<b?6:0))/6; break; case g: h=((b-r)/d+2)/6; break; case b: h=((r-g)/d+4)/6; break; }
  }
  return [h*360, s*100, l*100];
}

function hslToHex(h,s,l) {
  h = ((h%360)+360)%360; s = Math.max(0,Math.min(100,s))/100; l = Math.max(0,Math.min(100,l))/100;
  const a = s * Math.min(l, 1-l);
  const f = n => { const k=(n+h/30)%12, c=l-a*Math.max(-1,Math.min(k-3,9-k,1)); return Math.round(255*c).toString(16).padStart(2,'0'); };
  return `#${f(0)}${f(8)}${f(4)}`;
}

function hexToHsv(hex) {
  hex = (hex||'#000').replace('#','');
  if (hex.length === 3) hex = hex.split('').map(c=>c+c).join('');
  const r=parseInt(hex.slice(0,2),16)/255, g=parseInt(hex.slice(2,4),16)/255, b=parseInt(hex.slice(4,6),16)/255;
  const max=Math.max(r,g,b), min=Math.min(r,g,b), d=max-min;
  let h=0, s=max?d/max:0, v=max;
  if (d) { if(max===r) h=((g-b)/d+6)%6; else if(max===g) h=(b-r)/d+2; else h=(r-g)/d+4; h*=60; }
  return [Math.round(h)%360, Math.round(s*100), Math.round(v*100)];
}

function hsvToHex(h,s,v) {
  s/=100; v/=100; const c=v*s, x=c*(1-Math.abs((h/60)%2-1)), m=v-c;
  let r,g,b;
  if(h<60){r=c;g=x;b=0}else if(h<120){r=x;g=c;b=0}else if(h<180){r=0;g=c;b=x}
  else if(h<240){r=0;g=x;b=c}else if(h<300){r=x;g=0;b=c}else{r=c;g=0;b=x}
  return '#' + [r+m,g+m,b+m].map(n=>Math.round(n*255).toString(16).padStart(2,'0')).join('');
}

function luma(hex) {
  return .299*parseInt(hex.slice(1,3),16) + .587*parseInt(hex.slice(3,5),16) + .114*parseInt(hex.slice(5,7),16);
}
function clamp(v,lo,hi) { return Math.max(lo, Math.min(hi, v)); }

// ── State ─────────────────────────────────────────────────────────────────────
let _subpath = '', _onApply = null, _onSave = null, _defaultPreset = null;
let _C = { chrome: '#1a1a2e', accent: '#7c9cbf' };
let _log = [], _saveTimer = null;
let _cpH=210, _cpS=65, _cpV=85, _cpCb=null, _cpKey=null, _cpSwatch=null;

// ── DOM helper ────────────────────────────────────────────────────────────────
function $(id) { return document.getElementById('tlt-' + id); }

// ── HTML-Injection ────────────────────────────────────────────────────────────
function injectHTML() {
  const wrap = document.createElement('div');
  wrap.innerHTML = `
<div id="tlt-cp-popup" class="tlt-cp-hidden">
  <div id="tlt-cp-field"><div id="tlt-cp-cursor"></div></div>
  <input type="range" id="tlt-cp-hue" min="0" max="359" step="1">
  <div id="tlt-cp-bottom">
    <div id="tlt-cp-preview"></div>
    <input id="tlt-cp-hex" maxlength="7" spellcheck="false" placeholder="#000000">
  </div>
</div>

<div class="tlt-float-panel" id="tlt-panel-main">
  <div class="tlt-fp-header" id="tlt-hdr-main">
    <span class="tlt-fp-title">◑ Theme</span>
    <span class="tlt-fp-toggle tlt-open" id="tlt-toggle-main">▲</span>
  </div>
  <div class="tlt-fp-body" id="tlt-body-main">
    <div class="tlt-fp-section">Basis</div>
    <div style="margin-bottom:5px;font-size:11px;color:#445">Chrome — Mittelgrund (bg2)</div>
    <div class="tlt-color-row">
      <button class="tlt-cp-swatch" id="tlt-swatch-chrome"></button>
      <input class="tlt-color-hex" id="tlt-hex-chrome" value="#1a1a2e" maxlength="7">
    </div>
    <div style="margin-bottom:5px;font-size:11px;color:#445">Akzent</div>
    <div class="tlt-color-row">
      <button class="tlt-cp-swatch" id="tlt-swatch-accent"></button>
      <input class="tlt-color-hex" id="tlt-hex-accent" value="#7c9cbf" maxlength="7">
    </div>
    <hr class="tlt-fp-sep">
    <div class="tlt-fp-section">Abstände</div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Spreizung (DCL) <span class="tlt-val" id="tlt-lbl-dcl">7</span></div>
      <input type="range" id="tlt-m-dcl" min="2" max="18" value="7">
    </div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Sweetspot dunkel↔hell <span class="tlt-val" id="tlt-lbl-sweet">110</span></div>
      <input type="range" id="tlt-m-sweet" min="60" max="200" value="110">
    </div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Sättigungs-Skala <span class="tlt-val" id="tlt-lbl-sat">100%</span></div>
      <input type="range" id="tlt-m-sat" min="0" max="200" value="100">
    </div>
    <hr class="tlt-fp-sep">
    <div class="tlt-fp-section">Presets</div>
    <div class="tlt-presets" id="tlt-presets"></div>
    <button class="tlt-fp-btn" id="tlt-btn-reset">Zurücksetzen</button>
    <hr class="tlt-fp-sep">
    <button class="tlt-fp-btn" id="tlt-btn-lab">⚗ Labor …</button>
  </div>
</div>

<div class="tlt-float-panel" id="tlt-panel-lab" style="display:none">
  <div class="tlt-fp-header" id="tlt-hdr-lab">
    <span class="tlt-fp-title">⚗ Labor</span>
    <span class="tlt-fp-toggle tlt-open" id="tlt-toggle-lab">▲</span>
  </div>
  <div class="tlt-fp-body" id="tlt-body-lab">
    <div class="tlt-fp-section">Live-Swatches</div>
    <div class="tlt-swatch-strip">
      ${['bg','bg2','bg3','text','muted','acc'].map(n=>`<div class="tlt-swatch-item">
        <div class="tlt-swatch-box" id="tlt-sw-${n}"></div>
        <div class="tlt-swatch-lbl">${n}</div>
        <div class="tlt-swatch-hex" id="tlt-shx-${n}"></div>
      </div>`).join('')}
    </div>
    <hr class="tlt-fp-sep">
    <div class="tlt-fp-section">Hintergrund (bg) — Abweichung von Chrome</div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Hue-Versatz <span class="tlt-val" id="tlt-lbl-bg-hue">0°</span></div>
      <input type="range" id="tlt-l-bg-hue" min="-30" max="30" value="0">
    </div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Sättigungs-Versatz <span class="tlt-val" id="tlt-lbl-bg-sat">0%</span></div>
      <input type="range" id="tlt-l-bg-sat" min="-50" max="50" value="0">
    </div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Spreizung <span class="tlt-val" id="tlt-lbl-bg-spread">7</span></div>
      <div class="tlt-spread-row">
        <input type="range" id="tlt-l-bg-spread" min="1" max="25" value="7" style="flex:1">
        <label class="tlt-spread-auto"><input type="checkbox" id="tlt-l-bg-auto"> auto</label>
      </div>
    </div>
    <hr class="tlt-fp-sep">
    <div class="tlt-fp-section">Vorderflächen (bg3) — Abweichung von Chrome</div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Hue-Versatz <span class="tlt-val" id="tlt-lbl-bg3-hue">0°</span></div>
      <input type="range" id="tlt-l-bg3-hue" min="-30" max="30" value="0">
    </div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Sättigungs-Versatz <span class="tlt-val" id="tlt-lbl-bg3-sat">0%</span></div>
      <input type="range" id="tlt-l-bg3-sat" min="-50" max="50" value="0">
    </div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Spreizung <span class="tlt-val" id="tlt-lbl-bg3-spread">7</span></div>
      <div class="tlt-spread-row">
        <input type="range" id="tlt-l-bg3-spread" min="1" max="25" value="7" style="flex:1">
        <label class="tlt-spread-auto"><input type="checkbox" id="tlt-l-bg3-auto"> auto</label>
      </div>
    </div>
    <hr class="tlt-fp-sep">
    <div class="tlt-fp-section">Text &amp; Muted</div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Text — Helligkeit <span class="tlt-val" id="tlt-lbl-text-l">91%</span></div>
      <input type="range" id="tlt-l-text-l" min="70" max="100" value="91">
    </div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Text — Farbanteil <span class="tlt-val" id="tlt-lbl-text-s">15%</span></div>
      <input type="range" id="tlt-l-text-s" min="0" max="60" value="15">
    </div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Muted — Helligkeit <span class="tlt-val" id="tlt-lbl-muted-l">60%</span></div>
      <input type="range" id="tlt-l-muted-l" min="35" max="80" value="60">
    </div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Muted — Farbanteil <span class="tlt-val" id="tlt-lbl-muted-s">35%</span></div>
      <input type="range" id="tlt-l-muted-s" min="0" max="80" value="35">
    </div>
    <hr class="tlt-fp-sep">
    <div class="tlt-fp-section">Oberflächen-Blur</div>
    <div class="tlt-ctrl">
      <div class="tlt-ctrl-lbl">Blur <span class="tlt-val" id="tlt-lbl-blur">8px</span></div>
      <input type="range" id="tlt-l-blur" min="0" max="24" value="8">
    </div>
    <hr class="tlt-fp-sep">
    <div class="tlt-fp-section">Snapshot-Log</div>
    <div style="display:flex;gap:6px;margin-bottom:5px">
      <button class="tlt-fp-btn tlt-pri" style="margin:0;flex:1" id="tlt-btn-snap">📸 Snapshot</button>
      <button class="tlt-fp-btn" style="margin:0;flex:1" id="tlt-btn-copy">📋 Kopieren</button>
    </div>
    <div class="tlt-log-list" id="tlt-log-list">
      <div class="tlt-log-empty">Noch keine Snapshots</div>
    </div>
  </div>
</div>
`;
  document.body.appendChild(wrap);
}

// ── Color Picker ──────────────────────────────────────────────────────────────
function cpRender() {
  const hex = hsvToHex(_cpH, _cpS, _cpV);
  $('cp-field').style.background =
    `linear-gradient(to bottom,rgba(0,0,0,0),#000),` +
    `linear-gradient(to right,#fff,hsl(${_cpH},100%,50%))`;
  const cur = $('cp-cursor');
  cur.style.left = _cpS + '%'; cur.style.top = (100 - _cpV) + '%';
  cur.style.borderColor = _cpV > 50 ? '#fff' : '#ccc';
  $('cp-hue').value = _cpH;
  $('cp-preview').style.background = hex;
  if (document.activeElement !== $('cp-hex')) $('cp-hex').value = hex;
  if (_cpSwatch) _cpSwatch.style.background = hex;
  _C[_cpKey] = hex;
  $('hex-' + _cpKey).value = hex;
  if (_cpCb) _cpCb();
}

function cpOpen(swatchEl, key, cb) {
  _cpKey = key; _cpCb = cb; _cpSwatch = swatchEl;
  [_cpH, _cpS, _cpV] = hexToHsv(_C[key]);
  const popup = $('cp-popup');
  popup.classList.remove('tlt-cp-hidden');
  const rect = swatchEl.getBoundingClientRect();
  let top = rect.bottom + 8, left = rect.left;
  if (left + 244 > window.innerWidth) left = window.innerWidth - 248;
  if (top + 290 > window.innerHeight) top = rect.top - 294;
  if (top < 8) top = 8;
  popup.style.top = top + 'px'; popup.style.left = left + 'px';
  cpRender();
}

function cpClose() {
  $('cp-popup').classList.add('tlt-cp-hidden');
  _cpCb = null; _cpKey = null; _cpSwatch = null;
}

function cpHexInput(key) {
  const v = $('hex-' + key).value.trim();
  if (/^#[0-9a-fA-F]{6}$/.test(v)) { _C[key] = v; syncSwatch(key); }
}

function syncSwatch(key) { $('swatch-' + key).style.background = _C[key]; }

// ── Params & Compute ──────────────────────────────────────────────────────────
function getParams() {
  const bgAuto  = $('l-bg-auto').checked;
  const bg3Auto = $('l-bg3-auto').checked;
  return {
    chrome:     _C.chrome,
    accent:     _C.accent,
    dcl:        +$('m-dcl').value,
    sweetspot:  +$('m-sweet').value,
    satScale:   +$('m-sat').value / 100,
    bg_hue:     +$('l-bg-hue').value,
    bg_sat:     +$('l-bg-sat').value,
    bg_spread:  bgAuto  ? null : +$('l-bg-spread').value,
    bg3_hue:    +$('l-bg3-hue').value,
    bg3_sat:    +$('l-bg3-sat').value,
    bg3_spread: bg3Auto ? null : +$('l-bg3-spread').value,
    text_l:     +$('l-text-l').value,
    text_s:     +$('l-text-s').value / 100,
    muted_l:    +$('l-muted-l').value,
    muted_s:    +$('l-muted-s').value / 100,
    blur:       +$('l-blur').value,
  };
}

function computeTheme(p) {
  const [h,s,l]      = hexToHsl(p.chrome);
  const [ah,as_,al]  = hexToHsl(p.accent);
  const isDark = luma(p.chrome) < p.sweetspot;
  const cs = clamp(s * p.satScale, 0, 100);
  const bgSpread  = p.bg_spread  !== null ? p.bg_spread  : p.dcl;
  const bg3Spread = p.bg3_spread !== null ? p.bg3_spread : p.dcl;
  const bgH = h + p.bg_hue,   bgS  = clamp(cs + p.bg_sat,  0, 100);
  const bg3H = h + p.bg3_hue, bg3S = clamp(cs + p.bg3_sat, 0, 100);
  let v = {};
  if (isDark) {
    v['--bg']     = hslToHex(bgH,  bgS,       clamp(l - bgSpread,      2, 96));
    v['--bg2']    = hslToHex(h,    cs,         l);
    v['--bg3']    = hslToHex(bg3H, bg3S,      clamp(l + bg3Spread + 4, 2, 96));
    v['--border'] = hslToHex(h,    cs * .7,   clamp(l + p.dcl - 2,     2, 96));
    v['--text']   = hslToHex(h,    cs * p.text_s,  p.text_l);
    v['--muted']  = hslToHex(h,    cs * p.muted_s, p.muted_l);
  } else {
    v['--bg']     = hslToHex(bgH,  bgS  * .08, clamp(l + bgSpread,      50, 99));
    v['--bg2']    = hslToHex(h,    cs   * .18, clamp(l,                 45, 97));
    v['--bg3']    = hslToHex(bg3H, bg3S * .28, clamp(l - bg3Spread - 4, 38, 92));
    v['--border'] = hslToHex(h,    cs   * .28, clamp(l - p.dcl + 10,    38, 90));
    v['--text']   = hslToHex(h,    cs * p.text_s,  clamp(115 - p.text_l,  4, 30));
    v['--muted']  = hslToHex(h,    cs * p.muted_s, clamp(115 - p.muted_l, 30, 65));
  }
  v['--acc']  = p.accent;
  v['--acc2'] = hslToHex(ah, Math.max(as_, 50), Math.min(al + 14, 82));
  v['--blur'] = p.blur + 'px';
  return { vars: v, isDark };
}

// ── Apply & Update ────────────────────────────────────────────────────────────
function applyVars(vars, isDark) {
  const root = document.documentElement.style;
  for (const [k, val] of Object.entries(vars)) root.setProperty(k, val);
  document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
}

function fmtOff(v, unit) { return (v > 0 ? '+' : '') + v + unit; }

function update() {
  const p = getParams();
  const { vars, isDark } = computeTheme(p);
  applyVars(vars, isDark);

  $('lbl-dcl').textContent   = p.dcl;
  $('lbl-sweet').textContent = p.sweetspot + (isDark ? ' ◾' : ' ◽');
  $('lbl-sat').textContent   = Math.round(p.satScale * 100) + '%';
  $('lbl-bg-hue').textContent   = fmtOff(p.bg_hue,  '°');
  $('lbl-bg-sat').textContent   = fmtOff(p.bg_sat,  '%');
  $('lbl-bg3-hue').textContent  = fmtOff(p.bg3_hue, '°');
  $('lbl-bg3-sat').textContent  = fmtOff(p.bg3_sat, '%');
  const bgAuto  = $('l-bg-auto').checked;
  const bg3Auto = $('l-bg3-auto').checked;
  $('lbl-bg-spread').textContent  = bgAuto  ? 'auto' : p.bg_spread;
  $('lbl-bg3-spread').textContent = bg3Auto ? 'auto' : p.bg3_spread;
  $('l-bg-spread').disabled  = bgAuto;
  $('l-bg3-spread').disabled = bg3Auto;
  $('lbl-text-l').textContent  = p.text_l + '%';
  $('lbl-text-s').textContent  = Math.round(p.text_s * 100) + '%';
  $('lbl-muted-l').textContent = p.muted_l + '%';
  $('lbl-muted-s').textContent = Math.round(p.muted_s * 100) + '%';
  $('lbl-blur').textContent    = p.blur + 'px';

  const swMap = { bg:'--bg', bg2:'--bg2', bg3:'--bg3', text:'--text', muted:'--muted', acc:'--acc' };
  for (const [name, cssVar] of Object.entries(swMap)) {
    const hex = vars[cssVar] || p.accent;
    $('sw-' + name).style.background = hex;
    $('shx-' + name).textContent = hex;
  }
  syncSwatch('chrome'); syncSwatch('accent');

  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(() => saveToServer(p), 800);
}

// ── Server Sync ───────────────────────────────────────────────────────────────
async function loadFromServer() {
  if (_subpath == null) return;
  try {
    const r = await fetch(_subpath + '/theme');
    if (r.ok) restoreParams(await r.json());
  } catch (e) {}
}

async function saveToServer(params) {
  if (_subpath) {
    try {
      await fetch(_subpath + '/theme', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
    } catch (e) {}
  }
  if (_onSave) _onSave(params);
}

// ── Restore params → UI ───────────────────────────────────────────────────────
function restoreParams(p) {
  _C.chrome = p.chrome; _C.accent = p.accent;
  $('hex-chrome').value = p.chrome;
  $('hex-accent').value = p.accent;
  $('m-dcl').value    = p.dcl;
  $('m-sweet').value  = p.sweetspot;
  $('m-sat').value    = Math.round(p.satScale * 100);
  $('l-bg-hue').value = p.bg_hue;   $('l-bg-sat').value  = p.bg_sat;
  $('l-bg3-hue').value = p.bg3_hue; $('l-bg3-sat').value = p.bg3_sat;
  $('l-bg-auto').checked  = p.bg_spread  === null;
  $('l-bg3-auto').checked = p.bg3_spread === null;
  if (p.bg_spread  !== null) $('l-bg-spread').value  = p.bg_spread;
  if (p.bg3_spread !== null) $('l-bg3-spread').value = p.bg3_spread;
  $('l-text-l').value  = p.text_l;
  $('l-text-s').value  = Math.round(p.text_s  * 100);
  $('l-muted-l').value = p.muted_l;
  $('l-muted-s').value = Math.round(p.muted_s * 100);
  $('l-blur').value    = p.blur;
}

// ── Panel Toggle ──────────────────────────────────────────────────────────────
function togglePanel(id) {
  const body = $('body-' + id), tog = $('toggle-' + id);
  const open = !body.classList.contains('tlt-collapsed');
  body.classList.toggle('tlt-collapsed', open);
  tog.textContent = open ? '▼' : '▲';
  tog.classList.toggle('tlt-open', !open);
}

// ── Presets ───────────────────────────────────────────────────────────────────
const UI_PRESETS = [
  { chrome:'#1a1a2e', accent:'#7c9cbf', label:'Nacht-Blau'  },
  { chrome:'#1a2418', accent:'#6abf6a', label:'Nacht-Grün'  },
  { chrome:'#2a1a2e', accent:'#b07cc0', label:'Nacht-Lila'  },
  { chrome:'#2a1a1a', accent:'#bf7c7c', label:'Nacht-Rot'   },
  { chrome:'#241f14', accent:'#d4a060', label:'Warm-Dunkel' },
  { chrome:'#1a2028', accent:'#c0a060', label:'Nacht-Gold'  },
  { chrome:'#f0f0f5', accent:'#4a6abf', label:'Hell-Kühl'   },
  { chrome:'#f5f0ea', accent:'#9a6040', label:'Hell-Warm'   },
];

function buildPresets() {
  const wrap = $('presets'); wrap.innerHTML = '';
  UI_PRESETS.forEach(p => {
    const el = document.createElement('div');
    el.className = 'tlt-preset-swatch';
    el.style.background = p.chrome;
    el.style.outlineColor = p.accent;
    el.style.outlineWidth = '2px';
    el.style.outlineStyle = 'solid';
    el.title = p.label;
    el.onclick = () => {
      _C.chrome = p.chrome; _C.accent = p.accent;
      $('hex-chrome').value = p.chrome;
      $('hex-accent').value = p.accent;
      if (_cpKey === 'chrome') [_cpH,_cpS,_cpV] = hexToHsv(p.chrome);
      if (_cpKey === 'accent') [_cpH,_cpS,_cpV] = hexToHsv(p.accent);
      update();
    };
    wrap.appendChild(el);
  });
}

function resetTheme() {
  const p = _defaultPreset || { chrome:'#1a1a2e', accent:'#7c9cbf' };
  _C.chrome = p.chrome; _C.accent = p.accent;
  $('hex-chrome').value = p.chrome;
  $('hex-accent').value = p.accent;
  $('m-dcl').value = 7; $('m-sweet').value = 110; $('m-sat').value = 100;
  $('l-bg-hue').value = 0;   $('l-bg-sat').value = 0;   $('l-bg-spread').value = 7;
  $('l-bg3-hue').value = 0;  $('l-bg3-sat').value = 0;  $('l-bg3-spread').value = 7;
  $('l-bg-auto').checked = false; $('l-bg3-auto').checked = false;
  $('l-text-l').value = 91; $('l-text-s').value = 15;
  $('l-muted-l').value = 60; $('l-muted-s').value = 35;
  $('l-blur').value = 8;
  update();
}

// ── Snapshot ──────────────────────────────────────────────────────────────────
function _saveSnapLog() {
  if (_subpath != null) {
    fetch(_subpath + '/snapshots', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_log),
    }).catch(() => {});
  } else {
    try { localStorage.setItem('tlt_snap_log', JSON.stringify(_log)); } catch(e) {}
  }
}

async function _loadSnapLog() {
  if (_subpath != null) {
    try {
      const r = await fetch(_subpath + '/snapshots');
      if (r.ok) { const d = await r.json(); if (Array.isArray(d)) _log = d; }
    } catch(e) {}
  } else {
    try { const s = localStorage.getItem('tlt_snap_log'); if (s) _log = JSON.parse(s); } catch(e) {}
  }
}

function snapshot() {
  const p = getParams();
  const { vars } = computeTheme(p);
  const now = new Date();
  const ts = [now.getHours(), now.getMinutes(), now.getSeconds()]
    .map(n => n.toString().padStart(2,'0')).join(':');
  _log.unshift({ ts, p, vars });
  _saveSnapLog();
  renderLog();
  if (_onApply) _onApply(p, vars);
}

function renderLog() {
  const el = $('log-list');
  if (!_log.length) { el.innerHTML = '<div class="tlt-log-empty">Noch keine Snapshots</div>'; return; }
  el.innerHTML = _log.map(({ ts, p, vars }, i) => {
    const sw = ['--bg','--bg2','--bg3','--acc'].map(v =>
      `<div class="tlt-log-sw" style="background:${vars[v]}" title="${v}"></div>`).join('');
    const off = (p.bg_hue || p.bg3_hue || p.bg_sat || p.bg3_sat) ?
      ` bg${fmtOff(p.bg_hue,'°')}/${fmtOff(p.bg_sat,'%')}` : '';
    return `<div class="tlt-log-entry" onclick="tulTheme._restoreSnap(${i})">
      <div class="tlt-log-swatches">${sw}</div>
      <div><div class="tlt-log-meta">${p.chrome} d${p.dcl}${off}</div><div class="tlt-log-ts">${ts}</div></div>
      <div class="tlt-log-del" onclick="event.stopPropagation();tulTheme._delSnap(${i})">×</div>
    </div>`;
  }).join('');
}

function copyLog() {
  if (!_log.length) { alert('Kein Log vorhanden.'); return; }
  const txt = JSON.stringify(_log.map(({ ts, p, vars }) => ({ ts, params: p, colors: vars })), null, 2);
  navigator.clipboard.writeText(txt)
    .catch(() => { const ta = document.createElement('textarea'); ta.value = txt; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); });
  alert(`${_log.length} Snapshot(s) in Zwischenablage`);
}

// ── Events ────────────────────────────────────────────────────────────────────
function setupEvents() {
  ['m-dcl','m-sweet','m-sat',
   'l-bg-hue','l-bg-sat','l-bg-spread',
   'l-bg3-hue','l-bg3-sat','l-bg3-spread',
   'l-text-l','l-text-s','l-muted-l','l-muted-s','l-blur'].forEach(id => {
    $(id).addEventListener('input', update);
  });
  ['l-bg-auto','l-bg3-auto'].forEach(id => $(id).addEventListener('change', update));

  $('hex-chrome').addEventListener('input', () => { cpHexInput('chrome'); update(); });
  $('hex-accent').addEventListener('input', () => { cpHexInput('accent'); update(); });
  $('swatch-chrome').addEventListener('click', () => cpOpen($('swatch-chrome'), 'chrome', update));
  $('swatch-accent').addEventListener('click', () => cpOpen($('swatch-accent'), 'accent', update));

  $('hdr-main').addEventListener('click', () => togglePanel('main'));
  $('hdr-lab').addEventListener('click',  () => togglePanel('lab'));

  $('btn-lab').addEventListener('click', () => {
    const lab = $('panel-lab');
    const hidden = lab.style.display === 'none';
    lab.style.display = hidden ? 'flex' : 'none';
    if (hidden) {
      $('body-lab').classList.remove('tlt-collapsed');
      $('toggle-lab').textContent = '▲';
      $('toggle-lab').classList.add('tlt-open');
    }
  });

  $('btn-reset').addEventListener('click', resetTheme);
  $('btn-snap').addEventListener('click', snapshot);
  $('btn-copy').addEventListener('click', copyLog);

  // Picker SL-Feld
  let drag = false;
  function slMove(e) {
    const cl = e.touches ? e.touches[0] : e;
    const r = $('cp-field').getBoundingClientRect();
    _cpS = clamp(((cl.clientX - r.left) / r.width) * 100, 0, 100);
    _cpV = clamp(100 - ((cl.clientY - r.top) / r.height) * 100, 0, 100);
    cpRender();
  }
  $('cp-field').addEventListener('mousedown', e => { drag=true; slMove(e); e.preventDefault(); });
  document.addEventListener('mousemove',       e => { if (drag) slMove(e); });
  document.addEventListener('mouseup',         () => drag = false);
  $('cp-field').addEventListener('touchstart', e => { drag=true; slMove(e); e.preventDefault(); }, { passive:false });
  document.addEventListener('touchmove',       e => { if (drag) slMove(e); }, { passive:false });
  document.addEventListener('touchend',        () => drag = false);

  $('cp-hue').addEventListener('input', () => { _cpH = +$('cp-hue').value; cpRender(); });
  $('cp-hex').addEventListener('input', () => {
    const v = $('cp-hex').value.trim();
    if (/^#[0-9a-fA-F]{6}$/.test(v)) { [_cpH,_cpS,_cpV] = hexToHsv(v); cpRender(); }
  });
  document.addEventListener('click', e => {
    const popup = $('cp-popup');
    if (popup.classList.contains('tlt-cp-hidden')) return;
    if (!popup.contains(e.target) && !e.target.classList.contains('tlt-cp-swatch')) cpClose();
  });
}

// ── Public API ────────────────────────────────────────────────────────────────
const tulTheme = {
  PRESETS: MODULE_PRESETS,

  init(opts = {}) {
    _subpath       = opts.subpath  || '';
    _onApply       = opts.onApply  || null;
    _onSave        = opts.onSave   || null;
    _defaultPreset = opts.preset   || null;

    injectHTML();
    buildPresets();

    if (_defaultPreset) {
      _C.chrome = _defaultPreset.chrome;
      _C.accent = _defaultPreset.accent;
      $('hex-chrome').value = _defaultPreset.chrome;
      $('hex-accent').value = _defaultPreset.accent;
    }

    setupEvents();
    update();

    if (opts.labVisible === true) $('panel-lab').style.display = 'flex';

    // Server-Theme laden → überschreibt Default-Preset; dann Snapshots laden
    loadFromServer().then(() => update()).then(() => _loadSnapLog().then(() => renderLog()));
  },

  // Aufgerufen aus onclick in renderLog (inline HTML)
  _restoreSnap(i) { restoreParams(_log[i].p); update(); },
  _delSnap(i)     { _log.splice(i, 1); _saveSnapLog(); renderLog(); },

  // Programmatic API für Board-Theme-Switching
  setParams(p)    { restoreParams(p); update(); },
  getParams()     { return getParams(); },
};

global.tulTheme = tulTheme;
})(window);

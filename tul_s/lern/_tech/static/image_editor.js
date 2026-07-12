// ── Anleitung-Modal ───────────────────────────────────────────────────────────

function openHelp() {
  document.getElementById('help-modal').style.display = 'flex';
}
function closeHelp() {
  document.getElementById('help-modal').style.display = 'none';
}

// ── Lizenz-Modal ──────────────────────────────────────────────────────────────

function openLicense() {
  document.getElementById('license-modal').style.display = 'flex';
}
function closeLicense() {
  document.getElementById('license-modal').style.display = 'none';
}

// ── Bildeditor ────────────────────────────────────────────────────────────────

const IE = {
  filename: '',
  origImg: null,
  origCanvas: null,   // unskalierter Original-Canvas für Pixel-Zugriff
  cropRatio: 2.25,
  cardWmm: 180.0,
  cardHmm: 80.0,
  cropScale: 1.0,     // 0.1..1.0 – Anteil des maximalen Ausschnitts
  cropOffsetX: 0.0,
  cropOffsetY: 0.0,
  saturation: 1.0,
  activeChannel: 'rgb',
  controlPoints: {},
  luts: { rgb: null, r: null, g: null, b: null },
  dragIdx: null,
};

const IE_COLORS = { rgb: '#ccccdd', r: '#e88060', g: '#60c880', b: '#6090e8' };

function _ieDefaultPoints(ch) {
  if (ch === 'rgb') return [
    {x:0,y:0},{x:64,y:64},{x:128,y:128},{x:192,y:192},{x:255,y:255}
  ];
  return [{x:0,y:0},{x:128,y:128},{x:255,y:255}];
}

function openImageEditorFromSelect(selectId) {
  const sel = document.getElementById(selectId);
  const val = sel ? sel.value : '';
  if (!val) { alert('Zuerst ein Bild auswählen.'); return; }
  openImageEditor(val);
}

function openImageEditor(filename) {
  IE.filename = filename;
  IE.cardWmm  = parseFloat(document.getElementById('card-w')?.value) || 180;
  IE.cardHmm  = parseFloat(document.getElementById('card-h')?.value) || 80;
  IE.cropRatio = IE.cardWmm / IE.cardHmm;
  IE.controlPoints = {
    rgb: _ieDefaultPoints('rgb'),
    r:   _ieDefaultPoints('r'),
    g:   _ieDefaultPoints('g'),
    b:   _ieDefaultPoints('b'),
  };
  IE.cropScale   = 1.0;
  IE.cropOffsetX = 0; IE.cropOffsetY = 0;
  IE.saturation  = 1.0;
  IE.activeChannel = 'rgb';
  IE.dragIdx = null;

  document.getElementById('ie-title').textContent = filename;
  document.getElementById('ie-save-as').value =
    filename.replace(/(_edit)?(\.[^.]+)$/, '_edit$2');
  document.getElementById('ie-saturation').value = '1';
  document.getElementById('ie-sat-val').textContent = '1.00';
  document.getElementById('ie-crop-scale').value = '1';
  document.getElementById('ie-crop-scale-val').textContent = '100%';
  document.getElementById('ie-crop-x').value = '0';
  document.getElementById('ie-crop-y').value = '0';
  document.getElementById('ie-crop-x-val').textContent = '0.00';
  document.getElementById('ie-crop-y-val').textContent = '0.00';
  document.getElementById('ie-save-status').textContent = '';
  document.querySelectorAll('.ie-tab').forEach(b => b.classList.remove('active'));
  document.getElementById('ie-tab-rgb').classList.add('active');

  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.onload = () => {
    IE.origImg = img;
    const oc = document.createElement('canvas');
    oc.width = img.naturalWidth; oc.height = img.naturalHeight;
    oc.getContext('2d').drawImage(img, 0, 0);
    IE.origCanvas = oc;
    _ieMakeAllLUTs();
    _ieRedrawCurve();
    _ieRedrawPreview();
  };
  img.onerror = () => alert('Bild konnte nicht geladen werden: ' + filename);
  img.src = '/api/pictures/serve/' + encodeURIComponent(filename);

  document.getElementById('ie-modal').style.display = 'flex';
}

function closeImageEditor() {
  document.getElementById('ie-modal').style.display = 'none';
}

// ── Monotone kubische Spline (Fritsch-Carlson) ────────────────────────────────

function _ieSpline(pts) {
  const n = pts.length;
  if (n === 0) return () => 128;
  if (n === 1) return () => pts[0].y;
  if (n === 2) {
    return x => pts[0].y + (pts[1].y - pts[0].y) *
      Math.max(0, Math.min(1, (x - pts[0].x) / (pts[1].x - pts[0].x || 1)));
  }
  const d = [], m = new Array(n);
  for (let i = 0; i < n - 1; i++) {
    const dx = pts[i+1].x - pts[i].x;
    d[i] = dx === 0 ? 0 : (pts[i+1].y - pts[i].y) / dx;
  }
  m[0] = d[0]; m[n-1] = d[n-2];
  for (let i = 1; i < n - 1; i++) m[i] = (d[i-1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (Math.abs(d[i]) < 1e-8) { m[i] = m[i+1] = 0; continue; }
    const a = m[i] / d[i], b = m[i+1] / d[i], s = a*a + b*b;
    if (s > 9) { const t = 3 / Math.sqrt(s); m[i] = t*a*d[i]; m[i+1] = t*b*d[i]; }
  }
  return x => {
    if (x <= pts[0].x)   return pts[0].y;
    if (x >= pts[n-1].x) return pts[n-1].y;
    let lo = 0, hi = n - 2;
    while (lo < hi) { const mid = (lo+hi)>>1; if (pts[mid+1].x <= x) lo = mid+1; else hi = mid; }
    const i = lo, h = pts[i+1].x - pts[i].x;
    if (h === 0) return pts[i].y;
    const t = (x - pts[i].x) / h, t2 = t*t, t3 = t2*t;
    return (2*t3 - 3*t2 + 1)*pts[i].y + (t3 - 2*t2 + t)*h*m[i] +
           (-2*t3 + 3*t2)*pts[i+1].y + (t3 - t2)*h*m[i+1];
  };
}

function _ieMakeLUT(pts) {
  const fn = _ieSpline(pts);
  return Array.from({length: 256}, (_, i) => Math.max(0, Math.min(255, Math.round(fn(i)))));
}

function _ieMakeAllLUTs() {
  for (const ch of ['rgb','r','g','b']) IE.luts[ch] = _ieMakeLUT(IE.controlPoints[ch]);
}

// Gesamt-LUT × Kanal-LUT: erst RGB-Kurve, dann Kanal-Kurve
function _ieCompose(ch) {
  const base = IE.luts.rgb, chan = IE.luts[ch];
  return base.map(v => chan[v]);
}

// ── Kurven-Canvas ─────────────────────────────────────────────────────────────

function _ieRedrawCurve() {
  const cv = document.getElementById('ie-curve');
  if (!cv) return;
  const ctx = cv.getContext('2d');
  const W = cv.width, H = cv.height;

  ctx.fillStyle = '#10101c';
  ctx.fillRect(0, 0, W, H);

  // Gitter
  ctx.strokeStyle = '#222234'; ctx.lineWidth = 1;
  for (const v of [64, 128, 192]) {
    ctx.beginPath(); ctx.moveTo(v/255*W, 0); ctx.lineTo(v/255*W, H); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, (1-v/255)*H); ctx.lineTo(W, (1-v/255)*H); ctx.stroke();
  }

  // Diagonale
  ctx.strokeStyle = '#2a2a40'; ctx.setLineDash([3,4]);
  ctx.beginPath(); ctx.moveTo(0,H); ctx.lineTo(W,0); ctx.stroke();
  ctx.setLineDash([]);

  // Inaktive Kanäle (gedimmt)
  for (const ch of ['rgb','r','g','b']) {
    if (ch === IE.activeChannel) continue;
    const lut = IE.luts[ch]; if (!lut) continue;
    ctx.strokeStyle = IE_COLORS[ch] + '44'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, (1-lut[0]/255)*H);
    for (let i = 1; i < 256; i++) ctx.lineTo(i/255*W, (1-lut[i]/255)*H);
    ctx.stroke();
  }

  // Aktiver Kanal
  const lut = IE.luts[IE.activeChannel];
  ctx.strokeStyle = IE_COLORS[IE.activeChannel]; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(0, (1-lut[0]/255)*H);
  for (let i = 1; i < 256; i++) ctx.lineTo(i/255*W, (1-lut[i]/255)*H);
  ctx.stroke();

  // Kontrollpunkte
  for (const p of IE.controlPoints[IE.activeChannel]) {
    const px = p.x/255*W, py = (1-p.y/255)*H;
    ctx.beginPath(); ctx.arc(px, py, 5, 0, Math.PI*2);
    ctx.fillStyle = IE_COLORS[IE.activeChannel]; ctx.fill();
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke();
  }
}

// ── Kurven-Interaktion ────────────────────────────────────────────────────────

function _iePtDist(p, mx, my) {
  return Math.sqrt((p.x-mx)**2 + (p.y-my)**2);
}

function _ieCurveCoords(cv, e) {
  const r = cv.getBoundingClientRect();
  return {
    x: Math.round((e.clientX - r.left) / r.width  * 255),
    y: Math.round((1 - (e.clientY - r.top) / r.height) * 255),
  };
}

function _ieCurveMouseDown(e) {
  const cv = document.getElementById('ie-curve');
  const {x, y} = _ieCurveCoords(cv, e);
  const pts = IE.controlPoints[IE.activeChannel];
  const threshold = 14 * 255 / cv.offsetWidth;
  let best = -1, bestD = threshold;
  for (let i = 0; i < pts.length; i++) {
    const d = _iePtDist(pts[i], x, y);
    if (d < bestD) { bestD = d; best = i; }
  }
  if (best >= 0) {
    IE.dragIdx = best;
  } else {
    // Neuen Punkt einfügen
    pts.push({x: Math.max(0, Math.min(255, x)), y: Math.max(0, Math.min(255, y))});
    pts.sort((a, b) => a.x - b.x);
    IE.dragIdx = pts.findIndex(p => p.x === Math.max(0, Math.min(255, x)) && p.y === Math.max(0, Math.min(255, y)));
    _ieMakeAllLUTs(); _ieRedrawCurve(); _ieRedrawPreview();
  }
  e.preventDefault();
}

function _ieCurveMouseMove(e) {
  if (IE.dragIdx === null) return;
  const cv = document.getElementById('ie-curve');
  if (!cv) return;
  const {x, y} = _ieCurveCoords(cv, e);
  const pts = IE.controlPoints[IE.activeChannel];
  const p = pts[IE.dragIdx];
  p.y = Math.max(0, Math.min(255, y));
  if (IE.dragIdx === 0) p.x = 0;
  else if (IE.dragIdx === pts.length - 1) p.x = 255;
  else p.x = Math.max(pts[IE.dragIdx-1].x + 1, Math.min(pts[IE.dragIdx+1].x - 1, x));
  _ieMakeAllLUTs(); _ieRedrawCurve(); _ieRedrawPreview();
}

function _ieCurveMouseUp() { IE.dragIdx = null; }

function _ieCurveDblClick(e) {
  const cv = document.getElementById('ie-curve');
  const {x, y} = _ieCurveCoords(cv, e);
  const pts = IE.controlPoints[IE.activeChannel];
  if (pts.length <= 2) return;
  const threshold = 14 * 255 / cv.offsetWidth;
  for (let i = 1; i < pts.length - 1; i++) {
    if (_iePtDist(pts[i], x, y) < threshold) {
      pts.splice(i, 1);
      _ieMakeAllLUTs(); _ieRedrawCurve(); _ieRedrawPreview();
      return;
    }
  }
}

function _ieSetChannel(ch) {
  IE.activeChannel = ch;
  document.querySelectorAll('.ie-tab').forEach(b => b.classList.remove('active'));
  document.getElementById('ie-tab-' + ch).classList.add('active');
  _ieRedrawCurve();
}

function _ieResetCurve() {
  IE.controlPoints[IE.activeChannel] = _ieDefaultPoints(IE.activeChannel);
  _ieMakeAllLUTs(); _ieRedrawCurve(); _ieRedrawPreview();
}

// ── Vorschau ──────────────────────────────────────────────────────────────────

function _ieRedrawPreview() {
  const cv = document.getElementById('ie-preview');
  if (!cv || !IE.origCanvas) return;
  const ctx = cv.getContext('2d');
  const W = cv.width, H = cv.height;

  ctx.fillStyle = '#0c0c18'; ctx.fillRect(0, 0, W, H);

  const srcW = IE.origImg.naturalWidth, srcH = IE.origImg.naturalHeight;
  const scale = Math.min(W / srcW, H / srcH);
  const dW = Math.round(srcW * scale), dH = Math.round(srcH * scale);
  const dX = Math.floor((W - dW) / 2), dY = Math.floor((H - dH) / 2);

  // Skaliertes Bild mit LUT/Sättigung auf Offscreen-Canvas anwenden
  const tmp = document.createElement('canvas');
  tmp.width = dW; tmp.height = dH;
  const tctx = tmp.getContext('2d');
  tctx.drawImage(IE.origCanvas, 0, 0, dW, dH);

  const id = tctx.getImageData(0, 0, dW, dH);
  const px = id.data;
  const lR = _ieCompose('r'), lG = _ieCompose('g'), lB = _ieCompose('b');
  const sat = IE.saturation;

  for (let i = 0; i < px.length; i += 4) {
    let r = lR[px[i]], g = lG[px[i+1]], b = lB[px[i+2]];
    if (sat !== 1.0) {
      const gr = 0.299*r + 0.587*g + 0.114*b;
      r = Math.max(0, Math.min(255, gr + (r - gr) * sat));
      g = Math.max(0, Math.min(255, gr + (g - gr) * sat));
      b = Math.max(0, Math.min(255, gr + (b - gr) * sat));
    }
    px[i] = r; px[i+1] = g; px[i+2] = b;
  }
  tctx.putImageData(id, 0, 0);
  ctx.drawImage(tmp, dX, dY);

  // Crop-Overlay: maximaler Ausschnitt skaliert auf cropScale
  const ratio = IE.cropRatio;
  const imgRatio = srcW / srcH;
  let maxCropW, maxCropH;
  if (imgRatio > ratio) {
    maxCropH = dH; maxCropW = Math.round(dH * ratio);
  } else {
    maxCropW = dW; maxCropH = Math.round(dW / ratio);
  }
  const cropW = Math.max(4, Math.round(maxCropW * IE.cropScale));
  const cropH = Math.max(4, Math.round(maxCropH * IE.cropScale));
  const slackX = dW - cropW, slackY = dH - cropH;
  const cX = dX + Math.round(slackX / 2 * (1 + IE.cropOffsetX));
  const cY = dY + Math.round(slackY / 2 * (1 + IE.cropOffsetY));

  // Abdunkelung außerhalb des Crops
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.beginPath();
  ctx.rect(dX, dY, dW, dH);
  ctx.rect(cX, cY, cropW, cropH);
  ctx.fill('evenodd');

  // Crop-Rahmen
  ctx.strokeStyle = 'rgba(255,255,255,0.85)'; ctx.lineWidth = 1.5;
  ctx.strokeRect(cX + 0.5, cY + 0.5, cropW - 1, cropH - 1);
}

function _ieUpdateCropScale(val) {
  IE.cropScale = parseFloat(val);
  document.getElementById('ie-crop-scale-val').textContent =
    Math.round(IE.cropScale * 100) + '%';
  _ieRedrawPreview();
}
function _ieUpdateCropX(val) {
  IE.cropOffsetX = parseFloat(val);
  document.getElementById('ie-crop-x-val').textContent = parseFloat(val).toFixed(2);
  _ieRedrawPreview();
}
function _ieUpdateCropY(val) {
  IE.cropOffsetY = parseFloat(val);
  document.getElementById('ie-crop-y-val').textContent = parseFloat(val).toFixed(2);
  _ieRedrawPreview();
}
function _ieUpdateSaturation(val) {
  IE.saturation = parseFloat(val);
  document.getElementById('ie-sat-val').textContent = parseFloat(val).toFixed(2);
  _ieRedrawPreview();
}

// ── Speichern ─────────────────────────────────────────────────────────────────

async function saveImageEdit() {
  const saveAs = document.getElementById('ie-save-as').value.trim();
  if (!saveAs) { alert('Dateiname eingeben'); return; }
  const status = document.getElementById('ie-save-status');
  status.textContent = 'Speichert…';

  const resp = await fetch('/api/pictures/edit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      filename:      IE.filename,
      save_as:       saveAs,
      luts:          { r: _ieCompose('r'), g: _ieCompose('g'), b: _ieCompose('b') },
      saturation:    IE.saturation,
      crop_scale:    IE.cropScale,
      crop_offset_x: IE.cropOffsetX,
      crop_offset_y: IE.cropOffsetY,
      card_ratio:    IE.cropRatio,
      card_w_mm:     IE.cardWmm,
      card_h_mm:     IE.cardHmm,
    }),
  });
  const d = await resp.json();
  status.textContent = d.ok ? `Gespeichert: ${d.saved_as}` : `Fehler: ${d.error}`;
  if (d.ok) {
    setTimeout(() => { status.textContent = ''; }, 4000);
    _reloadImageDropdowns(saveAs);
  }
}

async function _reloadImageDropdowns(selectName) {
  try {
    const resp = await fetch('/api/pictures/list');
    const d = await resp.json();
    if (!d.ok) return;
    ['front-bg', 'back-bg'].forEach(id => {
      const sel = document.getElementById(id);
      if (!sel) return;
      const prev = sel.value;
      const emptyOpt = sel.querySelector('option[value=""]');
      sel.innerHTML = '';
      if (emptyOpt) sel.appendChild(emptyOpt.cloneNode(true));
      d.images.forEach(name => {
        const o = document.createElement('option');
        o.value = name; o.textContent = name;
        sel.appendChild(o);
      });
      sel.value = (selectName && d.images.includes(selectName)) ? selectName : prev;
    });
    if (typeof previewCard === 'function') previewCard();
  } catch (_) {}
}

// ── Event-Listener (einmalig beim Laden) ──────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  const cv = document.getElementById('ie-curve');
  if (!cv) return;
  cv.addEventListener('mousedown',  _ieCurveMouseDown);
  cv.addEventListener('dblclick',   _ieCurveDblClick);
  document.addEventListener('mousemove', _ieCurveMouseMove);
  document.addEventListener('mouseup',   _ieCurveMouseUp);
});

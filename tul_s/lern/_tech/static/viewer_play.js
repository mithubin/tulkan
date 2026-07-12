// ── Config aus sessionStorage ─────────────────────────────────────────────────

const CFG = (() => {
  try { return JSON.parse(sessionStorage.getItem('viewer_cfg') || '{}'); } catch { return {}; }
})();

if (!CFG.pdf) {
  document.body.innerHTML = '<p style="padding:40px;color:#888">Keine Session-Daten. Bitte über den Viewer starten.</p>';
  throw new Error('no cfg');
}

// ── State ─────────────────────────────────────────────────────────────────────

const S = {
  cards:        [],       // geordnete Karten-Nummern (1-basiert) vom Server
  page_count:   0,
  idx:          0,        // Index in S.cards
  side:         'q',      // 'q' | 'a'
  scores:       {},       // {card_num: 'richtig'|'falsch'|'neutral'}
  startTime:    Date.now(),
  mode:         CFG.mode || 'manual',  // 'manual' | 'auto'
  timing:       CFG.timing || [10, 16, 12, 20],
  paused:       false,
  timerId:      null,
  imgCache:     {},       // {url: Image}
  ready:        false,
};

// ── DOM-Refs ──────────────────────────────────────────────────────────────────

const cardImg    = document.getElementById('card-img');
const stProgress = document.getElementById('st-progress');
const stScore    = document.getElementById('st-score');
const stMode     = document.getElementById('st-mode');
const timerWrap  = document.getElementById('timer-bar-wrap');
const timerBar   = document.getElementById('timer-bar');
const keyHints   = document.getElementById('key-hints');
const pauseOvl   = document.getElementById('pause-overlay');
const endOvl     = document.getElementById('end-overlay');

// ── Bild laden ────────────────────────────────────────────────────────────────

function pageUrl(pageNum) {
  return `/api/viewer/page/${encodeURIComponent(CFG.pdf)}/${pageNum}`;
}

function cardPage(cardNum, side) {
  return side === 'q' ? (cardNum - 1) * 2 + 1 : (cardNum - 1) * 2 + 2;
}

function preload(cardNum, side) {
  const url = pageUrl(cardPage(cardNum, side));
  if (!S.imgCache[url]) {
    const img = new Image();
    img.src = url;
    S.imgCache[url] = img;
  }
}

function showPage(pageNum, onLoad) {
  const url = pageUrl(pageNum);
  if (S.imgCache[url]?.complete && S.imgCache[url].naturalWidth) {
    cardImg.src = url;
    onLoad?.();
  } else {
    const img = new Image();
    img.onload = () => { cardImg.src = url; S.imgCache[url] = img; onLoad?.(); };
    img.src = url;
    S.imgCache[url] = img;
  }
}

// ── Anzeige-Update ────────────────────────────────────────────────────────────

function updateStatus() {
  const card = S.cards[S.idx];
  const sideLabel = S.side === 'q' ? 'Frage' : 'Antwort';
  stProgress.textContent = `${S.idx + 1} / ${S.cards.length}  ·  ${sideLabel}${S.scores[card] ? '  ·  ' + scoreLabel(S.scores[card]) : ''}`;

  let r = 0, f = 0, n = 0;
  Object.values(S.scores).forEach(v => { if (v==='richtig') r++; else if (v==='falsch') f++; else n++; });
  stScore.innerHTML = `<span class="sc-r">✓ ${r}</span><span class="sc-f">✗ ${f}</span><span class="sc-n">○ ${n}</span>`;
  stMode.textContent = S.mode === 'auto' ? (S.paused ? '⏸ Autopilot' : '▶ Autopilot') : 'Manuell';
}

function scoreLabel(v) {
  return v === 'richtig' ? '✓' : v === 'falsch' ? '✗' : '○';
}

// ── Navigation ────────────────────────────────────────────────────────────────

function goTo(idx, side) {
  cancelTimer();
  S.idx  = Math.max(0, Math.min(S.cards.length - 1, idx));
  S.side = side;
  const card = S.cards[S.idx];
  const page = cardPage(card, S.side);
  showPage(page, () => {
    // Preload nächste
    if (S.side === 'q') preload(card, 'a');
    else if (S.idx + 1 < S.cards.length) { preload(S.cards[S.idx + 1], 'q'); }
    if (S.mode === 'auto' && !S.paused) startTimer();
    updateStatus();
  });
}

function advance() {
  // Zeigt nächste Seite: Q→A oder A→nächstes Q
  if (S.side === 'q') {
    goTo(S.idx, 'a');
  } else {
    if (S.idx + 1 >= S.cards.length) {
      showEnd(false);
    } else {
      goTo(S.idx + 1, 'q');
    }
  }
}

function back() {
  if (S.side === 'a') {
    goTo(S.idx, 'q');
  } else if (S.idx > 0) {
    goTo(S.idx - 1, 'a');
  }
}

// ── Bewertung ─────────────────────────────────────────────────────────────────

function score(result) {
  const card = S.cards[S.idx];
  S.scores[card] = result;
  updateStatus();
  // Wenn auf Antwort-Seite: nach kurzem Moment weiter
  if (S.side === 'a') {
    cancelTimer();
    setTimeout(advance, 300);
  }
}

// ── Autopilot-Timer ───────────────────────────────────────────────────────────

function startTimer() {
  cancelTimer();
  const [qMin, qMax, aMin, aMax] = S.timing;
  const ms = S.side === 'q'
    ? (qMin + Math.random() * (qMax - qMin)) * 1000
    : (aMin + Math.random() * (aMax - aMin)) * 1000;

  // Animierter Balken
  timerWrap.style.display = '';
  timerBar.style.transition = 'none';
  timerBar.style.width = '100%';
  timerBar.offsetWidth; // reflow
  timerBar.style.transition = `width ${ms}ms linear`;
  timerBar.style.width = '0%';

  S.timerId = setTimeout(advance, ms);
}

function cancelTimer() {
  if (S.timerId) { clearTimeout(S.timerId); S.timerId = null; }
  timerBar.style.transition = 'none';
  timerBar.style.width = '100%';
  timerWrap.style.display = 'none';
}

// ── Pause ─────────────────────────────────────────────────────────────────────

function togglePause() {
  if (S.mode !== 'auto') return;
  S.paused = !S.paused;
  pauseOvl.style.display = S.paused ? 'flex' : 'none';
  if (S.paused) {
    cancelTimer();
  } else {
    startTimer();
  }
  updateStatus();
}

// ── Modus wechseln ────────────────────────────────────────────────────────────

function toggleMode() {
  cancelTimer();
  S.mode = S.mode === 'manual' ? 'auto' : 'manual';
  if (S.mode === 'auto' && !S.paused) startTimer();
  updateStatus();
}

// ── End-Overlay ───────────────────────────────────────────────────────────────

function showEnd(aborted) {
  cancelTimer();
  S.ready = false;

  const dur = Math.round((Date.now() - S.startTime) / 1000);
  const total = S.cards.length;
  let r = 0, f = 0, n = 0;
  Object.values(S.scores).forEach(v => { if (v==='richtig') r++; else if (v==='falsch') f++; else n++; });
  const unscored = total - r - f - n;

  document.getElementById('end-title').textContent = aborted ? 'Session beendet' : 'Alle Karten gezeigt';
  document.getElementById('end-total').textContent = `${total} (${unscored} unbewertet)`;
  document.getElementById('end-r').textContent   = `${r} (${total ? Math.round(r/total*100) : 0}%)`;
  document.getElementById('end-f').textContent   = `${f} (${total ? Math.round(f/total*100) : 0}%)`;
  document.getElementById('end-n').textContent   = `${n}`;
  document.getElementById('end-dur').textContent = `${Math.floor(dur/60)}m ${dur%60}s`;

  endOvl.style.display = 'flex';
  document.getElementById('end-name').focus();
}

async function saveScore() {
  const name  = document.getElementById('end-name').value.trim();
  const dur   = Math.round((Date.now() - S.startTime) / 1000);
  let r = 0, f = 0, n = 0;
  Object.values(S.scores).forEach(v => { if (v==='richtig') r++; else if (v==='falsch') f++; else n++; });

  await fetch(_BASE+'/api/viewer/score', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      pdf: CFG.pdf,
      name,
      rounds: [{
        richtig: r, falsch: f, neutral: n,
        duration: dur,
        level_filter: CFG.level_filter || [],
        randomize: !!CFG.randomize,
      }],
    }),
  });
  window.close();
}

function closePlayer() { window.close(); }

// ── Keyboard ──────────────────────────────────────────────────────────────────

document.addEventListener('keydown', e => {
  if (!S.ready && endOvl.style.display !== 'flex') return;
  if (endOvl.style.display === 'flex') {
    if (e.key === 'Escape') { e.preventDefault(); closePlayer(); }
    return;
  }
  switch (e.key) {
    case 'ArrowRight': case ' ': advance(); break;
    case 'ArrowLeft':            back();    break;
    case 'j': case 'J': case '+': score('richtig'); break;
    case 'n': case 'N': case '-': score('falsch');  break;
    case '0':                      score('neutral'); break;
    case 'p': case 'P':            togglePause();   break;
    case 't': case 'T':            toggleMode();    break;
    case 'q': case 'Q': case 'Escape': showEnd(true); break;
    default: return;
  }
  e.preventDefault();
});

// ── Init ──────────────────────────────────────────────────────────────────────

(async () => {
  // Key-Hints nach 4s ausblenden
  setTimeout(() => keyHints.classList.add('hidden'), 4000);

  // Session-Daten vom Server holen (Karten-Liste)
  let resp, d;
  try {
    resp = await fetch(_BASE+'/api/viewer/session', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        pdf:          CFG.pdf,
        level_filter: CFG.level_filter || [],
        randomize:    !!CFG.randomize,
      }),
    });
    d = await resp.json();
  } catch (err) {
    document.body.innerHTML = `<p style="padding:40px;color:#888">Verbindungsfehler: ${err}</p>`;
    return;
  }

  if (!d.ok || !d.cards.length) {
    document.body.innerHTML = `<p style="padding:40px;color:#888">Keine Karten: ${d.error || 'leerer Filter?'}</p>`;
    return;
  }

  S.cards      = d.cards;
  S.page_count = d.page_count;

  // Vollbild anfordern
  try { await document.documentElement.requestFullscreen(); } catch (_) {}

  // Erstes Bild laden
  goTo(0, 'q');
  S.ready = true;

  // Autopilot-Modus-Anzeige
  if (S.mode === 'auto') {
    stMode.textContent = '▶ Autopilot';
  }
})();

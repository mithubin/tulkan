// ── Layout-Toggle ─────────────────────────────────────────────────────────────

const LAYOUT_KEY = "lk_panel_layout";

function toggleLayout() {
  const el  = document.getElementById("create-layout");
  const btn = document.getElementById("layout-toggle");
  if (!el) return;
  const isSide = el.classList.contains("side-by-side");
  if (isSide) {
    el.classList.replace("side-by-side", "stacked");
    btn.textContent = "⇔ Nebeneinander";
    localStorage.setItem(LAYOUT_KEY, "stacked");
  } else {
    el.classList.replace("stacked", "side-by-side");
    btn.textContent = "↕ Untereinander";
    localStorage.setItem(LAYOUT_KEY, "side");
  }
}

function initLayout() {
  const el  = document.getElementById("create-layout");
  const btn = document.getElementById("layout-toggle");
  if (!el) return;
  const saved     = localStorage.getItem(LAYOUT_KEY);
  const preferSide = saved !== "stacked";
  if (preferSide) {
    el.classList.add("side-by-side");
    if (btn) btn.textContent = "↕ Untereinander";
  } else {
    el.classList.add("stacked");
    if (btn) btn.textContent = "⇔ Nebeneinander";
  }
}

// ── Viewer ────────────────────────────────────────────────────────────────────

function launchViewer() {
  const status = document.getElementById("viewer-status");
  status.textContent = "Starte…";
  fetch(_BASE+"/api/viewer/launch", { method: "POST" })
    .then(r => r.json())
    .then(d => { status.textContent = d.ok ? "Gestartet." : "Fehler: " + d.error; })
    .catch(() => { status.textContent = "Verbindungsfehler."; });
}

// ── Druck-Vorschau ────────────────────────────────────────────────────────────

let _printPreviewTimer = null;

function updatePrintPreview() {
  clearTimeout(_printPreviewTimer);
  _printPreviewTimer = setTimeout(_doUpdatePrintPreview, 500);
}

function _doUpdatePrintPreview() {
  const form = document.getElementById("print-form");
  const img  = document.getElementById("print-preview-img");
  const err  = document.getElementById("print-preview-err");
  if (!form || !img) return;
  const pdf = form.querySelector("[name=pdf]")?.value;
  if (!pdf) return;

  err.textContent  = "Lade…";
  img.style.display = "none";

  fetch(_BASE+"/api/print/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pdf:       pdf,
      paper:     form.querySelector("[name=paper]").value,
      cols:      parseInt(form.querySelector("[name=cols]").value)    || 3,
      rows:      parseInt(form.querySelector("[name=rows]").value)    || 5,
      margin_mm: parseFloat(form.querySelector("[name=margin_mm]").value) || 0,
      gutter:    parseFloat(form.querySelector("[name=spacing]").value || 1) * 2.8346,
    }),
  })
    .then(r => r.json())
    .then(d => {
      err.textContent = "";
      if (d.ok) {
        img.src = "data:image/png;base64," + d.image;
        img.style.display = "block";
      } else {
        err.textContent = d.error;
      }
    })
    .catch(() => { err.textContent = "Verbindungsfehler."; });
}

// ── Druck-PDF ─────────────────────────────────────────────────────────────────

const PRINT_PRESETS = {
  "A4q_3x5": { paper: "A4 quer", cols: 3, rows: 5, spacing: 1, crop_marks: false },
  "A4h_2x7": { paper: "A4 hoch", cols: 2, rows: 7, spacing: 1, crop_marks: false },
};

function applyPrintPreset(id) {
  const p = PRINT_PRESETS[id];
  if (!p) return;
  const form = document.getElementById("print-form");
  form.querySelector("[name=paper]").value    = p.paper;
  form.querySelector("[name=cols]").value     = p.cols;
  form.querySelector("[name=rows]").value     = p.rows;
  form.querySelector("[name=spacing]").value  = p.spacing;
  if (p.crop_marks !== undefined)
    form.querySelector("[name=crop_marks]").checked = p.crop_marks;
  updatePrintPreview();
}

function buildPrint() {
  const form   = document.getElementById("print-form");
  const status = document.getElementById("print-status");
  const result = document.getElementById("print-result");
  status.textContent = "Wird erzeugt…";

  const MM       = 2.8346;
  const gutter_pt = parseFloat(form.querySelector("[name=spacing]").value  || 1) * MM;
  const margin_pt = parseFloat(form.querySelector("[name=margin_mm]").value || 0) * MM;

  const data = {
    pdf:         form.querySelector("[name=pdf]").value,
    paper:       form.querySelector("[name=paper]").value,
    cols:        parseInt(form.querySelector("[name=cols]").value),
    rows:        parseInt(form.querySelector("[name=rows]").value),
    margin:      margin_pt,
    gutter:      gutter_pt,
    range_start: parseInt(form.querySelector("[name=range_start]").value) || null,
    range_end:   parseInt(form.querySelector("[name=range_end]").value)   || null,
    crop_marks:  form.querySelector("[name=crop_marks]").checked,
  };

  fetch(_BASE+"/api/print/build", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
    .then(r => r.json())
    .then(d => {
      if (d.ok) {
        status.textContent = "";
        result.style.display = "block";
        document.getElementById("print-result-text").textContent =
          `${d.cards} Karten, ${d.pages} Druckseiten`;
        const dl = document.getElementById("print-download");
        dl.href = _BASE+"/api/print/download/" + d.filename;
        dl.download = d.filename;
      } else {
        status.textContent = "Fehler: " + d.error;
        result.style.display = "none";
      }
    })
    .catch(() => { status.textContent = "Verbindungsfehler."; });
}

// ── CSV laden ─────────────────────────────────────────────────────────────────

let csvLoaded  = false;
let csvSource  = null; // "upload" oder Server-Dateiname

function _showCSVResult(d, filename) {
  const box = document.getElementById("csv-status");
  box.style.display = "block";
  if (d.ok) {
    csvLoaded = true;
    let msg = `✓ ${d.cards} Karten`;
    if (d.levels.length) msg += ` · Level: ${d.levels.join(", ")}`;
    if (d.name)          msg += ` · ${d.name}`;
    if (d.warnings.length) msg += "\n⚠ " + d.warnings.join("\n⚠ ");
    showStatus(box, msg, "ok");
    const nameEl = document.getElementById("output-name");
    if (nameEl && !nameEl.value) {
      const base = (filename || d.name || "").replace(/\.csv$/i, "");
      if (base) nameEl.value = base + ".pdf";
    }
    _renderCSVPreview(d.preview || []);
  } else {
    csvLoaded = false;
    showStatus(box, "✗ " + d.errors.join("\n✗ "), "err");
    _renderCSVPreview([]);
  }
}

function _renderCSVPreview(rows) {
  const el = document.getElementById("csv-preview");
  if (!el) return;
  if (!rows.length) { el.style.display = "none"; el.innerHTML = ""; return; }
  const trunc = (s, n) => s.length > n ? s.slice(0, n) + "…" : s;
  let html = '<table class="csv-prev-table"><thead><tr>'
    + "<th>Level</th><th>Thema</th><th>Frage</th><th>Antwort</th></tr></thead><tbody>";
  for (const r of rows) {
    html += `<tr><td>${r.level}</td><td>${r.thema}</td>`
      + `<td>${trunc(r.frage, 60)}</td><td>${trunc(r.antwort, 60)}</td></tr>`;
  }
  html += "</tbody></table>";
  el.innerHTML = html;
  el.style.display = "block";
}

function loadCSV() {
  const file = document.getElementById("csv-file").files[0];
  if (!file) { showStatus(document.getElementById("csv-status"), "Keine Datei.", "warn"); return; }
  const fd = new FormData();
  fd.append("file", file);
  fetch(_BASE+"/api/csv/validate", { method: "POST", body: fd })
    .then(r => r.json()).then(d => { if (d.ok) csvSource = "upload"; _showCSVResult(d, file.name); })
    .catch(() => showStatus(document.getElementById("csv-status"), "Verbindungsfehler.", "err"));
}

function loadCSVFromServer() {
  const name = document.getElementById("csv-select").value;
  if (!name) { showStatus(document.getElementById("csv-status"), "Keine Datei gewählt.", "warn"); return; }
  fetch(_BASE+"/api/csv/load-server", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  }).then(r => r.json()).then(d => { if (d.ok) csvSource = name; _showCSVResult(d, name); })
    .catch(() => showStatus(document.getElementById("csv-status"), "Verbindungsfehler.", "err"));
}

// ── Template laden / speichern ────────────────────────────────────────────────

function loadTemplate() {
  const name = document.getElementById("template-select").value;
  fetch(_BASE+"/api/template/load/" + encodeURIComponent(name))
    .then(r => r.json())
    .then(applyTemplateToForm);
}

function applyTemplateToForm(t) {
  setVal("card-w",              t.card_width_mm        ?? 180);
  setVal("card-h",              t.card_height_mm       ?? 80);
  setVal("margin",              t.margin_mm            ?? 4);
  setVal("topic-w",             t.topic_width_mm       ?? 10);
  setVal("line-spacing",        t.line_spacing         ?? 1.2);
  setVal("answer-line-spacing", t.answer_line_spacing  ?? t.line_spacing ?? 1.2);
  setVal("repeat-gap",          t.repeat_gap_mm        ?? 4);
  setSelect("front-bg",  t.front_bg || "");
  setSelect("back-bg",   t.back_bg  || "");
  _setBgAlpha("front-bg-alpha", t.front_bg_alpha ?? 1.0);
  _setBgAlpha("back-bg-alpha",  t.back_bg_alpha  ?? 1.0);
  applyStyle("topic",    t.topic_style);
  applyStyle("question", t.question_style);
  applyStyle("answer",   t.answer_style);
  applyStyle("repeat",   t.repeat_style);
  previewCard();
}

function applyStyle(pid, s) {
  if (!s) return;
  setVal(pid+"-size", s.size ?? 12);
  setColor(pid+"-color", s.color ?? [1,1,1]);
  const fontPath = s.font_path || "";
  setVal(pid+"-font-path", fontPath);
  const sel = document.getElementById(pid+"-font-sel");
  if (sel) {
    sel.value = fontPath;
    if (sel.value !== fontPath) sel.value = "";
  }
  const hasShadow = (s.shadow_offset?.[0] ?? 0) !== 0 || (s.shadow_offset?.[1] ?? 0) !== 0;
  const cb = document.getElementById(pid+"-sh-on");
  if (cb) cb.checked = hasShadow;
  setColor(pid+"-sh-color", s.shadow_color ?? [0,0,0]);
  setVal(pid+"-sh-x", s.shadow_offset?.[0] ?? 0);
  setVal(pid+"-sh-y", s.shadow_offset?.[1] ?? 0);
  setColor(pid+"-bg-color", s.bg_color ?? [0,0,0]);
  setVal(pid+"-bg-alpha", s.bg_alpha ?? 0);
  const bgLbl = document.getElementById(pid+"-bg-alpha-val");
  if (bgLbl) bgLbl.textContent = Math.round((s.bg_alpha ?? 0) * 100) + '%';
}

function applyFontSel(pid) {
  setVal(pid+"-font-path", document.getElementById(pid+"-font-sel")?.value ?? "");
  previewCard();
}

function toggleShadow(pid) { previewCard(); }

function saveTemplate()   { _doSaveTemplate(document.getElementById("template-select").value); }
function saveTemplateAs() {
  const name = prompt("Name für neues Template:", "mein_template");
  if (name) _doSaveTemplate(name);
}

function _doSaveTemplate(name) {
  fetch(_BASE+"/api/template/save/" + encodeURIComponent(name), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collectTemplateFromForm()),
  }).then(r => r.json()).then(d => alert(d.ok ? `"${name}" gespeichert.` : "Fehler: " + d.error));
}

function collectTemplateFromForm() {
  return {
    card_width_mm:       num("card-w"),
    card_height_mm:      num("card-h"),
    margin_mm:           num("margin"),
    topic_width_mm:      num("topic-w"),
    line_spacing:        num("line-spacing"),
    answer_line_spacing: num("answer-line-spacing"),
    repeat_gap_mm:       num("repeat-gap"),
    front_bg:       selVal("front-bg"),
    back_bg:        selVal("back-bg"),
    front_bg_alpha: num("front-bg-alpha"),
    back_bg_alpha:  num("back-bg-alpha"),
    topic_style:    collectStyle("topic"),
    question_style: collectStyle("question"),
    answer_style:   collectStyle("answer"),
    repeat_style:   collectStyle("repeat"),
  };
}

function collectStyle(pid) {
  const cb    = document.getElementById(pid+"-sh-on");
  const hasSh = cb && cb.checked;
  return {
    font:          "helv",
    font_path:     val(pid+"-font-path"),
    size:          num(pid+"-size"),
    color:         hexToRgb(pid+"-color"),
    shadow_offset: hasSh ? [num(pid+"-sh-x"), num(pid+"-sh-y")] : [0, 0],
    shadow_color:  hexToRgb(pid+"-sh-color"),
    bg_color:      hexToRgb(pid+"-bg-color"),
    bg_alpha:      num(pid+"-bg-alpha"),
  };
}

// ── Vorschau ──────────────────────────────────────────────────────────────────

function refreshPreview() { previewCard(); }

function previewCard() {
  fetch(_BASE+"/api/preview/card", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collectTemplateFromForm()),
  })
    .then(r => r.json())
    .then(d => {
      if (d.front) drawCanvasImage("preview-front", d.front);
      if (d.back)  drawCanvasImage("preview-back",  d.back);
    });
}

function drawCanvasImage(canvasId, b64) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const img = new Image();
  img.onload = () => {
    canvas.width  = img.width;
    canvas.height = img.height;
    canvas.getContext("2d").drawImage(img, 0, 0);
  };
  img.src = "data:image/png;base64," + b64;
}

// ── PDF erstellen ─────────────────────────────────────────────────────────────

function createPDF() {
  if (!csvLoaded) { alert("Bitte zuerst eine CSV-Datei laden."); return; }
  const status   = document.getElementById("create-status");
  const resultEl = document.getElementById("create-result");
  let name = (document.getElementById("output-name")?.value || "").trim() || "karten_neu.pdf";
  if (!name.endsWith(".pdf")) name += ".pdf";
  status.textContent = "Wird erstellt…";

  const fd = new FormData();
  if (csvSource === "upload") {
    const file = document.getElementById("csv-file")?.files[0];
    if (file) fd.append("file", file);
  } else if (csvSource) {
    fd.append("csv_server_name", csvSource);
  }
  fd.append("template",    JSON.stringify(collectTemplateFromForm()));
  fd.append("output_name", name);

  fetch(_BASE+"/api/create/pdf", { method: "POST", body: fd })
    .then(r => r.json())
    .then(d => {
      if (d.ok) {
        status.textContent = `✓ ${d.cards} Karten`;
        resultEl.style.display = "block";
        const dl = document.getElementById("create-download");
        dl.href = _BASE+"/api/create/download/" + d.filename;
        dl.download = d.filename;
      } else {
        status.textContent = "Fehler: " + d.error;
        resultEl.style.display = "none";
      }
    })
    .catch(() => { status.textContent = "Verbindungsfehler."; });
}

// ── Hilfsfunktionen ───────────────────────────────────────────────────────────

function val(id)    { return document.getElementById(id)?.value ?? ""; }
function num(id)    { return parseFloat(document.getElementById(id)?.value) || 0; }
function selVal(id) { return document.getElementById(id)?.value ?? ""; }

function setVal(id, v)   { const el = document.getElementById(id); if (el) el.value = v; }
function setSelect(id, v) {
  const el = document.getElementById(id);
  if (!el) return;
  for (const o of el.options) { if (o.value === v) { el.value = v; return; } }
}
function _setBgAlpha(id, v) {
  const el = document.getElementById(id);
  if (!el) return;
  el.value = v;
  const lbl = document.getElementById(id + "-val");
  if (lbl) lbl.textContent = Math.round(v * 100) + "%";
}
function setColor(id, rgb) {
  const el = document.getElementById(id);
  if (!el) return;
  el.value = "#" + rgb.map(c => Math.round(c * 255).toString(16).padStart(2, "0")).join("");
}
function hexToRgb(id) {
  const hex = val(id).replace("#", "");
  if (hex.length < 6) return [0, 0, 0];
  return [parseInt(hex.slice(0,2),16)/255, parseInt(hex.slice(2,4),16)/255, parseInt(hex.slice(4,6),16)/255];
}
function showStatus(el, msg, type) {
  el.className = "status-box status-" + type;
  el.style.display = "block";
  el.textContent = msg;
}

// ── Init ──────────────────────────────────────────────────────────────────────

window.addEventListener("DOMContentLoaded", () => {
  initLayout();
  if (window.location.pathname === "/create") {
    const sel = document.getElementById("template-select");
    if (sel) loadTemplate();
  }
  if (window.location.pathname === "/print") {
    updatePrintPreview();
  }
});

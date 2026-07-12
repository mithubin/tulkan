# DV-Protokoll – Dateiverwaltung tul.yourdomain.example

Stand: 2026-06-28

---

## Leitgedanke

Das DV-Modal (`tul-files.js`) ist das einheitliche Datei-Interface für alle tul-Tools. Es verwaltet
nicht nur die eigenen Dateien eines Tools, sondern fungiert als **Datei-Fähre** zwischen Tools und
externen Diensten (mkan, Nextcloud). Jedes Tool nutzt dieselbe Komponente mit
werkzeug-spezifischer Konfiguration — keine One-off-Lösungen.

Ergänzend zum DV-Modal gibt es die **Panel-Dateiliste** im Sidebar/Panel der jeweiligen Tool-Seite.
Diese ist kein Teil von tul-files.js, sondern tool-spezifisch — zeigt aber dieselben Daten
als kompakten Schnellzugriff (Checkboxen statt Chips).

### Architektur-Invariante

Drei Schichten, alle Tools:

| Schicht | Datei | Rolle |
|---------|-------|-------|
| UI-Logik | `static/tul-files.js` (hub-Container) | Einheitliches Modal — Upload, Chips, NC, Tabs |
| Backend-Routen | `tul_auth/files_routes.py` (Blueprint, jeder Container) | Einheitliche API — `/files`, `/files/upload`, `/files/<id>/…` |
| Tool-Profil | `tulFiles.init(opts)` im Tool-HTML | Tool-spezifische Konfiguration |

Das Tool-Profil ist der einzige Ort, wo sich Tools unterscheiden dürfen. Alles andere ist geteilt.

### Per-Tool-Konfigurationsübersicht

| Tool     | `ncEnabled` | `recycleOutput`  | `inputAction` | `groupByGrp` | mkan-Tab (Quelle)        | → mkan Push | Panel-Dateiliste |
|----------|:-----------:|:----------------:|:-------------:|:------------:|:------------------------:|:-----------:|:----------------:|
| trskr    | ✓           | `true` (↥ move)  | —             | —            | —                        | ✓ (auto)    | ✓ audio/video    |
| lern     | ✓           | —                | —             | —            | —                        | ✓ (auto)    | ✓ CSV/Bild/Font  |
| kurv     | ✓           | —                | —             | ✓ (nach grp) | —                        | ✓ (auto)    | ✓ CSV            |
| popt     | ✓           | —                | —             | —            | ✓ pool (PDF, onWire)     | ✓ (auto)    | ✓ PDF            |
| bild     | ✓           | —                | —             | —            | ✓ cards-for-tool (Bild)  | ✓ (auto)    | ✓ Bild           |
| nach     | ✗²          | —                | —             | —            | ✗²                       | ✗²          | eigene Liste (nicht tul-files.js) |
| buch     | ✓           | —                | —             | —            | —                        | ✓ (auto)    | ✓ PDF            |
| kal-trel | ✓           | `'copy'` (→ Eingang) | `'load'`  | —          | —                        | ✓ (auto)    | — (kein Batch)   |

² nach bindet `tul-files.js`/`make_files_blueprint` überhaupt nicht ein (direkter Upload statt DV-Modal,
per Code-Review 2026-07-12 bestätigt) — kein Sonderfall einzelner Features, sondern kein DV-Tool.
Die Panel-Dateiliste ist dort eine eigenständige, tool-spezifische Ansicht ohne tul-files.js-Bezug.
„→ mkan Push" ist bei allen anderen Tools automatisch aktiv, sobald mkan-Karten mit `targetTul` auf das Tool zeigen (kein Tool-spezifisches Setup nötig).

---

## Zwei Ebenen der Datei-Präsentation

| Ebene              | Wo                  | Wer rendert     | Zweck                                     |
|--------------------|---------------------|-----------------|-------------------------------------------|
| **Panel-Dateiliste** | Sidebar / Panel   | Tool-eigenes JS | Schnellzugriff: auswählen, Job starten    |
| **DV-Modal**       | Modal (tul-files.js)| tul-files.js    | Verwaltung: Upload, listed-Toggle, NC, Löschen |

Die Panel-Dateiliste ist eine **gefilterte Projektion** der DV-Daten:
- Zeigt nur Eingabe-Dateien
- Eigene Dateien + mkan-Pool (nach MIME gefiltert, excl-Prefs beachtet)
- Kein Management-Overhead — nur Checkbox + Name + Größe

Änderungen im DV-Modal (≡ Toggle, Upload, Löschen) aktualisieren die Panel-Dateiliste via
`onChange`-Callback.

---

## Feature-Kanon

### Panel-Dateiliste (Schnellzugriff — jedes Tool mit Job-Workflow)

| Feature               | Beschreibung                                                          |
|-----------------------|-----------------------------------------------------------------------|
| Sektion „Eigene"      | Eigene tul-files-Eingaben mit Checkbox + optionalem 1×-Badge          |
| Sektion „🔗 aus mkan" | mkan-Pool, MIME-gefiltert, excl-Prefs beachtet — nur wenn ≥1 Datei   |
| Alle / Keine          | Selektion über beide Sektionen                                        |
| Live-Sync mit DV      | Nach Modal-Aktion: `onChange → loadInputFiles()` aktualisiert Liste  |

### DV-Modal Eingabe-Spalte

| Feature                  | Beschreibung                                                          |
|--------------------------|-----------------------------------------------------------------------|
| Upload-Dropzone          | Drag & Drop + Datei-Picker + Paste/URL-Einfügen                      |
| Eigene-Tab               | Eigene Uploads mit Retention-Chips, ≡-Listed-Toggle, Löschen         |
| mkan-Tab                 | mkan-Pool via Hub, MIME-gefiltert, ≡ = Ein-/Ausschließen aus Panel   |
| Cross-Tool-Tabs          | Andere tul-Tool-Ausgaben (MIME-gefiltert, s.u.), Tooltip = Quelle    |
| ≡ in allen externen Tabs | Blendet Datei in die Panel-Dateiliste ein/aus (Prefs server-seitig)  |
| → in allen externen Tabs | Adoptiert Datei direkt in den Tool-Workspace (Wire/Import)           |

### DV-Modal Ausgabe-Spalte

| Feature                  | Beschreibung                                                          |
|--------------------------|-----------------------------------------------------------------------|
| Dateiliste               | Name, Größe, Datum, Retention-Chips, Gruppen-Faltung nach Stamm      |
| Gruppen-Selektion ☑☐⇅   | Alle/Keine/Toggle **pro Gruppe** — automatisch in allen Tools aktiv  |
| groupByGrp               | (kurv) Output nach `grp`-DB-Feld — ein Run = ein Verzeichnis, keine losen Dateien |
| Einzeldownload           | `↓`-Chip, direkt                                                     |
| ZIP-Download             | Gruppe herunterladen (↓ ZIP-Button im Gruppen-Header)                |
| Nextcloud-Push           | `↑ NC`-Chip pro Datei + NC-Bar (Ziel-Dropdown + Alle senden)         |
| NC Push-only             | DV-Modal zeigt nur `direction=push`-Targets; Fetch-Quellen im Panel  |
| NC-Ziel Persistenz       | Letztes Ziel in `localStorage['tlf-nc-sel:<tool>']` — tool-differenziert |
| → mkan Push              | `→ mkan`-Chip pro Datei — Datei direkt an mkan-Karte senden; mkan-Bar (Zielkarten-Dropdown wenn mehrere) |
| Batch-Aktionen           | Mehrfachauswahl: Löschen, NC-Send                                    |
| Retention-Steuerung      | 1× / 1W / 1M / xT / ∞ per Chip                                      |
| Requeue → Eingang        | (optional) `→ Eingang`-Chip: Output-Datei wird zur Eingabe           |
| Inline-Vorschau          | `/files/<id>/inline` serviert Datei ohne Attachment-Header — für iframe/PDF-Embed |

**NC-Push ist kein optionales Feature** — jede Ausgabe-Spalte muss es haben (`ncEnabled: true`).

**→ mkan Push** erscheint automatisch wenn `_mkanPushCards.length > 0` — kein Tool-Setup nötig.
Der `→ mkan`-Chip lädt die Datei clientseitig vom Tool-Server und postet sie als Multipart an den
Hub-Proxy (`POST /api/mkan-push-to-card`). Bei mehreren Zielkarten erscheint eine mkan-Bar mit
Dropdown analog zur NC-Bar.

**Gruppen-Selektion** ist immer aktiv (in `makeGroupRow()` und `renderCol()` eingebaut).
Bei kurv greift zusätzlich `groupByGrp: true` in der GROUPS-Konfiguration — Output wird nach dem
`grp`-DB-Feld gruppiert anstatt nach Dateiname-Stamm.

**Requeue** ist sinnvoll bei Batch-Processing-Tools: ein Ergebnis soll nochmals verarbeitet
werden. Zwei Varianten — je nach Tool-Semantik:

| Variante              | Option                   | Route                  | Semantik                                     |
|-----------------------|--------------------------|------------------------|----------------------------------------------|
| Move (default)        | `recycleOutput: true`    | `POST /files/<id>/recycle`          | Datei **verschoben**: Output → Input; Original weg |
| Copy (kal-trel-Stil)  | `recycleOutput: 'copy'`  | `POST /files/<id>/copy-to-input`    | Datei **kopiert**: Original in Ausgabe bleibt erhalten |

Der `→ Eingang`-Chip erscheint in beiden Fällen; bei Copy lautet der Chip-Text `→ Eingang`,
bei Move `↥`.

---

## tulFiles.init() — Konfigurationsoptionen

```javascript
tulFiles.init({
  subpath:       _B,            // Pflicht: Tool-URL-Prefix (z.B. '/popt')
  tool:          'popt',        // Pflicht: Tool-ID für DB-Routing + mkan-Auto-Discovery
  ncEnabled:     true,          // NC-Push-Chip in Ausgabe-Spalte (Default: false)
  recycleOutput: false,         // false | true | 'copy' — Requeue-Chip in Ausgabe
  inputAction:   null,          // null | 'load' — ersetzt ≡-Toggle in Eingabe-Spalte
  accept:        null,          // MIME-Filter für Upload-Dropzone (Default: alle)
  onSelect:      fn,            // Callback wenn Nutzer Input-Datei aktiviert (id-Array)
  onChange:      fn,            // Callback nach Upload/Delete/Recycle/excl-Toggle
  externalSources: [],          // Explizite ext. Quellen (mkan-pool, cross-tool) — s.u.
  onWire:        fn,            // Callback für → Wire-Button in ext-Tabs (Datei adoptieren)
});
```

**`tool` aktiviert mkan-Auto-Discovery:** Ist `tool` gesetzt, fetcht `loadExtSources()` automatisch
`/api/mkan-cards-for-tool?tool=<tool>` und baut pro Karte einen eigenen Tab auf
(`_fromMulti`-Sources mit `id: 'mkan-card-<card_id>'`). Das Tool muss dafür nichts weiter tun.

**Öffentliches API:** `tulFiles.{ init, open, close, refresh, markActive, getExtExcluded }`

`getExtExcluded()` gibt `_extExcluded` (`{srcId: Set<fileId>}`) zurück — für Tool-Panels, die
excl-Sync brauchen (z.B. bild `loadMkanImages` filtert ausgeschlossene Dateien heraus).

### `inputAction: 'load'`

Ersetzt den `≡`-Listen-Toggle in der Eingabe-Spalte durch einen `laden`-Chip.
Sinnvoll wenn das Tool kein Panel-Dateilisten-Konzept hat (kein Batch-Job-Workflow,
kein "ist diese Datei in der Warteliste?"). Klick auf `laden` ruft `onSelect([fileId])` auf.

**Aktiv bei:** kal-trel (JSON-Boards — ein Board lädt man direkt, kein Batch)

### `recycleOutput: 'copy'`

Legt eine Kopie der Ausgabe-Datei im Eingang ab; Original bleibt unberührt.
Nützlich wenn die Ausgabe-Datei selbst wertvoll ist (exportierter Stand, Archiv-JSON)
und man trotzdem einen neuen Bearbeitungszyklus starten will.

Route: `POST /files/<id>/copy-to-input` (in `files_routes.py`), neuer DB-Eintrag mit
`file_type='requeued'`, `category='input'`.

**Aktiv bei:** kal-trel

---

## mkan-Bridge: Implementierungsmuster

mkan ist ein eigenständiger Dienst (FastAPI, eigenes JWT) im selben Docker-Netz (`webproxy`).
Die Integration erfolgt über drei Schichten: mkan-Backend (X-Tul-Secret), Hub-Proxy (tul-JWT),
tul-files.js (Browser). Kein Cross-Origin-Problem, keine mkan-JWT-Exposition nach außen.

### Hub-Proxy (alle Routen)

```
GET  /api/mkan-pool                    → mkan:/attachments/dv/pool
GET  /api/mkan-file?att_id=X          → mkan:/attachments/dv/file/{X}
GET  /api/mkan-card?card_id=X         → mkan:/attachments/dv/card/{X}
GET  /api/mkan-cards-for-tool?tool=X  → mkan:/attachments/dv/cards-for-tool/{X}
POST /api/mkan-push-to-card?card_id=X → mkan:/attachments/dv/upload-to-card/{X}  (Multipart pass-through)
POST /api/mkan-unlink-card?card_id=X  → mkan:/attachments/dv/unlink-card/{X}
```

Alle Hub-Routen: `@require_login` (tul-JWT). Hub leitet mit `X-Tul-Secret`-Header weiter.
`mkan-push-to-card` leitet den rohen Multipart-Body transparent durch (Content-Type inkl. Boundary
bleibt erhalten) — kein Re-Encoding im Hub.

### mkan-Backend (Endpunkte, alle X-Tul-Secret)

| Endpunkt                                        | Zweck                                            |
|-------------------------------------------------|--------------------------------------------------|
| `GET /attachments/dv/pool`                      | Alle `dv_shared=1` Karten + Dateien              |
| `GET /attachments/dv/file/{att_id}`             | Datei-Download (inkl. file_card-Kinder-Check)    |
| `GET /attachments/dv/card/{card_id}`            | Dateien einer Karte (direkt + file_card-Kinder)  |
| `GET /attachments/dv/cards-for-tool/{tul}`      | Karten mit `dv_shared=1` + `targetTul=tul`       |
| `POST /attachments/dv/upload-to-card/{card_id}` | Datei als Anhang hochladen (UploadFile); prüft `dv_shared` |
| `POST /attachments/dv/unlink-card/{card_id}`    | `targetTul` aus `card_settings` entfernen        |

---

### Muster 1: Pool-Tab (globaler Zugriff auf alle dvShared-Karten)

Wird von popt verwendet — alle freigegebenen PDFs, unabhängig von `targetTul`.

```javascript
tulFiles.init({
  subpath: _B, tool: 'popt', ncEnabled: true,
  onChange: loadInputFiles,
  externalSources: [{
    id:      'mkan-pool',
    label:   'mkan',
    url:     '/api/mkan-pool',
    toEntry: f => ({ id: f.id, name: f.name, size: f.size, mime: f.mime }),
    filter:  f => /application\/pdf/.test(f.mime),
  }],
  onWire: async (srcId, entry) => {
    const blob = await fetch('/api/mkan-file?att_id=' + entry.id).then(r => r.blob());
    const fd = new FormData();
    fd.append('file', blob, entry.name);
    fd.append('category', 'input');
    fd.append('retention', 'task');
    await fetch(_B + '/files/upload', { method: 'POST', body: fd });
    tulFiles.close();
    await loadInputFiles();
  },
});
```

Server-seitiger Download (wenn Tool-Server die Datei selbst verarbeitet, z.B. popt/Ghostscript):

```python
_MKAN_URL   = os.environ.get('MKAN_URL', 'http://mkan:8000')
_TUL_SECRET = os.environ.get('TUL_SECRET', '')

def _mkan_download(att_id: str, dest_dir: Path) -> bool:
    req = urllib.request.Request(
        _MKAN_URL + f'/attachments/dv/file/{att_id}',
        headers={'X-Tul-Secret': _TUL_SECRET},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        fname = _extract_filename(resp.headers) or (att_id + '.pdf')
        with open(dest_dir / fname, 'wb') as f:
            f.write(resp.read())
    return True
```

---

### Muster 2: targetTul-Flow — Karte zielt auf ein bestimmtes Tool

Eingeführt 2026-06-28. Karte in mkan setzt `cardSettings.targetTul = 'bild'` (via dreistufigen
UI-Flow im Karten-Modal). Das Tool bekommt automatisch einen Tab pro Zielkarte im DV-Modal.

**Dreistufiger UI-Flow in mkan:**
1. Toggle "tul-DV freigeben" (`dvShared = true`)
2. Pill-Auswahl "Zugang für: [trskr][lern][bild]…" → speichert `cardSettings.targetTul`
3. Link "→ bild öffnen" erscheint (öffnet `https://tul.yourdomain.example/<tul>`)

**Auto-Discovery im Tool (tul-files.js):**
Kein `externalSources`-Eintrag nötig. Sobald `tool` in `tulFiles.init` gesetzt ist, fetcht
`loadExtSources()` automatisch `/api/mkan-cards-for-tool?tool=<tool>` und baut pro Karte einen
`_fromMulti`-Tab mit `id: 'mkan-card-<card_id>'` und Kartentitel als Label.

**Excl-Sync (DV ↔ Panel):**
Jeder Tab hat ☑☐⇅-Buttons (`makeExtSelBtns(src)`). Ausschluss-Prefs landen auf
`/prefs/excl-mkan-card-<uuid>`. Toggle ruft `_onChange` auf → Panel aktualisiert sich.
`tulFiles.getExtExcluded()` gibt `_extExcluded` zurück, damit Tool-Panels (z.B. bild) ohne
Extra-Fetch filtern können.

**Panel-seitige Nutzung (Beispiel bild):**
```javascript
async function loadMkanImages() {
  const resp = await fetch('/api/mkan-cards-for-tool?tool=bild');
  const cards = await resp.json();
  const excl = tulFiles.getExtExcluded ? tulFiles.getExtExcluded() : {};
  const imgs = (Array.isArray(cards) ? cards : []).flatMap(c => {
    const srcId = 'mkan-card-' + c.card_id;
    const excluded = excl[srcId] || new Set();
    return (c.files || [])
      .filter(f => f.mime && f.mime.startsWith('image/') && !excluded.has(f.id))
      .map(f => ({ ...f, cardTitle: c.title }));
  });
  // render...
}
```

---

### Muster 3: Reverse Flow — tul Ausgabe → mkan Karte

Eingeführt 2026-06-28. Aus der Ausgabe-Spalte des DV-Modals kann eine Datei direkt an eine
mkan-Karte zurückgesendet werden.

**Ablauf:**
1. `→ mkan`-Chip in der Ausgabe-Spalte (erscheint wenn `_mkanPushCards.length > 0`)
2. Klick → `mkanPushFile(fileId, filename, mime, btn)`
3. Download der Datei von `_sub + '/files/' + fileId + '/download'` als Blob
4. POST als `FormData` an `/api/mkan-push-to-card?card_id=<_mkanPushCardId>`
5. Hub leitet Multipart transparent weiter (X-Tul-Secret); mkan speichert Anhang auf Karte

**`_mkanPushCards`** wird nach jedem `loadExtSources()` aus den `_fromMulti`-Sources und dem
optionalen URL-Param `?mkanCard=<id>` befüllt. Bei einer Karte zeigt die mkan-Bar nur den Namen;
bei mehreren Karten ein Dropdown zur Auswahl der Zielkarte.

---

### Muster 4: Verbindung lösen

Eingeführt 2026-06-28. Im Fuß jedes `_fromMulti`-Tabs (Karten-Tab im DV-Modal) erscheint ein
`⊗ Verbindung lösen`-Button.

Klick → Confirm-Dialog → `POST /api/mkan-unlink-card?card_id=<id>` → mkan entfernt `targetTul`
aus `card_settings` und broadcastet Board-Update → DV springt auf „Eigene" zurück, Tab verschwindet.

In mkan: die Karte ist nach dem Lösen noch `dvShared=true`, aber hat kein `targetTul` mehr —
sichtbar daran, dass kein Pill hervorgehoben ist. Der User kann dort eine neue Verbindung herstellen.

---

## Cross-Tool-Tabs (tul-intern): Konzept

Für Dateien die bereits in tul-files liegen (Output eines anderen tul-Tools):

```
GET /<tool>/api/cross-files?mime=application/pdf
→ { "buch": [{id, name, size, file_id, listed, listed_url}…],
    "bild": [{…}] }
```

tul-files.js baut Tabs daraus dynamisch (`crossMimes`-Option). **Noch nicht implementiert** —
aktuell nur manuelle `externalSources`-Einträge (buch → bild-A).

Backend-Helper geplant in `tul_auth/db.py`:
```python
def get_cross_output_files(requesting_tool, mime_types, user_id): …
```

---

## MIME-Affinitäten der aktuellen Tools

| Tool     | Eingabe-MIMEs                          | mkan-Pool | Cross-Tool (geplant) |
|----------|----------------------------------------|-----------|----------------------|
| popt     | `application/pdf`                      | ✓         | buch, bild           |
| buch     | `application/pdf`                      | —         | bild                 |
| trskr    | `audio/*`, `video/*`                   | —         | —                    |
| lern     | `text/csv`, `image/*`, `font/*`        | —         | —                    |
| kurv     | `text/csv`                             | —         | —                    |
| bild     | `image/*`                              | —¹        | —                    |
| nach     | `text/html`, `application/zip`         | —         | —                    |
| kal-trel | `image/*`, `application/json`          | —         | bild (geplant)       |

¹ bild nutzte früher den globalen mkan-Pool, wurde aber am 2026-06-29 auf den gezielten
`cards-for-tool`-Mechanismus (targetTul-Flow) umgestellt — kein Pool mehr, siehe Implementierungsstand unten.

---

## Tab-Darstellung im DV-Modal

```
Eingabe                                    Ausgabe
┌─────────────────────────────────────┐   ┌────────────────────────────────┐
│ [Eigene] [mkan] [buch] …            │   │ datei_o2.pdf   1.2 MB  ↓ ↑NC  │
├─────────────────────────────────────┤   │ datei2_o2.pdf  0.8 MB  ↓ ↑NC  │
│ vorlage.pdf          2.1 MB  ≡  →   │   │                                │
│ entwurf.pdf (grau)   1.3 MB  ≡  →   │   │ [Alle NC senden] Ziel: _pdfs  │
└─────────────────────────────────────┘   └────────────────────────────────┘
```

Panel-Dateiliste (daneben, im Sidebar):
```
Eingabe-Dateien                    ↺
─── Eigene ─────────────────────────
☐ 1× bericht.pdf           1.4 MB
─── 🔗 aus mkan ────────────────────
☐ mk  vorlage.pdf           2.1 MB
[Alle] [Keine]
```

- `≡` im DV-Modal steuert, ob eine mkan-Datei in der Panel-Liste erscheint
- `1×`-Badge = onetimeuse (wird nach Job gelöscht)
- `mk`-Badge = mkan-Herkunft

---

## Implementierungsstand

Stand: 2026-06-28

| Feature                                | Status                                                                           |
| -------------------------------------- | -------------------------------------------------------------------------------- |
| tul-files.js Grundgerüst               | ✓ alle Tools                                                                     |
| NC-Push Ausgabe                        | ✓ trskr, lern, buch, popt, bild, kurv / fehlt: nach                             |
| NC Push-only im DV-Modal               | ✓ `ncLoad()` filtert `?direction=push`                                           |
| NC-Ziel Persistenz (localStorage)      | ✓ `tlf-nc-sel:<tool>` — tool-differenziert                                       |
| Gruppen-Selektion ☑☐⇅ (alle Tools)    | ✓ in `makeGroupRow()` + `renderCol()` — greift überall wo Gruppen gerendert werden |
| Ext-Source-Tab-Selektion ☑☐⇅           | ✓ `makeExtSelBtns(src)` — pro ext-Quellen-Tab; Prefs auf `/prefs/excl-<srcId>`  |
| groupByGrp (kurv)                      | ✓ Output nach `grp`-DB-Feld — ein Run = eine Gruppe                             |
| /files/<id>/inline Route               | ✓ für PDF/HTML-Embedding in iframe (kein Content-Disposition-Header)             |
| mkan-Hub-Proxy                         | ✓ 6 Routen (pool, file, card, cards-for-tool, push-to-card, unlink-card)        |
| mkan-Pool-Tab (Muster 1)               | ✓ popt (PDFs, onWire + server-Download)                                         |
| targetTul-Flow (mkan → Tool, Muster 2) | ✓ mkan-Modal dreistufig; `/cards-for-tool`; Multi-Card-Tabs; excl-Sync           |
| bild panel via cards-for-tool          | ✓ `loadMkanImages()` nutzt targetTul-Endpoint; excl-Sync via `getExtExcluded()` |
| Reverse Flow tul → mkan (Muster 3)     | ✓ `→ mkan`-Chip, mkan-Bar, `mkanPushFile()`; Hub: `mkan-push-to-card`          |
| Verbindung lösen (Muster 4)            | ✓ `⊗ Verbindung lösen` im Tab-Fuß; Hub: `mkan-unlink-card`                     |
| server-seitiger mkan-Download          | ✓ popt (`_mkan_download` + MKAN_URL)                                            |
| externalSources (manuell)              | ✓ buch → bild-A                                                                 |
| Requeue Move (`recycleOutput:true`)    | ✓ `/recycle`-Route; aktiv: trskr                                                |
| Requeue Copy (`recycleOutput:'copy'`)  | ✓ `/copy-to-input`-Route; aktiv: kal-trel                                       |
| Input-Action (`inputAction:'load'`)    | ✓ laden-Chip statt ≡-Toggle; aktiv: kal-trel                                    |
| crossMimes (auto-Discovery)            | ✗ noch nicht implementiert                                                       |
| api/cross-files Route                  | ✗ noch nicht implementiert                                                       |
| server-side Adopt                      | ✗ noch nicht implementiert                                                       |
| get_cross_output_files() Helper        | ✗ noch nicht in tul_auth/                                                        |
| NC-Push für nach                       | ✗ ncEnabled fehlt                                                                |

### Nächste Schritte

1. **tul-mime Routing-Tabelle** implementieren (s. Abschnitt unten) — `crossMimes` + `get_cross_output_files()` + Hub-Route
2. **URL-als-DV-Eingabe** in trskr `/start`-Handler (`url_[yt-id].txt` registrieren)
3. **NC-Push** für nach — `ncEnabled: true` setzen
4. **server-side Adopt** (`/api/adopt`) für großen Datei-Transfer ohne Browser-Mediation
5. **mkan-Panel-Liste** für weitere Tools nachrüsten (lern: Bilder/Fonts) — wenn Tools reif

---

## Datei-Standard (minimales Protokoll)

Jede DV-Quelle (eigen, mkan, cross-tool) liefert dasselbe Schema:

```json
{
  "id":         "opaque-referenz",    // UUID, rel-Pfad, att_id — je nach Quelle
  "name":       "dateiname.pdf",
  "size":       12345,                // Bytes
  "mime":       "application/pdf",
  "file_id":    "uuid-für-db-ops",   // optional; für ≡-Toggle und Adopt
  "listed":     1,                    // 0 = in Panel-Dateiliste versteckt
  "listed_url": "/tool/api/…",       // optional; für ≡-Toggle-Endpunkt
  "back_url":   "/mkan/board/42/…"   // optional; Navigation zur Quelle
}
```

Felder `file_id`, `listed`, `listed_url`, `back_url` sind optional.
tul-files.js rendert die entsprechenden UI-Chips nur wenn vorhanden.

---

## tul-mime: Semantisches Routing-Label

### Grundidee

tul-mime ist ein **berechnetes Label** — kein DB-Feld, keine neue Infrastruktur. Es wird
aus drei bereits vorhandenen Werten abgeleitet:

```
tul-mime = format : tool : phase
```

| Teil   | Herkunft        | Beispiele                                         |
|--------|-----------------|---------------------------------------------------|
| format | `file_type`     | `audio`, `video`, `text`, `pdf`, `image`, `csv`, `url-ref`, `html`, `zip`, `json` |
| tool   | `tool`-Feld DB  | `trskr`, `lern`, `popt`, `buch`, `bild`, `kurv`, `nach`, `kal-trel` |
| phase  | `category` + Kontext | `input`, `output`, oder tool-spezifische Sub-Phase |

Das Label macht semantisch unterschiedliche Rollen sichtbar, die an der Dateiendung allein
nicht erkennbar sind — z.B. unterscheiden sich `text:trskr:transcription-output` und
`url-ref:trskr:input` beide als `.txt`-Datei, haben aber völlig verschiedene Routing-Ziele.

### Routing-Tabelle (Draft, Stand 2026-06-25)

```python
ROUTING = {
    # trskr — Transkription
    "audio:trskr:input":                    ["trskr:transcription"],
    "video:trskr:input":                    ["trskr:transcription"],
    "url-ref:trskr:input":                  ["trskr:transcription"],     # URL-Reuse (s.u.)
    "text:trskr:transcription-output":      ["trskr:nachbearbeitung"],   # Rohtranskript → NB
    "text:trskr:nachbearbeitung-output":    ["lern:input"],              # Fertiges Transkript

    # popt
    "pdf:popt:input":                       ["popt:processing"],
    "pdf:popt:output":                      ["buch:input"],              # NOT re-opt (Original bleibt)

    # bild
    "image:bild:input":                     ["bild:processing"],
    "pdf:bild:output":                      ["popt:input", "buch:input"],# bild-Export → opt + buch

    # buch
    "pdf:buch:input":                       ["buch:processing"],
    "pdf:buch:output":                      ["popt:input"],              # Zusammenstellung → opt

    # lern
    "csv:lern:input":                       ["lern:processing"],
    "image:lern:input":                     ["lern:processing"],

    # kurv
    "csv:kurv:input":                       ["kurv:processing"],

    # nach
    "html:nach:input":                      ["nach:hosting"],
    "zip:nach:input":                       ["nach:hosting"],

    # kal-trel
    "json:kal-trel:output":                 ["kal-trel:input"],          # recycleOutput:'copy'
}
```

**Leseregel:** Ein Eintrag `[a, b]` bedeutet, dass die DV diese Datei in den Cross-Tool-Tabs
von Tool a und Tool b anbietet. Leere Liste `[]` = Datei bleibt im Ursprungs-Tool, kein
Cross-Tool-Angebot.

**trskr als Zwei-Phasen-Tool:** `trskr:transcription` und `trskr:nachbearbeitung` sind
im Code kein getrennter Dienst, aber semantisch getrennte Phasen. Die Routing-Tabelle
bildet das sauber ab ohne Infrastruktur-Änderung.

### URL-Eingaben als DV-Objekte (trskr)

Bisher ist eine URL ein flüchtiger Parameter — nach dem Job weg. Ziel: URL-Inputs werden
beim Job-Start als DV-Eingabedatei registriert und bleiben bis zur expliziten Löschung.

| Eingabeart | DV-Dateiname          | tul-mime            | Inhalt              |
|------------|-----------------------|---------------------|---------------------|
| Einzel-URL | `url_[yt-id].txt`     | `url-ref:trskr:input` | die URL             |
| Batch-URLs | `url-batch_[yt-id].txt` | `url-ref:trskr:input` | Liste von URLs    |

Implementierung: Hook im `/start`-Handler — nach Eingang der URL, vor Job-Start,
`POST /files/upload` mit dem URL-Text, `category=input`, Dateiname nach Schema oben.

### Was noch fehlt

Die Routing-Tabelle existiert bisher nur als Konzept. Die Implementierung braucht:
- `crossMimes` in `tulFiles.init()` → tul-files.js baut Cross-Tool-Tabs daraus
- `get_cross_output_files(tool, tul_mimes, user_id)` in `tul_auth/db.py`
- `GET /api/cross-files?tul_mime=…` Route im Hub
- URL-als-DV-Datei im trskr-`/start`-Handler

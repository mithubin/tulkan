Stand: Phase 33 (2026-07-06) — Datum korrigiert 2026-07-12, vorheriger Datumsstempel (2026-06-16) war
inkonsistent mit dem tatsächlichen Phase-33-Abschluss. Phasenplan + Features → `PROJEKT.md`. Git: Branch `mkan`.

Live: `https://mkan.milan.how/`

## Struktur
- `server/` – FastAPI-Backend (Python 3.12, SQLite, uvicorn)
  - `routers/` – auth, boards, cards, columns, swimlanes, labels, attachments, events, persons, snapshots, klassenbuch
  - `static/index.html` – **Einzige Frontend-Quelle** (direkt editiert, via `GET /` ausgeliefert)
- `data/` – Laufzeitdaten (gitignore), auf NUC: Docker-Volume unter `/mnt/mkan/`

## Stack
- Python 3.12, FastAPI, uvicorn, sqlite3 (stdlib), bcrypt, PyJWT
- Kein ORM — reines sqlite3 mit WAL-Mode
- Docker Compose: services `mkan` + `onlyoffice` im `webproxy`-Netz
- Frontend: single-file SPA, JWT in sessionStorage
- OnlyOffice 9.4: hinter `https://onlo.milan.how/`, DDNS auf NUC-IP

## Deploy-Prozess

Workflow: `server/static/index.html` direkt editieren → committen → deployen.

```bash
# 1. committen (nur geänderte Dateien angeben, nie -A)
git add server/static/index.html   # ggf. weitere Dateien
git commit -m "mkan: ..."

# 2. deployen — entweder deploy.sh (empfohlen):
bash deploy.sh

# oder manuell:
tar czf /tmp/mkan-deploy.tar.gz server/ docker-compose.yml deploy-mkan.sh
scp /tmp/mkan-deploy.tar.gz user@yourserver:/tmp/
ssh user@yourserver 'bash -s' << 'REMOTE'
cd /tmp && rm -rf mkan-server && mkdir mkan-server
tar xzf mkan-deploy.tar.gz -C mkan-server
bash mkan-server/deploy-mkan.sh
REMOTE
```

**Hinweis:** `multikanban-server.html` im Projektwurzel ist ein veraltetes Relikt — nicht verwenden. `deploy.sh` kopiert sie nicht mehr nach `server/static/index.html`.

## Public-Repo (GitHub)
`../mkan-public/` — bereinigter Spiegel ohne History, ohne sensitive Daten.
Repo: `https://github.com/mithubin/mkan`

```bash
# Sync + Push nach GitHub (aus trello-klon-sv heraus):
bash publish-public.sh                         # auto-Message
bash publish-public.sh "feat: neues Feature"   # eigene Message
```

`publish-public.sh` kopiert alle tracked Files (außer `trel_sv userdata.md`), ersetzt sensitive Strings (OO-Secret, NUC-Hostname, lokale Pfade) und pusht nach GitHub. Pfade relativ zu `$0` — funktioniert von überall.

**Wichtig:** `trello-klon-sv` hat keinen git-Remote — nie `git push` direkt von hier ausführen. Das würde sensitive Daten (OO-Secret, NUC-Hostname) unbereinigt auf GitHub landen lassen. Einziger Weg zu GitHub: `bash publish-public.sh`.

## Routen-Übersicht (alle implementiert)
- `GET /`, `GET /health`
- `/auth/*` – register, login, change-password, me
  - `GET /auth/users` – alle System-User (id, name, email); für Mitglieder-Dropdown
- `/boards/*` – CRUD, members (GET/POST/DELETE/create), import, events (SSE live); `startDate`/`endDate` in BoardUpdate
  - `POST /boards/{id}/members/create` – Owner-only: legt neuen User an + fügt ihn zum Board hinzu; sendet 2 Mails
  - `POST /boards/{id}/members/{uid}/send-url` – sendet URL-Erinnerungsmail (owner only)
  - `POST /boards/{id}/members/{uid}/send-reset` – erzeugt Reset-Token + sendet Link (owner only)
  - `GET /boards/{id}/cards/search?q=` – Volltextsuche Top-Level-Karten (LIMIT 30), gibt `[{id, title, colTitle}]`
  - Board-Response enthält `members: [{id, name, role}]` — wird in `S.members` gespeichert
- `/cards/*` – CRUD, duplicate (`?linked=true` für verknüpfte Kopie), subtasks (CRUD), labels (assign/remove)
  - `POST /cards` akzeptiert `col_id`/`lane_id` für Top-Level-Karten, gibt `{id, position, createdAt, colId, laneId}` zurück
  - `PATCH /cards/{id}` akzeptiert: `linkedCards`, `personId`, `cardMode`, `dueDate`, `timeSpent`, `attendanceN`, `attendanceData`, `createdAt`, `coverPos`, `assigneeIds`
  - Board-Response und `GET /cards/{id}` liefern zusätzlich: `updatedAt`, `coverPos`, `assignees: [{id, name}]`
  - `GET /cards/{id}/board-links` – gibt outgoing + incoming `[{targetCardId, targetBoardId, targetCardTitle, targetBoardTitle, missing, deleteCardId}]`
  - `POST /cards/{id}/board-links` – `{target_card_id, target_board_id}`; prüft ob User Zugang zu Target-Board hat
  - `DELETE /cards/{id}/board-links/{target_card_id}` – löscht in beiden Richtungen
- `/columns/*`, `/swimlanes/*`, `/labels/*` – CRUD
  - `GET /swimlanes/{id}/attachments.zip`, `/covers.zip` – ZIP-Download
- `/attachments/*` – upload, file-download, cover (POST/GET/DELETE); Cover-Upload setzt `cards.updated_at`
  - `GET /attachments/cards/{card_id}/attachments.zip` – alle Anhänge der Karte + Datei-Kinder als ZIP
  - `PATCH /attachments/{att_id}/move` – Anhang zu anderer Karte verschieben (`{card_id}`, board-intern)
  - `PATCH /attachments/{att_id}/position` – Reihenfolge (`{position: int}`)
  - `POST /attachments/{att_id}/oo-discard {key}` – OO-Verwerfen-Mechanismus (In-Memory-Set)
  - `PUT /attachments/{att_id}/content` – Dateiinhalt überschreiben (Galerie-Editor)
- `/boards/{id}/persons`, `/persons/{id}` – CRUD; DELETE unlinkt `cards.person_id`
- `/boards/{id}/snapshots`, `/snapshots/{id}`, `/snapshot-cards/{id}` – Snapshot-CRUD + Nachkorrektur
- `/boards/{id}/klassenbuch`, `/klassenbuch/{id}` – Log-CRUD (verknüpft mit Snapshots via `snapshot_id`)
- `/admin/*` – admin-only
  - `POST /admin/users` – User anlegen + 2 Willkommensmails
  - `GET|PATCH|DELETE /admin/email-templates/{key}` – Template-CRUD (6 Keys, DB-Override mit Fallback auf DEFAULTS)
  - `POST /admin/email-templates/test` – Testmail an beliebige Adresse
  - `GET /db/export`, `POST /db/import` – SQLite-Backup/Restore
  - `DELETE /admin/boards/{id}` – Board löschen (admin-only)
- `/planner/*` – Planer-Items
  - `GET /planner/items?date_from=&date_to=` – inkl. `user_name`, `updated_by_name`, `is_freiraum`
  - `POST /planner/items`, `PATCH /planner/items/{id}` – Ownership-Check (403 für fremde Items)
  - `DELETE /planner/items/{id}`, `POST /planner/items/{id}/split {at: HH:MM}`
  - `POST|GET|DELETE /planner/items/{id}/cover`
  - `GET /planner/due-dates?date_from=&date_to=`

## tul-DV Bridge (Stand 2026-06-28)

Karten können ihre Dateien für tul-Tools (tul.yourdomain.example) freigeben. Implementiert in
`server/routers/attachments.py` (Prefix `/attachments`), Auth via `X-Tul-Secret`
(Env-Var `TUL_SECRET`); kein mkan-JWT erforderlich.

### dvShared + targetTul — UI-Flow in mkan

Im Karten-Modal gibt es eine dreistufige Sektion (`dvSharedSec`):

1. **Toggle** "tul-DV freigeben" → setzt `cards.dv_shared = 1`
2. **Pill-Auswahl** "Zugang für: [trskr][lern][popt][bild]…" → speichert `cardSettings.targetTul`
   (z.B. `"bild"`); gleiche Pill nochmal → entfernt targetTul
3. **Link** "→ bild öffnen" erscheint (öffnet `https://tul.yourdomain.example/<tul>`)

`card_settings` (JSON TEXT in DB): `{"targetTul": "bild", ...}` — unveränderliche Keys neben
anderen Karten-Settings (z.B. `templateCardId`, `dataSrcId`).

### Endpunkte (alle X-Tul-Secret)

| Route                                             | Methode | Zweck                                                     |
|---------------------------------------------------|---------|-----------------------------------------------------------|
| `/attachments/dv/pool`                            | GET     | Alle `dv_shared=1`-Karten + Dateien (direkte + file_card-Kinder) |
| `/attachments/dv/file/{att_id}`                   | GET     | Datei-Download (prüft dv_shared, inkl. file_card-Kinder)  |
| `/attachments/dv/card/{card_id}`                  | GET     | Dateien einer spezifischen Karte (direkte + file_card-Kinder) |
| `/attachments/dv/cards-for-tool/{tul}`            | GET     | Karten mit `dv_shared=1` und `card_settings.targetTul=tul` |
| `/attachments/dv/upload-to-card/{card_id}`        | POST    | UploadFile als Anhang auf Karte speichern; prüft `dv_shared` |
| `/attachments/dv/unlink-card/{card_id}`           | POST    | `targetTul` aus `card_settings` entfernen; broadcastet Board-Update |

### Dateiformat (Antwort-Schema)

```json
[
  {
    "card_id": "uuid",
    "title": "Meine Karte",
    "files": [
      { "id": "att-uuid", "name": "bild.jpg", "size": 45000, "mime": "image/jpeg" }
    ]
  }
]
```

`files` enthält sowohl direkte Attachments als auch Anhänge von file_card-Kindern.

### Reverse Flow (tul → mkan)

Upload-to-card: tul-Hub leitet Multipart-Body transparent durch (Content-Type inkl. Boundary
bleibt unverändert, nur X-Tul-Secret wird hinzugefügt). mkan speichert die Datei im
`UPLOAD_PATH/<card_id>/`-Ordner und legt einen `attachments`-Eintrag an. Board-Broadcast
signalisiert allen Clients die Karte als aktualisiert.

### Deploy-Hinweis

**Korrigiert 2026-07-12** — die vorherige Fassung dieses Abschnitts war falsch und stand im Widerspruch
zum tatsächlichen, seit 2026-06-23 gültigen Workflow. `server/static/index.html` ist die einzige
Frontend-Quelle — direkt editieren, direkt committen. `multikanban-server.html` im Projektwurzel ist ein
veraltetes Relikt, nie kopieren. Vollständiger Deploy-Ablauf: siehe `project_deploy_workflow.md`
(Memory) bzw. `DEPLOY.md`.

## Was noch fehlt / offene Todos

Siehe `PROJEKT.md` (Abschnitt „Offene Punkte") — dort aktuell gepflegt, hier nicht mehr duplizieren.

### WebDAV entfernen + Python-Desktop-Bridge
WebDAV ist unpraktisch (schwerfälliger Zugriff, gvfs rendert Vorschauen statt Dateien zu öffnen). Geplanter Ersatz: Python-Bridge-Skript (lokal, öffnet Dateien direkt aus mkan via OS-Default-App). Entfernen wenn Bridge steht: `server/routers/dav.py` + Import/Mount in `main.py` (`get_dav_app`, `/dav`-Route) + `wsgidav` aus `requirements.txt`.

### kleines feature-update: direktes Modal-Öffnen aus Unterkarten-Chip im Elternmodal

## OnlyOffice-Konfiguration (NUC)
- OO läuft als Docker-Service `onlyoffice` hinter nginx → `https://onlo.milan.how/`
- Persistente Konfiguration: `/path/to/mkan/oo-local.json` → gemountet als `/etc/onlyoffice/documentserver/local.json:ro`
- `oo-local.json` enthält: `blockPrivateIP:false`, `allowPrivateIPAddress:true`, JWT-Token-Config + Secrets, `storage.fs.secretString`
- **Kritisch**: `storage.fs.secretString` muss mit `secure_link_secret` aus `/etc/onlyoffice/documentserver/nginx/ds.conf` übereinstimmen (beide: `YOUR_OO_SECRET_HERE`)
- JWT-Token für Init-Config: `pyjwt.encode(config_dict, OO_SECRET, 'HS256')` — kein `{'payload':...}`-Wrapper (OO 9.x)
- Analytics.js-Stub in mkan `<head>`: verhindert uBlock-Blockade
- Env: `OO_URL=https://onlo.milan.how`, `OO_MKAN_BASE=http://mkan:8000`, `OO_SECRET=<shared-secret>`
- OO-Verwerfen: `POST /attachments/{att_id}/oo-discard {key}` vor `destroyEditor()` — sonst bleibt WebSocket-Session offen → nächster OO-Aufruf scheitert

## Karten-Modi

Jede Karte hat `card_mode`: `'org'` | `'knowledge'` | `'student'` | `'monster'` | `'email'` | `'doc'`

| Sektion im Modal     | Org | Wissen | Schüler | Monster | Mail | Dok |
| -------------------- | :-: | :----: | :-----: | :-----: | :--: | :-: |
| Notizen/MD           |  ✓  |   ✓    |    ✓    |    ✓    |  ✓   |  ✓  |
| Notiz/Vorlage-Toggle |  —  |   —    |    —    |    —    |  —   |  ✓  |
| Subtasks             |  ✓  |   ✓    |    ✓    |    ✓    |  —   |  —  |
| Due-Datum + Timer    |  ✓  |   —    |    —    |    ✓    |  ✓   |  —  |
| Dateikarten          |  ✓  |   ✓    |    ✓    |    ✓    |  ✓   | ✓*  |
| Person (Kürzel)      |  —  |   —    |    ✓    |    ✓    |  —   |  —  |
| Zugewiesen           |  ✓  |   ✓    |    ✓    |    ✓    |  ✓   |  ✓  |
| Punkte               |  —  |   —    |    ✓    |    ✓    |  —   |  —  |
| Anwesenheits-Widget  |  —  |   —    |    ✓    |    ✓    |  —   |  —  |
| emailSec             |  —  |   —    |    —    |    —    |  ✓   |  —  |
| docSec               |  —  |   —    |    —    |    —    |  —   |  ✓  |

*) Dateikarten sichtbar, aber templateCardId-Karte ist versteckt (mkCard + buildFiles filtern)

Zugewiesen in `#mMetaRow` — immer sichtbar, unabhängig vom Modus; `applyModalMode` steuert es nicht mehr.

Mode-Toggle: Buttons in `buildBreadcrumb(card)`. `applyModalMode(card)` blendet Sektionen ein/aus.
Board-Indikatoren: alle als CSS `::after`-Dreieck via `border`-Trick:
- knowledge = rechts unten, 60×60px, `linear-gradient(135deg, transparent 50%, rgba(255,255,255,.28) 50%)`
- email-Modus = links oben, 60×60px, `rgba(14,165,233,.40)` (blau)
- doc-Modus = links oben, 60×60px, `rgba(239,68,68,.38)` (rot)

### Dok-Modus (card_mode='doc')

**Konzept:** Karte verwaltet eine DOCX-Vorlage (in OO bearbeitet) + Datenquelle → Seriendokument-Generierung.

**cardSettings:** `{templateCardId, dataSrcId, filenameTemplate, outputFormat: 'docx'|'pdf'}`

**Template-file_card:** versteckte Kindkarte mit DOCX-Anhang. Angelegt via `POST /cards/{id}/doc-template` (python-docx, Startvorlage mit Beispieltext). Wird aus mkCard-Filecards-Strip und buildFiles() herausgefiltert.

**Notiz/Vorlage-Toggle** (`#docViewToggle`, `_docSetView()`): schaltet zwischen mNotes und `#docTplArea` (zeigt Dateiname + OO-Öffnen-Button).

**docSec (Sidebar):**
- Template-Management: "Vorlage anlegen" oder "OO öffnen"
- Format-Toggle DOCX/PDF (`_docSetFmt()`)
- Dateiname-Template (z.B. `anmeldung_{{name}}.docx`)
- Datenquelle (table_card/query_card) + `{{feld}}`-Chips
- "↓ Felder ins Dokument"-Button: `POST /cards/{id}/doc-insert-fields` → schreibt alle Felder als erste Zeile in die DOCX (grau/9pt, Marker `‹ Felder: ›`, vor OO-Öffnen anwenden)
- "▶ Seriendokumente erstellen": `POST /cards/{id}/series-docs`

**Seriengenerierung (`POST /cards/{id}/series-docs`, `server/routers/docs.py`):**
- Liest Datenquelle (table_card/query_card via board-DB)
- `_fill_docx()`: python-docx füllt `{{feld}}`-Platzhalter run-übergreifend sicher (Paragraphen-Ebene), `{{datum}}` automatisch
- `_make_filename()`: Dateiname aus Template + Zeilenwerten
- Erstellt Ausgabe-Karte `"Ausgabe - [Vorlagenname]"` (gleiche Spalte/Lane), Wiederholung → `(2)`, `(3)` etc.
- Pro Datenzeile: `file_card` als Kind der Ausgabe-Karte mit DOCX-/PDF-Anhang
- PDF: Fallback auf DOCX wenn `_convert_bytes_to_pdf` nicht verfügbar

**Gotchas:**
- `docs.py`-Routen dürfen kein `/cards`-Präfix haben — `main.py` fügt es via `prefix='/cards'` schon hinzu. Falsch: `@router.post('/cards/{id}/...')`, richtig: `@router.post('/{id}/...')`.
- OO-Button muss `openOO(att.id, att.name)` direkt aufrufen — `openModal(tc.id)` funktioniert nicht, weil die template-file_card aus der normalen Modal-Navigation herausgefiltert ist.

### Doclink-Karte (doclink_card)

**Konzept:** Zentrale DB-Karte zur Verwaltung von Seriendokumenten über mehrere board-seitige Dok-Karten.

**Analog zu `maillink_card`** — eigener DB-Kartentyp (`▤ Dok-Template`), Datenquelle + Datensatz-Auswahl zentral, mehrere verlinkte Vorlagen als Chips.

**cardSettings:** `{dataSrcId, activeTemplateCardId, outputFormat: 'docx'|'pdf', filenameTemplate}`

**Verknüpfung:** Dok-mode Boardkarten setzen `cardSettings.linkedDocCardId` → erscheinen als Chips in der doclink_card. docSec-Sidebar der Boardkarte zeigt "Dok-Karte koppeln"-Abschnitt mit Dropdown + Koppeln/Trennen.

**Seriengenerierung:** `POST /cards/{id}/doclink-series` mit `{templateCardId, dataSrcId, outputFormat, filenameTemplate, selectedIndices}`.
- `templateCardId` = die Boardkarte (doc-mode) → deren `cardSettings.templateCardId` → DOCX-Anhang
- `selectedIndices`: Array ausgewählter Zeilen-Indices; `null` = alle
- Ausgabe-Karte in gleicher Spalte/Lane wie doclink_card

**DB-Karten-Typnamen (UI):** `▤ Dok-Template`, `✉ E-Mail-Template`, `⊡ MD-Template`, `⊕ Serien-Hub`, `📋 Log` — alle monochrom, kein farbiges Emoji.

**DB-Karte Badges:** `badge-doc` = rot (`rgba(239,68,68,…)`, `#f87171`); `badge-log` = blaugrau (`rgba(100,116,139,.1)`, `#94a3b8`)

### Serien-Hub (serienlink_card)

**Konzept:** Kombinierter Hub für Seriendokument-Erzeugung + Serienmail-Versand in einem Modal. Ersetzt den separaten Einsatz von doclink_card + maillink_card.

**cardSettings:** `{dataSrcId, activeDokCardId, activeMailCardId, outputFormat:'docx'|'pdf', filenameTemplate, accountId}`

**Layout (2-Spalten):**
- Hilfe-Button links (`margin-left:15px`)
- Datenquelle: Dropdown 30% Breite + `↻ Daten laden` inline (`margin-left:15px`)
- Datentabelle (volle Breite, mit Checkboxen)
- Zwei-Spalten-Grid: links Dok-Generierung, rechts Mail-Versand
- Vorschau-Button + Panel ganz unten, volle Breite

**Chip-Scanning (kein Dropdown):**
- Dok: scannt `S.cards` nach `cardMode==='doc' && cardSettings.linkedDocCardId===hub.id`
- Mail: scannt `S.cards` nach `cardMode==='email' && cardSettings.linkedEmailCardId===hub.id`
- Aktive Karte: `activeDokCardId` / `activeMailCardId` als Closure-Variablen; `_saveCs()` persistiert in `cardSettings`
- Reload-Button `↻` mit `margin-left:15px` (kein `float:right` — kollidiert mit Grid-Spalten)

**origIdx-as-position:** `file_card.position = original row index` in der Datenquelle. Ermöglicht Zuordnung Dok-Anhang ↔ Datenzeile bei Checkbox-Selektion (`ausgabeRef.files.find(f=>f.position===origIdx)`).

**ausgabeRef:** `{value: cardId, files: [{attId, name, position}]}` — Brücke zwischen Dok-Generierung (links) und Mail-Versand (rechts). Nach Generierung via `_refreshAusgabe(true)` befüllt.

**selAttsMap:** `{id→name}` parallel zu `selAtts` (Set) — speichert Dateinamen statischer Anhänge für Vorschau ohne API-Call.

**Test-Email:** `isTest=true` → checked Rows = Daten-Preview (mehrere möglich); Empfänger = Absender (`acc.from_address || acc.smtp_user`). Kein Versand an echte Empfänger.

**Seriengenerierung:** `POST /cards/{id}/serienlink-docs` mit `{dokBoardCardId, dataSrcId, outputFormat, filenameTemplate, selectedIndices}`.
- Ausgabe-Karte landet in col/lane der **Dok-Boardkarte** (nicht der serienlink_card)
- `_make_filename()`: strip `\.[a-zA-Z0-9]{1,6}$` + korrekte Extension anhängen — Dateiname-Input immer ohne Erweiterung

**log_card:** Nach realem Versand automatisch angelegt (gleiche col/lane wie serienlink_card). Enthält Protokolltext als `notes` + TXT-Anhang `versandlog.txt`. DB-Kategorie "Logs" in der DB-Spalte, ganz unten. Badge: `badge-log` (blaugrau).

**Anhang-Vorschau Extension:** Extension-Span mit eigenem `color:var(--muted);opacity:.55` — nicht via `innerHTML`-opacity, da Parent-`color:var(--acc)` sonst überschreibt. Pattern: `sp.appendChild(document.createTextNode(base)); ext.style.cssText='color:var(--muted);opacity:.55'; sp.appendChild(ext)`.

**Datenquellen-Warnung:** Rot (`rgba(239,68,68,.12)` / `rgba(220,38,38,.85)`), fett, **vor** dem Dropdown — Hinweis auf unveränderliche Zuordnung zwischen Dok-Erzeugung und Versand.

**Gotcha:** `_saveCs()` referenziert `srcSel`, `fmtPdf`, `fnInp`, `accSel` via Closure. Alle als Sende-Handler aufgerufen, nie vor Deklaration — kein Problem. Aber nie `_saveCs` auf Modulebene aufrufen.

**Routen (docs.py, prefix `/cards` in main.py):**
- `POST /{id}/serienlink-docs` — Seriendokumente für serienlink_card
- `GET /{id}/ausgabe-cards` — Liste vorhandener Ausgabe-Karten mit Datei-Infos (`[{id, title, fileCount, files:[{attId,name,position}]}]`)
- `POST /{id}/doclink-series` — für doclink_card (älterer Typ)

### Dateikarten – Verschieben/Kopieren-Picker (Phase 33)

`mkFileItem({name, size, type, isFC, fcId, attId, attUrl, date, onOpen, onDel, onSetCover, onMove, onCopy, srcCardId, draggable})` — `onMove`, `onCopy`, `srcCardId` aktivieren den Picker.

**Picker-UI:**
- Suchfeld `_pinp` + Ergebnisliste `_plist` (max 30 Karten, max-height 130px scrollbar)
- Erstes Ergebnis wird automatisch vorselektiert
- Checkboxen: Kopieren (`_copyChk`), Boardfähre/neue Karte (`_faehreChk`), Link zur Zielkarte (`_linkChk`)
- OK/✕ in eigener `_pbtnRow` (nicht in `_ptop`) — bleiben bei Boardfähre-Tick sichtbar
- col_scope: Picker filtert auf `S.myColId` wenn gesetzt

**Boardfähre** (`_faehreChk`):
- Blendet `_ptop` (Suchfeld) und `_plist` aus, zeigt Namens-Input `_faehreInp`
- Erstellt Top-Level-Karte (`parentCardId: null`) im selben `colId`/`laneId` wie Quellkarte (`S.cards[srcCardId]`)
- Name vorbelegt mit `MOVE_<Dateiname>`, editierbar
- `POST /cards` mit `{col_id, lane_id}` → Response enthält `colId`/`laneId` direkt
- `S.cells[ck(sc.laneId, sc.colId)].push(r.id)` + `renderBoard()` → sofort sichtbar
- Kein `_pickedId`-Guard bei aktivem Boardfähre-Modus

**onMove / onCopy für file_cards:**
```js
onMove: PATCH /cards/{fc.id} {parentCardId, colId, laneId} + refreshParentCard beider Karten
onCopy: POST /cards/{fc.id}/duplicate → PATCH /cards/{new.id} → GET /cards/{new.id} → refreshParentCard
```

**onMove / onCopy für Anhänge:**
```js
onMove: PATCH /attachments/{att.id}/move {card_id} + rebuild buildFiles
onCopy: fetch(att.url) → Blob → FormData → POST /attachments/cards/{targetId}
```

### DB-Spalten (via `_migrate_db`)
```
cards: card_mode TEXT DEFAULT 'org'
       due_date TEXT
       time_spent INTEGER DEFAULT 0        (Sekunden, akkumuliert)
       attendance_n INTEGER
       attendance_data TEXT                (JSON [true/false/...])
       cover_pos TEXT                      (z.B. "42.3% 18.7%")
snapshot_cards: card_mode, due_date, time_spent, attendance_n, attendance_data,
                assignee_names TEXT        (JSON [name, ...], eingefroren beim Snapshot)
card_assignees: card_id, user_id           (many-to-many, ON DELETE CASCADE beidseitig)
columns: bg_color TEXT
planner_items: id, user_id, title, date, time_start, time_end, color, notes,
               cover_path, updated_by, created_at, updated_at, is_freiraum
inter_board_links: card_id, target_card_id, target_board_id (PK: card_id+target_card_id)
email_templates: key PK, subject, body
attachments: position INTEGER
board_members: col_id TEXT              (Nur-Spalten-Zugriff; NULL = uneingeschränkt)
cards: created_by TEXT                  (User-ID Ersteller; für col_scope delete-check)
```

### Timer
- `_timers = {}` (cardId → {startTs}); `startTimer(id)` / `stopTimer(id)` akkumulieren in `card.timeSpent` und PATCHen
- `updateBoardTimerSum()` erst nach Board-Load aufrufen (S kann null sein)
- `fmtSecs(s)` → `'H:MM:SS'`; `parseSecs(str)` → Sekunden (akzeptiert H:MM:SS oder Minuten)

### Anwesenheits-Widget
Sitzt in **m-side**; N-Eingabe → `attendanceData=[true*N]`; Quadrate klickbar → toggle → PATCH + `refreshParentCard()`.
Board-Karte: Gradient-Overlay (`.card-att-overlay`) — abdunkelt abwesende Segmente.

## Modal-Layout

- `.modal` max-width 1220px; `.m-side` 440px
- **Zeile 1** (`#mBreadcrumb`): Level-Badge + Pfad + Mode-Toggle-Buttons
- **Zeile 2** (`#mMetaRow`): Labels links (`.m-meta-lbl`, flex-wrap) + Zugewiesen rechts (`.m-meta-asgn`, 440px, 22px-Avatare) — für alle Modi sichtbar
- **Zeile 3** (`#mColorRowWrap`, `.m-color-row-sect`): Farbzeile — `#colorRow` (Trello-Streifen-Farbe) + Karten-Hintergrundfarbe. Wird in `buildBreadcrumb()` befüllt.
- **Rechte Sidebar (m-side)** von oben: Fälligkeit → Zeiterfassung → Titelbild → Person → Punkte → Anwesenheit → Karte verschieben
- Kartenfuß (`.card-footer`, 3 Zonen): **links** Mode-Icon + Hochkant-Balken je Unterkarte (`.sc-bar`, 3×9px, Kartenfarbe) | **mitte** Due-Date-Badge | **rechts** klickbares Erstelldatum (öffnet `<input type="date">` → PATCH `createdAt`)
- **Kein Speichern-Button** — alles Auto-Save; `dbSaveBtn` vollständig entfernt

### Meta-Zeile
Labels und Zugewiesen zwischen `#mBreadcrumb` und `.m-body`:
- **Labels** (`.m-meta-lbl`): horizontale `.mlbl-chip`-Chips; `.on`-Klasse = aktiv zugewiesen; opacity steuert Sichtbarkeit; `✎`-hover zeigt Inline-Edit-Form (Farbswatch + Text + Löschen)
- **Zugewiesen** (`.m-meta-asgn`): `buildAssignees(card)` rendert 22px-Avatare; alle Modi
- Labels nicht mehr in der Optik-Sidebar; `buildModalLabels()` schreibt direkt in `#lblList` (statisch im HTML)

## Schlüssel-Konzepte

### Assignees / Board-Mitglieder (3 Schichten)
- `users` — System-Accounts (Login)
- `persons` — Board-interne Roster (Schüler-Code/Kürzel + Name), `person_id` auf Karte
- `card_assignees` — Betreuer-Zuweisung: Board-Members auf Karten (many-to-many)

`buildAssignees(card)`: PATCH `assigneeIds: [userId, ...]` ersetzt alle Zuweisungen atomisch.
Owner-Aktion: `POST /boards/{id}/members/create` legt User-Account an + fügt zum Board hinzu in einem Request.
`S.members`: aus Board-Response, `[{id, name, role}]`; Quelle für Assignee-Picker.

### Inter-Board-Links
Bidirektional: `GET /cards/{id}/board-links` liefert outgoing + incoming; jeder Eintrag hat `deleteCardId` (die Seite, die den DB-Row besitzt).
`DELETE /cards/{id}/board-links/{other_id}` löscht in beiden Richtungen — von jeder Seite aufrufbar.
Frontend nutzt `bl.deleteCardId` für den DELETE-Call.

### Nur-Spalten-Zugriff (col_scope)
`board_members.col_id` (nullable TEXT) — wenn gesetzt, sieht und bearbeitet das Mitglied nur diese Spalte.
`cards.created_by` (TEXT) — User-ID des Erstellers; Spalten-Editor darf nur eigene Karten löschen.

`get_col_scope(user_id, board_id, conn) → str | None` in `auth.py`: gibt `col_id` zurück oder `None` (Owner immer None).

Backend-Checks: `boards.py` filtert Spalten/Karten in `build_board_response()`; `cards.py` prüft bei CREATE/UPDATE/DELETE; `snapshots.py` blockt Snapshot für Spalten-Editoren. Board-Response enthält `myColId`.

Frontend: `S.myColId`; `_visibleCols()` filtert; `applyColScope(card)` blendet moveSec, lnkSec, dupLinkBtn, copyBtn aus; delBtn nur bei eigenen Karten.
Owner setzt Scope: `PATCH /boards/{id}/members/{uid}/scope {col_id}` — im Mitglieder-Dialog per Dropdown beim Einladen oder nachträglich.

### Mail-System
SMTP-Config aus Env: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`.
6 Template-Keys: `welcome_board`, `welcome_admin`, `board_added`, `invite_token`, `url_reminder`, `reset_link`.
Zwei-Kanal-Sicherheit: Credentials und URL-Reminder als separate Mails — ein abgefangenes Mail reicht allein nicht.

### Grafischer Planer
- CSS-Vars: `--pl-dur` (Tagdauer in min), `--pl-rh` (Zeilenhöhe in px); Pixel→Minuten: `Math.round(px / _plRowH) * 30`
- Freiräume = echte DB-Einträge (`is_freiraum=1`); `_rebalanceFr(date)` nach Drag/Modal-Speichern aufrufen
- Ownership: nur eigene Items editierbar; Backend wirft 403 für fremde Items; fremde Freiräume werden nicht gerendert
- Parking-Zone: `tabsParked` via `_saveUserPrefs()` / `_loadUserPrefs()` serverseits persistiert
- Z-Order überlappender Items: `localStorage('pl_front')` = `{itemId: serial}` — kein Backend nötig
- Board-Optik localStorage-Key: `kbTheme_<userId>_<boardId>`

### WebDAV / Desktop-Bridge
```bash
gio mount davs://mkan.milan.how/dav/
# davfs2 funktioniert nicht (inkompatibel HTTP/2)
```
Verzeichnis: `/dav/{board_safe}/{card_id[:8]}_{card_title_safe}/{filename}` — `_safe_dir()` ohne Punkte für Ordner (Punkt → gvfs behandelt Ordner als Datei).

Kritische Fallstricke:

| Problem | Fix |
|---------|-----|
| `gio mount` → „Temporary Redirect" | Explizite FastAPI-Route für `/dav` (301 auf https) **vor** `app.mount()` |
| DAV-Listing leer / hrefs ohne `/dav/`-Prefix | `provider_mapping={'/': MkanProvider()}`, paths mit `DAV_PREFIX='/dav'` präfixen |
| `environ['mkan.user_id']` nicht im Provider | `environ.get('wsgidav.auth.user_name')` + `_user_id_for_email()` im Provider |
| Datei öffnet Thumbnail statt Original | Rechtsklick → „Öffnen mit"; oder lokal kopieren |

Einschränkungen: nur bestehende Anhänge editierbar; kein Role-Check auf DAV-Ebene; kein CREATE/DELETE/RENAME via DAV.

### Optik-Menü
`buildBreadcrumb()` erzeugt `#colorRow`, `#cardBgOn`, `#cardBgPick` dynamisch und befüllt damit `#mColorRowWrap` — diese Elemente existieren nur wenn das Modal offen ist.
**Kritisch**: Handler dürfen NICHT auf Modulebene auf diese IDs zugreifen (Element existiert dann nicht → crash).
`closeOptik` ignoriert Klicks in `#colorPicker` (fixed-positioned, außerhalb anchor-DOM).
Farbzeile sitzt in `#mColorRowWrap` (Zeile 3 des Modals, unterhalb Labels) — nicht im Breadcrumb.

### Filter – Ohne Zuweisung + Tiefe
`F.unassigned` (boolean) + `_unassignedDepth` (1 | 2 | Infinity, default 2) steuern den "Ohne Zuweisung"-Filter.
- Kleiner Button `fUnassignedDepth` neben der Checkbox zeigt `1 Eb. / 2 Eb. / ∞ Eb.` — Klick rotiert durch den Cycle
- `anyDescendantMatches(id, maxDepth)` rekursiert bis zur Tiefe; `F.unassigned` nutzt `_unassignedDepth`, alle anderen Filter `Infinity`
- Ohne `maxDepth`-Begrenzung würden tiefe unzugewiesene Kindkarten zugewiesene Eltern ausgegraut anzeigen

### Unterkarten-Chips: Assignee-Badges
`.mc-av` ist `position:absolute`, Kaskade von rechts nach unten:
- Erste Spalte (`right:2px`): Badges von `top:18px` abwärts (18px = Titelfreiraum)
- Wenn Spalte voll (`perCol = floor((_mcHeight-18-4)/15)`): neue Spalte weiter innen (`right += 15px`), wieder von oben
- Max. 6 Badges; `startTop=18px` hält den Kartentitel frei

**Gotcha**: `.mini-card.has-cover > div:not(.mc-cover-ov):not(.mc-av)` — das `:not(.mc-av)` ist nötig, sonst überschreibt der has-cover-Selektor `position:absolute` der Badges mit `position:relative`.

### Unterkarten-Chip-Höhe (`--mc-height`)
CSS-Variable `--mc-height` (default 60px) steuert `.mini-card { height: var(--mc-height, 60px) }`.
Slider im **Board-Optik-Modal** (`#thMcH`, 42–120px); live via `document.documentElement.style.setProperty('--mc-height', ...)`.
`mcHeight` wird in Board-Settings (`PUT /boards/{id}/settings`) gespeichert → cross-device via `_applyThemeBlob(s)`.
`localStorage('kb_mc_height')` als schneller Fallback beim Laden.

### Galerie-MD-Editor (galInitMdEditor)

- Öffnet im **WYSIWYG-Modus** (`initialEditType:'wysiwyg'`) — Checkboxen sind nativ klickbar (contenteditable), kein Preview-Tab-Hack nötig
- **Kein Save-Button** — Auto-Save 1,5s nach letzter Änderung (`debounce`); Ctrl+S sofort; `_galSaveFn` bleibt für `galExitEdit`-Dirty-Check
- `_galSaveFn` wird beim Editor-Destroy auf `null` gesetzt — nie stale belassen, Ctrl+S könnte sonst falsche Datei speichern

### marked.js – globaler Link-Renderer

`ensureMarked()` setzt nach dem Laden einmalig einen Custom-Renderer:
```js
marked.use({renderer:{link({href,title,text}){ return `<a href="${href}"... target="_blank" rel="noopener noreferrer">${text}</a>`; }}});
```
Gilt für alle `marked.parse()`-Aufrufe: Notizen-Preview, Dateivorschau, Hover-Preview, Karten-Face, Seriendruck. Einmal setzen reicht — marked behält den Renderer global.

### Dateimodal – Inline-Editor (fcFileEditor)

`buildFcView(card)` zeigt im oberen Bereich entweder `fcPreview` (Bilder, PDF, unbekannte Typen) **oder** `fcFileEditor` (TXT/MD und alle `text/*`-MIME-Typen):

- **MD-Dateien**: `fcFileEditor` mit Edit/Split/View-Tabs via `setMdMode('fcFile', mode)` — identisch zum Notizen-Editor. `renderMdPreview('fcFile')` rendert in `#fcFilePreview`.
- **TXT/sonstige Textdateien**: nur Textarea, keine Tabs.
- **Speichern**: `saveFcFile()` — lädt `#fcFile.value` als Blob zu `PUT /attachments/{att_id}/content` hoch. Ctrl+S und Save-Button verfügbar. `_fcFileDirty`-Flag steuert "● Ungespeichert"-Indicator (`#fcFileDirty`).
- **Auto-Save**: `saveModalChanges()` ruft `saveFcFile()` am Anfang auf, wenn `_fcFileDirty && cardType==='file_card'`.
- **Leere Dateien**: `renderFilePreview` zeigt "Datei ist leer" statt leerem Container.
- **MD-Vorschau display:flex-Bug**: `.md-body{display:flex}` vererbt sich auf Vorschau-Kontexte. Fix: `display:block` explizit in `.fc-preview .md-body`, `.file-inline-prev .md-body`, `#hoverPreview .md-body`.

### .doc-Vorschau (antiword)

Legacy Word-Binärdateien (`.doc`, OLE2) werden via `antiword` in UTF-8-Text umgewandelt:
- `server/routers/attachments.py`: `subprocess.run(['antiword', path], capture_output=True, timeout=15)`
- `server/Dockerfile`: `apt-get install -y --no-install-recommends antiword`
- Rohes UTF-16-LE-Decode (vorher) ergab Kanji-Rauschen — antiword ist die korrekte Lösung.

### Galerie-Navigation

Beide Buttons (`galNavigate` ← → und `galSkip` ⏮⏭/Tab) respektieren den aktiven Filter — beide nutzen `galFiltered()`. `galUpdateNav` disabled alle vier Buttons anhand `f.length<=1`.

### Reorder Ebene II/III (Kind-Karten)

`wasChild&&!reparentMode`-Branch im Drop-Handler muss:
1. `siblings` aus `S.cards` filtern: **`&&x.cardType!=='file_card'`** — identisch zur render-Logik in `mkCell`/`mkDrillBand`. Ohne Ausschluss divergieren DOM-Index und State-Index bei Elternkarten mit Dateianhängen.
2. `siblings.splice` + `forEach(position=i)` → State aktualisieren
3. `renderBoard()` aufrufen — sonst springt das DOM nach dem Drop zurück
4. Danach PATCH für die gezogene Karte; Backend aktualisiert Geschwister-Positionen eigenständig

### Weitere nicht-offensichtliche Gotchas
- `renderFilePreview(container, att)`: `container` MUSS im DOM eingehängt sein **vor** dem Aufruf — sonst `clientWidth=0`, PDF-Vorschau fällt auf Fallback-Breite zurück
- OO-Button: `attId` übergeben, nicht `fcId` (file_card-ID ≠ attachment-ID → sonst 404)
- `card_links`-Tabelle: kanonische Paare `(min(id_a,id_b), max(id_a,id_b))`, `INSERT OR IGNORE`
- `S.cells` enthält nur Top-Level-Karten (`parentCardId IS NULL`); Kinder über `S.cards[id].parentCardId`
- Level-III-Unterkarten: `_cardDepth` inline berechnen; `subcardSec` erst ab depth ≥ 2 ausblenden
- `boards.py` `build_board_response()`: Karten-Dict muss `'position': c['position']` enthalten — fehlt es, ist `S.cards[id].position === undefined`, der Drop-Handler-Guard `tc.position==null` greift (undefined == null) und bricht Drag-Sort lautlos ab
- Picker-Buttons (OK/✕) die beim Boardfähre-Tick sichtbar bleiben müssen: **nicht in `_ptop`** (das wird ausgeblendet), sondern in eigener `_pbtnRow`

## Lokale Entwicklung
```bash
# Schnellstart (kein Docker, kein NUC):
bash start-local.sh   # richtet venv ein, startet Server, öffnet Browser

# DB vom NUC spiegeln (optional, für Tests mit echten Daten):
scp user@yourserver:/mnt/mkan/db/kanban.sqlite server/data/db/kanban.sqlite

# manuell:
cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -q
.venv/bin/uvicorn main:app --port 8000 --reload
# → http://localhost:8000
```
Uploads/Cover zeigen lokal 404 (Dateien nur auf NUC) — kein Problem, nur UI testen.
OO-Features (Dokument-Edit, Seriendok) nicht verfügbar ohne laufende OO-Instanz.

## Arbeitshinweise
- Uvicorn läuft aus `server/` → Imports ohne Paketpräfix (`from db import ...`)
- `db.get_conn()` ist ein Contextmanager, immer mit `with` verwenden
- `auth.require_board_access()` vor jeder board-bezogenen Operation aufrufen
- Positionen (Spalten, Lanes, Karten) immer als Integer, 0-basiert
- Karten-Response (camelCase): `colId`, `laneId`, `bgColor`, `pointsMax`, `coverImage`, `labelIds`, `cardMode`, `dueDate`, `timeSpent`, `attendanceN`, `attendanceData`, `coverPos`, `updatedAt`, `assignees: [{id, name}]`
- SSE-Broadcast: live in allen Routern, Frontend `initSSE()` mit `EventSource`
- Cover-Images: `coverUrl(card)` verwenden (beinhaltet Token + Cache-Buster), nie `card.coverImage` direkt als src
- Attachment-Downloads: `fetch()` mit Auth-Header → Blob-URL → programmatischer Click
- Duplicate mit `?linked=true` legt `card_links`-Eintrag an und kopiert Anhänge + Cover (shutil.copy2)
- Undo-Stack: snapshottiert cards + position (aus S.cells); löscht auf Undo neue Karten; Stack nur bei Board-Wechsel geleert
- `card_type`: `'card'` | `'file_card'`; Unterkarten sind normale Karten mit `parentCardId`
- `file_card` darf an jeder Tiefe hängen (Leaf-Knoten)
- `_drillPath[]`: Array von Karten-IDs Root→Fokus; `drillInto(id)` baut Pfad via parentCardId-Chain
- Board-Optik in DB: `PUT /boards/{id}/settings` mit JSON-Blob; inkl. `fileChipColor`, `fileTypeSat` (0-100), `mcHeight` (42–120, Unterkarten-Chip-Höhe in px)
- `fileTypeColor(mime)`: HSL-Strings, Sättigung via `fileTypeSat`
- Level-Badge (I/II/III): in `mkCard()` immer gesetzt, position:absolute top/right
- Modal: `_notesEl(c)` → `$('fcNotes')` für file_cards, `$('mNotes')` für alle anderen
- `#fcFile` / `#fcFileBody` / `#fcFileTabs` / `#fcFileEditor`: Inline-Editor für TXT/MD-Anhänge im fc-modal; `saveFcFile()` für PUT-Upload
- Breadcrumb (`mBreadcrumb`): Level-Badge + Pfad + Mode-Toggle-Buttons via `buildBreadcrumb(card)`. Farbzeile landet in `#mColorRowWrap` (Zeile darunter), nicht im Breadcrumb.
- Enter in `mTitle` → `closeModal()` (kein Zeilenumbruch)
- Upload in `buildFiles()`: POST `/cards` mit `cardType:'file_card'` + POST `/attachments/cards/{id}`
- `mkFileItem` Signatur: `{name, size, type, isFC, fcId, attId, attUrl, date, onOpen, onDel, onSetCover, onMove, onCopy, srcCardId, draggable}`
- `ck(laneId, colId)` = `laneId + '::' + colId` — Cell-Key für `S.cells` (Lane zuerst!)

# tul.yourdomain.example – Projektstand & Planung

Stand: 2026-06-26

---

## Module

| Modul     | URL                        | Port | Funktion                              | Status        |
|-----------|----------------------------|------|---------------------------------------|---------------|
| tul-hub   | tul.yourdomain.example/             | 5000 | Login, Hub-Übersicht, Admin           | ✓ aktiv       |
| trskr     | tul.yourdomain.example/trskr        | 5004 | Whisper-Transkription (faster-whisper)| ✓ aktiv       |
| bild      | tul.yourdomain.example/bild         | 5005 | Canvas-Bildlayout (kein Header)       | ✓ aktiv       |
| popt      | tul.yourdomain.example/popt         | 5006 | PDF-Optimierung (Ghostscript)         | ✓ aktiv       |
| lern      | tul.yourdomain.example/lern         | 5007 | Lernkarten-Viewer + Ersteller         | ✓ aktiv       |
| kurv      | tul.yourdomain.example/kurv         | 5008 | Ofen-Log-Kurven (CSV → Diagramm)      | ✓ aktiv       |
| nach      | tul.yourdomain.example/nach         | 5009 | HTML-Hoster: Singles + ZIP-Sets       | ✓ aktiv       |
| kal-trel  | tul.yourdomain.example/kal-trel     | 5010 | Multi-Kanban (SQLite-Persistenz)      | ✓ aktiv       |
| buch      | tul.yourdomain.example/buch         | 5011 | PDF-Shuffle: Seiten reorder/merge     | ✓ aktiv       |

---

## Architektur

```
Internet → KAS-DDNS → Router → NUC (user@yourserver)
NUC: nginx (im nexcloc-Stack) → Docker-Netz webproxy → Container pro Modul
```

### Docker

- Ein zentraler Compose-Stack: `~/tul/tools_nuc/docker-compose.yml`
- Build-Context ist `..` (= `~/tul/`), Dockerfiles unter `tools_nuc/`
- `static/` ist im Hub-Image eingebaut (nicht als Volume) → Hub neu bauen bei JS/CSS-Änderungen

### nginx

Konfiguration: `nginx_tul.conf` (wird von `deploy-tul.sh` in den nexcloc-nginx-Container eingebunden).
Jedes Modul hat einen `location /modul/` Block → `proxy_pass http://<modul>:<port>/`.

**Bekannte Falle:** Nie `proxy_pass http://$variable/;` (Variable + Trailing-Slash) — nginx sendet
dann alle Requests als `GET /` ans Backend. Korrektes Muster:
```nginx
set $upstream tool:port;
rewrite ^/tool(.*) $1 break;
proxy_pass http://$upstream;   # kein Trailing-Slash
```

### Volumes auf dem NUC

| Host-Pfad               | Inhalt                                     | Wer nutzt es          |
|-------------------------|--------------------------------------------|-----------------------|
| `/mnt/tul/db/`          | `tul.sqlite` (Auth, Themes, Datei-Metadaten) | alle Container      |
| `/mnt/tul/trskr/`       | Whisper-Modelle, Ausgabe-Jobs              | trskr                 |
| `/mnt/tul/lern/`        | Lernkarten (CSV, Bilder, Fonts, PDFs)      | lern                  |
| `/mnt/tul/bild/files/`  | tul-files DV-Speicher für bild             | bild, buch (ro)       |
| `/mnt/tul/buch/files/`  | tul-files DV-Speicher für buch             | buch                  |

---

## Gemeinsame Infrastruktur

### Auth

- JWT (HS256, 30 Tage), httpOnly-Cookie `tul_token`, Pfad `/`
- Gemeinsame SQLite-DB: `/tul_data/db/tul.sqlite` in allen Containern
- `tul_auth/`: `auth.py`, `db.py`, `files_routes.py`, `__init__.py`
- Alle Panel-Server: `get_current_user()` im `before_request`-Guard
- `/logout` POST-Route in jedem Panel-Server erforderlich

### Theme-System (`tul-theme.js` / `tul-theme.css`)

CSS-Variablen-Kanon (alle Module):
`--bg`, `--bg2`, `--bg3`, `--acc`, `--acc2`, `--border`, `--text`, `--muted`, `--blur`

Modul-Presets:

| Modul    | Chrome     | Akzent     | Charakter             |
|----------|------------|------------|-----------------------|
| trskr    | `#131828`  | `#5c8fc8`  | Dunkelblau / Aufnahme |
| lern     | `#142018`  | `#5abf5a`  | Dunkelgrün / Natur    |
| kurv     | `#211808`  | `#d4882a`  | Braun / Hitze         |
| popt     | `#141a1f`  | `#6ab0c8`  | Grau-Blau / Dokument  |
| bild     | `#1c1020`  | `#bf5ab0`  | Violett / Bild        |
| nach     | `#101820`  | `#50a8c8`  | Cyan / Hoster         |
| kal-trel | `#0e1620`  | `#5588cc`  | Blau / Board          |
| buch     | `#1a1510`  | `#c09050`  | Pergament / Druck     |

Theme-Persistenz: **SQLite** (`user_themes`-Tabelle). `theme_post()` liest bestehende Settings,
merged per `existing.update(incoming)`, schreibt zurück — Presets überleben Theme-Wechsel.

### Panel-Header-Standard

```
[ ← Panel ]  [ modul-spez. ]     Titel (Mitte)     [ ◑ ]  [ ? ]  [ © ]  [ AB ⏏ ]
└── .hdr-left (manuell) ───────┘                   └── .tlt-hdr-right (tul-theme.js) ──┘
```

- `tulTheme.init({ subpath: _B, preset: tulTheme.PRESETS.<modul> })`
- `tulFiles.init({ subpath: _B, tool: '<modul>', onChange: … })` — injiziert DV-Button **in .tlt-hdr-right**
- Kein separater DV-Link im `.hdr-left` — tul-files.js übernimmt das selbst
- **Ausnahme bild**: kein Header-Bar; rechtes Fix-Panel + linkes Floating-Panel

---

## DV-System (`tul-files.js`)

Vollständiges Konzept: **`DV_PROTOKOLL.md`**

Kurzfassung:
- Floating Modal (Eingabe | Ausgabe) per DV-Button, von tul-files.js in Header injiziert
- Eingabe-Spalte: Eigene Uploads + **externe Quell-Tabs** (bild-A, mkan-X, …)
- Ausgabe-Spalte: tool-spezifisch, Download, ZIP, Nextcloud-Push
- **Gruppen-Selektion ☑☐⇅** je Gruppe — Eingabe und Ausgabe; automatisch in allen Tools aktiv
- **groupByGrp** (kurv): Output nach `grp`-DB-Feld gruppiert — ein Run = ein Verzeichnis, keine losen Dateien
- **NC Push-only im Modal**: `ncLoad()` filtert `?direction=push`; Fetch-Quellen sind Panel-seitig
- **NC-Ziel Persistenz**: `localStorage['tlf-nc-sel:<tool>']` — tool-differenziert
- `externalSources` in `tulFiles.init()` für Cross-Tool-Wiring (`onWire`-Callback)
- buch: bild-Ausgabe als „bild-A"-Tab; Wiring → Import in Workspace; Export → DV-Ausgabe

---

## Deployment — WICHTIG

**Der einzige korrekte Deploy-Weg ist git subtree push, ausgeführt vom Repo-Root aus** (`tulkan/`,
nicht aus `tul_s/` — seit dem Merge mit mkan 2026-07-12 in ein gemeinsames Repo würde
`git push nuc master` sonst versehentlich den ganzen kombinierten Baum pushen):

```bash
git add <dateien>
git commit -m "..."
git subtree push --prefix=tul_s nuc master
# oder: bash tul_s/push-nuc.sh
```

Der post-receive-Hook auf dem NUC (`~/tul.git/hooks/post-receive`) erledigt automatisch:
1. `git checkout -f` → Work Tree `~/tul/tools_nuc/` auf Stand bringen
2. `deploy-tul.sh` → nginx.conf aus `nginx_tul.conf` zusammenbauen + nginx reload
3. `docker compose up -d --build` → alle Container neu bauen und starten

**Nie manuell SCP + ssh-Befehle** — das führt zu Zustand-Divergenz zwischen lokalem Repo und NUC.
Wenn doch mal ein Hotfix per SCP nötig ist, danach sofort committen und pushen.

Logs auf NUC prüfen:
```bash
ssh user@yourserver "docker logs kurv --tail 30"
```

---

## Offene Aufgaben

### popt
- Ausgabe-Download nach Optimierung manchmal instabil (prüfen)

### lern
- Bilder/Fonts/CSV im Ersteller per DV verwalten (lokale Atavismen bereinigen)
- PDFs im Viewer per DV

### trskr
- Crash-Resilienz: abgeschlossene Jobs nach Container-Neustart auffindbar machen
- `file_type='batch'` wird von keinem Flow gesetzt — Batch-TXT ohne Typ-Badge

### kurv
- NC-Push-Ziel anlegen und Workflow testen (WebDAV-Kompatibilität)
- kWh.log UTF-8-Encoding in Vorschau prüfen
- Align-Felder (align_temp/align_offset_h) nach letztem Bugfix im HTML-Output-Pfad nochmal testen

### nach
- ncEnabled fehlt noch

### buch
- mkan-Karten-Anhänge als weiterer externalSource-Tab (→ DV_PROTOKOLL.md)

### Allgemein
- Cleanup-Cron für abgelaufene DV-Dateien (`files.expires_at`)
- crossMimes auto-Discovery und `api/cross-files`-Route (→ DV_PROTOKOLL.md, tul-mime-Konzept)

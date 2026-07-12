# tul_s (vormals tools_nuc) – Projektregeln

Deployment-Zentrale für `tool.milan.how`. Hier laufen alle Panel-Module zusammen.

**Namenshinweis (Stand 2026-07-12):** Lokal umgezogen nach `SKRIPTE/tulkan/tul_s/` (vormals
`SKRIPTE+nuc/tools_nuc/`, zwischenzeitlich `SKRIPTE+nuc/tulkan/tul_s/`). Seit 2026-07-12 außerdem
mit `mkan` in **ein gemeinsames Git-Repo** gemerged (`tulkan/`, `tul_s/` und `mkan/` als
Unterverzeichnisse, jeweils mit vollständig erhaltener eigener Historie via `git subtree`) —
siehe Deployment-Abschnitt unten für den dadurch geänderten Push-Weg.

Das NUC-seitige Checkout-Verzeichnis heißt weiterhin `~/tul/tools_nuc/` (im `post-receive`-Hook
auf dem NUC hartcodiert, nicht Teil dieses Repos) — daher bleiben alle `tools_nuc/...`-Pfade in
`docker-compose.yml`, den Dockerfiles, `deploy-tul.sh` und `push-tul.sh` absichtlich unverändert.
Nur die lokale/Obsidian-Seite hat einen neuen Namen.

## Fork-Policy (wichtig)

Jedes Modul besteht historisch aus einem **Ur-Skript** (der ursprünglichen Vorlage) und einem
**Panel-Fork** hier in `tul_s/<modul>/` (NUC-seitig weiterhin `tools_nuc/<modul>/`).

**Seit 2026-07-12 liegen die Ur-Skripte als Referenzkopien direkt in `tul_s/_ur_skripte/<modul>/`**
(siehe `_ur_skripte/README.md` für Herkunft/Kopierdatum) — keine externen Pfadabhängigkeiten mehr
zu Projektordnern anderswo in `SKRIPTE/`. Es ist **keine Laufzeit-Abhängigkeit**: kein Code in
`tul_s` importiert oder liest die Ur-Skripte, sie sind reine Provenienz-Dokumentation.

| Modul | Ur-Skript (Referenzkopie) | Panel-Fork (hier, tatsächlich aktiv) |
|-------|---------------------------|----------------------------------------|
| trskr | `_ur_skripte/trskr/whisper_transkriplate.py` | `trskr/whisper_transkriplate_panel.py` |
| lern  | `_ur_skripte/lern/lernkarten_viewer_v3.26_lxw.py` | `lern/_tech/scripts/` (mehrere Dateien: csv_loader.py, card_creator.py, image_editor.py, pdf_grid.py, viewer_config.py — Logik wurde aufgeteilt, keine einzelne `_panel.py` mehr) |
| kurv  | `_ur_skripte/ofen/courbes.py` | `kurv/courbes_panel.py` |
| popt  | `_ur_skripte/pdfopt/pdfopt_vz.sh` | `popt/pdfopt_vz_panel.sh` |
| bild  | `_ur_skripte/bild/bildseiteerstellen.htm` | `bild/bildseiteerstellen_panel.htm` |

**Regel:** Panel-Erweiterungen (Flask-Subpath, live_editor, stop_event, Docker-Env-Checks u.ä.)
kommen ausschließlich in den Fork. Das Ur-Skript bleibt unangetastete Referenz.
`panel_server.py` importiert immer den Fork, nie das Ur-Skript.

Neues Modul: Ur-Skript-Referenzkopie nach `_ur_skripte/<name>/` ablegen → Fork unter
`<name>/<name>_panel.*` anlegen → Panel-Erweiterungen dort einarbeiten.

## Panel-Header-Standard

Jedes Modul folgt diesem Header-Aufbau (von links nach rechts):

```
[ ← Panel ]  [ DV ]  [ modul-spezifisch ]     Titel (Mitte)     [ ◑ Theme ]  [ ? ]  [ © ]  [ AB ⏏ ]
└── hdr-left (manuell) ────────────────────┘                    └── tlt-hdr-right (von tul-theme.js injiziert) ──┘
```

- **hdr-left**: `← Panel`-Link (immer), DV-Button (wenn tul-files.js aktiv), modulspezifische Schnellzugriffe
- **Mitte**: `<h1>` mit Modulname, `flex:1; text-align:center`
- **hdr-right**: wird automatisch von `tulTheme.init()` erzeugt — Theme, Hilfe, Lizenz, Nutzer-Badge + Logout
- **Ausnahme bild**: kein Header; rechtes Fixpanel + linkes Floating-Panel statt Header-Leiste

Technisch:
- `<div class="hdr-left">` im HTML, `.tlt-hdr-right` wird von tul-theme.js eingefügt
- `tulTheme.init({ subpath: _B, preset: tulTheme.PRESETS.<modul> })` — Preset für jedes Modul in tul-theme.js vorhanden
- `/logout` POST-Route in jedem panel_server.py erforderlich (löscht JWT-Cookie via `clear_token_cookie`)
- CSS-Basis: `:root`-Block mit `--bg/--bg2/--bg3/--acc/--border/--text/--muted` als Defaultwerte, werden von tul-theme.js überschrieben

## Module (aktuell)

```
tul_s/   (NUC-seitig: tools_nuc/)
├── trskr/    → tul.yourdomain.example/trskr    (Transkription)
├── lern/     → tul.yourdomain.example/lern     (Lernkarten)
├── kurv/     → tul.yourdomain.example/kurv     (Ofen-Kurven)
├── popt/     → tul.yourdomain.example/popt     (PDF-Optimierung)
├── bild/     → tul.yourdomain.example/bild     (Bildseite, Sonderaufbau)
├── nach/     → tul.yourdomain.example/nach     (HTML-Hoster: Singles + ZIP-Sets)
├── kal-trel/ → tul.yourdomain.example/kal-trel (Multi-Kanban, SQLite-Persistenz)
└── buch/     → tul.yourdomain.example/buch     (PDF-Shuffle: Seiten zusammenstellen)
```

## Deployment — WICHTIG, bitte lesen

**Der einzige korrekte Deploy-Weg ist git subtree push, ausgeführt vom Repo-Root aus**
(`tulkan/`, NICHT aus `tulkan/tul_s/` heraus — seit dem Merge mit mkan in ein gemeinsames Repo
2026-07-12 würde ein normaler `git push nuc master` aus Versehen den ganzen kombinierten Baum
inkl. mkan/ zum NUC pushen):

```bash
git add <dateien>            # Pfade relativ zum Repo-Root, z.B. tul_s/trskr/panel_server.py
git commit -m "..."
git subtree push --prefix=tul_s nuc master
```

Einfacher über den Wrapper (wechselt zuverlässig zum Repo-Root):
```bash
bash tul_s/push-nuc.sh
```

Der post-receive-Hook auf dem NUC (`~/tul.git/hooks/post-receive`) erledigt automatisch:
1. `git checkout -f` → Work Tree `~/tul/tools_nuc/` auf Stand bringen
2. `deploy-tul.sh` → nginx.conf aus `nginx_tul.conf` zusammenbauen + nginx reload
3. `docker compose up -d --build` → alle Container neu bauen und starten

**Niemals manuell SCP + deploy-tul.sh auf dem NUC ausführen** — das führt zu Zustand-Divergenz
zwischen lokalem Repo und NUC. Wenn doch mal ein Hotfix per SCP nötig ist, danach sofort committen
und pushen um alles wieder zu synchronisieren.

### nginx-Architektur (nicht verwechseln)

`nginx_tul.conf` im Repo ist **nicht** die aktive nginx-Config, sondern wird bei jedem
Deploy automatisch in `/home/milnuc/nexcloc/nginx.conf` (die zentrale Config des NUC,
die alle Dienste enthält) eingehängt. Das macht `deploy-tul.sh` via `nginx.conf.base`-Mechanismus.

**nginx proxy_pass — bekannte Falle:** Nie `proxy_pass http://$variable/;` (Variable + Trailing-Slash)
verwenden. nginx sendet dann alle Requests als `GET /` ans Backend, der Pfad geht verloren.
Korrektes Muster in `nginx_tul.conf`:
```nginx
set $upstream tool:port;
rewrite ^/tool(.*) $1 break;   # Prefix strippen
proxy_pass http://$upstream;   # kein Trailing-Slash → $uri wird unverändert verwendet
```

### static/ und hub

`tul-theme.js`, `tul-files.js`, `tul-theme.css` sind in `static/` und werden in den
tul-hub-Container gebacken (Dockerfile.hub: `COPY tools_nuc/static/ static/`). Jede Änderung
an `static/` erfordert einen hub-Rebuild — der passiert automatisch via `git subtree push --prefix=tul_s nuc master` (bzw. `bash tul_s/push-nuc.sh`).

Nie nur einzelne JS-Dateien per SCP auf den NUC schicken ohne danach zu pushen.

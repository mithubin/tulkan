# trskr – Testnotizen (Stand: 2026-06-17)

Diese Session hat den trskr-Panel von Grund auf refaktoriert und erweitert.
Deployment noch ausstehend; bitte vor dem Testen neu bauen.

## Build

**Obsolet seit lokalem Umzug nach `tulkan/tul_s/` (2026-07-12):** Der lokale Build unten setzt voraus,
dass der Ordner `tools_nuc` heißt (Build-Context `..` + `dockerfile: tools_nuc/Dockerfile.trskr` in
`docker-compose.yml`) — das ist jetzt nicht mehr der Fall. `docker-compose.yml` bleibt bewusst
unverändert, weil dieselben Pfade auch das NUC-seitige Checkout-Verzeichnis (`~/tul/tools_nuc/`)
referenzieren. Lokaler Test-Build so nicht mehr direkt möglich — stattdessen immer `git push nuc
master` (ohnehin der einzige offiziell korrekte Deploy-Weg, siehe `tul_s/CLAUDE.md`).

```bash
# Veraltet — funktioniert lokal nicht mehr, da der Ordner nicht mehr "tools_nuc" heißt:
docker compose -f docker-compose.yml build trskr
docker compose -f docker-compose.yml up -d trskr
```

Alternativ direkt:
```bash
docker build -f Dockerfile.trskr -t trskr ../.. 
```

## Was wurde geändert

| Datei | Änderung |
|-------|----------|
| `whisper_transkriplate_panel.py` | Komplett refaktoriert: CLI-Code (~950 Zeilen) entfernt, `stop_event` überall propagiert, Level 7 hinzugefügt, TRANSFORMERS_OFFLINE-Fix |
| `panel_server.py` | `_cleanup_upload_tmp()`, Stop-Event in Batch, `/posthoc` Batch-Support (`ph_paths_text`) |
| `panel.html` | Level-7-Pill in Haupt- und Post-hoc-Sektion; Post-hoc Batch-Modus (Textarea) |
| `Dockerfile.trskr` | `anthropic`-Paket ergänzt |

## Testfälle

### 1. Grundfunktion (Pflicht)
- [ ] URL eingeben (YouTube o.ä.) → Transkription startet, Log streamt, Transkript erscheint live
- [ ] Stop-Button während Transkription → Job bricht ab, kein Hänger
- [ ] Commit-Button → Transkription stoppt, bisherige Segmente werden weiterverarbeitet

### 2. Ausgabeformate
- [ ] `.txt`, `.srt`, `.vtt` alle angehakt → alle drei Dateien im Ausgabeordner
- [ ] Datei-Tabs erscheinen nach Abschluss korrekt

### 3. TOC + Zusammenfassung (API)
Voraussetzung: `ANTHROPIC_API_KEY` als Docker-Env-Variable gesetzt.
- [ ] TOC aktiviert → `*_toc_*.md` im Ausgabeordner
- [ ] Stufe 1–5 → kurze bis ausführliche Zusammenfassungen
- [ ] **Stufe 6 (Schwerpunkte)** → Stichwort-Feld erscheint, Zusammenfassung bezieht sich darauf
- [ ] **Stufe 7 (Tiefenanalyse)** → längere Ausgabe (~2 Seiten), Modell im Log sollte Sonnet sein (nicht Haiku)
- [ ] Kombination mehrerer Stufen → ein API-Call pro Sprache (im Log erkennbar: "Kombinierter Call")

### 4. Batch-Transkription
- [ ] Batch-Modus, zwei URLs zeilenweise → beide werden nacheinander transkribiert
- [ ] Stop während Batch → laufende Datei fertig, keine neue mehr gestartet

### 5. Nachbearbeitung – Einzelordner
- [ ] Ausgabe-Ordner-Dropdown erscheint, zeigt vorhandene Job-Ordner
- [ ] TOC oder Stufe 4 starten → Datei landet im gleichen Ordner

### 6. **Nachbearbeitung – Batch (neu)**
- [ ] Radio "Mehrere Ordner" wählen → Textarea erscheint
- [ ] Zwei Ordnernamen eintragen (je eine Zeile) → beide werden nachbearbeitet
- [ ] `# Kommentarzeile` wird übersprungen
- [ ] Leere Textarea → Fehlermeldung "mindestens einen Ordnernamen"

### 7. Helsinki-Übersetzung
- Im Docker **nicht installiert** (torch wäre >2 GB Image-Blocker).
- Erwartetes Verhalten: Fehlermeldung im Log, kein Crash.
- Lokal (außerhalb Docker) funktioniert es, wenn `transformers` + `sentencepiece` installiert sind.

## TODO – Crash-Resilienz (noch nicht implementiert)

**Ziel:** Nach einem Container-Absturz oder Panel-Neustart soll ein laufendes oder abgeschlossenes
Job-Ergebnis im Working-Verzeichnis erhalten bleiben und im Panel wieder auffindbar sein.

**Aktueller Stand:**
- Job-State liegt nur im Speicher (`_JOBS`-Dict in `panel_server.py`) — geht bei Neustart verloren
- Ausgabe-Dateien landen bereits persistent in `_OUTPUT_BASE` (z.B. `/data/output/<job-slug>/`)
- Frontend speichert `job_id` in `sessionStorage` — überlebt Browser-Reload, aber nicht Backend-Neustart

**Umsetzungsidee:**
1. `panel_server.py`: Nach jedem Job-Abschluss (in `_worker` finally-Block) eine kleine
   `job_meta.json` in den Ausgabeordner schreiben:
   ```json
   { "job_id": "…", "status": "done", "output_dir": "/data/output/…",
     "source": "…", "finished_at": 1234567890 }
   ```
2. Beim Start (`/sysinfo`-Call oder separater `/jobs/persisted`-Route) alle `job_meta.json`
   aus `_OUTPUT_BASE/*/job_meta.json` einlesen und als wiederherstellbare Jobs anbieten.
3. `panel.html`: Im "Ausgabe-Verwaltung"-Modal (oder Nachbearbeitung-Dropdown) einen Hinweis
   auf wiederherstellbare Jobs zeigen — Klick lädt Datei-Tabs des alten Jobs (`loadFiles(id)`).

**Abgrenzung:** Laufende Jobs nach Crash wirklich fortsetzen (Re-attach an laufende Transkription)
ist deutlich komplexer und wahrscheinlich nicht lohnenswert — Whisper muss von vorne starten.
Ziel ist nur: *abgeschlossene oder abgebrochene Ergebnisse sichtbar machen* ohne manuelles
Navigieren im Filesystem.

## Bekannte Lücken / nicht getestet

- Post-hoc Upload-Modus: UI vorhanden, Backend-Pfad unklar — nicht angefasst
- Nextcloud-Upload (NC-Ziel): unverändert, kein Test in dieser Session
- Helsinki im Docker: bewusst ausgelassen

## Env-Variablen im Container

```
DOCKER=1
SUBPATH=/trskr
PORT=5004
ANTHROPIC_API_KEY=<setzen in docker-compose.yml oder als Secret>
```

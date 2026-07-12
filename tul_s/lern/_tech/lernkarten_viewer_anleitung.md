# Lernkarten Panel – Anleitung

Ein browserbasiertes Werkzeug zum Erstellen, Drucken und Lernen mit Lernkarten aus CSV-Daten.

---

## 0. Panel starten / stoppen

```bash
# Standard: Port 5000, Browser öffnet sich automatisch
python3 panel_server.py

# Alternativer Port
python3 panel_server.py --port 5001

# Ohne Browser-Autostart
python3 panel_server.py --no-browser

# Stoppen
Ctrl+C
```

Browser öffnet sich automatisch auf `http://localhost:5000`.

### Port-Konflikt

```bash
# Was belegt Port 5000?
fuser 5000/tcp
lsof -i :5000

# Belegenden Prozess beenden und sofort neu starten
fuser -k 5000/tcp && python3 panel_server.py

# Oder anderen Port verwenden
python3 panel_server.py --port 5001
```

### Abhängigkeiten (einmalig installieren)

```bash
pip install flask pymupdf pillow
# Auf Ubuntu 23+ / Debian mit externem Paketmanagement:
pip install flask pymupdf pillow --break-system-packages
```

> **Zur pip-Meldung** bei der Installation: Wenn pip eine Zeile mit `ERROR: pip's dependency resolver ...` und dem Hinweis auf `types-flask-migrate` ausgibt, ist das **kein echter Fehler**. Das Paket `types-flask-migrate` (ein Typ-Stub eines anderen Projekts) erwartet `Flask-SQLAlchemy`, das hier nicht benötigt wird. Die entscheidende Zeile ist die letzte: `Successfully installed flask-...`. Der Server läuft normal.

---

## 1. Verzeichnisstruktur

```
lernkarten_panel/
├── panel_server.py          Einstiegspunkt – hier starten
│
├── csv/                     Eingabe: CSV-Dateien ablegen
├── bilder/                  Hintergrundbilder für Karten
├── fonts/                   TTF-Schriften
├── karten-pdfs/             Ausgabe: fertige Karten-PDFs
│   └── scores/              Lernfortschritt-Logs des Viewers
├── druck_pdf/               Ausgabe: Druckraster-PDFs
│
└── _tech/                   Technische Dateien (nicht direkt bearbeiten)
    ├── card_templates/      JSON-Templates (default, eigene, ...)
    ├── scripts/             Python-Module (CSV, PDF, Bildeditor, Viewer)
    ├── static/              CSS, JS
    └── templates/           HTML-Templates
```

---

## 2. Übersicht (Tab)

Zeigt alle fertigen Karten-PDFs in `karten-pdfs/` mit:
- Dateiname und Karten-Anzahl
- Erkannte Level (falls vorhanden)
- Download-Link und Drucken-Link

---

## 3. Viewer (Tab)

Browser-basierter Vollbild-Viewer. Kein externes Programm nötig.

### 3.1 Konfiguration

**PDF wählen:** Alle PDFs aus `karten-pdfs/` werden aufgelistet. Klick wählt das PDF aus.

**Level-Konfiguration:**
- *Auto-erkennen*: scannt das PDF nach `=lev:`-Markern (die beim Erstellen aus der CSV eingebettet werden) und legt Level automatisch an.
- Level können manuell ergänzt, umbenannt, verschoben oder gelöscht werden.
- Seitenangaben sind 1-basiert, paarweise (Seite 1+2 = Karte 1).
- *Speichern* schreibt in `karten-pdfs/config.json`.

**Session:**
- *Level-Filter*: „Alle" oder einzelne/mehrere Level auswählen.
- *Reihenfolge*: fest oder zufällig.
- *Modus*: Manuell oder Autopilot.
- *Autopilot-Timing*: Anzeigedauer für Frage und Antwort (min–max in Sekunden).

**▶ Starten** öffnet den Player in einem neuen Tab im Vollbild.

### 3.2 Player-Tastatur

| Taste | Aktion |
|---|---|
| `Space` / `→` | Frage → Antwort → nächste Karte |
| `←` | Zurück (Antwort → Frage → vorherige Antwort) |
| `j` / `+` | Karte als **richtig** markieren, weiter |
| `n` / `−` | Karte als **falsch** markieren, weiter |
| `0` | **Neutral**, weiter |
| `P` | Autopilot Pause / Weiter |
| `T` | Modus wechseln: Autopilot ↔ Manuell |
| `Q` / `Esc` | Session beenden |

**Statusleiste** (oben): aktueller Fortschritt, Bewertungsstand (✓ ✗ ○).  
**Timer-Balken** (unten): nur im Autopilot, zeigt verbleibende Anzeigezeit.

### 3.3 Score-Speicherung

Am Ende der Session erscheint ein Overlay mit Ergebnis-Zusammenfassung.  
Name eingeben (optional) → *Speichern & Schließen* schreibt ein Log nach `karten-pdfs/scores/`.

Log-Format: `<pdf-name>_<datum>_<name>.log`, einfaches Textformat, einsehbar über den Viewer-Tab.

---

## 4. Erstellen (Tab)

Erzeugt Lernkarten-PDFs aus einer CSV-Datei.

### 4.1 Ablauf

1. **CSV laden:** Datei hochladen oder aus `csv/` wählen. Pflicht-Spalten: `LEVEL;THEMA;FRAGE;ANTWORT` (Semikolon-getrennt).
2. **Template:** Vorlage laden oder Parameter anpassen. *Speichern* überschreibt, *Als neu…* legt eine neue an.
3. **Kartenmaße:** Breite/Höhe in mm, Rand, Themafeld-Breite, Zeilenabstände.
4. **Fragekarte / Antwortkarte:** Hintergrundbild, Schrift, Textfarbe, optionaler Schatten. Pro Textfeld (Thema, Frage, Antwort, Wiederholung) zusätzlich **Hintergrundfarbe + Deckkraft** — 0 % = unsichtbar, 100 % = opak. ✎ öffnet den Bildeditor.
5. **PDF erstellen:** Dateiname eingeben, *PDF erstellen*. Das PDF landet in `karten-pdfs/` und erscheint sofort in der Übersicht.

### 4.2 CSV-Format

```
LEVEL;THEMA;FRAGE;ANTWORT
=lev: Grundlagen;;;
;Variablen;Was ist eine Variable?;Ein benannter Speicherplatz.
;Variablen;Typen in Python?;int, float, str, bool, …
=lev: Fortgeschritten;;;
;Funktionen;Was macht *args?;Beliebig viele Positionsargumente.
```

- `=lev: Name` in der LEVEL-Spalte markiert einen Level-Wechsel; diese Zeile erzeugt keine Karte.
- THEMA wird solange weitergegeben bis ein neues gesetzt wird (carry-forward).
- Semikolon als Trennzeichen; BOM-sicher (`utf-8-sig`).

---

## 5. Drucken (Tab)

Erzeugt ein druckfertiges Raster-PDF für beidseitigen Druck.

1. PDF aus der Übersicht wählen.
2. Vorlage wählen (z. B. *A4 hoch 2×7*) oder Parameter manuell setzen: Papier, Spalten, Zeilen, Innenabstand in mm.
3. *Druck-PDF erzeugen* → herunterladen → Drucker: **Duplex, lange Kante** → ausschneiden.

Druckdateien landen in `druck_pdf/`.

---

## 6. Bildeditor

Öffnet per ✎ neben der Bildauswahl in der Erstellen-Seite.

- **Links:** Vorschau mit Crop-Rahmen im Kartenratio des aktiven Templates. *Ausschnitt-Größe* skaliert den Crop-Bereich (kleiner = mehr Zoom). X/Y-Versatz verschiebt den Ausschnitt.
- **Rechts:** Wertekurven für Gesamt (RGB) und Einzelkanäle (R/G/B). Punkt ziehen: verschieben. Doppelklick: löschen. Klick auf freie Stelle: Punkt hinzufügen. Sättigungs-Regler.
- **Speichern:** Das Bild wird auf das Kartenmaß bei 200 PPI resampled (Lanczos) und in `bilder/` gespeichert. Die Dropdown-Auswahl aktualisiert sich automatisch.

---

## 7. Optik

◑-Button rechts oben öffnet das Theme-Modal:
- **Schnell-Auswahl:** 6 Farbschemata (Panel, Indigo, Emerald, Rose, Amber, Lila).
- **Grundton:** Basis-Farbe für Hintergrund, Flächen, Rahmen. Dunkler Grundton = Dunkel-Modus, heller = Hell-Modus.
- **Akzentfarbe:** Buttons, Links, aktive Navigation.
- **Ebenen-Tiefe:** Kontrast-Abstufung zwischen den Hintergrund-Ebenen.
- Einstellungen werden im Browser (localStorage) **und** server-seitig (`_tech/panel_theme.json`) gespeichert – bleiben also auch bei Browserwechsel erhalten.

---

## 8. Problemlösung

| Problem | Lösung |
|---|---|
| `ModuleNotFoundError: fitz` | `pip install pymupdf` |
| `ModuleNotFoundError: PIL` | `pip install pillow` |
| `ModuleNotFoundError: flask` | `pip install flask` |
| Port 5000 belegt | `fuser -k 5000/tcp` oder `--port 5001` |
| Bild erscheint nicht im Dropdown | Datei in `bilder/` ablegen; Bildeditor aktualisiert automatisch nach Speichern |
| PDF nicht in Viewer-Liste | PDF muss in `karten-pdfs/` liegen |
| Level nicht erkannt | CSV muss `=lev: Name` in der LEVEL-Spalte enthalten; PDF muss aus diesem Panel erstellt worden sein |
| pip meldet `ERROR: dependency resolver …` bei Installation | Kein echter Fehler, siehe Abschnitt 0 |

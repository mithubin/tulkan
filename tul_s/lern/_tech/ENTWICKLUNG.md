# Lernkarten Panel – Entwicklerdoku

## Projektstruktur

```
lernkarten_panel/
├── panel_server.py              Flask-Server (Einstiegspunkt)
│
├── csv/                         Eingabe: CSV-Quelldateien
├── bilder/                      Hintergrundbilder für Karten
├── fonts/                       TTF-Fonts
├── karten-pdfs/                 Ausgabe: fertige Karten-PDFs
│   ├── config.json              Viewer-Config (Level, letzte Session, je PDF per Hash)
│   └── scores/                  Lernfortschritt-Logs
├── druck_pdf/                   Ausgabe: Druckraster-PDFs
│
└── _tech/
    ├── requirements.txt
    ├── ENTWICKLUNG.md           diese Datei
    ├── lernkarten_viewer_anleitung.md   Benutzer-Anleitung
    ├── panel_theme.json         gespeichertes Theme (browserübergreifend)
    ├── card_templates/          JSON-Karten-Templates
    ├── _tmp/                    Temporäre Dateien
    ├── scripts/
    │   ├── card_creator.py      PDF-Rendering (PyMuPDF)
    │   ├── csv_loader.py        CSV-Einlesen und Validierung
    │   ├── pdf_grid.py          Druckraster-Logik
    │   ├── image_editor.py      Bildbearbeitung (Pillow)
    │   └── viewer_config.py     Viewer: Config, Level-Erkennung, Karten-Selektion
    ├── static/
    │   ├── style.css
    │   ├── panel.js             UI-Logik + Theme-System
    │   ├── image_editor.js      Bildeditor + Modals
    │   └── viewer_play.js       Browser-Viewer Player-Logik
    └── templates/
        ├── base.html            Nav, Modals (Anleitung, Lizenz, Theme, Bildeditor)
        ├── index.html           Übersicht (PDFs, Download, Drucken)
        ├── viewer.html          Viewer-Konfig-Seite
        ├── viewer_play.html     Viewer-Player (standalone, kein base.html)
        ├── print.html           Druck-Seite
        └── create.html          Erstellungs-Seite
```

## Abhängigkeiten

```bash
pip install flask pymupdf pillow
# oder:
pip install -r _tech/requirements.txt
```

## Routen-Übersicht

| Methode | Pfad | Funktion |
|---------|------|----------|
| GET | `/` | Übersicht (PDFs + Level-Info) |
| GET | `/viewer` | Viewer-Konfig-Seite |
| GET | `/viewer/play` | Viewer-Player (standalone) |
| GET | `/print` | Druck-Seite |
| GET | `/create` | Erstellungs-Seite |
| GET | `/api/viewer/pdfs` | PDF-Liste mit Config aus config.json |
| POST | `/api/viewer/detect-levels` | Level aus PDF-Text erkennen |
| POST | `/api/viewer/save-levels` | Level in config.json speichern |
| POST | `/api/viewer/session` | Karten-Liste berechnen + Session speichern |
| GET | `/api/viewer/page/<pdf>/<n>` | PDF-Seite als JPEG (2×-Skalierung, gecacht) |
| POST | `/api/viewer/score` | Score-Log schreiben |
| GET | `/api/viewer/scores` | Score-Log-Liste |
| GET | `/api/viewer/score-read/<file>` | Score-Log-Inhalt |
| GET | `/api/theme` | Theme aus panel_theme.json laden |
| POST | `/api/theme` | Theme in panel_theme.json speichern |
| GET | `/api/pictures/list` | Bild-Liste aus bilder/ |
| POST | `/api/pictures/edit` | Bild bearbeiten (Crop + Kurven + Lanczos) |
| POST | `/api/print/build` | Druckraster-PDF erzeugen |
| POST | `/api/print/preview` | Druckraster-Vorschau (PNG, Base64) |
| GET | `/api/print/download/<file>` | Druckraster-PDF herunterladen |
| POST | `/api/csv/validate` | CSV als Upload prüfen |
| POST | `/api/csv/load-server` | CSV aus csv/ laden |
| GET | `/api/template/load/<name>` | Template-JSON laden |
| POST | `/api/template/save/<name>` | Template-JSON speichern |
| POST | `/api/preview/card` | Kartenvorschau (Base64-PNGs) |
| POST | `/api/create/pdf` | Karten-PDF erzeugen |
| GET | `/api/create/download/<file>` | Karten-PDF herunterladen |
| GET | `/api/cards/download/<file>` | Karten-PDF herunterladen (Übersicht) |

## Viewer (`viewer_config.py` + `viewer_play.js`)

### Config-Format (`karten-pdfs/config.json`)

```json
{
  "last_used_hash": "sha256...",
  "pdfs": {
    "<sha256>": {
      "filename": "karten_xyz.pdf",
      "levels": [
        {"name": "Grundlagen", "start": 1, "end": 40},
        {"name": "Fortgeschritten", "start": 41, "end": 80}
      ],
      "last_session": {
        "level_filter": ["Grundlagen"],
        "randomize": true
      }
    }
  }
}
```

### Level-Erkennung

`detect_levels()` scannt jede PDF-Seite nach dem Regex `lev:\s*([^=\n]+)`.
Marker werden beim Erstellen aus `=lev: Name` in der CSV in die Karten eingebettet.
Gefundene Marker → Seitenbereiche per Differenz (letztes Level bis Seitenende).

### Karten-Selektion (`select_cards`)

Jede Karte = zwei aufeinanderfolgende Seiten (ungerade = Frage, gerade = Antwort).
Level-Seitenbereich → Karten-Index: `start_card = (start + 1) // 2`, `end_card = end // 2`.

### Session-Flow (Browser)

1. `viewer.html` speichert Config in `sessionStorage` → öffnet `/viewer/play`
2. `viewer_play.js` liest `sessionStorage`, ruft `POST /api/viewer/session` → erhält geordnete Karten-Liste
3. Player lädt Seiten via `GET /api/viewer/page/<pdf>/<n>` (JPEG, Browser-Cache)
4. Am Ende: Score-Overlay → `POST /api/viewer/score`

## Theme-System (`panel.js`)

Chrome-Farbe (Grundton) → alle CSS-Variablen per HSL-Ableitung:

| Variable | Bedeutung |
|---|---|
| `--bg` | Body-Hintergrund (dunkler als Chrome) |
| `--surface` | Karten-Flächen (= Chrome-Helligkeit) |
| `--border` | Rahmen (etwas heller) |
| `--text` | Haupttext (nahe Weiß) |
| `--muted` | Sekundärtext |
| `--accent` | Akzent (frei gewählt) |

Hell-/Dunkel-Modus wird aus der Luminanz der Chrome-Farbe bestimmt (< 110 → dunkel).
Persistenz: localStorage (schnell, kein Flackern) + `_tech/panel_theme.json` (browserübergreifend via Nextcloud).

## CSV-Format

Trennzeichen: Semikolon (automatisch erkannt). BOM-sicher (`utf-8-sig`).
Pflicht-Spalten: `LEVEL`, `THEMA`, `FRAGE`, `ANTWORT`.

Level-Wechsel-Marker:
```
=lev: Grundlagen
```
THEMA carry-forward: leer = letztes gesetztes THEMA übernehmen.

## Template-System

JSON-Dateien in `card_templates/`. Wichtige Felder:

```json
{
  "card_width_mm": 180, "card_height_mm": 80,
  "margin_mm": 4, "topic_width_mm": 10,
  "line_spacing": 1.2, "answer_line_spacing": 1.2,
  "front_bg": "bild.jpg", "back_bg": "",
  "topic_style": {
    "font_path": "", "size": 9, "color": [1,1,1],
    "shadow_offset": [1,1], "shadow_color": [0,0,0],
    "bg_color": [0,0,0], "bg_alpha": 0.0
  },
  "question_style": { ... },
  "answer_style":   { ... },
  "repeat_style":   { ... }
}
```

`bg_color` (RGB 0–1) und `bg_alpha` (0–1, default 0 = unsichtbar) sind in jedem Stil-Objekt vorhanden. Alte Templates ohne diese Felder funktionieren unverändert.

## Rendering-Invarianten (`card_creator.py`)

**Font-Alias-Kollision:** Zwei TTFs auf einer Seite brauchen verschiedene Alias-Namen.
`_font_kw()` erzeugt `"f" + format(hash(pfad) & 0xFFFFFF, "x")`.

**Höhenmessung:** `insert_textbox` auf 10000pt-Probeseite; verwendete Höhe = `10000 − ret`.

**Trailing-Zeilenabstand:** Visuelle Höhe für Zentrierung:
```python
visual_h = mh - fs * (line_spacing - 1.0)
```

**Rotierter Text (Thema-Feld):** `rotate=90` → Dimensionen tauschen für `_fit_size`. Text-Block wird in physischer X-Richtung zentriert mit ≥ 2 mm Mindestabstand zu beiden Streifenrändern. Schriftgröße wird auf volle Streifenbreite gefittet, Zentrierung durch `x0`-Versatz.

**Innenabstand:** `_render_normal` hat Parameter `pad` (pt). Fragekarte nutzt `pad=2*MM` (alle Seiten). Antwortkarte berechnet `inner_x/y/w/h` mit 2 mm links/rechts/oben direkt in `_add_answer_page`.

**Feldhintergründe:** `_draw_field_bg(page, rect, style)` zeichnet vor dem Text ein gefülltes Rect wenn `style.bg_alpha > 0`. Hintergrund immer auf vollem Feldrect; auf der Antwortkarte überlagert der Wiederholungs-Hintergrund den Antwort-Hintergrund im unteren Bereich.

**Antwortkarte – Reihenfolge:** Erst Frage-Wiederholung fitten (max 25 % des inneren Feldes), dann Antwort auf Rest, dann Block ab `inner_y` (= Rand + 2 mm) zentrieren.

## Bildeditor (`image_editor.py` + `image_editor.js`)

**Backend:** Crop auf Kartenratio + Versatz → Lanczos-Resize auf Kartenmaß × 200 PPI → Sättigung (`ImageEnhance.Color`) → per-Kanal-LUT (`band.point(lut)`).

**Frontend:** Monotone kubischer Spline (Fritsch-Carlson) → 256-Werte-LUT. Kanal-Kurven werden mit RGB-Gesamtkurve komponiert. Nach Speichern: Dropdown-Reload via `GET /api/pictures/list` + `previewCard()`.

## Druckraster (`pdf_grid.py`)

Zellgröße aus Kartenverhältnis der ersten Quelldatei-Seite (proportionserhaltend).
Duplex: Rückseiten spiegeln Spaltenreihenfolge horizontal (`back_col = (cols−1) − col`).

## Neues Template anlegen

```bash
cp _tech/card_templates/default.json _tech/card_templates/mein_template.json
```
Dann in Erstellen → Template-Dropdown → auswählen → anpassen → speichern.

## Server neu starten

```bash
fuser -k 5000/tcp && python3 panel_server.py
```

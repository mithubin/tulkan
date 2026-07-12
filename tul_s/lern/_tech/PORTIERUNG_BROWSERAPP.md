# Entwurf: Lernkarten-Panel als reine Browser-App

Kontext: Einsatz auf Firmenrechnern ohne Installationsrechte.
Stand: Gesprächsnotiz 2026-05-20, noch nicht umgesetzt.

## Ausgangslage

Das aktuelle Panel läuft als Flask-Server (Python) + Browser-Frontend.
Auf Firmenrechnern ist Python oft nicht erlaubt, nginx ebenso, USB-Executables
werden häufig durch AppLocker/Endpoint-Protection geblockt.

Alternative: reine HTML/CSS/JS-App, die der Browser direkt öffnet – kein Prozess,
keine Policy-Frage, Datei vom USB-Stick oder Netzlaufwerk.

## Was geht ohne Server

- Kartenerstellung + Vorschau (Canvas-Rendering läuft komplett in JS)
- CSV-Import (JS-Parser)
- Persistenz via `localStorage` / `IndexedDB`
- PDF-Export: `jsPDF`-Bibliothek oder Browser-Druckdialog (Strg+P → Als PDF)
- Vollständige UI mit Tabs, Theme, Schieberegler etc.

## Was sich ändert

- **Tkinter-Viewer entfällt** → Ersatz: Fullscreen-Browser-Modus (F11),
  Autopilot-Logik in JS portierbar
- **Bilder**: kein Serverpfad mehr → Bilder per `<input type="file">` laden
  und als Base64 in IndexedDB speichern; oder aus festem USB-Unterordner
  via File System Access API (nur Chromium: Chrome, Edge)
- **Datei-Export**: Kartensätze als JSON-Download, reimportierbar
- **Kein zentraler Ablageort** – jeder Rechner hat seinen eigenen localStorage;
  Sync über JSON-Export/Import manuell

## Technischer Stack

| Komponente | Lösung |
|---|---|
| UI-Framework | Vanilla JS oder kleines Bundle (kein npm-Build nötig) |
| Canvas-Rendering | wie jetzt, direkt portierbar |
| Persistenz | IndexedDB (via idb-Bibliothek, ~3 KB) |
| PDF | jsPDF (CDN oder lokal im USB-Ordner) |
| Bilder | File System Access API (Chromium) oder Base64-Embed |

Alle Bibliotheken können als lokale Dateien auf dem USB-Stick liegen –
kein CDN-Zugriff nötig.

## Portierungsaufwand (grob)

- Canvas-Renderer und Vorschau-Logik: direkt übertragbar (~1–2h)
- Persistenz-Schicht neu bauen (IndexedDB statt Dateiablage): ~2–3h
- Autopilot/Viewer in JS: ~2h
- PDF-Export: ~1h
- Gesamt: überschaubar, kein Neubau von Grund auf

## Offene Fragen vor Umsetzung

- Welche Browser stehen auf dem Zielrechner zur Verfügung? (File System Access API nur Chromium)
- Soll der Kartensatz-Stand zwischen Rechnern synchronisiert werden, oder reicht lokaler Stand?
- Druckvorschau: reicht Browser-Druckdialog, oder wird pixelgenaue PDF-Ausgabe wie jetzt gebraucht?

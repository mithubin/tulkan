# Ur-Skripte — Provenienz-Referenz

Historische Vorlagen, von denen die Panel-Fork-Module in `tul_s/<modul>/` ursprünglich einmal
kopiert wurden (siehe Fork-Policy in `../CLAUDE.md`). **Keine Laufzeit-Abhängigkeit** — kein
Code in `tul_s` importiert oder liest diese Dateien. Reine Referenzkopien, damit `tulkan`
autonom von externen Projektordnern ist.

Kopiert am 2026-07-12, jeweils Einzeldatei (nicht die vollständigen Ur-Projektordner, die
zusätzlich große Test-/Ausgabedaten enthalten, ~150–320 MB pro Ordner).

| Modul | Datei hier | Ursprünglicher Pfad (vor dem Kopieren) |
|-------|-----------|------------------------------------------|
| trskr | `trskr/whisper_transkriplate.py` | `SKRIPTE/videotranskriplate/whisper_transkriplate.py` |
| lern  | `lern/lernkarten_viewer_v3.26_lxw.py` | `SKRIPTE/skul-skripts/lernkarten_panel/lernkarten_viewer_v3.26_lxw.py` |
| bild  | `bild/bildseiteerstellen.htm` | `SKRIPTE/skul-skripts/bildseite_erstellen/bildseiteerstellen.htm` |
| kurv  | `ofen/courbes.py` | `SKRIPTE/x_mehr_skripte/ofendatenzukurven/courbes.py` |
| popt  | `pdfopt/pdfopt_vz.sh` | `SKRIPTE/x_mehr_skripte/pdf_opt_vz/pdfopt_vz.sh` |

Die Ur-Projektordner selbst (mit ihren jeweiligen Test-/Ausgabedaten) bleiben unverändert an
ihrem bisherigen Ort — nur diese eine Referenzdatei pro Modul wurde hierher übernommen.

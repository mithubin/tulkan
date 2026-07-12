"""
CSV-Einlesen und Validierung für Lernkarten.
Erwartet Spalten: LEVEL, THEMA, FRAGE, ANTWORT (optional: HUMOR)
Level-Wechsel-Marker: =lev: <Name> in der LEVEL-Spalte
Trennzeichen: Semikolon oder Komma, wird automatisch erkannt.
"""

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


REQUIRED_COLUMNS = {"LEVEL", "THEMA", "FRAGE", "ANTWORT"}


@dataclass
class Card:
    level: str
    thema: str
    frage: str
    antwort: str
    humor: str = ""


@dataclass
class LoadResult:
    cards: list[Card] = field(default_factory=list)
    levels: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def _detect_delimiter(sample: str) -> str:
    # Nur die erste Zeile (Header) prüfen – Zellinhalte können viele Kommas enthalten
    # und würden die Zählung verfälschen.
    first_line = sample.lstrip().split("\n")[0]
    return ";" if ";" in first_line else ","


def load_csv(path: Path) -> LoadResult:
    result = LoadResult()

    try:
        raw = path.read_text(encoding="utf-8-sig")
    except Exception as e:
        result.errors.append(f"Datei nicht lesbar: {e}")
        return result

    delimiter = _detect_delimiter(raw[:2000])
    reader = csv.DictReader(io.StringIO(raw), delimiter=delimiter)

    # Spalten prüfen
    if reader.fieldnames is None:
        result.errors.append("CSV hat keine Kopfzeile.")
        return result

    cols = {c.strip().upper() for c in reader.fieldnames}
    missing = REQUIRED_COLUMNS - cols
    if missing:
        result.errors.append(f"Fehlende Spalten: {', '.join(sorted(missing))}")
        return result

    # Feldname-Mapping (case-insensitive)
    name_map = {c.strip().upper(): c for c in reader.fieldnames}

    current_level = ""
    current_thema = ""
    seen_levels = []

    for row_num, row in enumerate(reader, start=2):
        raw_level = (row.get(name_map["LEVEL"]) or "").strip()
        thema_raw = (row.get(name_map["THEMA"]) or "").strip()
        thema = thema_raw if thema_raw else current_thema
        if thema_raw:
            current_thema = thema_raw
        frage = (row.get(name_map["FRAGE"]) or "").strip()
        antwort = (row.get(name_map["ANTWORT"]) or "").strip()
        humor = (row.get(name_map.get("HUMOR", ""), "") or "").strip()

        # Level-Wechsel-Marker
        if raw_level.startswith("=lev:"):
            current_level = raw_level[5:].strip()
            if current_level not in seen_levels:
                seen_levels.append(current_level)
            raw_level = ""  # kein separater Eintrag, nur Marker

        if not frage and not antwort:
            continue  # Leerzeilen überspringen

        if not frage:
            result.warnings.append(f"Zeile {row_num}: Frage leer – übersprungen.")
            continue
        if not antwort:
            result.warnings.append(f"Zeile {row_num}: Antwort leer – übersprungen.")
            continue

        result.cards.append(Card(
            level=current_level,
            thema=thema,
            frage=frage,
            antwort=antwort,
            humor=humor,
        ))

    result.levels = seen_levels

    if not result.cards:
        result.errors.append("Keine gültigen Karten gefunden.")

    return result

"""
Viewer-Konfiguration: karten-pdfs/config.json lesen/schreiben,
Level-Erkennung aus PDF, Karten-Selektion.
"""
import hashlib
import json
import random
import re
from pathlib import Path
from typing import Optional

import fitz


# ── Config-Datei ──────────────────────────────────────────────────────────────

def _cfg_path(cards_dir: Path) -> Path:
    return cards_dir / "config.json"


def _load(cards_dir: Path) -> dict:
    p = _cfg_path(cards_dir)
    if p.exists():
        try:
            return json.loads(p.read_text("utf-8"))
        except Exception:
            pass
    return {"last_used_hash": None, "pdfs": {}}


def _save(cards_dir: Path, data: dict):
    _cfg_path(cards_dir).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), "utf-8"
    )


def pdf_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ── PDF-Liste ─────────────────────────────────────────────────────────────────

def list_pdfs(cards_dir: Path) -> list:
    cfg = _load(cards_dir)
    changed = False
    result = []
    for pdf_path in sorted(cards_dir.glob("*.pdf")):
        h = pdf_hash(pdf_path)
        with fitz.open(str(pdf_path)) as doc:
            page_count = doc.page_count
        stored = cfg["pdfs"].setdefault(h, {})
        # Auto-Erkennung: einmalig beim ersten Auftauchen ohne gespeicherte Level
        if "levels" not in stored:
            detected = detect_levels(pdf_path)
            stored["levels"] = detected
            stored["filename"] = pdf_path.name
            changed = True
        result.append({
            "filename": pdf_path.name,
            "hash": h,
            "page_count": page_count,
            "card_count": page_count // 2,
            "levels": stored.get("levels"),
            "last_session": stored.get("last_session"),
        })
    if changed:
        _save(cards_dir, cfg)
    return result


# ── Level-Erkennung ───────────────────────────────────────────────────────────

def detect_levels(pdf_path: Path) -> Optional[list]:
    """Scannt PDF nach =lev:-Markern, gibt Level-Liste zurück oder None."""
    with fitz.open(str(pdf_path)) as doc:
        page_count = doc.page_count
        markers = []
        for i in range(page_count):
            text = doc[i].get_text().replace("\n", " ").replace("\r", " ")
            m = re.search(r'lev:\s*([^=\n]+)', text, re.IGNORECASE)
            if m:
                markers.append((i + 1, m.group(1).strip()))  # 1-basiert
    if not markers:
        return None
    levels = []
    for i, (start, name) in enumerate(markers):
        end = markers[i + 1][0] - 1 if i < len(markers) - 1 else page_count
        levels.append({"name": name, "start": start, "end": end})
    return levels


# ── Config speichern ──────────────────────────────────────────────────────────

def save_levels(cards_dir: Path, h: str, levels: Optional[list]):
    data = _load(cards_dir)
    data["pdfs"].setdefault(h, {})["levels"] = levels
    _save(cards_dir, data)


def save_session(cards_dir: Path, h: str, filename: str,
                 page_count: int, levels: Optional[list], last_session: dict):
    data = _load(cards_dir)
    entry = data["pdfs"].setdefault(h, {})
    entry["filename"] = filename
    entry["levels"] = levels
    entry["last_session"] = last_session
    data["last_used_hash"] = h
    _save(cards_dir, data)


# ── Karten-Selektion ──────────────────────────────────────────────────────────

def select_cards(page_count: int, levels: Optional[list],
                 level_filter: list, randomize: bool) -> list:
    """Gibt geordnete Liste von 1-basierten Karten-Nummern zurück."""
    card_count = page_count // 2
    if not levels or not level_filter:
        cards = list(range(1, card_count + 1))
    else:
        cards = []
        for lev in levels:
            if lev["name"] in level_filter:
                start_card = (lev["start"] + 1) // 2
                end_card = lev["end"] // 2
                cards.extend(range(start_card, end_card + 1))
    if randomize:
        random.shuffle(cards)
    return cards

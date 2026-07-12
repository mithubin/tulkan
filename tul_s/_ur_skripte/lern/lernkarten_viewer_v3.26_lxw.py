#!/usr/bin/env python3
"""
Flashcard Viewer - Präsentationstool für Lernkarten aus PDF
"""

import json
import hashlib
import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import tkinter as tk
from tkinter import messagebox
import fitz  # PyMuPDF
import random


class Config:
    """Verwaltet die config.json mit allen bekannten PDFs"""
    
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.data = self._load()
    
    def _load(self) -> dict:
        """Lädt die Config oder erstellt eine neue"""
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"last_used_hash": None, "pdfs": {}}
    
    def save(self):
        """Speichert die Config"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, indent=2, fp=f)
    
    def get_pdf_config(self, pdf_hash: str) -> Optional[dict]:
        """Gibt die Config für ein PDF zurück"""
        return self.data["pdfs"].get(pdf_hash)
    
    def set_pdf_config(self, pdf_hash: str, filename: str, size: int, levels: Optional[List[dict]], last_session: Optional[dict] = None):
        """Speichert oder aktualisiert die Config für ein PDF"""
        # Behalte existierende last_session wenn keine neue übergeben wurde
        existing_last_session = None
        if pdf_hash in self.data["pdfs"]:
            existing_last_session = self.data["pdfs"][pdf_hash].get("last_session")
        
        config = {
            "filename": filename,
            "size": size,
            "levels": levels
        }
        
        # Setze last_session: neue hat Vorrang, sonst existierende behalten
        if last_session is not None:
            config["last_session"] = last_session
        elif existing_last_session is not None:
            config["last_session"] = existing_last_session
        
        self.data["pdfs"][pdf_hash] = config
        self.data["last_used_hash"] = pdf_hash
        self.save()
    
    def clear_levels(self, pdf_hash: str):
        """Entfernt die Level-Konfiguration für ein PDF"""
        if pdf_hash in self.data["pdfs"]:
            self.data["pdfs"][pdf_hash]["levels"] = None
            self.save()


class PDFManager:
    """Verwaltet PDF-Dateien und deren Metadaten"""
    
    @staticmethod
    def calculate_hash(pdf_path: Path) -> str:
        """Berechnet SHA256 Hash eines PDFs"""
        sha256 = hashlib.sha256()
        with open(pdf_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    @staticmethod
    def find_pdfs(directory: Path) -> List[Path]:
        """Findet alle PDF-Dateien im Verzeichnis (rekursiv)"""
        return sorted(directory.rglob("*.pdf"))
    
    @staticmethod
    def get_page_count(pdf_path: Path) -> int:
        """Gibt die Seitenzahl des PDFs zurück"""
        doc = fitz.open(pdf_path)
        count = len(doc)
        doc.close()
        return count


class LevelConfigurator:
    """Konfiguriert die Level für ein PDF"""
    
    @staticmethod
    def configure(page_count: int, pdf_path: Optional[Path] = None) -> Optional[List[dict]]:
        """Interaktive Level-Konfiguration"""
        card_count = page_count // 2
        print(f"\nPDF hat {page_count} Seiten ({card_count} Karten)")
        
        # Warnung bei ungerader Seitenzahl
        if page_count % 2 != 0:
            print(f"⚠️  Warnung: Ungerade Seitenzahl - letzte Seite wird ignoriert!")
        
        # Versuche automatische Level-Erkennung
        auto_levels = None
        if pdf_path:
            auto_levels = LevelConfigurator._detect_levels_from_pdf(pdf_path, page_count)
            if auto_levels:
                print(f"\n✓ Level automatisch erkannt:")
                for level in auto_levels:
                    cards = (level['end'] - level['start'] + 1) // 2
                    print(f"   {level['name']:15s} Seite {level['start']}-{level['end']} ({cards} Karten)")
                
                use_auto = input("\nAutomatische Level verwenden? [J/n]: ").strip().lower()
                if use_auto != 'n':  # Enter oder 'j' = ja
                    return auto_levels
        
        use_levels = input("\nLevel manuell konfigurieren? [N/j]: ").strip().lower()
        if use_levels != 'j':  # Enter oder alles außer 'j' = nein
            print("\n→ Alle Karten ohne Level-Unterscheidung")
            return None
        
        levels = []
        level_num = 1
        last_card = 0
        
        while True:
            if level_num == 1:
                prompt = "Erster Level-Sprung ab Karte: "
            else:
                prompt = "Weiterer Level-Sprung ab Karte: "
            
            user_input = input(prompt).strip()
            
            # Leere Eingabe oder nicht-numerisch = fertig
            if not user_input or not user_input.isdigit():
                break
            
            card = int(user_input)
            
            # Validierung: Muss größer als letzter Sprung sein
            if card <= last_card:
                print(f"  ✗ Fehler: Karte muss größer als {last_card} sein (nächster Sprung)")
                continue
            
            # Validierung: Darf nicht größer als Kartenzahl sein
            if card > card_count:
                print(f"  ✗ Fehler: Karte muss maximal {card_count} sein")
                continue
            
            # Konvertiere Karte zu Seiten
            jump_page = (card - 1) * 2 + 1  # Erste Seite der Karte
            
            # Beim ersten Sprung: Erstelle Level I von Anfang bis Sprung
            if level_num == 1:
                end_page = jump_page - 1
                levels.append({
                    "name": LevelConfigurator._roman_numeral(1),
                    "start": 1,
                    "end": end_page
                })
                level_num += 1
            
            # Vorherigen Level abschließen (ab Level II)
            if len(levels) > 1:
                levels[-1]["end"] = jump_page - 1
            
            # Neuen Level beginnen (ab dem Sprung)
            levels.append({
                "name": LevelConfigurator._roman_numeral(level_num),
                "start": jump_page,
                "end": page_count  # Geht bis Ende, wird ggf. überschrieben
            })
            
            last_card = card  # Aktualisiere für nächste Validierung
            level_num += 1
        
        # Falls keine Level-Sprünge eingegeben wurden
        if not levels:
            levels.append({
                "name": "I",
                "start": 1,
                "end": page_count
            })
        
        # Zusammenfassung anzeigen
        print(f"\n→ {len(levels)} Level konfiguriert:")
        for level in levels:
            card_count = (level["end"] - level["start"] + 1) // 2
            print(f"   Level {level['name']:3s}: Seite {level['start']}-{level['end']}  ({card_count} Karten)")
        
        confirm = input("\nKorrekt? [J] Speichern [n] Neu eingeben: ").strip().lower()
        if confirm == 'n':
            return LevelConfigurator.configure(page_count, pdf_path)
        
        # Optional: Level benennen
        name_levels = input("\nLevel benennen? [j/N]: ").strip().lower()
        if name_levels == 'j':
            print("\nBitte Namen eingeben (leer lassen = römische Ziffer behalten):")
            for i, level in enumerate(levels):
                current_name = level['name']
                new_name = input(f"  Level {current_name}: ").strip()
                if new_name:
                    levels[i]['name'] = new_name
                    # Speichere auch die römische Ziffer als ID
                    levels[i]['roman'] = current_name
            
            # Zeige finale Namen
            print("\n→ Finale Level-Namen:")
            for level in levels:
                card_count = (level["end"] - level["start"] + 1) // 2
                print(f"   {level['name']:15s} ({card_count} Karten)")
        
        return levels
    
    @staticmethod
    def _roman_numeral(num: int) -> str:
        """Konvertiert Zahl zu römischer Ziffer (1-9)"""
        numerals = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"]
        return numerals[num - 1] if num <= 9 else str(num)
    
    @staticmethod
    def _detect_levels_from_pdf(pdf_path: Path, page_count: int) -> Optional[List[dict]]:
        """Scannt PDF nach Level-Markern (=lev: Name)"""
        import fitz
        import re
        
        doc = fitz.open(pdf_path)
        levels = []
        
        try:
            # Sammle alle Marker
            markers = []
            for page_num in range(page_count):
                page = doc[page_num]
                text = page.get_text()
                
                # Normalisiere Text
                text_normalized = text.replace('\n', ' ').replace('\r', ' ')
                
                # Suche nach lev: Marker
                match = re.search(r'lev:\s*([^=\n]+)', text_normalized, re.IGNORECASE)
                if match:
                    level_name = match.group(1).strip()
                    markers.append((page_num + 1, level_name))  # 1-indexed
            
            # Erstelle Level-Bereiche
            if not markers:
                doc.close()
                return None
            
            for i, (start_page, name) in enumerate(markers):
                if i < len(markers) - 1:
                    # Ende ist Seite VOR nächstem Marker
                    end_page = markers[i + 1][0] - 1
                else:
                    # Letztes Level geht bis Ende
                    end_page = page_count
                
                levels.append({
                    'name': name,
                    'start': start_page,
                    'end': end_page
                })
            
            doc.close()
            return levels
            
            doc.close()
            
            # Falls keine Level gefunden
            if not levels:
                return None
            
            return levels
            
        except Exception as e:
            doc.close()
            print(f"Fehler bei Level-Erkennung: {e}")
            return None


class CardSelector:
    """Wählt Karten basierend auf Filter und Modus aus"""
    
    def __init__(self, page_count: int, levels: Optional[List[dict]]):
        self.page_count = page_count
        self.levels = levels
        self.card_count = page_count // 2
    
    def get_level_names(self) -> List[str]:
        """Gibt alle Level-Namen zurück"""
        if not self.levels:
            return []
        return [level["name"] for level in self.levels]
    
    def select_cards(self, level_filter: List[str], randomize: bool) -> List[int]:
        """
        Gibt Liste von Kartennummern (1-basiert) zurück
        level_filter: Liste von Level-Namen oder [] für alle
        """
        if not self.levels or not level_filter:
            # Keine Level oder alle Level
            cards = list(range(1, self.card_count + 1))
        else:
            # Filtere nach ausgewählten Levels
            cards = []
            for level in self.levels:
                if level["name"] in level_filter:
                    start_card = (level["start"] + 1) // 2  # Erste Karte (ungerade Seite)
                    end_card = level["end"] // 2             # Letzte Karte
                    cards.extend(range(start_card, end_card + 1))
        
        if randomize:
            random.shuffle(cards)
        
        return cards
    
    def card_to_pages(self, card_num: int) -> Tuple[int, int]:
        """Konvertiert Kartennummer zu (Frage-Seite, Antwort-Seite)"""
        question_page = (card_num - 1) * 2 + 1
        answer_page = question_page + 1
        return question_page, answer_page


class FlashcardViewer:
    """GUI für die Karten-Präsentation"""
    
    def __init__(self, pdf_path: Path, cards: List[int], card_selector: CardSelector, total_cards: int, levels: Optional[List[dict]] = None):
        self.pdf_path = pdf_path
        self.cards = cards
        self.card_selector = card_selector
        self.total_cards = total_cards  # Gesamtzahl aller Karten im PDF
        self.levels = levels  # Level-Definitionen für Namensanzeige
        self.current_index = 0
        self.showing_answer = False
        self.history = []  # Stack von (card_index, showing_answer)
        
        # Flags für Rückgabewerte
        self.return_to_main = False
        self.request_level_clear = False
        self.round_complete = False  # Runde zu Ende?
        
        # Score-Tracking
        self.scores = {}  # {card_index: 'richtig'/'falsch'/'neutral'}
        self.score_richtig = 0
        self.score_falsch = 0
        self.score_neutral = 0
        self.round_start_time = None
        
        # PDF öffnen
        self.doc = fitz.open(pdf_path)
        
        # GUI Setup
        self.root = tk.Tk()
        self.root.title("Flashcard Viewer")
        self.root.attributes('-fullscreen', True)
        self.root.lift()
        self.root.focus_force()
        self.root.configure(bg='black')
        
        # Canvas für PDF-Rendering
        self.canvas = tk.Canvas(self.root, bg='black', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # Tastatur-Bindings
        self.root.bind('<space>', self.next_page)
        self.root.bind('<Right>', self.next_page)
        self.root.bind('<Left>', self.prev_page)
        self.root.bind('<r>', self.random_jump)
        self.root.bind('<R>', self.random_jump)
        self.root.bind('<f>', self.change_filter)
        self.root.bind('<F>', self.change_filter)
        self.root.bind('<l>', self.level_clear)
        self.root.bind('<L>', self.level_clear)
        # Score-Bewertung (nur bei Antwort)
        # + Taste (verschiedene Varianten)
        self.root.bind('<plus>', self.score_richtig_key)
        self.root.bind('<KP_Add>', self.score_richtig_key)  # Numpad +
        self.root.bind('<Key-plus>', self.score_richtig_key)
        self.root.bind('<j>', self.score_richtig_key)
        self.root.bind('<J>', self.score_richtig_key)
        # - Taste (verschiedene Varianten)
        self.root.bind('<minus>', self.score_falsch_key)
        self.root.bind('<KP_Subtract>', self.score_falsch_key)  # Numpad -
        self.root.bind('<Key-minus>', self.score_falsch_key)
        self.root.bind('<n>', self.score_falsch_key)
        self.root.bind('<N>', self.score_falsch_key)
        # Q und ESC = zurück zum Hauptmenü
        self.root.bind('<Escape>', self.back_to_menu)
        self.root.bind('<q>', self.back_to_menu)
        self.root.bind('<Q>', self.back_to_menu)
        
        # Erste Karte nach kurzer Verzögerung anzeigen (GUI muss erst fertig sein)
        self.root.after(100, self.start_round)
    
    def start_round(self):
        """Startet die Runde und setzt Timer"""
        import time
        self.round_start_time = time.time()
        self.show_current_card()
    
    def show_current_card(self):
        """Zeigt die aktuelle Karte/Seite an"""
        if self.current_index >= len(self.cards):
            # Alle Karten durch - Wiederholung anbieten
            self.round_complete = True
            self.return_to_main = True
            self.quit()
            return
        
        card_num = self.cards[self.current_index]
        question_page, answer_page = self.card_selector.card_to_pages(card_num)
        
        # Zeige Frage oder Antwort
        page_num = answer_page if self.showing_answer else question_page
        
        # Render PDF-Seite
        page = self.doc[page_num - 1]  # PyMuPDF ist 0-basiert
        
        # Skaliere auf Fenstergröße
        window_width = self.root.winfo_width()
        window_height = self.root.winfo_height()
        
        # Berechne Zoom-Faktor
        page_rect = page.rect
        zoom_x = window_width / page_rect.width
        zoom_y = window_height / page_rect.height
        zoom = min(zoom_x, zoom_y) * 0.95  # 95% für Rand
        
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        
        # Konvertiere zu PhotoImage
        img_data = pix.tobytes("ppm")
        self.photo = tk.PhotoImage(data=img_data)
        
        # Zentriere auf Canvas
        self.canvas.delete("all")
        x = window_width // 2
        y = window_height // 2
        self.canvas.create_image(x, y, image=self.photo)
        
        # Status-Info mit Frage/Karte-Unterscheidung
        card_num = self.cards[self.current_index]
        
        # Berechne aktuelle Frage/Antwort-Nummer
        question_num = self.current_index + 1 if not self.showing_answer else self.current_index + 1
        
        # Erste Zeile: Frage-Nummer mit Farb-Unterscheidung
        if self.showing_answer:
            line1 = f"Antwort {question_num} von {len(self.cards)}"
            line1_color = "#4a90c0"  # Blauton für Antwort
        else:
            line1 = f"Frage {question_num} von {len(self.cards)}"
            line1_color = "#c04a4a"  # Rotton für Frage
        
        # Zweite Zeile: Karte-Nummer
        line2 = f"Karte {card_num} von {self.total_cards}"
        
        self.canvas.create_text(10, 10, text=line1, anchor="nw", 
                               fill=line1_color, font=("Arial", 14, "bold"))
        self.canvas.create_text(10, 30, text=line2, anchor="nw", 
                               fill="lightgray", font=("Arial", 11))
        
        # Dritte Zeile: Level-Namen (falls vorhanden)
        if self.levels:
            card_page = (card_num - 1) * 2 + 1  # Erste Seite der Karte
            for level in self.levels:
                if level['start'] <= card_page <= level['end']:
                    level_name = level['name']
                    self.canvas.create_text(10, 52, text=level_name, anchor="nw", 
                                           fill="#c07b4a", font=("Arial", 13, "bold"))
                    break
        
        # Hilfe-Text unten - unterschiedlich für Frage/Antwort
        if self.showing_answer:
            help_text = "[+/j] Richtig | [-/n] Falsch | [→/Space] Neutral | [←] Zurück | [Q] Zurück"
        else:
            help_text = "[Space/→/+/-] Weiter | [←] Zurück | [R] Random | [Q] Zurück"
        self.canvas.create_text(window_width // 2, window_height - 20, 
                               text=help_text, anchor="s", 
                               fill="grey", font=("Arial", 10))
    
    def next_page(self, event=None):
        """Nächste Seite: Frage → Antwort → Nächste Frage"""
        # History speichern
        self.history.append((self.current_index, self.showing_answer))
        
        if not self.showing_answer:
            # Zeige Antwort
            self.showing_answer = True
        else:
            # Bei Antwort: Space/→ = Neutral-Score
            if self.current_index not in self.scores:
                self._record_score('neutral')
            
            # Nächste Karte
            self.showing_answer = False
            self.current_index += 1
        
        self.show_current_card()
    
    def prev_page(self, event=None):
        """Zurück in History"""
        if not self.history:
            return
        
        # Lösche Score der aktuellen Karte (wird neu bewertet)
        if self.current_index in self.scores:
            old_result = self.scores[self.current_index]
            if old_result == 'richtig':
                self.score_richtig -= 1
            elif old_result == 'falsch':
                self.score_falsch -= 1
            elif old_result == 'neutral':
                self.score_neutral -= 1
            del self.scores[self.current_index]
        
        self.current_index, self.showing_answer = self.history.pop()
        self.show_current_card()
    
    def random_jump(self, event=None):
        """Springe zu zufälliger Karte (oder zeige erst Antwort wenn bei Frage)"""
        if len(self.cards) <= 1:
            return
        
        # Wenn Frage gezeigt wird: erst Antwort zeigen
        if not self.showing_answer:
            self.showing_answer = True
            self.show_current_card()
            return
        
        # Bei Antwort: Springe zu zufälliger Karte
        # Wähle andere Karte als aktuelle
        available = [i for i in range(len(self.cards)) if i != self.current_index]
        self.history.append((self.current_index, self.showing_answer))
        self.current_index = random.choice(available)
        self.showing_answer = False
        self.show_current_card()
    
    def change_filter(self, event=None):
        """Filter ändern - zurück zum Hauptmenü"""
        self.return_to_main = True
        self.quit()
    
    def level_clear(self, event=None):
        """Level-Konfiguration neu einrichten"""
        response = messagebox.askyesno(
            "Level clear",
            "Level-Konfiguration ändern?\nPräsentation wird beendet."
        )
        if response:
            self.request_level_clear = True
            self.quit()
    
    def back_to_menu(self, event=None):
        """Zurück zum Hauptmenü"""
        self.return_to_main = True
        self.quit()
    
    def score_richtig_key(self, event=None):
        """Bewerte aktuelle Karte als richtig"""
        if self.showing_answer:
            self._record_score('richtig')
            self._flash_feedback('green')
            self.next_page()
        else:
            # Bei Frage: Zeige erst Antwort
            self.next_page()
    
    def score_falsch_key(self, event=None):
        """Bewerte aktuelle Karte als falsch"""
        if self.showing_answer:
            self._record_score('falsch')
            self._flash_feedback('red')
            self.next_page()
        else:
            # Bei Frage: Zeige erst Antwort
            self.next_page()
    
    def _record_score(self, result: str):
        """Speichert Score für aktuelle Karte"""
        # Entferne alten Score falls vorhanden (bei Zurück-Navigation)
        if self.current_index in self.scores:
            old_result = self.scores[self.current_index]
            if old_result == 'richtig':
                self.score_richtig -= 1
            elif old_result == 'falsch':
                self.score_falsch -= 1
            elif old_result == 'neutral':
                self.score_neutral -= 1
        
        # Neuen Score speichern
        self.scores[self.current_index] = result
        if result == 'richtig':
            self.score_richtig += 1
        elif result == 'falsch':
            self.score_falsch += 1
        elif result == 'neutral':
            self.score_neutral += 1
    
    def _flash_feedback(self, color: str):
        """Kurzes visuelles Feedback"""
        try:
            # Ändere Hintergrund kurz
            original_bg = self.canvas.cget('bg')
            self.canvas.configure(bg=color)
            self.root.update()
            # Verwende time.sleep statt after (sicherer)
            import time
            time.sleep(0.15)
            self.canvas.configure(bg=original_bg)
            self.root.update()
        except:
            pass  # Falls Fenster schon geschlossen
    
    def get_score_summary(self) -> dict:
        """Gibt Score-Zusammenfassung zurück"""
        import time
        duration = time.time() - self.round_start_time if self.round_start_time else 0
        
        total = self.score_richtig + self.score_falsch + self.score_neutral
        
        return {
            'richtig': self.score_richtig,
            'falsch': self.score_falsch,
            'neutral': self.score_neutral,
            'total': len(self.cards),
            'bewertet': total,
            'duration': duration
        }
    
    def quit(self, event=None):
        """Beende Viewer"""
        self.doc.close()
        self.root.quit()
        self.root.destroy()
    
    def run(self):
        """Starte die GUI"""
        self.root.mainloop()
        score_summary = self.get_score_summary()
        return self.return_to_main, self.request_level_clear, self.round_complete, score_summary


class AutopilotViewer:
    """
    Zeigt Frage-Antwort-Paare automatisch mit zufälligen Anzeigezeiten an.

    Tastenbelegung (Countdown läuft immer weiter — kein Pause-Modus):
      →  / Space : sofort zur nächsten Phase überspringen
      ←          : eine Phase zurück; Autopilot läuft danach normal weiter
      P          : Pause / Resume umschalten
      Q / Esc    : Abbrechen

    History: Jede Phase wird gespeichert. ← navigiert zurück,
    → springt innerhalb der History vor oder startet neue Phasen.
    Sobald man wieder an der Front ist, läuft der Countdown normal.

    timing: (frage_min, frage_max, antwort_min, antwort_max) in Sekunden
    Standard: (6, 8, 6, 6)
    """

    DEFAULT_TIMING = (6, 8, 6, 6)
    _PHASE_Q = 'q'
    _PHASE_A = 'a'

    def __init__(self, pdf_path: Path, cards: List[int], card_selector: CardSelector,
                 total_cards: int, levels,
                 timing: Tuple[int, int, int, int]):
        self.pdf_path      = pdf_path
        self.cards         = cards
        self.card_selector = card_selector
        self.total_cards   = total_cards
        self.levels        = levels
        self.timing        = timing

        self.stopped  = False
        self.paused   = False
        self._after_id = None

        # History: Liste von (card_index, phase)
        # _cursor zeigt auf den aktuell angezeigten Eintrag.
        # Wenn _cursor == len(_history)-1 sind wir an der "Front".
        self._history: List[Tuple[int, str]] = []
        self._cursor: int = -1          # -1 = noch leer

        self.doc = fitz.open(pdf_path)

        self.root = tk.Tk()
        self.root.title("Autopilot – Flashcard Viewer")
        self.root.attributes('-fullscreen', True)
        self.root.lift()
        self.root.focus_force()
        self.root.configure(bg='black')

        self.canvas = tk.Canvas(self.root, bg='black', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.status_var = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self.status_var,
                 fg='#555555', bg='black', font=("Arial", 14)
                 ).place(relx=1.0, rely=0.0, anchor='ne', x=-10, y=10)

        # True = manuell (kein Countdown), False = Autopilot mit Countdown
        self.manual = False

        self.root.bind('<Escape>', self._stop)
        self.root.bind('<q>',      self._stop)
        self.root.bind('<Q>',      self._stop)
        self.root.bind('<Right>',  self._nav_forward)
        self.root.bind('<space>',  self._nav_forward)
        self.root.bind('<Left>',   self._nav_back)
        self.root.bind('<p>',      self._toggle_pause)
        self.root.bind('<P>',      self._toggle_pause)
        self.root.bind('<t>',      self._toggle_mode)
        self.root.bind('<T>',      self._toggle_mode)

    # ── parse_timing (statisch) ───────────────────────────────────────────
    @staticmethod
    def parse_timing(user_input: str):
        user_input = user_input.strip()
        if not user_input:
            return None
        parts = [p.strip() for p in user_input.split(',')]
        if len(parts) != 4:
            return False
        try:
            values = tuple(int(p) for p in parts)
        except ValueError:
            return False
        q_min, q_max, a_min, a_max = values
        if q_min <= 0 or a_min <= 0 or q_min > q_max or a_min > a_max:
            return False
        return values

    # ── Interne Helfer ────────────────────────────────────────────────────
    def _cancel_timer(self):
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _stop(self, event=None):
        self.stopped = True
        self._cancel_timer()
        self._quit()

    def _quit(self):
        self.doc.close()
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

    def _at_front(self) -> bool:
        """True wenn cursor am Ende der History (= live)."""
        return self._cursor == len(self._history) - 1

    # -- Pause / Mode-Toggle -------------------------------------------------
    def _toggle_pause(self, event=None):
        if self.stopped:
            return
        if self.paused:
            self.paused = False
            if self._cursor >= 0:
                ci, ph = self._history[self._cursor]
                if not self.manual:
                    self._start_countdown(ci, ph)
                else:
                    self._update_status()
        else:
            self.paused = True
            self._cancel_timer()
            self._update_status()

    def _toggle_mode(self, event=None):
        """T: Autopilot / Manuell umschalten."""
        if self.stopped:
            return
        self.manual = not self.manual
        if self.manual:
            # Manuell: Countdown abbrechen, Status leeren
            self._cancel_timer()
            self.status_var.set("")
        else:
            # Autopilot: Countdown fuer aktuelle Phase starten
            if not self.paused and self._cursor >= 0:
                ci, ph = self._history[self._cursor]
                self._start_countdown(ci, ph)
        self._render_current()

    # ── Navigation ────────────────────────────────────────────────────────
    def _nav_forward(self, event=None):
        """→ / Space: nächste Phase — Timer abbrechen, sofort weiter."""
        if self.stopped:
            return
        self._cancel_timer()

        if self._cursor < 0:
            # Noch gar nichts — starte
            self._push_and_show(0, self._PHASE_Q)
            return

        if not self._at_front():
            # Wir sind in der History — einen Schritt vorwärts
            self._cursor += 1
            ci, ph = self._history[self._cursor]
            self._render_current()
            if not self.paused:
                self._start_countdown(ci, ph)
            return

        # Wir sind an der Front — nächste Phase berechnen
        ci, ph = self._history[self._cursor]
        if ph == self._PHASE_Q:
            self._push_and_show(ci, self._PHASE_A)
        else:
            nxt = ci + 1
            if nxt >= len(self.cards):
                self._quit()
            else:
                self._push_and_show(nxt, self._PHASE_Q)

    def _nav_back(self, event=None):
        """← : eine Phase zurück. Countdown läuft weiter (oder neu)."""
        if self.stopped or self._cursor <= 0:
            return
        self._cancel_timer()
        self._cursor -= 1
        ci, ph = self._history[self._cursor]
        self._render_current()
        if not self.paused:
            self._start_countdown(ci, ph)

    # ── History + Anzeige ─────────────────────────────────────────────────
    def _push_and_show(self, card_index: int, phase: str):
        """Neuen Eintrag an die History anhängen und anzeigen."""
        if card_index >= len(self.cards):
            self._quit()
            return
        # Alles hinter dem Cursor wegschneiden (falls wir in history waren)
        self._history = self._history[:self._cursor + 1]
        self._history.append((card_index, phase))
        self._cursor = len(self._history) - 1
        self._render_current()
        if not self.paused and not self.manual:
            self._start_countdown(card_index, phase)

    def _render_current(self):
        """Aktuelle History-Position rendern."""
        if self._cursor < 0:
            return
        ci, ph = self._history[self._cursor]
        card_num = self.cards[ci]
        q_page, a_page = self.card_selector.card_to_pages(card_num)
        page_num    = q_page if ph == self._PHASE_Q else a_page
        phase_label = "Frage" if ph == self._PHASE_Q else "Antwort"
        hist_info   = "" if self._at_front() else f"  ←{self._cursor+1}/{len(self._history)}"
        card_label  = f"Karte {ci+1}/{len(self.cards)} – {phase_label}{hist_info}"
        self._render_page(page_num, card_label)
        self._update_status()

    # ── Countdown ─────────────────────────────────────────────────────────
    def _start_countdown(self, card_index: int, phase: str):
        """Startet einen frischen Countdown für die angegebene Phase."""
        q_min, q_max, a_min, a_max = self.timing
        if phase == self._PHASE_Q:
            ms     = random.randint(q_min, q_max) * 1000
            prefix = "❓"
            def cb():
                self._push_and_show(card_index, self._PHASE_A)
        else:
            ms     = random.randint(a_min, a_max) * 1000
            prefix = "✓"
            def cb():
                nxt = card_index + 1
                if nxt >= len(self.cards):
                    self._quit()
                else:
                    self._push_and_show(nxt, self._PHASE_Q)
        self._tick(ms, prefix, cb)

    def _tick(self, remaining_ms: int, prefix: str, callback):
        if self.stopped or self.paused or self.manual:
            return
        secs = (remaining_ms + 999) // 1000
        self.status_var.set(f"{prefix} {secs}s")
        if remaining_ms <= 0:
            self.status_var.set("")
            callback()
            return
        tick = min(500, remaining_ms)
        self._after_id = self.root.after(
            tick,
            lambda: self._tick(remaining_ms - tick, prefix, callback)
        )

    def _update_status(self):
        if self.paused:
            self.status_var.set("⏸  [P] weiter  [T] Modus")
        elif self.manual:
            self.status_var.set("✋ Manuell  [T] Autopilot")
        # Im Autopilot-Modus zeigt _tick den Countdown

    # ── Rendering ─────────────────────────────────────────────────────────
    def _render_page(self, page_num: int, label: str = ""):
        page = self.doc[page_num - 1]
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        r = page.rect
        zoom = min(w / r.width, h / r.height)
        pix  = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)

        import io as _io
        from PIL import Image, ImageTk
        photo = ImageTk.PhotoImage(Image.open(_io.BytesIO(pix.tobytes("ppm"))))
        self.canvas.delete("all")
        self.canvas._photo = photo
        self.canvas.create_image(w // 2, h // 2, image=photo, anchor="center")
        self.canvas.create_text(
            w // 2, h - 20,
            text=f"[←] Zurück  [→/Spc] Weiter  [P] Pause  [T] Modus  [Q/Esc] Abbrechen  |  {label}",
            anchor="s", fill="grey", font=("Arial", 10)
        )

    # ── Entry point ───────────────────────────────────────────────────────
    def run(self):
        self.root.after(150, lambda: self._push_and_show(0, self._PHASE_Q))
        self.root.mainloop()
        return self.stopped


class MainMenu:
    """Hauptmenü für PDF-Auswahl und Konfiguration"""
    
    def __init__(self, config: Config, cards_dir: Path):
        self.config = config
        self.cards_dir = cards_dir  # Direkt karten-pdfs/ Verzeichnis
        self.pdf_path: Optional[Path] = None
        self.pdf_hash: Optional[str] = None
        self.page_count: int = 0
        self.levels: Optional[List[dict]] = None
        self.score_name: str = "Anonym"  # Für Score-Logging
        self.current_log_file: Optional[Path] = None  # Aktuelle Log-Datei
    
    def run(self):
        """Hauptschleife des Menüs"""
        while True:
            # PDF auswählen
            result = self.select_pdf()
            if result == False:
                return
            
            # Level konfigurieren falls nötig
            self.ensure_levels()
            
            # Quick Start? - zeige trotzdem Menü zur Bestätigung
            if result == 'quick_start' and self.last_config:
                print("\n→ Letzte Konfiguration wird vorgeschlagen:")
                level_filter = self.last_config.get('level_filter', [])
                randomize = self.last_config.get('randomize', False)
                if level_filter:
                    print(f"   Level: {', '.join(level_filter)}")
                else:
                    print(f"   Level: Alle")
                print(f"   Modus: {'Zufällig' if randomize else 'Reihenfolge'}")
                # Falle durch zum Hauptmenü
            
            # Hauptmenü-Schleife
            while True:
                action = self.show_main_menu()
                
                if action == 'start':
                    return_to_main, level_clear_requested = self.start_presentation()
                    if level_clear_requested:
                        self.reconfigure_levels()
                        # Zeige Menü neu nach Level-Änderung
                        continue
                    elif not return_to_main:
                        # Beenden gewünscht
                        return
                    # Sonst: return_to_main=True → zeige Menü neu
                elif action == 'autopilot':
                    self.start_autopilot()
                    # Nach Autopilot immer zurück zum Menü
                elif action == 'change_config':
                    self.reconfigure_levels()
                    # Zeige Menü neu nach Änderung
                elif action == 'level_clear':
                    self.reconfigure_levels()
                    # Zeige Menü neu nach Änderung
                elif action == 'other_pdf':
                    break  # Zurück zur PDF-Auswahl
                elif action == 'quit':
                    return
    
    def select_pdf(self) -> bool:
        """PDF-Auswahl, gibt False zurück wenn beendet werden soll"""
        # PDFs direkt im cards_dir suchen (kein Unterordner mehr!)
        pdf_dir = self.cards_dir
        
        # Suche PDFs
        pdfs = PDFManager.find_pdfs(pdf_dir)
        
        if not pdfs:
            print(f"\n⚠ Keine PDFs in '{pdf_dir}' gefunden.")
            print("   Lege PDF-Dateien dort ab und starte neu.")
            return False
        
        if len(pdfs) == 1:
            # Automatisch laden
            self.pdf_path = pdfs[0]
            print(f"\nPDF gefunden: {self.pdf_path.name}")
        else:
            # Auswahlmenü
            print("\nMehrere PDFs gefunden:")
            for i, pdf in enumerate(pdfs, 1):
                size_mb = pdf.stat().st_size / (1024 * 1024)
                marker = ""
                # Prüfe ob zuletzt verwendet
                pdf_hash = PDFManager.calculate_hash(pdf)
                if pdf_hash == self.config.data.get("last_used_hash"):
                    marker = " (zuletzt verwendet)"
                print(f"[{i}] {pdf.name} ({size_mb:.1f} MB){marker}")
            
            while True:
                choice = input(f"\nAuswahl [1-{len(pdfs)}] oder [q]uit: ").strip()
                if choice.lower() == 'q':
                    return False
                if choice.isdigit() and 1 <= int(choice) <= len(pdfs):
                    self.pdf_path = pdfs[int(choice) - 1]
                    break
                print("Ungültige Eingabe")
        
        # PDF-Metadaten laden
        self.pdf_hash = PDFManager.calculate_hash(self.pdf_path)
        self.page_count = PDFManager.get_page_count(self.pdf_path)
        
        # Config laden oder erstellen
        pdf_config = self.config.get_pdf_config(self.pdf_hash)
        if pdf_config:
            print(f"PDF bekannt, Config geladen.")
            self.levels = pdf_config["levels"]
            self.last_config = pdf_config.get("last_session")
            
            # Biete "Weiter mit letzter Config" an
            if self.last_config:
                print(f"\nLetzte Konfiguration:")
                level_names = self.last_config.get('level_filter', [])
                if not level_names:
                    level_str = "Alle Level"
                elif len(level_names) == 1:
                    level_str = f"Nur Level {level_names[0]}"
                else:
                    level_str = f"Level {', '.join(level_names)}"
                
                mode_str = "Zufällig" if self.last_config.get('randomize') else "Reihenfolge"
                print(f"  - {level_str}")
                print(f"  - Modus: {mode_str}")
                
                quick_start = input("\n[Enter] Mit letzter Config starten  [n] Neue Config: ").strip().lower()
                if quick_start != 'n':
                    # Direkt starten mit letzter Config
                    return 'quick_start'
                else:
                    # Neue Config gewünscht - Level zurücksetzen
                    print("\n→ Neue Level-Konfiguration...")
                    self.levels = None
                    self.last_config = None
        else:
            print(f"Neue Datei erkannt.")
            self.levels = None
            self.last_config = None
        
        return True
    
    def ensure_levels(self):
        """Stellt sicher, dass Level konfiguriert sind (falls gewünscht)"""
        if self.levels is None:
            self.levels = LevelConfigurator.configure(self.page_count, self.pdf_path)
            self.config.set_pdf_config(
                self.pdf_hash,
                self.pdf_path.name,
                self.pdf_path.stat().st_size,
                self.levels
            )
    
    def reconfigure_levels(self):
        """Level neu konfigurieren"""
        print("\n" + "="*50)
        self.config.clear_levels(self.pdf_hash)
        self.levels = LevelConfigurator.configure(self.page_count, self.pdf_path)
        self.config.set_pdf_config(
            self.pdf_hash,
            self.pdf_path.name,
            self.pdf_path.stat().st_size,
            self.levels
        )
    
    def show_main_menu(self) -> str:
        """Zeigt Hauptmenü und gibt gewählte Aktion zurück"""
        print("\n" + "="*50)
        card_count = self.page_count // 2
        level_info = "Keine Level" if not self.levels else f"Levels: {'-'.join(l['name'] for l in self.levels)}"
        print(f"PDF: {self.pdf_path.name} | Karten: {card_count} | {level_info}")
        print("="*50)
        
        # Level-Filter
        level_options = []
        if self.levels:
            print("\nLevel-Filter:")
            # Einzelne Level mit Kartenzahl
            for i, level in enumerate(self.levels):
                level_options.append([level['name']])
                # Berechne Kartenzahl für dieses Level
                level_cards = (level['end'] - level['start'] + 1) // 2
                print(f"[{i+1}] Nur {level['name']:3s}  ({level_cards} Karten)")
            
            # Alle mit Gesamtkartenzahl
            level_options.append([])
            print(f"[{len(level_options)}] Alle Level  ({card_count} Karten)")
        
        print("\n[Z] Zufällig  |  [Enter] Reihenfolge (Standard)  |  [P] Autopilot")
        print("Beispiele: [Enter] = alle | 'z' = alle zufällig | '2+4' = Level 2+4 | '2+4z' = Level 2+4 zufällig")
        print("[K]onfig ändern  [L]evel clear  [A]nderes PDF  [Q] Beenden")
        
        while True:
            inp = input("\nEingabe: ").strip().upper()
            
            # Q = Zurück
            if inp == 'Q':
                return 'quit'
            
            # K/L/A/P Aktionen
            if inp == 'K':
                return 'change_config'
            if inp == 'L':
                return 'level_clear'
            if inp == 'A':
                return 'other_pdf'
            if inp == 'P':
                return 'autopilot'
            
            # Leere Eingabe = Alle Level, Reihenfolge
            if inp == '':
                self.selected_level_filter = []
                self.selected_randomize = False
                print(f"  ✓ Level: Alle")
                print(f"  ✓ Modus: Reihenfolge")
                return 'start'
            
            # Z allein = Alle zufällig
            if inp == 'Z':
                self.selected_level_filter = []
                self.selected_randomize = True
                print(f"  ✓ Level: Alle")
                print(f"  ✓ Modus: Zufällig")
                return 'start'
            
            # Parse Level + optional Z
            randomize = False
            if inp.endswith('Z'):
                randomize = True
                inp = inp[:-1]  # Entferne Z
            
            # Jetzt haben wir entweder: Zahl, Zahl+Zahl, oder leer
            if inp:
                # Level-Auswahl
                try:
                    if '+' in inp:
                        # Kombination
                        nums = [int(p) for p in inp.split('+')]
                        if self.levels and all(1 <= n <= len(self.levels) for n in nums):
                            combined = []
                            for n in nums:
                                if n <= len(level_options):
                                    combined.extend(level_options[n - 1])
                            level_choice = combined
                            level_names = [self.levels[n-1]['name'] for n in nums if n <= len(self.levels)]
                            print(f"  ✓ Level: {' + '.join(level_names)}")
                            print(f"  ✓ Modus: {'Zufällig' if randomize else 'Reihenfolge'}")
                            self.selected_level_filter = level_choice
                            self.selected_randomize = randomize
                            return 'start'
                        else:
                            if self.levels:
                                print(f"  ✗ Ungültige Level-Kombination (1-{len(self.levels)})")
                            else:
                                print(f"  ✗ Keine Level vorhanden")
                            continue
                    elif inp.isdigit():
                        # Einzelnes Level
                        num = int(inp)
                        if self.levels and 1 <= num <= len(level_options):
                            level_choice = level_options[num - 1]
                            level_name = self.levels[num-1]['name']
                            print(f"  ✓ Level: {level_name}")
                            print(f"  ✓ Modus: {'Zufällig' if randomize else 'Reihenfolge'}")
                            self.selected_level_filter = level_choice
                            self.selected_randomize = randomize
                            return 'start'
                        else:
                            print(f"  ✗ Ungültige Level-Wahl (1-{len(level_options)})")
                            continue
                    else:
                        print(f"  ✗ Ungültige Eingabe")
                        continue
                except ValueError:
                    print(f"  ✗ Ungültige Eingabe")
                    continue
            else:
                # Nur Z eingegeben (wurde schon behandelt)
                print(f"  ✗ Ungültige Eingabe")
                print(f"  ✗ Ungültige Eingabe: {inp}")
                if self.levels:
                    print(f"     Optionen: 1-{len(level_options)} [+kombination] S/Z, oder K/L/A/Q")
                else:
                    print("     Optionen: S/Z, oder K/L/A/Q")
    
    def start_autopilot(self):
        """
        Startet den Autopilot-Modus.
        Fragt nach Timing und Level-Filter, dann läuft alles automatisch.
        """
        print("\n" + "="*50)
        print("AUTOPILOT-MODUS")
        print("="*50)
        print("Anzeigedauer: q_min,q_max,a_min,a_max (Sekunden)")
        print("  z.B. '3,7,4,8' → Frage 3-7s, Antwort 4-8s")
        print("  Enter → Standard (6,8,6,6)")
        
        # Timing einlesen
        while True:
            raw = input("\nTiming [Enter=Standard / z.B. 3,7,4,8]: ").strip()
            result = AutopilotViewer.parse_timing(raw)
            if result is None:
                timing = AutopilotViewer.DEFAULT_TIMING
                print(f"  ✓ Standard-Timing: Frage {timing[0]}-{timing[1]}s, Antwort {timing[2]}-{timing[3]}s")
                break
            elif result is False:
                print("  ✗ Ungültig. Format: ganzzahl,ganzzahl,ganzzahl,ganzzahl  (min ≤ max, alle > 0)")
                continue
            else:
                timing = result
                q_min, q_max, a_min, a_max = timing
                if q_min == q_max:
                    q_str = f"{q_min}s"
                else:
                    q_str = f"{q_min}-{q_max}s"
                if a_min == a_max:
                    a_str = f"{a_min}s"
                else:
                    a_str = f"{a_min}-{a_max}s"
                print(f"  ✓ Frage: {q_str}  |  Antwort: {a_str}")
                break
        
        # Level-Filter: verwende aktuelle Auswahl aus dem Menü
        # (self.selected_level_filter / self.selected_randomize wurden beim letzten
        #  show_main_menu-Aufruf gesetzt – falls noch nicht gesetzt, alle/zufällig)
        level_filter = getattr(self, 'selected_level_filter', [])
        # Autopilot läuft immer zufällig (macht mehr Sinn), aber Nutzer kann
        # die Level-Auswahl aus dem Menü übernehmen
        print("\nKarten-Auswahl für Autopilot:")
        if level_filter:
            print(f"  Level-Filter: {level_filter}  (aus aktueller Menü-Auswahl)")
        else:
            print("  Alle Karten")
        
        rnd_inp = input("Zufällige Reihenfolge? [J/n]: ").strip().lower()
        randomize = rnd_inp != 'n'
        print(f"  ✓ {'Zufällig' if randomize else 'Reihenfolge'}")
        
        card_selector = CardSelector(self.page_count, self.levels)
        cards = card_selector.select_cards(level_filter, randomize)
        
        if not cards:
            print("\nKeine Karten im gewählten Filter!")
            input("Enter zum Fortfahren...")
            return
        
        print(f"\n{len(cards)} Karten werden automatisch angezeigt.")
        print("[Q] oder [Escape] zum Abbrechen während der Präsentation.")
        input("Enter zum Starten...")
        
        total_cards = self.page_count // 2
        autopilot = AutopilotViewer(
            self.pdf_path, cards, card_selector,
            total_cards, self.levels, timing
        )
        stopped = autopilot.run()
        
        if stopped:
            print("\n→ Autopilot abgebrochen.")
        else:
            print("\n✓ Autopilot: alle Karten angezeigt.")
        
        input("Enter zum Fortfahren...")

    def start_presentation(self) -> Tuple[bool, bool]:
        """
        Startet die Präsentation
        Gibt zurück: (return_to_main, level_clear_requested)
        """
        # Speichere letzte Config
        last_session = {
            'level_filter': self.selected_level_filter,
            'randomize': self.selected_randomize
        }
        self.config.set_pdf_config(
            self.pdf_hash,
            self.pdf_path.name,
            self.pdf_path.stat().st_size,
            self.levels,
            last_session
        )
        
        card_selector = CardSelector(self.page_count, self.levels)
        cards = card_selector.select_cards(
            self.selected_level_filter,
            self.selected_randomize
        )
        
        if not cards:
            print("\nKeine Karten im gewählten Filter!")
            input("Enter zum Fortfahren...")
            return True, False
        
        round_num = 1
        
        while True:
            if round_num == 1:
                print(f"\nStarte Präsentation mit {len(cards)} Karten...")
            else:
                print(f"\n=== Runde {round_num} ===")
                print(f"Erneut {len(cards)} Karten...")
            
            print("\nTastatur-Steuerung:")
            print("  [Space/→] Nächste Seite")
            print("  [←] Zurück")
            print("  [R] Random Jump")
            print("  [L] Level clear")
            print("  [Q] Hauptmenü")
            
            if round_num == 1:
                input("\nEnter zum Starten...")
            
            total_cards = self.page_count // 2
            viewer = FlashcardViewer(self.pdf_path, cards, card_selector, total_cards, self.levels)
            return_to_main, level_clear_requested, round_complete, score_summary = viewer.run()
            
            # Level clear wurde angefragt?
            if level_clear_requested:
                return False, True
            
            # Score anzeigen (auch bei vorzeitigem Abbruch wenn Karten bewertet wurden)
            if score_summary['bewertet'] > 0:
                self._show_score_summary(score_summary, round_num)
                self._save_score(score_summary, round_num)
            
            # Zurück zum Hauptmenü?
            if not round_complete:
                return return_to_main, False
            
            # Runde komplett - Wiederholung anbieten
            print(f"\n✓ Runde {round_num} abgeschlossen!")
            print(f"Runde {round_num + 1}? [Enter] Ja  [q] Hauptmenü")
            
            # Warte auf einzelne Taste (ohne Enter)
            import sys, tty, termios
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(sys.stdin.fileno())
                key = sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            
            # Q oder q = zurück
            if key.lower() == 'q':
                print("\n→ Zurück zum Hauptmenü")
                return True, False
            
            # Sonst weiter
            print("\n→ Nächste Runde!")
            
            # Nächste Runde mit neuer Randomisierung
            round_num += 1
            cards = card_selector.select_cards(
                self.selected_level_filter,
                self.selected_randomize
            )
    
    def _show_score_summary(self, score: dict, round_num: int):
        """Zeigt Score-Zusammenfassung an"""
        print("\n" + "="*50)
        print(f"Score Runde {round_num}:")
        print("="*50)
        
        total = score['bewertet']
        if total > 0:
            richtig_pct = (score['richtig'] / total) * 100
            falsch_pct = (score['falsch'] / total) * 100
            neutral_pct = (score['neutral'] / total) * 100
            
            print(f"  Richtig: {score['richtig']}/{total} ({richtig_pct:.0f}%)")
            print(f"  Falsch:  {score['falsch']}/{total} ({falsch_pct:.0f}%)")
            print(f"  Neutral: {score['neutral']}/{total} ({neutral_pct:.0f}%)")
        else:
            print("  Keine Karten bewertet")
        
        # Dauer
        duration = score['duration']
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        print(f"  Dauer: {minutes}m {seconds}s")
        print("="*50)
    
    def _save_score(self, score: dict, round_num: int):
        """Speichert Score in Log-Datei"""
        from datetime import datetime
        
        # Scores-Ordner erstellen
        scores_dir = self.cards_dir / "scores"
        scores_dir.mkdir(exist_ok=True)
        
        # Bei erster Runde: Name abfragen und Header schreiben
        if round_num == 1:
            name = input("\nName eingeben (optional, Enter=anonym): ").strip()
            if not name:
                name = "Anonym"
            self.score_name = name
            
            # Dateiname: pdf-name_datum_name.log
            date_str = datetime.now().strftime("%Y-%m-%d")
            # Bereinige Namen für Dateinamen (keine Sonderzeichen)
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name.replace(' ', '_')
            log_file = scores_dir / f"{self.pdf_path.stem}_{date_str}_{safe_name}.log"
            self.current_log_file = log_file
            
            # Header schreiben
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"=== {self.pdf_path.name} ===\n")
                f.write(f"Datum: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Name: {name}\n\n")
        elif round_num > 1:
            # Bei weiteren Runden: verwende bereits erstellte Datei
            log_file = self.current_log_file
        
        # Score-Daten anhängen
        with open(log_file, 'a', encoding='utf-8') as f:
            # Level-Info
            level_str = "Alle Level" if not self.selected_level_filter else ", ".join(self.selected_level_filter)
            modus_str = "Zufällig" if self.selected_randomize else "Reihenfolge"
            
            f.write(f"Runde {round_num} (Level: {level_str}, Modus: {modus_str})\n")
            
            total = score['bewertet']
            if total > 0:
                richtig_pct = (score['richtig'] / total) * 100
                falsch_pct = (score['falsch'] / total) * 100
                neutral_pct = (score['neutral'] / total) * 100
                
                f.write(f"  Richtig: {score['richtig']}/{total} ({richtig_pct:.0f}%)\n")
                f.write(f"  Falsch:  {score['falsch']}/{total} ({falsch_pct:.0f}%)\n")
                f.write(f"  Neutral: {score['neutral']}/{total} ({neutral_pct:.0f}%)\n")
            else:
                f.write(f"  Keine Karten bewertet\n")
            
            # Dauer
            duration = score['duration']
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            f.write(f"  Dauer: {minutes}m {seconds}s\n\n")
        
        print(f"→ Score gespeichert: {log_file.name}")


def setup_cards_directory(work_dir: Path) -> Tuple[Path, List[Path]]:
    """
    Organisiert PDFs in karten-pdfs/ Verzeichnis.
    
    Returns:
        (cards_dir, pdf_list) - Verzeichnis und Liste der PDFs
    """
    keywords = ["kart", "card", "carte"]
    
    # Prüfe: Gibt es karten-pdfs/ Unterverzeichnis?
    cards_dir = work_dir / "karten-pdfs"
    
    # Sammle PDFs die verschoben werden sollen
    pdfs_to_move = []
    for pdf_file in work_dir.glob("*.pdf"):
        if any(keyword in pdf_file.name.lower() for keyword in keywords):
            pdfs_to_move.append(pdf_file)
    
    # Erstelle Verzeichnis falls nötig
    if not cards_dir.exists() and pdfs_to_move:
        print(f"→ Erstelle: karten-pdfs/")
        cards_dir.mkdir(exist_ok=True)
    
    # Verschiebe PDFs
    moved = 0
    for pdf_file in pdfs_to_move:
        target = cards_dir / pdf_file.name
        
        # Existiert schon? -> Timestamp anhängen
        if target.exists():
            import time
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            stem = target.stem
            suffix = target.suffix
            target = cards_dir / f"{stem}_{timestamp}{suffix}"
            print(f"→ Verschiebe (umbenannt): {pdf_file.name} → {target.name}")
        else:
            print(f"→ Verschiebe: {pdf_file.name}")
        
        pdf_file.rename(target)
        moved += 1
    
    if moved:
        print(f"✓ {moved} PDF(s) verschoben")
    
    # Prüfe: Gibt es PDFs ohne Keyword im Namen?
    if cards_dir.exists():
        pdfs_without_keyword = []
        for pdf_file in cards_dir.glob("*.pdf"):
            if not any(keyword in pdf_file.name.lower() for keyword in keywords):
                pdfs_without_keyword.append(pdf_file)
        
        # Biete Umbenennung an
        if pdfs_without_keyword:
            print(f"\n⚠ {len(pdfs_without_keyword)} PDF(s) ohne 'kart'/'card'/'carte' im Namen gefunden:")
            for pdf in pdfs_without_keyword:
                print(f"   - {pdf.name}")
            
            choice = input("\nMit 'karten_' Präfix umbenennen? [j/n]: ").strip().lower()
            if choice == 'j':
                for pdf_file in pdfs_without_keyword:
                    new_name = f"karten_{pdf_file.name}"
                    new_path = cards_dir / new_name
                    pdf_file.rename(new_path)
                    print(f"   ✓ {pdf_file.name} → {new_name}")
    
    # Sammle finale PDF-Liste
    if cards_dir.exists():
        pdf_list = sorted(cards_dir.glob("*.pdf"))
    else:
        pdf_list = []
    
    return cards_dir, pdf_list


def main():
    """Haupteinstiegspunkt"""
    work_dir = Path.cwd().absolute()
    
    print(f"Lernkarten-Viewer")
    print(f"Arbeitsverzeichnis: {work_dir}\n")
    
    # Setup: Organisiere PDFs
    cards_dir, pdf_list = setup_cards_directory(work_dir)
    
    # Prüfe Ergebnis
    if not pdf_list:
        print("\n⚠ Keine PDFs gefunden!")
        print(f"   Lege PDF-Dateien in: {cards_dir}")
        print(f"   Tipp: Dateiname sollte 'kart', 'card' oder 'carte' enthalten")
        return
    
    print(f"\n✓ {len(pdf_list)} PDF(s) bereit\n")
    
    # Config laden (im karten-pdfs/ Verzeichnis)
    config_path = cards_dir / "config.json"
    config = Config(config_path)
    
    # Hauptmenü starten (mit expliziter PDF-Liste)
    menu = MainMenu(config, cards_dir)
    menu.run()
    
    print("\nCiao dann.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAbgebrochen.")
        sys.exit(0)

#!/usr/bin/env python3
"""
Tkinter PDF Viewer – Qualitätsrendering + Autopilot
Args: --pdf PATH [--dpi N] [--cards '[1,2,...]'] [--levels '[...]']
      [--total N] [--mode manual|autopilot] [--timing q_min,q_max,a_min,a_max]
      [--fullscreen]
Tasten: ←/→/Space  j/+ richtig  n/- falsch  0/Space(Antwort) neutral
        P Pause     T Modus      Q/Esc Ende
"""
import argparse, base64, io, json, random, sys, time
import tkinter as tk
from pathlib import Path

try:
    import fitz
except ImportError:
    print("PyMuPDF nicht installiert.", file=sys.stderr); sys.exit(1)

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

_Q, _A = "q", "a"


def card_to_pages(card_num):
    q = (card_num - 1) * 2
    return q, q + 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pdf",        required=True)
    p.add_argument("--dpi",        type=int, default=150)
    p.add_argument("--cards",      default="")
    p.add_argument("--levels",     default="")
    p.add_argument("--total",      type=int, default=0)
    p.add_argument("--mode",       default="manual", choices=["manual", "autopilot"])
    p.add_argument("--timing",     default="6,8,6,6")
    p.add_argument("--fullscreen", action="store_true")
    args = p.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"PDF nicht gefunden: {pdf_path}", file=sys.stderr); sys.exit(1)

    cards  = json.loads(args.cards)  if args.cards  else []
    levels = json.loads(args.levels) if args.levels else []
    try:
        t = [int(x) for x in args.timing.split(",")]
        timing = tuple(t[:4]) if len(t) >= 4 else (6, 8, 6, 6)
    except Exception:
        timing = (6, 8, 6, 6)

    doc = fitz.open(str(pdf_path))
    total_pages = doc.page_count
    total_cards = args.total or total_pages // 2
    if not cards:
        cards = list(range(1, total_cards + 1))

    # ── Mutable state ────────────────────────────────────────────────────────
    history  = []       # [(card_index, phase), ...]
    cursor   = [-1]
    paused   = [False]
    manual   = [args.mode == "manual"]
    stopped  = [False]
    after_id = [None]
    img_ref  = [None]
    scores   = {}       # card_index → "richtig"/"falsch"/"neutral"
    sc       = {"richtig": 0, "falsch": 0, "neutral": 0}

    # ── Window ───────────────────────────────────────────────────────────────
    root = tk.Tk()
    root.title(f"tk-view  {pdf_path.name}")
    root.configure(bg="#000")
    if args.fullscreen:
        root.attributes("-fullscreen", True)
    else:
        root.geometry("1280x800")
    root.lift(); root.focus_force()

    canvas = tk.Canvas(root, bg="#000", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)

    status_var = tk.StringVar(value="")
    tk.Label(root, textvariable=status_var, fg="#555", bg="#000",
             font=("Arial", 13)).place(relx=1.0, rely=0.0, anchor="ne", x=-12, y=10)

    # ── Helpers ──────────────────────────────────────────────────────────────
    def level_name_for(card_num):
        page = (card_num - 1) * 2 + 1
        for lv in levels:
            if lv.get("start", 0) <= page <= lv.get("end", 9999):
                return lv.get("name", "")
        return ""

    def render_page(page_0idx):
        page = doc[page_0idx]
        cw = max(canvas.winfo_width(),  100)
        ch = max(canvas.winfo_height(), 100)
        rect = page.rect
        fit   = min(cw / rect.width, ch / rect.height)
        scale = max(fit, args.dpi / 72.0)
        pix   = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        raw   = pix.tobytes("png")
        if HAS_PIL:
            img = Image.open(io.BytesIO(raw))
            if img.width > cw or img.height > ch:
                img.thumbnail((cw, ch), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
        else:
            pix2  = page.get_pixmap(matrix=fitz.Matrix(fit, fit))
            photo = tk.PhotoImage(data=base64.b64encode(pix2.tobytes("png")).decode())
        img_ref[0] = photo
        canvas.delete("all")
        canvas.create_image(cw // 2, ch // 2, image=photo, anchor=tk.CENTER)

    def draw_overlay(ci, ph):
        cw = max(canvas.winfo_width(),  100)
        ch = max(canvas.winfo_height(), 100)
        cn = cards[ci]
        n  = ci + 1

        # Frage / Antwort
        if ph == _Q:
            lbl, col = f"Frage {n} / {len(cards)}", "#c04a4a"
        else:
            lbl, col = f"Antwort {n} / {len(cards)}", "#4a90c0"
        canvas.create_text(12, 12, text=lbl, anchor="nw",
                           fill=col, font=("Arial", 14, "bold"))
        canvas.create_text(12, 32, text=f"Karte {cn} von {total_cards}",
                           anchor="nw", fill="#888", font=("Arial", 11))

        lname = level_name_for(cn)
        y_sc  = 52
        if lname:
            canvas.create_text(12, 52, text=lname, anchor="nw",
                               fill="#c07b4a", font=("Arial", 13, "bold"))
            y_sc = 72

        # Score-Zeile
        r, f, ne = sc["richtig"], sc["falsch"], sc["neutral"]
        if r + f + ne > 0:
            canvas.create_text(12, y_sc,
                               text=f"✓ {r}   ✗ {f}   ○ {ne}",
                               anchor="nw", fill="#555", font=("Arial", 10))

        # History-Hinweis
        at_front = cursor[0] == len(history) - 1
        hist     = "" if at_front else f"   ← {cursor[0]+1}/{len(history)}"

        # Hilfe unten
        if ph == _A:
            htxt = f"[+/j] Richtig  [-/n] Falsch  [Space/→/0] Neutral  [←] Zurück  [P] Pause  [T] Modus  [Q] Ende{hist}"
        else:
            htxt = f"[Space/→] Weiter  [←] Zurück  [P] Pause  [T] Modus  [Q] Ende{hist}"
        canvas.create_text(cw // 2, ch - 14, text=htxt, anchor="s",
                           fill="#444", font=("Arial", 10))

    def show_current():
        if cursor[0] < 0 or cursor[0] >= len(history):
            return
        ci, ph = history[cursor[0]]
        if ci >= len(cards):
            close(); return
        cn       = cards[ci]
        q_p, a_p = card_to_pages(cn)
        render_page(a_p if ph == _A else q_p)
        draw_overlay(ci, ph)
        update_status()

    # ── Countdown ────────────────────────────────────────────────────────────
    def cancel_timer():
        if after_id[0]:
            try: root.after_cancel(after_id[0])
            except: pass
            after_id[0] = None

    def start_countdown(ci, ph):
        q_min, q_max, a_min, a_max = timing
        if ph == _Q:
            ms, prefix = random.randint(q_min, q_max) * 1000, "❓"
            def cb(): push_and_show(ci, _A)
        else:
            ms, prefix = random.randint(a_min, a_max) * 1000, "✓"
            def cb():
                nxt = ci + 1
                if nxt >= len(cards): close()
                else: push_and_show(nxt, _Q)
        tick(ms, prefix, cb)

    def tick(ms, prefix, cb):
        if stopped[0] or paused[0] or manual[0]:
            return
        status_var.set(f"{prefix} {(ms + 999) // 1000}s")
        if ms <= 0:
            status_var.set(""); cb(); return
        step = min(500, ms)
        after_id[0] = root.after(step, lambda: tick(ms - step, prefix, cb))

    def update_status():
        if   paused[0]:  status_var.set("⏸  [P] weiter")
        elif manual[0]:  status_var.set("✋  [T] Autopilot")

    # ── History + Navigation ─────────────────────────────────────────────────
    def at_front():
        return cursor[0] == len(history) - 1

    def push_and_show(ci, ph):
        if ci >= len(cards): close(); return
        del history[cursor[0] + 1:]
        history.append((ci, ph))
        cursor[0] = len(history) - 1
        show_current()
        if not paused[0] and not manual[0]:
            start_countdown(ci, ph)

    def nav_forward(event=None):
        cancel_timer()
        if cursor[0] < 0:
            push_and_show(0, _Q); return
        if not at_front():
            cursor[0] += 1
            show_current()
            if not paused[0] and not manual[0]:
                start_countdown(*history[cursor[0]])
            return
        ci, ph = history[cursor[0]]
        if ph == _Q:
            push_and_show(ci, _A)
        else:
            if ci not in scores: record_score(ci, "neutral")
            nxt = ci + 1
            if nxt >= len(cards): close()
            else: push_and_show(nxt, _Q)

    def nav_back(event=None):
        if cursor[0] <= 0: return
        cancel_timer()
        cursor[0] -= 1
        show_current()
        if not paused[0] and not manual[0]:
            start_countdown(*history[cursor[0]])

    # ── Scoring ──────────────────────────────────────────────────────────────
    def record_score(ci, result):
        if ci in scores:
            sc[scores[ci]] -= 1
        scores[ci] = result
        sc[result]  += 1

    def flash_and_advance(result):
        if cursor[0] < 0: return
        ci, ph = history[cursor[0]]
        if ph != _A: nav_forward(); return
        record_score(ci, result)
        color = {"richtig": "#003300", "falsch": "#330000", "neutral": "#001133"}[result]
        try:
            canvas.configure(bg=color); root.update()
            time.sleep(0.13)
            canvas.configure(bg="#000"); root.update()
        except Exception:
            pass
        cancel_timer()
        nxt = ci + 1
        if nxt >= len(cards): close()
        else: push_and_show(nxt, _Q)

    # ── Mode / Pause ─────────────────────────────────────────────────────────
    def toggle_pause(event=None):
        if stopped[0]: return
        paused[0] = not paused[0]
        if paused[0]:
            cancel_timer(); update_status()
        else:
            if not manual[0] and cursor[0] >= 0:
                start_countdown(*history[cursor[0]])
            update_status()

    def toggle_mode(event=None):
        if stopped[0]: return
        manual[0] = not manual[0]
        if manual[0]:
            cancel_timer()
        elif not paused[0] and cursor[0] >= 0:
            start_countdown(*history[cursor[0]])
        show_current()

    def close(event=None):
        stopped[0] = True; cancel_timer(); doc.close()
        try: root.quit(); root.destroy()
        except Exception: pass

    # ── Bindings ─────────────────────────────────────────────────────────────
    for seq in ("<Right>", "<space>"):
        root.bind(seq, nav_forward)
    root.bind("<Left>",        nav_back)
    root.bind("<p>",           toggle_pause)
    root.bind("<P>",           toggle_pause)
    root.bind("<t>",           toggle_mode)
    root.bind("<T>",           toggle_mode)
    root.bind("<j>",           lambda e: flash_and_advance("richtig"))
    root.bind("<J>",           lambda e: flash_and_advance("richtig"))
    root.bind("<plus>",        lambda e: flash_and_advance("richtig"))
    root.bind("<KP_Add>",      lambda e: flash_and_advance("richtig"))
    root.bind("<n>",           lambda e: flash_and_advance("falsch"))
    root.bind("<N>",           lambda e: flash_and_advance("falsch"))
    root.bind("<minus>",       lambda e: flash_and_advance("falsch"))
    root.bind("<KP_Subtract>", lambda e: flash_and_advance("falsch"))
    root.bind("<0>",           lambda e: flash_and_advance("neutral"))
    root.bind("<Escape>",      close)
    root.bind("<q>",           close)
    root.bind("<Q>",           close)
    canvas.bind("<Configure>", lambda e: show_current() if cursor[0] >= 0 else None)
    if args.fullscreen:
        root.bind("<F11>", lambda e: root.attributes("-fullscreen", False))

    root.after(150, lambda: push_and_show(0, _Q))
    root.mainloop()


if __name__ == "__main__":
    main()

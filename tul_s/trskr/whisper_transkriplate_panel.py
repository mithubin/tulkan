#!/usr/bin/env python3
"""
whisper_transkriplate_panel.py
Engine-Modul für das trskr-Panel: Transkription, Übersetzung, TOC, Zusammenfassung.
Wird von panel_server.py als Bibliothek importiert — kein eigenständiger Einstiegspunkt.
"""

import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path

# ─── Konfiguration ────────────────────────────────────────────────────────────

MODELS_DIR = "trscrplate_mls"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

TOC_MODEL     = os.environ.get("TOC_MODEL",     "claude-sonnet-4-6")
SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "claude-haiku-4-5-20251001")

def _handle_api_error(e, model: str) -> None:
    """Gibt bei API-Fehlern eine lesbare Fehlermeldung aus."""
    try:
        from anthropic import NotFoundError, AuthenticationError, RateLimitError
    except ImportError:
        err(f"API-Fehler: {e}"); return
    if isinstance(e, NotFoundError):
        err(f"Modell nicht gefunden: '{model}'")
        err("  → Env-Variable setzen: TOC_MODEL=<modell-id> oder SUMMARY_MODEL=<modell-id>")
        err("  → Aktuelle Modell-IDs: https://docs.anthropic.com/en/docs/about-claude/models")
    elif isinstance(e, AuthenticationError):
        err("API-Key ungültig — ANTHROPIC_API_KEY prüfen.")
    elif isinstance(e, RateLimitError):
        err("Rate-Limit erreicht — kurz warten und erneut versuchen.")
    else:
        err(f"API-Fehler ({type(e).__name__}): {e}")


# Modell-Overrides pro Stufe (Standard: SUMMARY_MODEL)
SUMMARY_LEVEL_MODELS = {
    7: TOC_MODEL,  # Tiefenanalyse braucht Sonnet
}

SUMMARY_LEVELS = {
    1: ("sehr_knapp", "sehr knapp",
        "Fasse das Kernthema in maximal 2 Sätzen zusammen. Kein weiteres Detail.",
        800),
    2: ("knapp", "knapp",
        "Schreibe einen Absatz (4–6 Sätze) mit dem wesentlichen Inhalt. Keine Aufzählungen.",
        1200),
    3: ("kurz", "kurz",
        "Schreibe einen einleitenden Absatz (3–4 Sätze), dann 5–8 Stichpunkte zu den wichtigsten Unterthemen.",
        2000),
    4: ("normal", "normal",
        "Schreibe einen einleitenden Absatz (3–4 Sätze), dann Stichpunkte zu den Hauptthemen, je mit 2–3 Unterdetails.",
        2500),
    5: ("tief", "tief",
        "Schreibe zunächst einen strukturierten Überblick mit einleitendem Absatz und Stichpunkten zu den Hauptthemen "
        "(wie Stufe 4). Füge danach einen Abschnitt '**Offene Punkte / Vertiefung**' hinzu: "
        "Benenne konkret, welche im Transkript angedeuteten Aspekte, Widersprüche oder Fragen "
        "in der obigen Zusammenfassung zu kurz kommen, und beantworte sie mit dem konkreten Inhalt aus dem Transkript. "
        "Keine allgemeinen Formulierungen — nur was tatsächlich im Transkript steht.",
        3500),
    6: ("schwerpunkt", "Schwerpunkte",
        None,  # dynamisch durch _build_level6_instr(keywords) ersetzt
        4000),
    7: ("tiefenanalyse", "Tiefenanalyse",
        (
            "Erstelle eine vollständige Tiefenanalyse.\n"
            "Struktur:\n"
            "- Einleitender Absatz: Thema, erkennbarer Kontext, Sprecher/Gesprächspartner\n"
            "- Thematische Abschnitte mit **Zwischenüberschriften**: Alle inhaltlich bedeutsamen Punkte "
            "vollständig — Argumente, Behauptungen, Beispiele, Zahlen, Namen, Zitate und konkrete Aussagen. "
            "Kein relevanter Aspekt wird übergangen.\n"
            "- Wenn du auf Basis des Transkripts Querverbindungen, Widersprüche, Lücken oder Weiterführendes "
            "erkennst, das sich inhaltlich aufdrängt: eingerückter Block '> **Anm.:** …' — "
            "nur wenn wirklich inhaltlich begründet, keine allgemeinen Kommentare.\n"
            "- Abschlussparagraph: Kernaussage, offene Fragen, Strittiges.\n"
            "Keine Einleitung wie 'Hier ist die Analyse'. Kein Fließtext ohne Gliederung."
        ),
        6000),
}


def _build_level6_instr(keywords):
    """Prompt für Stufe 6 (Schwerpunkte) aus Keyword-Liste."""
    kw_str = ", ".join(f'„{k.strip()}"' for k in keywords if k.strip())
    base = (
        "Schreibe zunächst einen strukturierten Überblick mit einleitendem Absatz und Stichpunkten "
        "zu den Hauptthemen (wie Stufe 4). "
        "Füge danach einen Abschnitt '**Offene Punkte / Vertiefung**' hinzu: "
        "Benenne konkret, welche im Transkript angedeuteten Aspekte, Widersprüche oder Fragen "
        "in der obigen Zusammenfassung zu kurz kommen, und beantworte sie mit dem konkreten Inhalt aus dem Transkript. "
        "Keine allgemeinen Formulierungen — nur was tatsächlich im Transkript steht. "
    )
    if kw_str:
        return (
            base
            + f"Füge abschließend einen Abschnitt '**Schwerpunkte**' hinzu, der gezielt auf folgende Themen eingeht: {kw_str}. "
            "Nutze ausschließlich konkreten Inhalt aus dem Transkript — keine Spekulation, keine allgemeinen Aussagen. "
            "Wenn ein Schwerpunkt im Transkript nicht vorkommt, benenne das kurz."
        )
    return base + (
        "Füge abschließend einen Abschnitt '**Schwerpunkte**' hinzu und benenne die wichtigsten "
        "inhaltlichen Aspekte, die besondere Aufmerksamkeit verdienen."
    )


# ─── Ausgabe-Helfer ───────────────────────────────────────────────────────────
# ANSI-Codes werden von panel_server._Writer() ohnehin gestrippt — bleiben für
# lokales Debugging und Docker-Logs lesbar.

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RED    = "\033[91m"
BLUE   = "\033[94m"

def c(text, *codes): return "".join(codes) + str(text) + RESET
def header(text):    print(f"\n{c('  ' + text, BOLD, CYAN)}\n  {'─' * len(text)}")
def ok(text):        print(f"  {c('✓', GREEN, BOLD)} {text}")
def warn(text):      print(f"  {c('!', YELLOW, BOLD)} {text}")
def err(text):       print(f"  {c('✗', RED, BOLD)} {text}")
def info(text):      print(f"  {c('·', DIM)} {text}")


def update_ytdlp():
    """Aktualisiert yt-dlp via pip, still im Hintergrund."""
    print(f"  {c('↻', CYAN, BOLD)} Aktualisiere yt-dlp …", end="", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "--upgrade",
         "yt-dlp", "--break-system-packages"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"\r  {c('✓', GREEN, BOLD)} yt-dlp aktualisiert.          ")
    else:
        print(f"\r  {c('!', YELLOW, BOLD)} yt-dlp-Update fehlgeschlagen (weiter mit installierter Version).")


# ─── Systemerkennung ──────────────────────────────────────────────────────────

def detect_system():
    import psutil
    mem      = psutil.virtual_memory()
    ram_gb   = mem.total / 1024**3
    avail_gb = mem.available / 1024**3
    cpu_count = os.cpu_count() or 2

    has_cuda = False
    has_gpu  = False
    gpu_name = "keine dedizierte GPU erkannt"

    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0 and r.stdout.strip():
                gpu_name  = r.stdout.strip().splitlines()[0]
                has_cuda  = True
                has_gpu   = True
        except Exception:
            pass

    if not has_gpu and shutil.which("rocminfo"):
        try:
            r = subprocess.run(["rocminfo"], capture_output=True, text=True, timeout=5)
            if "GPU" in r.stdout:
                gpu_name = "AMD ROCm GPU"
                has_gpu  = True
        except Exception:
            pass

    return {
        "ram_gb":    ram_gb,
        "avail_gb":  avail_gb,
        "cpu_count": cpu_count,
        "has_cuda":  has_cuda,
        "has_gpu":   has_gpu,
        "gpu_name":  gpu_name,
    }


def recommend_params(sys_info):
    """Leitet optimale Whisper-Parameter aus Systeminfo ab."""
    avail = sys_info["avail_gb"]
    cpus  = sys_info["cpu_count"]

    if avail >= 8:
        model, model_note = "medium",  "hohe Qualität"
    elif avail >= 4:
        model, model_note = "small",   "sehr gute Qualität"
    elif avail >= 2:
        model, model_note = "base",    "gute Qualität"
    else:
        model, model_note = "tiny",    "schnell, eingeschränkte Qualität"

    if sys_info["has_cuda"]:
        device, compute = "cuda", "float16"
    else:
        device, compute = "cpu",  "int8"

    threads = min(cpus, 8) if device == "cpu" else 0

    return {
        "model":      model,
        "model_note": model_note,
        "device":     device,
        "compute":    compute,
        "threads":    threads,
    }


# ─── Audio-Extraktion ─────────────────────────────────────────────────────────

def download_audio(url, tmp_dir, keep=None, output_dir=None):
    """Lädt Audio via yt-dlp herunter. keep: None/opus/480p/original."""
    import yt_dlp

    _js = {"js_runtimes": {"nodejs": {}}}

    if keep == "480p":
        out_template = str(Path(tmp_dir) / "video.%(ext)s")
        ydl_opts = {
            "format":      "bestvideo[height<=480]+bestaudio/best[height<=480]",
            "outtmpl":     out_template,
            "quiet":       False,
            "no_warnings": False,
            **_js,
        }
        print()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        for f in Path(tmp_dir).iterdir():
            if f.suffix in (".mp4", ".webm", ".mkv") and "video" in f.stem:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                dest = Path(output_dir) / f.name
                shutil.copy2(str(f), str(dest))
                ok(f"Video gespeichert: {dest}")
                break
        audio_opts = {
            "format":    "bestaudio/best",
            "outtmpl":   str(Path(tmp_dir) / "audio.%(ext)s"),
            "quiet":     True,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
            **_js,
        }
        with yt_dlp.YoutubeDL(audio_opts) as ydl:
            ydl.download([url])
    elif keep == "opus":
        out_template = str(Path(tmp_dir) / "audio.%(ext)s")
        ydl_opts = {
            "format":      "bestaudio/best",
            "outtmpl":     out_template,
            "quiet":       False,
            "no_warnings": False,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "opus"}],
            **_js,
        }
        print()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        opus = Path(tmp_dir) / "audio.opus"
        if opus.exists() and output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            dest = Path(output_dir) / opus.name
            shutil.copy2(str(opus), str(dest))
            ok(f"Audio gespeichert: {dest}")
        wav_out = str(Path(tmp_dir) / "audio.wav")
        subprocess.run([
            "ffmpeg", "-y", "-i", str(opus),
            "-ar", "16000", "-ac", "1", "-f", "wav", wav_out,
            "-loglevel", "warning"
        ])
    else:
        out_template = str(Path(tmp_dir) / "audio.%(ext)s")
        ydl_opts = {
            "format":      "bestaudio/best",
            "outtmpl":     out_template,
            "quiet":       False,
            "no_warnings": False,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
            **_js,
        }
        print()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    wav = Path(tmp_dir) / "audio.wav"
    if wav.exists():
        return str(wav)
    for f in Path(tmp_dir).iterdir():
        if f.suffix in (".wav", ".mp3", ".m4a", ".opus", ".webm"):
            return str(f)
    raise FileNotFoundError("Audio-Extraktion fehlgeschlagen.")


def extract_url_id(url):
    import re
    yt = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,12})", url)
    if yt:
        return yt.group(1)
    vimeo = re.search(r"vimeo\.com/(\d+)", url)
    if vimeo:
        return vimeo.group(1)
    clean = re.sub(r"[^A-Za-z0-9]", "", url)
    return clean[-8:] if len(clean) >= 8 else clean


def clean_youtube_url(url):
    """Bereinigt YouTube-URLs: behält nur v=, list=, t=, index=."""
    try:
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        parsed = urlparse(url)
        if "youtube.com" not in parsed.netloc and "youtu.be" not in parsed.netloc:
            return url
        if "youtu.be" in parsed.netloc:
            params = parse_qs(parsed.query)
            kept   = {k: v[0] for k, v in params.items() if k in ("t",)}
            return urlunparse(parsed._replace(query=urlencode(kept)))
        params = parse_qs(parsed.query)
        kept   = {k: v[0] for k, v in params.items() if k in ("v", "list", "t", "index")}
        return urlunparse(parsed._replace(query=urlencode(kept)))
    except Exception:
        return url


def slugify(text):
    import re, unicodedata
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:40]


def fetch_yt_title(url):
    import yt_dlp
    ydl_opts = {"quiet": True, "skip_download": True, "js_runtimes": {"nodejs": {}}}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            meta = ydl.extract_info(url, download=False)
            return meta.get("title", "")
    except Exception:
        return ""


def extract_audio_local(video_path, tmp_dir, keep=None, output_dir=None):
    """Extrahiert Audio aus lokaler Videodatei via ffmpeg."""
    out = str(Path(tmp_dir) / "audio.wav")

    if keep == "480p" and output_dir:
        ext      = Path(video_path).suffix or ".mp4"
        dest_480 = Path(output_dir) / f"{Path(video_path).stem}_480p{ext}"
        info("Erstelle 480p-Version …")
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path,
            "-vf", "scale=-1:480", "-c:v", "libx264", "-c:a", "aac",
            str(dest_480), "-loglevel", "warning"
        ])
        ok(f"480p gespeichert: {dest_480}")
    elif keep == "original" and output_dir:
        dest_orig = Path(output_dir) / Path(video_path).name
        shutil.copy2(video_path, str(dest_orig))
        ok(f"Original gespeichert: {dest_orig}")
    elif keep == "opus" and output_dir:
        dest_opus = Path(output_dir) / f"{Path(video_path).stem}.opus"
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path,
            "-c:a", "libopus", "-b:a", "128k",
            str(dest_opus), "-loglevel", "warning"
        ])
        ok(f"Opus gespeichert: {dest_opus}")

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-ar", "16000", "-ac", "1", "-f", "wav", out,
        "-loglevel", "warning"
    ]
    print()
    info(f"Extrahiere Audio: {video_path}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg-Fehler bei Audio-Extraktion.")
    return out


# ─── Fortschritt ──────────────────────────────────────────────────────────────

def get_audio_duration(audio_path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True, timeout=10
        )
        return float(r.stdout.strip())
    except Exception:
        return None


def fmt_dur(seconds):
    seconds = int(seconds)
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def progress_bar(current, total, width=28):
    frac   = min(current / total, 1.0) if total else 0
    filled = int(frac * width)
    bar    = "█" * filled + "░" * (width - filled)
    pct    = int(frac * 100)
    return bar, pct


# ─── Transkription ────────────────────────────────────────────────────────────

def transcribe(audio_path, params, language, output_dir, base_name, formats,
               task="transcribe", model_instance=None, live_editor=False,
               models_path=None, stop_event=None):
    from faster_whisper import WhisperModel
    import time
    import threading

    header("Transkription läuft …")
    info(f"Modell:  {params['model']}  |  Gerät: {params['device']}  |  Compute: {params['compute']}")
    info(f"Sprache: {language or 'automatisch erkennen'}  |  Aufgabe: {task}")

    duration = get_audio_duration(audio_path)
    if duration:
        info(f"Dauer:   {fmt_dur(duration)}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    info(f"Ausgabe: {output_dir}/")
    print()

    kwargs = {
        "device":       params["device"],
        "compute_type": params["compute"],
    }
    if params["threads"]:
        kwargs["cpu_threads"] = params["threads"]

    spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    if model_instance is not None:
        model = model_instance
        ok("Modell wiederverwendet (Batch-Modus).")
    else:
        spinner_active = True

        def spin():
            i = 0
            while spinner_active:
                ch = spinner_chars[i % len(spinner_chars)]
                print(f"\r  {c(ch, CYAN, BOLD)} Lade Modell '{params['model']}' …", end="", flush=True)
                time.sleep(0.1)
                i += 1

        t = threading.Thread(target=spin, daemon=True)
        t.start()
        try:
            whisper_dir = str(models_path / "whisper") if models_path else None
            model = WhisperModel(params["model"], download_root=whisper_dir, **kwargs)
        finally:
            spinner_active = False
            t.join(timeout=0.3)
            print(f"\r  {c('✓', GREEN, BOLD)} Modell geladen.                              ")

    seg_kwargs = {"task": task}
    if language:
        seg_kwargs["language"] = language
    beam      = params.get("beam_size", 5)
    cond_prev = params.get("condition_on_previous_text", True)
    temp      = params.get("temperature", None)

    t_kwargs = {"beam_size": beam, "condition_on_previous_text": cond_prev}
    if temp is not None:
        t_kwargs["temperature"] = temp

    spinner_active = True

    def spin2():
        i = 0
        while spinner_active:
            ch = spinner_chars[i % len(spinner_chars)]
            print(f"\r  {c(ch, CYAN, BOLD)} Erstes Segment wird verarbeitet …", end="", flush=True)
            time.sleep(0.1)
            i += 1

    t2 = threading.Thread(target=spin2, daemon=True)
    t2.start()

    segments, info_obj = model.transcribe(audio_path, **t_kwargs, **seg_kwargs)
    segments_iter = iter(segments)

    try:
        first_seg = next(segments_iter)
        spinner_active = False
        t2.join(timeout=0.3)
        print(f"\r  {c('✓', GREEN, BOLD)} Verarbeitung läuft …                              ")
        print()
    except StopIteration:
        spinner_active = False
        t2.join(timeout=0.3)
        print()
        ok("Keine Segmente gefunden.")
        return [], None, model

    # ── Live-txt vorbereiten (progressives Schreiben für Panel-Polling) ────────
    live_txt_path = None
    live_txt_file = None

    if live_editor and "txt" in formats:
        live_txt_path = output_dir / f"{base_name}.txt"
        live_txt_file = open(live_txt_path, "w", encoding="utf-8")

    def write_seg_live(seg):
        if live_txt_file:
            live_txt_file.write(seg.text.strip() + "\n")
            live_txt_file.flush()

    # ── Segmente einsammeln mit Fortschrittsbalken ─────────────────────────────
    seg_list  = [first_seg]
    t_start   = time.time()
    last_text = first_seg.text.strip()

    write_seg_live(first_seg)

    try:
        cols = os.get_terminal_size().columns
    except Exception:
        cols = 80

    def print_progress(seg):
        nonlocal last_text
        last_text = seg.text.strip()
        if duration:
            bar, pct = progress_bar(seg.end, duration)
            elapsed  = time.time() - t_start
            eta_str  = fmt_dur((elapsed / (pct / 100)) - elapsed) if pct > 2 else "--:--"
            pos_str  = f"{fmt_dur(seg.end)} / {fmt_dur(duration)}"
            snippet  = last_text[:30] + "…" if len(last_text) > 30 else last_text
            line     = f"  \033[96m[{bar}]\033[0m {pct:3d}%  {pos_str}  ETA {eta_str}  \033[2m{snippet}\033[0m"
            print(f"\r{line[:cols-1]:<{cols-1}}", end="", flush=True)
        else:
            elapsed = time.time() - t_start
            snippet = last_text[:40] + "…" if len(last_text) > 40 else last_text
            print(f"\r  {c(f'[{fmt_dur(elapsed)}]', DIM)}  {snippet:<50}", end="", flush=True)

    print_progress(first_seg)

    for seg in segments_iter:
        if stop_event and stop_event.is_set():
            print()
            ok("Transkription vorzeitig gestoppt — verarbeite bisher gesammelte Segmente …")
            break
        seg_list.append(seg)
        write_seg_live(seg)
        print_progress(seg)

    print()

    if live_txt_file:
        live_txt_file.close()

    print()

    detected_lang  = getattr(info_obj, "language", "?")
    elapsed_total  = time.time() - t_start
    ok(f"Erkannte Sprache: {detected_lang}  |  Transkriptionszeit: {fmt_dur(elapsed_total)}")

    # ── Ausgabe schreiben ──────────────────────────────────────────────────────
    written = []

    if "txt" in formats:
        txt_path = output_dir / f"{base_name}.txt"
        if live_txt_path and live_txt_path == txt_path:
            pass  # bereits live geschrieben
        else:
            with open(txt_path, "w", encoding="utf-8") as f:
                for seg in seg_list:
                    f.write(seg.text.strip() + "\n")
        written.append(str(txt_path))

    if "srt" in formats:
        srt_path = output_dir / f"{base_name}.srt"
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(seg_list, 1):
                f.write(f"{i}\n")
                f.write(f"{fmt_time_srt(seg.start)} --> {fmt_time_srt(seg.end)}\n")
                f.write(seg.text.strip() + "\n\n")
        written.append(str(srt_path))

    if "vtt" in formats:
        vtt_path = output_dir / f"{base_name}.vtt"
        with open(vtt_path, "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")
            for seg in seg_list:
                f.write(f"{fmt_time_vtt(seg.start)} --> {fmt_time_vtt(seg.end)}\n")
                f.write(seg.text.strip() + "\n\n")
        written.append(str(vtt_path))

    header("Fertig!")
    for w in written:
        ok(f"Gespeichert: {w}")

    return written, detected_lang, model


# ─── TOC-Generierung via Anthropic API ────────────────────────────────────────

def generate_toc(source_path, language, title, output_dir, base_name, source_url=None):
    """Generiert ein Inhaltsverzeichnis aus SRT oder txt via Anthropic API."""
    if not ANTHROPIC_API_KEY:
        warn("Kein ANTHROPIC_API_KEY gesetzt — TOC-Generierung nicht verfügbar.")
        return None
    try:
        import anthropic as anthropic_sdk
    except ImportError:
        err("anthropic-Paket fehlt  →  pip install anthropic --break-system-packages")
        return None

    is_srt = str(source_path).endswith(".srt")
    with open(source_path, encoding="utf-8") as f:
        content = f.read()

    info(f"TOC-Generierung: Quelle {'SRT' if is_srt else 'txt'}, {len(content)} Zeichen …")

    if is_srt:
        prompt = (
            f"Du bekommst eine vollständige SRT-Untertiteldatei eines Videos/Gesprächs "
            f"mit dem Titel '{title}'.\n"
            f"Erstelle ein Inhaltsverzeichnis mit GENAU 8 bis 12 Kapitelmarken — nicht mehr.\n"
            f"Lies das gesamte Transkript durch, erkenne die Gesamtstruktur, "
            f"fasse kleinere Themenwechsel zusammen.\n"
            f"Nur wirklich bedeutende Zäsuren werden als Kapitel markiert.\n"
            f"Format (eine Zeile pro Kapitel): - [MM:SS] Kurzer Kapiteltitel\n"
            f"Verwende den Timestamp des ersten Satzes des neuen Themas.\n"
            f"Sprache des TOC: {language or 'wie im Transkript'}.\n"
            f"Nur das TOC ausgeben — keine Einleitung, keine Erklärung, "
            f"keine Leerzeilen zwischen Einträgen.\n\n{content}"
        )
    else:
        prompt = (
            f"Du bekommst ein vollständiges Transkript eines Videos/Gesprächs "
            f"mit dem Titel '{title}'.\n"
            f"Erstelle ein Inhaltsverzeichnis mit GENAU 8 bis 12 Kapiteln — nicht mehr.\n"
            f"Lies das gesamte Transkript durch, erkenne die Gesamtstruktur, "
            f"fasse kleinere Themenwechsel zusammen.\n"
            f"Nur wirklich bedeutende Zäsuren werden als Kapitel markiert.\n"
            f"Format (eine Zeile pro Kapitel): - Kurzer Kapiteltitel\n"
            f"Sprache: {language or 'wie im Text'}.\n"
            f"Nur das TOC ausgeben — keine Einleitung, keine Erklärung, "
            f"keine Leerzeilen zwischen Einträgen.\n\n{content}"
        )

    client = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=TOC_MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        _handle_api_error(e, TOC_MODEL)
        return None
    toc_text = response.content[0].text.strip()

    lang_slug = _SUMMARY_LANG_SLUG.get(language or "",
                (language or "xx")[:8].lower().replace(" ", "_").replace("-", "_"))
    toc_path = Path(output_dir) / f"{base_name}_toc_{lang_slug}.md"
    with open(toc_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        if source_url:
            f.write(f"{source_url}\n\n")
        f.write(f"## Inhaltsverzeichnis\n\n")
        f.write(toc_text + "\n")

    ok(f"TOC gespeichert: {toc_path}")
    return str(toc_path)


# ─── Zusammenfassung via Anthropic API ────────────────────────────────────────

_SUMMARY_LANG_SLUG = {
    "Deutsch":      "de", "Englisch":    "en", "Französisch": "fr",
    "Spanisch":     "es", "Italienisch": "it", "Russisch":    "ru",
    "Portugiesisch":"pt", "Chinesisch":  "zh", "Polnisch":    "pl",
    "Niederländisch":"nl",
}


def generate_summary(source_path, language, title, output_dir, base_name, level,
                     source_url=None, focus_keywords=None,
                     context_summary_text=None, context_questions=None):
    """Generiert eine Zusammenfassung aus SRT oder txt via Anthropic API.
    level: 1–7; bei Level 6 focus_keywords=[...] sinnvoll; Level 7 nutzt Sonnet.
    """
    if not ANTHROPIC_API_KEY:
        warn("Kein ANTHROPIC_API_KEY gesetzt — Zusammenfassung nicht verfügbar.")
        return None
    try:
        import anthropic as anthropic_sdk
    except ImportError:
        err("anthropic-Paket fehlt  →  pip install anthropic --break-system-packages")
        return None

    _, level_label, level_instr, max_tokens = SUMMARY_LEVELS[level]
    if level == 6:
        level_instr = _build_level6_instr(focus_keywords or [])
    is_srt = str(source_path).endswith(".srt")

    with open(source_path, encoding="utf-8") as f:
        content = f.read()

    ctx_hint = " + Kontext" if context_summary_text else ""
    info(f"Zusammenfassung L{level} ({level_label}){ctx_hint} — {language}: {len(content)} Zeichen …")

    if context_summary_text:
        _ctx_q = ""
        if context_questions:
            _q_str = ", ".join(f'„{q}"' for q in context_questions if q)
            _ctx_q = f"Gehe dabei besonders auf folgende neue Stich-/Fragepunkte ein: {_q_str}\n"
        prompt = (
            f"Du bekommst {'eine SRT-Untertiteldatei' if is_srt else 'ein Transkript'} "
            f"eines Videos/Gesprächs mit dem Titel '{title}' "
            f"sowie eine bereits erstellte Zusammenfassung desselben.\n"
            f"Nutze die vorhandene Zusammenfassung als Ausgangspunkt — erkenne Lücken, "
            f"vertiefe gezielt, ergänze Aspekte die darin zu kurz kommen oder fehlen.\n"
            f"Erstelle eine neue, tiefere Zusammenfassung auf {language}.\n"
            f"Anweisung: {level_instr}\n"
            f"{_ctx_q}"
            f"Nur die Zusammenfassung ausgeben — keine Einleitung, keine Meta-Kommentare.\n\n"
            f"## Vorhandene Zusammenfassung\n\n{context_summary_text}\n\n"
            f"## Transkript\n\n{content}"
        )
    else:
        prompt = (
            f"Du bekommst {'eine SRT-Untertiteldatei' if is_srt else 'ein Transkript'} "
            f"eines Videos/Gesprächs mit dem Titel '{title}'.\n"
            f"Erstelle eine Zusammenfassung auf {language}.\n"
            f"Anweisung: {level_instr}\n"
            f"Nur die Zusammenfassung ausgeben — keine Einleitung wie "
            f"'Hier ist die Zusammenfassung', keine Meta-Kommentare.\n\n{content}"
        )

    model  = SUMMARY_LEVEL_MODELS.get(level, SUMMARY_MODEL)
    client = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        _handle_api_error(e, model)
        return None
    summary_text = response.content[0].text.strip()

    lang_slug = _SUMMARY_LANG_SLUG.get(language, language[:8].lower().replace(" ", "_"))
    out_path  = Path(output_dir) / f"{base_name}_summary_L{level}_{lang_slug}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        if source_url:
            f.write(f"{source_url}\n\n")
        f.write(f"**Zusammenfassung** — Stufe {level} ({level_label}), {language}\n\n")
        f.write(summary_text + "\n")

    ok(f"Zusammenfassung gespeichert: {out_path}")
    return str(out_path)


# ─── Kombinierte TOC + Zusammenfassung ────────────────────────────────────────

def _extract_xml_tag(text, tag):
    import re
    m = re.search(rf'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
    return m.group(1).strip() if m else None


def generate_toc_and_summaries(source_path, toc_language, summary_levels, summary_language,
                                title, output_dir, base_name, source_url=None, focus_keywords=None,
                                context_summary_text=None, context_questions=None):
    """Kombinierter API-Call: TOC + alle Zusammenfassungs-Stufen für eine Sprache.
    Fällt bei Parse-Fehlern auf Einzelaufrufe zurück.
    """
    if not ANTHROPIC_API_KEY:
        warn("Kein ANTHROPIC_API_KEY — kombinierte Generierung nicht verfügbar.")
        return None, []
    try:
        import anthropic as anthropic_sdk
    except ImportError:
        err("anthropic-Paket fehlt  →  pip install anthropic --break-system-packages")
        return None, []

    is_srt = str(source_path).endswith(".srt")
    with open(source_path, encoding="utf-8") as f:
        content = f.read()

    lvl_labels = "+".join(f"L{l}({SUMMARY_LEVELS[l][1]})" for l in summary_levels)
    info(f"Kombiniert: TOC ({toc_language}) + Zusammenfassung {lvl_labels} ({summary_language}): {len(content)} Zeichen …")

    sections = []
    if is_srt:
        toc_instr = (
            f"Inhaltsverzeichnis auf {toc_language} mit GENAU 8 bis 12 Kapitelmarken.\n"
            f"Format (eine Zeile pro Kapitel): - [MM:SS] Kurzer Kapiteltitel\n"
            f"Timestamp = erster Satz des neuen Themas. Nur bedeutende Zäsuren.\n"
            f"Keine Einleitung, keine Leerzeilen zwischen Einträgen."
        )
    else:
        toc_instr = (
            f"Inhaltsverzeichnis auf {toc_language} mit GENAU 8 bis 12 Kapiteln.\n"
            f"Format (eine Zeile pro Kapitel): - Kurzer Kapiteltitel\n"
            f"Nur bedeutende Zäsuren. Keine Einleitung, keine Leerzeilen."
        )
    sections.append(f"<toc>\n{toc_instr}\n</toc>")

    for lvl in summary_levels:
        _, _, instr, _ = SUMMARY_LEVELS[lvl]
        if lvl == 6:
            instr = _build_level6_instr(focus_keywords or [])
        sections.append(
            f"<summary_L{lvl}>\n"
            f"Zusammenfassung auf {summary_language}. Anweisung: {instr}\n"
            f"Keine Einleitung wie 'Hier ist die Zusammenfassung'.\n"
            f"</summary_L{lvl}>"
        )

    src_desc = "SRT-Untertiteldatei" if is_srt else "Transkript"
    if context_summary_text:
        _ctx_q = ""
        if context_questions:
            _q_str = ", ".join(f'„{q}"' for q in context_questions if q)
            _ctx_q = f"Für die Zusammenfassungen: gehe besonders auf folgende neue Stich-/Fragepunkte ein: {_q_str}\n"
        prompt = (
            f"Du bekommst eine {src_desc} des Videos/Gesprächs '{title}' "
            f"sowie eine bereits erstellte Zusammenfassung desselben.\n"
            f"Für die Zusammenfassungen: nutze die vorhandene Zusammenfassung als Ausgangspunkt — "
            f"erkenne Lücken, vertiefe gezielt, ergänze Aspekte die darin zu kurz kommen.\n"
            f"{_ctx_q}"
            f"Erstelle folgende Ausgaben. Halte dich EXAKT an die XML-Tags als Trennmarker.\n"
            f"Kein Text außerhalb der Tags.\n\n"
            + "\n\n".join(sections)
            + f"\n\n## Vorhandene Zusammenfassung\n\n{context_summary_text}\n\n"
            + f"## Transkript\n\n{content}"
        )
    else:
        prompt = (
            f"Du bekommst eine {src_desc} des Videos/Gesprächs '{title}'.\n"
            f"Erstelle folgende Ausgaben. Halte dich EXAKT an die XML-Tags als Trennmarker.\n"
            f"Kein Text außerhalb der Tags.\n\n"
            + "\n\n".join(sections)
            + f"\n\n{content}"
        )

    sum_tokens = sum(SUMMARY_LEVELS[lvl][3] for lvl in summary_levels)
    toc_tokens = 600
    max_tokens = min(sum_tokens + toc_tokens, 8000)

    # Wenn Stufe 7 dabei: Sonnet für den ganzen kombinierten Call
    use_model = TOC_MODEL if any(lvl in SUMMARY_LEVEL_MODELS for lvl in summary_levels) else TOC_MODEL
    client = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=use_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        _handle_api_error(e, use_model)
        return None, []
    raw = response.content[0].text

    written_summaries = []

    toc_path = None
    toc_text = _extract_xml_tag(raw, "toc")
    if toc_text:
        toc_lang_slug = _SUMMARY_LANG_SLUG.get(toc_language or "",
                        (toc_language or "xx")[:8].lower().replace(" ", "_").replace("-", "_"))
        toc_file = Path(output_dir) / f"{base_name}_toc_{toc_lang_slug}.md"
        with open(toc_file, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n")
            if source_url:
                f.write(f"{source_url}\n\n")
            f.write(f"## Inhaltsverzeichnis\n\n{toc_text}\n")
        ok(f"TOC gespeichert: {toc_file}")
        toc_path = str(toc_file)
    else:
        warn("TOC: kein Inhalt im API-Response — Fallback auf Einzelaufruf.")
        toc_path = generate_toc(source_path, language=toc_language, title=title,
                                output_dir=output_dir, base_name=base_name,
                                source_url=source_url)

    for lvl in summary_levels:
        sum_text = _extract_xml_tag(raw, f"summary_L{lvl}")
        _, level_label, _, _ = SUMMARY_LEVELS[lvl]
        if sum_text:
            lang_slug = _SUMMARY_LANG_SLUG.get(summary_language,
                        summary_language[:8].lower().replace(" ", "_"))
            out_path = Path(output_dir) / f"{base_name}_summary_L{lvl}_{lang_slug}.md"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n\n")
                if source_url:
                    f.write(f"{source_url}\n\n")
                f.write(f"**Zusammenfassung** — Stufe {lvl} ({level_label}), {summary_language}\n\n")
                f.write(sum_text + "\n")
            ok(f"Zusammenfassung gespeichert: {out_path}")
            written_summaries.append(str(out_path))
        else:
            warn(f"Zusammenfassung L{lvl}: kein Inhalt — Fallback auf Einzelaufruf.")
            p = generate_summary(source_path, summary_language, title, output_dir, base_name, lvl,
                                 source_url=source_url, focus_keywords=focus_keywords,
                                 context_summary_text=context_summary_text,
                                 context_questions=context_questions)
            if p:
                written_summaries.append(p)

    return toc_path, written_summaries


def generate_summaries_multi(source_path, language, levels, title, output_dir, base_name,
                             source_url=None, focus_keywords=None,
                             context_summary_text=None, context_questions=None):
    """Mehrere Zusammenfassungs-Stufen für eine Sprache in einem API-Call."""
    if len(levels) == 1:
        p = generate_summary(source_path, language, title, output_dir, base_name, levels[0],
                             source_url=source_url, focus_keywords=focus_keywords,
                             context_summary_text=context_summary_text,
                             context_questions=context_questions)
        return [p] if p else []

    if not ANTHROPIC_API_KEY:
        warn("Kein ANTHROPIC_API_KEY — Zusammenfassung nicht verfügbar.")
        return []
    try:
        import anthropic as anthropic_sdk
    except ImportError:
        err("anthropic-Paket fehlt  →  pip install anthropic --break-system-packages")
        return []

    is_srt = str(source_path).endswith(".srt")
    with open(source_path, encoding="utf-8") as f:
        content = f.read()

    lvl_labels = "+".join(f"L{l}({SUMMARY_LEVELS[l][1]})" for l in levels)
    info(f"Zusammenfassung {lvl_labels} ({language}): {len(content)} Zeichen …")

    sections = []
    for lvl in levels:
        _, _, instr, _ = SUMMARY_LEVELS[lvl]
        if lvl == 6:
            instr = _build_level6_instr(focus_keywords or [])
        sections.append(
            f"<summary_L{lvl}>\n"
            f"Zusammenfassung auf {language}. Anweisung: {instr}\n"
            f"Keine Einleitung wie 'Hier ist die Zusammenfassung'.\n"
            f"</summary_L{lvl}>"
        )

    src_desc = "SRT-Untertiteldatei" if is_srt else "Transkript"
    if context_summary_text:
        _ctx_q = ""
        if context_questions:
            _q_str = ", ".join(f'„{q}"' for q in context_questions if q)
            _ctx_q = f"Gehe dabei besonders auf folgende neue Stich-/Fragepunkte ein: {_q_str}\n"
        prompt = (
            f"Du bekommst eine {src_desc} des Videos/Gesprächs '{title}' "
            f"sowie eine bereits erstellte Zusammenfassung desselben.\n"
            f"Nutze die Zusammenfassung als Ausgangspunkt — erkenne Lücken, vertiefe gezielt, "
            f"ergänze Aspekte die darin zu kurz kommen oder fehlen.\n"
            f"{_ctx_q}"
            f"Erstelle folgende Ausgaben. Halte dich EXAKT an die XML-Tags.\n"
            f"Kein Text außerhalb der Tags.\n\n"
            + "\n\n".join(sections)
            + f"\n\n## Vorhandene Zusammenfassung\n\n{context_summary_text}\n\n"
            + f"## Transkript\n\n{content}"
        )
    else:
        prompt = (
            f"Du bekommst eine {src_desc} des Videos/Gesprächs '{title}'.\n"
            f"Erstelle folgende Ausgaben. Halte dich EXAKT an die XML-Tags.\n"
            f"Kein Text außerhalb der Tags.\n\n"
            + "\n\n".join(sections)
            + f"\n\n{content}"
        )

    max_tokens = min(sum(SUMMARY_LEVELS[lvl][3] for lvl in levels), 8000)
    use_model  = TOC_MODEL if any(lvl in SUMMARY_LEVEL_MODELS for lvl in levels) else SUMMARY_MODEL

    client   = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=use_model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text

    written = []
    for lvl in levels:
        sum_text = _extract_xml_tag(raw, f"summary_L{lvl}")
        _, level_label, _, _ = SUMMARY_LEVELS[lvl]
        if sum_text:
            lang_slug = _SUMMARY_LANG_SLUG.get(language,
                        language[:8].lower().replace(" ", "_"))
            out_path = Path(output_dir) / f"{base_name}_summary_L{lvl}_{lang_slug}.md"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n\n")
                if source_url:
                    f.write(f"{source_url}\n\n")
                f.write(f"**Zusammenfassung** — Stufe {lvl} ({level_label}), {language}\n\n")
                f.write(sum_text + "\n")
            ok(f"Zusammenfassung gespeichert: {out_path}")
            written.append(str(out_path))
        else:
            warn(f"Zusammenfassung L{lvl}: kein Inhalt — Fallback auf Einzelaufruf.")
            p = generate_summary(source_path, language, title, output_dir, base_name, lvl,
                                 source_url=source_url, focus_keywords=focus_keywords,
                                 context_summary_text=context_summary_text,
                                 context_questions=context_questions)
            if p:
                written.append(p)
    return written


def _run_api_postprocessing(written, detected_lang, lang_choice, task_choice,
                             generate_toc_flag, summary_levels, summary_langs,
                             title_raw, output_dir, base_name, source_url=None, focus_keywords=None):
    """Führt TOC- und/oder Zusammenfassungs-Generierung durch."""
    if not (generate_toc_flag or summary_levels):
        return
    if not ANTHROPIC_API_KEY:
        return
    try:
        import anthropic as _a  # noqa
    except ImportError:
        warn("anthropic-Paket fehlt — TOC/Zusammenfassung nicht verfügbar.")
        return

    srt_w = [w for w in written if w.endswith(".srt")]
    txt_w = [w for w in written if w.endswith(".txt")]
    src   = srt_w[0] if srt_w else (txt_w[0] if txt_w else None)

    if not src:
        if generate_toc_flag:
            warn("TOC: keine txt/srt-Datei gefunden.")
        if summary_levels:
            warn("Zusammenfassung: keine txt/srt-Datei gefunden.")
        return

    toc_lang_code = "en" if task_choice == "translate" else (lang_choice or detected_lang)
    toc_lang_name = LANG_NAMES.get(toc_lang_code, toc_lang_code or "Deutsch")

    if not summary_levels:
        header("Inhaltsverzeichnis wird generiert …")
        generate_toc(src, language=toc_lang_name, title=title_raw,
                     output_dir=output_dir, base_name=base_name, source_url=source_url)
        return

    lang_groups: dict = {}
    for lvl in summary_levels:
        for slang in (summary_langs or [None]):
            actual = slang if slang else toc_lang_name
            lang_groups.setdefault(actual, set()).add(lvl)

    for lang, lvls in lang_groups.items():
        lvl_list = sorted(lvls)
        if generate_toc_flag:
            header(f"TOC + Zusammenfassung ({lang}) — kombinierter API-Call …")
            generate_toc_and_summaries(src, lang, lvl_list, lang,
                                       title_raw, output_dir, base_name,
                                       source_url=source_url, focus_keywords=focus_keywords)
        else:
            header(f"Zusammenfassung ({lang}) wird generiert …")
            generate_summaries_multi(src, lang, lvl_list, title_raw, output_dir, base_name,
                                     source_url=source_url, focus_keywords=focus_keywords)


# ─── Helsinki-NLP Übersetzung ─────────────────────────────────────────────────

HELSINKI_PAIRS = {
    "de": ["en", "fr", "es", "it", "nl", "pl", "ru", "zh"],
    "en": ["de", "fr", "es", "it", "nl", "pl", "ru", "zh", "pt"],
    "fr": ["en", "de", "es", "it"],
    "es": ["en", "de", "fr"],
    "it": ["en", "de", "fr"],
    "ru": ["en", "de"],
    "zh": ["en"],
    "pl": ["en", "de"],
    "nl": ["en", "de"],
    "pt": ["en", "de"],
}

LANG_NAMES = {
    "de": "Deutsch", "en": "Englisch", "fr": "Französisch",
    "es": "Spanisch", "it": "Italienisch", "ru": "Russisch",
    "zh": "Chinesisch", "pl": "Polnisch", "nl": "Niederländisch",
    "pt": "Portugiesisch",
}


def helsinki_model_name(src, tgt):
    return f"Helsinki-NLP/opus-mt-{src}-{tgt}"


def available_translation_targets(src_lang):
    return HELSINKI_PAIRS.get(src_lang, [])


def translate_text(text_lines, src_lang, tgt_lang, output_dir, base_name, models_path=None):
    """Übersetzt eine Liste von Zeilen mit Helsinki-NLP und schreibt .txt."""
    try:
        from transformers import MarianMTModel, MarianTokenizer
    except ImportError:
        err("transformers nicht installiert  →  pip install transformers sentencepiece --break-system-packages")
        return None

    model_name   = helsinki_model_name(src_lang, tgt_lang)
    helsinki_dir = str(models_path / "helsinki") if models_path else None

    info(f"Lade Übersetzungsmodell: {model_name}")
    info("(Erstmaliger Download ~300 MB, danach gecacht)")
    print()

    # Offline-Modus nur setzen wenn dieses spezifische Modell tatsächlich gecacht ist
    if helsinki_dir:
        model_cache_name = f"models--{model_name.replace('/', '--')}"
        model_cache_path = Path(helsinki_dir) / model_cache_name
        if model_cache_path.exists():
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        else:
            os.environ.pop("TRANSFORMERS_OFFLINE", None)

    try:
        tokenizer = MarianTokenizer.from_pretrained(model_name, cache_dir=helsinki_dir)
        model     = MarianMTModel.from_pretrained(model_name, cache_dir=helsinki_dir)
    except Exception as e:
        err(f"Modell konnte nicht geladen werden: {e}")
        return None

    batch_size = 8
    translated = []
    total      = len(text_lines)

    try:
        cols = os.get_terminal_size().columns
    except Exception:
        cols = 80

    for i in range(0, total, batch_size):
        batch   = text_lines[i:i + batch_size]
        inputs  = tokenizer(batch, return_tensors="pt", padding=True, truncation=True, max_length=512)
        outputs = model.generate(**inputs)
        decoded = tokenizer.batch_decode(outputs, skip_special_tokens=True)
        translated.extend(decoded)

        pct    = min(int((i + batch_size) / total * 100), 100)
        bar, _ = progress_bar(i + batch_size, total, width=24)
        line   = f"  \033[96m[{bar}]\033[0m {pct:3d}%  {i + batch_size}/{total} Segmente"
        print(f"\r{line:<{cols-1}}", end="", flush=True)

    print()

    lang_label = LANG_NAMES.get(tgt_lang, tgt_lang)
    out_path = Path(output_dir) / f"{base_name}_{lang_label}.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        for line in translated:
            f.write(line.strip() + "\n")

    ok(f"Übersetzung gespeichert: {out_path}")
    return str(out_path)


# ─── Zeitformat-Helfer ────────────────────────────────────────────────────────

def fmt_time_srt(seconds):
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_time_vtt(seconds):
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _parse_multiselect(raw, max_val):
    """Parst '1', '2+3', '1+3+4' → sortierte Liste gültiger ints."""
    result = set()
    for part in raw.replace(",", "+").split("+"):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= max_val:
            result.add(int(part))
    return sorted(result)


def _parse_timecode(tc):
    """Parst MM:SS oder HH:MM:SS in Sekunden. Gibt None bei Fehler."""
    import re
    tc = tc.strip()
    m = re.fullmatch(r"(\d+):(\d{2}):(\d{2})", tc)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    m = re.fullmatch(r"(\d+):(\d{2})", tc)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.fullmatch(r"\d+", tc)
    if m:
        return int(tc)
    return None


def trim_audio(wav_path, start_sec, end_sec, tmp_dir):
    """Trimmt WAV-Datei mit ffmpeg."""
    out = str(Path(tmp_dir) / "audio_trim.wav")
    cmd = ["ffmpeg", "-y", "-i", wav_path]
    if start_sec is not None:
        cmd += ["-ss", str(start_sec)]
    if end_sec is not None:
        cmd += ["-to", str(end_sec)]
    cmd += ["-ar", "16000", "-ac", "1", "-f", "wav", out, "-loglevel", "warning"]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        warn("Beschnitt fehlgeschlagen — verwende ungekürzte Audio.")
        return wav_path
    s_str = fmt_dur(start_sec) if start_sec else "Anfang"
    e_str = fmt_dur(end_sec)   if end_sec   else "Ende"
    ok(f"Audio getrimmt: {s_str} → {e_str}")
    return out


# ─── Einzelverarbeitung ───────────────────────────────────────────────────────

def process_single(source, source_type, params, lang_choice, task_choice,
                   formats, base_dir, translation_src, translation_tgt,
                   model_instance=None, models_path=None,
                   live_editor=False, generate_toc_flag=False,
                   summary_levels=None, summary_langs=None, focus_keywords=None,
                   stop_event=None, on_output_dir=None):
    """
    Verarbeitet eine einzelne Quelle (URL oder lokale Datei).
    model_instance: WhisperModel-Instanz für Batch-Wiederverwendung.
    stop_event: threading.Event — bei gesetztem Event wird Transkription abgebrochen.
    on_output_dir: optionaler Callback(Path) — wird aufgerufen sobald output_dir bekannt ist.
    """
    url_id     = None
    auto_title = ""

    if source_type == "url":
        source     = clean_youtube_url(source)
        url_id     = extract_url_id(source)
        auto_title = fetch_yt_title(source)
        title_raw  = auto_title or "transkript"
    else:
        title_raw = Path(source).stem

    base_name  = slugify(title_raw) or "transkript"
    output_dir = Path(base_dir) / (f"{base_name}-{url_id}" if url_id else base_name)
    if on_output_dir:
        on_output_dir(output_dir)

    with tempfile.TemporaryDirectory() as tmp_dir:
        if source_type == "url":
            header(f"Lade Audio: {title_raw} …")
            audio_path = download_audio(source, tmp_dir)
        else:
            audio_path = extract_audio_local(source, tmp_dir)

        ok(f"Audio bereit: {audio_path}")

        if task_choice == "translate":
            written_orig, detected_lang, loaded_model = transcribe(
                audio_path, params, lang_choice, output_dir,
                base_name + "_orig", formats, task="transcribe",
                model_instance=model_instance, models_path=models_path,
                live_editor=live_editor, stop_event=stop_event,
            )
            written_en, _, _ = transcribe(
                audio_path, params, lang_choice, output_dir,
                base_name, formats, task="translate",
                model_instance=loaded_model, models_path=models_path,
                stop_event=stop_event,
            )
            written = list(written_en) + list(written_orig)
        else:
            written, detected_lang, _ = transcribe(
                audio_path, params, lang_choice, output_dir,
                base_name, formats, task=task_choice,
                model_instance=model_instance, models_path=models_path,
                live_editor=live_editor, stop_event=stop_event,
            )
            written = list(written)

        def run_translation(src, tgt):
            txt_files = [w for w in written if w.endswith(".txt")]
            if txt_files:
                with open(txt_files[0], encoding="utf-8") as f:
                    lines = [l.strip() for l in f if l.strip()]
                header(f"Übersetze {LANG_NAMES.get(src,src)} → {LANG_NAMES.get(tgt,tgt)} …")
                translate_text(lines, src, tgt, output_dir, base_name,
                               models_path=models_path)
            else:
                warn("Keine .txt-Datei — txt-Format für Übersetzung aktivieren.")

        if translation_tgt:
            run_translation(translation_src, translation_tgt)
        elif translation_src is None:
            # Panel übergibt immer einen expliziten Wert; None/None bedeutet: überspringen
            info("Übersetzung: Quellsprache nicht angegeben — wird übersprungen.")

        _run_api_postprocessing(
            written, detected_lang, lang_choice, task_choice,
            generate_toc_flag, summary_levels or [], summary_langs or [],
            title_raw, output_dir, base_name,
            source_url=source if source_type == "url" else None,
            focus_keywords=focus_keywords,
        )
        write_index_md(output_dir, base_name, title_raw,
                       source_url=source if source_type == "url" else None)

    return title_raw


# ─── Index-MD ─────────────────────────────────────────────────────────────────

def write_index_md(output_dir, base_name, title, source_url=None):
    """Erstellt eine Übersichts-MD aller generierten Dateien im Ausgabeordner."""
    folder = Path(output_dir)
    if not folder.exists():
        return

    _AUDIO_EXT = {".opus", ".mp3", ".mp4", ".webm", ".mkv", ".avi", ".wav", ".m4a", ".flac"}
    index_name = f"{base_name}_index.md"

    groups = {
        "Transkript":                         [],
        "Original (Whisper vor Übersetzung)": [],
        "Untertitel":                         [],
        "Inhaltsverzeichnis":                 [],
        "Zusammenfassung":                    [],
        "Übersetzung (Helsinki)":             [],
        "Audio / Video":                      [],
    }

    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.name == index_name:
            continue
        name = f.name
        if f.suffix == ".md":
            if "_toc_" in name or name.endswith("_toc.md"):
                groups["Inhaltsverzeichnis"].append(name)
            elif "_summary_" in name:
                groups["Zusammenfassung"].append(name)
        elif f.suffix == ".txt":
            if "_orig." in name:
                groups["Original (Whisper vor Übersetzung)"].append(name)
            elif any(f"_{lc}." in name for lc in ("de","en","fr","es","it","ru","zh","pl","nl","pt")):
                groups["Übersetzung (Helsinki)"].append(name)
            else:
                groups["Transkript"].append(name)
        elif f.suffix in (".srt", ".vtt"):
            if "_orig." in name:
                groups["Original (Whisper vor Übersetzung)"].append(name)
            else:
                groups["Untertitel"].append(name)
        elif f.suffix in _AUDIO_EXT:
            groups["Audio / Video"].append(name)

    index_path = folder / index_name
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(f"# {title}\n\n")
        if source_url:
            fh.write(f"{source_url}\n\n")
        fh.write("## Generierte Dateien\n\n")
        for group_name, files in groups.items():
            if not files:
                continue
            fh.write(f"### {group_name}\n\n")
            for fname in files:
                fh.write(f"- `{fname}`\n")
            fh.write("\n")

    ok(f"Index erstellt: {index_path}")
    return str(index_path)

#!/usr/bin/env python3
"""
whisper_transkriplate.py
Adaptives Whisper-Transkriptionsskript mit Systemerkennung und interaktivem Menü.

Abhängigkeiten (einmalig installieren):
    pip install faster-whisper yt-dlp psutil --break-system-packages

Für Audio-Extraktion aus Videos:
    sudo apt install ffmpeg
"""

import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path

# ─── Konfiguration ────────────────────────────────────────────────────────────

# Bevorzugter GUI-Editor für Live-Vorschau.
# Wird automatisch auf verfügbare Alternativen zurückgefallen.
PREVIEW_EDITOR = "gedit"

# Verzeichnis für Whisper- und Helsinki-Modelle.
# Relativ zum Arbeitsverzeichnis, wird beim ersten Start angelegt.
MODELS_DIR = "trscrplate_mls"

# Anthropic API-Key für TOC-Generierung.
# Leer lassen um TOC-Funktion zu deaktivieren.
# Empfohlen: per Umgebungsvariable setzen:
#   export ANTHROPIC_API_KEY="sk-ant-..."
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Modell für TOC-Generierung und Zusammenfassung (überschreibbar per Env-Var)
TOC_MODEL     = os.environ.get("TOC_MODEL",     "claude-sonnet-4-6")
SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "claude-haiku-4-5-20251001")


def _handle_api_error(e, model: str) -> None:
    try:
        from anthropic import NotFoundError, AuthenticationError, RateLimitError
    except ImportError:
        print(f"API-Fehler: {e}"); return
    if isinstance(e, NotFoundError):
        print(f"[FEHLER] Modell nicht gefunden: '{model}'")
        print("  → Env-Variable setzen: TOC_MODEL=<id> oder SUMMARY_MODEL=<id>")
        print("  → Aktuelle Modell-IDs: https://docs.anthropic.com/en/docs/about-claude/models")
    elif isinstance(e, AuthenticationError):
        print("[FEHLER] API-Key ungültig — ANTHROPIC_API_KEY prüfen.")
    elif isinstance(e, RateLimitError):
        print("[FEHLER] Rate-Limit erreicht — kurz warten und erneut versuchen.")
    else:
        print(f"[FEHLER] API-Fehler ({type(e).__name__}): {e}")

# Zusammenfassungs-Stufen: slug, label, Anweisung ans Modell
SUMMARY_LEVELS = {
    1: ("sehr_knapp", "sehr knapp",
        "Fasse das Kernthema in maximal 2 Sätzen zusammen. Kein weiteres Detail.",
        800),
    2: ("knapp",      "knapp",
        "Schreibe einen Absatz (4–6 Sätze) mit dem wesentlichen Inhalt. Keine Aufzählungen.",
        1200),
    3: ("kurz",       "kurz",
        "Schreibe einen einleitenden Absatz (3–4 Sätze), dann 5–8 Stichpunkte zu den wichtigsten Unterthemen.",
        2000),
    4: ("normal",     "normal",
        "Schreibe einen einleitenden Absatz (3–4 Sätze), dann Stichpunkte zu den Hauptthemen, je mit 2–3 Unterdetails.",
        2500),
    5: ("tief",       "tief",
        "Schreibe zunächst einen strukturierten Überblick mit einleitendem Absatz und Stichpunkten zu den Hauptthemen "
        "(wie Stufe 4). Füge danach einen Abschnitt '**Offene Punkte / Vertiefung**' hinzu: "
        "Benenne konkret, welche im Transkript angedeuteten Aspekte, Widersprüche oder Fragen "
        "in der obigen Zusammenfassung zu kurz kommen, und beantworte sie mit dem konkreten Inhalt aus dem Transkript. "
        "Keine allgemeinen Formulierungen — nur was tatsächlich im Transkript steht.",
        3500),
    6: ("schwerpunkt", "Schwerpunkte",
        None,  # dynamisch durch _build_level6_instr(keywords) ersetzt
        4000),
}

def _build_level6_instr(keywords):
    """Baut die Prompt-Anweisung für Stufe 6 (Schwerpunkte) aus einer Keyword-Liste.
    Baut vollständig auf Stufe 5 auf: Überblick + Offene Punkte/Vertiefung + Schwerpunkte.
    """
    kw_str = ", ".join(f'„{k.strip()}"' for k in keywords if k.strip())
    # Basis = vollständige Stufe-5-Anweisung
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

def find_editor():
    """Gibt den ersten verfügbaren GUI-Editor zurück.
    PREVIEW_EDITOR hat Vorrang, gedit ist Standard-Fallback."""
    candidates = [PREVIEW_EDITOR] + [
        e for e in ["gedit", "kate", "mousepad", "pluma", "geany", "xed", "leafpad"]
        if e != PREVIEW_EDITOR
    ]
    for ed in candidates:
        if shutil.which(ed):
            return ed
    return "gedit"  # Standard — auch wenn nicht im PATH, Fehlermeldung folgt dann beim Öffnen

def init_models_dir():
    """Prüft ob MODELS_DIR existiert, fragt sonst nach und legt ihn an."""
    models_path = Path(MODELS_DIR).resolve()  # immer absoluter Pfad
    if models_path.exists():
        ok(f"Modellverzeichnis: {models_path}/")
        return models_path

    print()
    warn(f"Modellverzeichnis nicht gefunden: {models_path}/")
    raw = ask(f"Pfad zum Anlegen [Enter = {MODELS_DIR}]:").strip()
    chosen = Path(raw).resolve() if raw else models_path

    try:
        (chosen / "whisper").mkdir(parents=True, exist_ok=True)
        (chosen / "helsinki").mkdir(parents=True, exist_ok=True)
        ok(f"Modellverzeichnis angelegt: {chosen.resolve()}/")
    except Exception as e:
        err(f"Konnte Verzeichnis nicht anlegen: {e}")
        sys.exit(1)

    return chosen

# ─── Abhängigkeiten prüfen ────────────────────────────────────────────────────

def check_dependency(module_name, pip_name=None):
    import importlib
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        pip_name = pip_name or module_name
        print(f"  [!] Fehlend: '{pip_name}'  →  pip install {pip_name} --break-system-packages")
        return False

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

def check_all_deps():
    ok = True
    ok &= check_dependency("faster_whisper", "faster-whisper")
    ok &= check_dependency("yt_dlp", "yt-dlp")
    ok &= check_dependency("psutil")
    if not shutil.which("ffmpeg"):
        print("  [!] ffmpeg nicht gefunden  →  sudo apt install ffmpeg")
        ok = False
    if ok:
        update_ytdlp()
        # Optionale Abhängigkeiten
        try:
            import transformers  # noqa
        except ImportError:
            print(f"  {c('i', BLUE, BOLD)} Tipp: für Helsinki-Übersetzung  →  pip install transformers sentencepiece sacremoses --break-system-packages")
        try:
            import anthropic  # noqa
        except ImportError:
            if ANTHROPIC_API_KEY:
                print(f"  {c('i', BLUE, BOLD)} Tipp: für TOC-Generierung  →  pip install anthropic --break-system-packages")
    return ok

# ─── Farb-/Terminal-Helfer ────────────────────────────────────────────────────

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
class UserQuit(Exception): pass

def ask(prompt):
    val = input(f"\n  {c('?', CYAN, BOLD)} {prompt} ").strip()
    if val.lower() == "q":
        raise UserQuit()
    return val

_readline_ready = False

def _init_readline():
    """Initialisiert readline einmalig (Backspace-Fix)."""
    global _readline_ready
    if _readline_ready:
        return
    try:
        import readline
        readline.parse_and_bind(r'"\x7f": backward-delete-char')
        readline.parse_and_bind(r'"\x08": backward-delete-char')
        _readline_ready = True
    except ImportError:
        pass

def _setup_path_completion():
    """Aktiviert Tab-Vervollständigung für Pfadeingaben."""
    _init_readline()
    try:
        import readline
        import glob

        def completer(text, state):
            matches = glob.glob(os.path.expanduser(text) + "*")
            # Verzeichnisse mit / abschließen
            matches = [m + "/" if os.path.isdir(m) else m for m in matches]
            return matches[state] if state < len(matches) else None

        readline.set_completer(completer)
        readline.set_completer_delims(" \t\n;")
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass

def ask_path(prompt, must_exist=True, extensions=None, allow_empty_as_cwd=False):
    """Pfadabfrage mit Tab-Vervollständigung und Wiederholung bis gültig."""
    _setup_path_completion()
    while True:
        raw = ask(prompt).strip().strip('"').strip("'")
        if not raw:
            if allow_empty_as_cwd:
                return Path(".")
            warn("Bitte einen Pfad eingeben.")
            continue
        path = Path(os.path.expanduser(raw))
        if must_exist and not path.exists():
            err(f"Nicht gefunden: {path}")
            warn("Bitte erneut eingeben (Tab = Vervollständigung).")
            continue
        if extensions and path.suffix.lower() not in extensions:
            err(f"Ungültiges Format: {path.suffix}  (erwartet: {', '.join(extensions)})")
            continue
        return path

def menu(title, options, default=None):
    """Einfaches nummeriertes Auswahlmenü."""
    print(f"\n  {c(title, BOLD)}")
    for i, (label, _) in enumerate(options, 1):
        marker = c(f"  [{i}]", CYAN)
        dflt   = c(" (Standard)", DIM) if default == i else ""
        print(f"{marker} {label}{dflt}")
    while True:
        raw = ask("Auswahl:")
        if raw == "" and default:
            return options[default - 1][1]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][1]
        warn("Ungültige Eingabe, bitte Nummer eingeben.")

# ─── Systemerkennung ──────────────────────────────────────────────────────────

def detect_system():
    import psutil

    # RAM (verfügbar, nicht gesamt)
    mem      = psutil.virtual_memory()
    ram_gb   = mem.total / 1024**3
    avail_gb = mem.available / 1024**3

    # CPU
    cpu_count = os.cpu_count() or 2

    # GPU-Erkennung (CUDA / ROCm / Intel via Vulkan)
    has_cuda = False
    has_gpu  = False
    gpu_name = "keine dedizierte GPU erkannt"

    # NVIDIA
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

    # AMD ROCm
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

    # Modell nach verfügbarem RAM
    if avail >= 8:
        model, model_note = "medium",    "hohe Qualität"
    elif avail >= 4:
        model, model_note = "small",     "sehr gute Qualität"
    elif avail >= 2:
        model, model_note = "base",      "gute Qualität"
    else:
        model, model_note = "tiny",      "schnell, eingeschränkte Qualität"

    # Gerät & Compute-Typ
    if sys_info["has_cuda"]:
        device, compute = "cuda", "float16"
    else:
        device, compute = "cpu",  "int8"   # int8 = massiver Speedup auf CPU

    # Threads: auf CPU sinnvoll begrenzen
    threads = min(cpus, 8) if device == "cpu" else 0

    return {
        "model":       model,
        "model_note":  model_note,
        "device":      device,
        "compute":     compute,
        "threads":     threads,
    }

def print_system_report(sys_info, params):
    header("Systemerkennung")
    ok(f"RAM gesamt:    {sys_info['ram_gb']:.1f} GB  |  verfügbar: {sys_info['avail_gb']:.1f} GB")
    ok(f"CPU-Kerne:     {sys_info['cpu_count']}")
    if sys_info["has_cuda"]:
        ok(f"GPU (CUDA):    {sys_info['gpu_name']}")
    elif sys_info["has_gpu"]:
        ok(f"GPU:           {sys_info['gpu_name']}")
    else:
        info(f"GPU:           {sys_info['gpu_name']}  →  CPU-Modus")

    header("Empfohlene Parameter")
    ok(f"Modell:        {c(params['model'], BOLD)} ({params['model_note']})")
    ok(f"Gerät:         {params['device']}  |  Compute: {params['compute']}")
    if params["threads"]:
        ok(f"CPU-Threads:   {params['threads']}")

# ─── Audio-Extraktion ─────────────────────────────────────────────────────────

def download_audio(url, tmp_dir, keep=None, output_dir=None):
    """Lädt Audio via yt-dlp herunter. keep: None/opus/480p/original."""
    import yt_dlp

    if keep == "480p":
        # Video 480p direkt von YouTube
        out_template = str(Path(tmp_dir) / "video.%(ext)s")
        ydl_opts = {
            "format":      "bestvideo[height<=480]+bestaudio/best[height<=480]",
            "outtmpl":     out_template,
            "quiet":       False,
            "no_warnings": False,
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
        # Audio separat für Transkription
        audio_opts = {
            "format":    "bestaudio/best",
            "outtmpl":   str(Path(tmp_dir) / "audio.%(ext)s"),
            "quiet":     True,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
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
        # WAV für Transkription
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
    """Extrahiert eine kurze eindeutige ID aus der URL."""
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
    """Wandelt einen Titel in einen dateisystem-sicheren String um."""
    import re, unicodedata
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:40]

def fetch_yt_title(url):
    """Holt den Video-Titel via yt-dlp ohne Download."""
    import yt_dlp
    ydl_opts = {"quiet": True, "skip_download": True}
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
        "-ar", "16000",   # Whisper bevorzugt 16 kHz
        "-ac", "1",       # Mono
        "-f", "wav", out,
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
    """Ermittelt Audiodauer in Sekunden via ffprobe."""
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
    """Sekunden → MM:SS oder HH:MM:SS."""
    seconds = int(seconds)
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def progress_bar(current, total, width=28):
    """Einfacher Block-Fortschrittsbalken."""
    frac   = min(current / total, 1.0) if total else 0
    filled = int(frac * width)
    bar    = "█" * filled + "░" * (width - filled)
    pct    = int(frac * 100)
    return bar, pct

# ─── Transkription ────────────────────────────────────────────────────────────

def transcribe(audio_path, params, language, output_dir, base_name, formats, task="transcribe", model_instance=None, live_editor=False, models_path=None):
    from faster_whisper import WhisperModel
    import time
    import threading

    header("Transkription läuft …")
    info(f"Modell:  {params['model']}  |  Gerät: {params['device']}  |  Compute: {params['compute']}")
    info(f"Sprache: {language or 'automatisch erkennen'}  |  Aufgabe: {task}")

    duration = get_audio_duration(audio_path)
    if duration:
        info(f"Dauer:   {fmt_dur(duration)}")

    # Ausgabeordner sofort anlegen
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

    # Modell laden oder wiederverwenden (Batch-Modus)
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

    # Spinner während erstes Segment verarbeitet wird
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

    # Erstes Segment holen (das startet die eigentliche Verarbeitung)
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
        return []

    # ── Live-txt vorbereiten (falls gewünscht und txt in formats) ─────────────
    live_txt_path = None
    live_txt_file = None
    editor_proc   = None

    if live_editor and "txt" in formats:
        live_txt_path = output_dir / f"{base_name}.txt"
        live_txt_file = open(live_txt_path, "w", encoding="utf-8")

    def write_seg_live(seg):
        """Schreibt ein Segment sofort in die Live-txt."""
        if live_txt_file:
            live_txt_file.write(seg.text.strip() + "\n")
            live_txt_file.flush()

    def open_editor_once():
        """Öffnet den Editor einmalig im Hintergrund."""
        nonlocal editor_proc
        if editor_proc is not None:
            return
        editor = find_editor()
        if editor:
            try:
                editor_proc = subprocess.Popen(
                    [editor, str(live_txt_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                info(f"Editor geöffnet: {editor}  ({live_txt_path.name})")
            except Exception as e:
                warn(f"Editor konnte nicht geöffnet werden: {e}")
        else:
            warn("Kein GUI-Editor gefunden (gedit, kate, mousepad …)")

    # ── Segmente einsammeln mit Fortschrittsbalken ─────────────────────────
    seg_list   = [first_seg]
    t_start    = time.time()
    last_text  = first_seg.text.strip()

    # Erstes Segment sofort schreiben und Editor öffnen
    write_seg_live(first_seg)
    if live_editor:
        open_editor_once()

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

    # Erstes Segment gleich anzeigen
    print_progress(first_seg)

    for seg in segments_iter:
        seg_list.append(seg)
        write_seg_live(seg)
        print_progress(seg)

    # Zeile abschließen
    print()

    # Live-Datei schließen
    if live_txt_file:
        live_txt_file.close()

    # Zeile abschließen
    print()

    detected_lang = getattr(info_obj, "language", "?")
    elapsed_total = time.time() - t_start
    ok(f"Erkannte Sprache: {detected_lang}  |  Transkriptionszeit: {fmt_dur(elapsed_total)}")

    # ── Ausgabe schreiben ──────────────────────────────────────────────────

    written = []

    if "txt" in formats:
        txt_path = output_dir / f"{base_name}.txt"
        if live_txt_path and live_txt_path == txt_path:
            # Bereits live geschrieben — nur in written aufnehmen
            pass
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

    # TOC — wird vom aufrufenden Code gesteuert (generate_toc_flag)
    return written, detected_lang, model

# ─── TOC-Generierung via Anthropic API ───────────────────────────────────────

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

    # Kompletten Inhalt in einem Request — Claude hat großes Kontextfenster
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
        _handle_api_error(e, TOC_MODEL); return None
    toc_text = response.content[0].text.strip()

    # TOC schreiben
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

# ─── Zusammenfassung via Anthropic API ──────────────────────────────────────

# Vollständige Sprachnamen → Kürzel für Dateinamen
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
    language: vollständiger Sprachname, z.B. 'Deutsch', 'Englisch'
    level: 1–6 (entsprechend SUMMARY_LEVELS); bei Level 6 focus_keywords=[...] sinnvoll
    context_summary_text: vorhandene Zusammenfassung als Vertiefungsbasis (optional)
    context_questions: neue Stich-/Fragepunkte für die Vertiefung (optional, Liste)
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

    client = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=SUMMARY_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        _handle_api_error(e, SUMMARY_MODEL); return None
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

# ─── Kombinierte TOC + Zusammenfassung ───────────────────────────────────────

def _extract_xml_tag(text, tag):
    """Extrahiert Inhalt eines XML-Tags. Gibt None zurück wenn nicht gefunden."""
    import re
    m = re.search(rf'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
    return m.group(1).strip() if m else None


def generate_toc_and_summaries(source_path, toc_language, summary_levels, summary_language,
                                title, output_dir, base_name, source_url=None, focus_keywords=None,
                                context_summary_text=None, context_questions=None):
    """Kombinierter API-Call: TOC + alle Zusammenfassungs-Stufen für eine Sprache.
    Spart Token — Transkript wird nur einmal gesendet.
    Fällt bei Parse-Fehlern auf Einzelaufrufe zurück.
    context_summary_text/context_questions: Vertiefungskontext für Zusammenfassungen (optional)
    Returns: (toc_path_or_None, [summary_paths])
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

    sum_tokens  = sum(SUMMARY_LEVELS[lvl][3] for lvl in summary_levels)
    toc_tokens  = 600  # TOC ist kompakt
    max_tokens  = min(sum_tokens + toc_tokens, 8000)

    client = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=TOC_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        _handle_api_error(e, TOC_MODEL); return None, []
    raw = response.content[0].text

    written_summaries = []

    # TOC extrahieren
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

    # Zusammenfassungen extrahieren
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
    """Mehrere Zusammenfassungs-Stufen für eine Sprache in einem API-Call.
    context_summary_text/context_questions: Vertiefungskontext (optional)
    """
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

    client = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=SUMMARY_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        _handle_api_error(e, SUMMARY_MODEL); return []
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
    """Führt TOC- und/oder Zusammenfassungs-Generierung durch.
    Kombiniert TOC + Zusammenfassung wenn sinnvoll (selbe Sprache → ein API-Call).
    Mehrere Stufen einer Sprache werden ebenfalls gebündelt.
    """
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
        # Nur TOC — bisheriger Standalone-Call
        header("Inhaltsverzeichnis wird generiert …")
        generate_toc(src, language=toc_lang_name, title=title_raw,
                     output_dir=output_dir, base_name=base_name, source_url=source_url)
        return

    # Zusammenfassungen nach Sprache gruppieren: lang_name → sortierte Stufenliste
    lang_groups: dict = {}
    for lvl in summary_levels:
        for slang in (summary_langs or [None]):
            actual = slang if slang else toc_lang_name
            lang_groups.setdefault(actual, set()).add(lvl)

    for lang, lvls in lang_groups.items():
        lvl_list = sorted(lvls)
        if generate_toc_flag:
            # Kombinierter Call: TOC + Zusammenfassung in dieser Sprache
            header(f"TOC + Zusammenfassung ({lang}) — kombinierter API-Call …")
            generate_toc_and_summaries(src, lang, lvl_list, lang,
                                       title_raw, output_dir, base_name,
                                       source_url=source_url, focus_keywords=focus_keywords)
        else:
            # Nur Zusammenfassung — alle Stufen dieser Sprache gebündelt
            header(f"Zusammenfassung ({lang}) wird generiert …")
            generate_summaries_multi(src, lang, lvl_list, title_raw, output_dir, base_name,
                                     source_url=source_url, focus_keywords=focus_keywords)

# ─── Helsinki-NLP Übersetzung ────────────────────────────────────────────────

# Bekannte opus-mt Sprachpaare: Quelle → [Ziele]
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
    """Gibt den HuggingFace-Modellnamen für ein Sprachpaar zurück."""
    return f"Helsinki-NLP/opus-mt-{src}-{tgt}"

def available_translation_targets(src_lang):
    """Gibt verfügbare Zielsprachen für eine Quellsprache zurück."""
    return HELSINKI_PAIRS.get(src_lang, [])

def translate_text(text_lines, src_lang, tgt_lang, output_dir, base_name, models_path=None):
    """Übersetzt eine Liste von Zeilen mit Helsinki-NLP und schreibt .txt."""
    try:
        from transformers import MarianMTModel, MarianTokenizer
    except ImportError:
        err("transformers nicht installiert  →  pip install transformers sentencepiece --break-system-packages")
        return None

    model_name = helsinki_model_name(src_lang, tgt_lang)
    info(f"Lade Übersetzungsmodell: {model_name}")
    info("(Erstmaliger Download ~300 MB, danach gecacht)")
    print()

    helsinki_dir = str(models_path / "helsinki") if models_path else None

    # Offline-Modus: kein Hub-Kontakt wenn Modell lokal vorhanden
    if helsinki_dir and Path(helsinki_dir).exists():
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    try:
        tokenizer = MarianTokenizer.from_pretrained(model_name, cache_dir=helsinki_dir)
        model     = MarianMTModel.from_pretrained(model_name, cache_dir=helsinki_dir)
    except Exception as e:
        err(f"Modell konnte nicht geladen werden: {e}")
        return None

    # In Batches übersetzen (je 8 Sätze) mit Fortschritt
    batch_size = 8
    translated = []
    total      = len(text_lines)

    try:
        cols = os.get_terminal_size().columns
    except Exception:
        cols = 80

    for i in range(0, total, batch_size):
        batch  = text_lines[i:i + batch_size]
        inputs = tokenizer(batch, return_tensors="pt", padding=True, truncation=True, max_length=512)
        outputs = model.generate(**inputs)
        decoded = tokenizer.batch_decode(outputs, skip_special_tokens=True)
        translated.extend(decoded)

        pct      = min(int((i + batch_size) / total * 100), 100)
        bar, _   = progress_bar(i + batch_size, total, width=24)
        line     = f"  \033[96m[{bar}]\033[0m {pct:3d}%  {i + batch_size}/{total} Segmente"
        print(f"\r{line:<{cols-1}}", end="", flush=True)

    print()

    # Ausgabe schreiben
    out_path = Path(output_dir) / f"{base_name}_{tgt_lang}.txt"
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

# ─── Batch-Hilfsfunktionen ───────────────────────────────────────────────────

def load_batchvt(path):
    """Liest batchvt.txt — eine URL/Pfad pro Zeile, # = Kommentar."""
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            entries.append(line)
    return entries

def resolve_batch_source(entry):
    """Erkennt ob ein Eintrag eine URL oder ein lokaler Pfad ist."""
    if entry.startswith("http://") or entry.startswith("https://"):
        return "url"
    return "local"

def process_single(source, source_type, params, lang_choice, task_choice,
                   formats, base_dir, translation_src, translation_tgt,
                   model_instance=None, models_path=None,
                   live_editor=False, generate_toc_flag=False,
                   summary_levels=None, summary_langs=None, focus_keywords=None):
    """
    Verarbeitet eine einzelne Quelle. Wenn model_instance übergeben wird,
    wird kein neues Modell geladen (Batch-Modus).
    """
    import tempfile

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

    with tempfile.TemporaryDirectory() as tmp_dir:
        if source_type == "url":
            header(f"Lade Audio: {title_raw} …")
            audio_path = download_audio(source, tmp_dir)
        else:
            audio_path = extract_audio_local(source, tmp_dir)

        ok(f"Audio bereit: {audio_path}")
        if task_choice == "translate":
            # Erst Original-Transkript sichern, dann Englisch-Übersetzung
            written_orig, detected_lang, loaded_model = transcribe(
                audio_path, params, lang_choice, output_dir,
                base_name + "_orig", formats, task="transcribe",
                model_instance=model_instance, models_path=models_path,
                live_editor=live_editor
            )
            written_en, _, _ = transcribe(
                audio_path, params, lang_choice, output_dir,
                base_name, formats, task="translate",
                model_instance=loaded_model, models_path=models_path
            )
            written = written_en + written_orig
        else:
            written, detected_lang, _ = transcribe(
                audio_path, params, lang_choice, output_dir,
                base_name, formats, task=task_choice,
                model_instance=model_instance, models_path=models_path,
                live_editor=live_editor
            )

        def run_translation(src, tgt):
            txt_files = [w for w in written if w.endswith(".txt")]
            if txt_files:
                with open(txt_files[0], encoding="utf-8") as f:
                    lines = [l.strip() for l in f if l.strip()]
                header(f"Übersetze {LANG_NAMES.get(src,src)} → {LANG_NAMES.get(tgt,tgt)} …")
                trl_path = translate_text(lines, src, tgt, output_dir, base_name,
                                          models_path=models_path)
                if generate_toc_flag and ANTHROPIC_API_KEY and trl_path:
                    try:
                        import anthropic as _a  # noqa
                        trl_base = Path(trl_path).stem
                        header("Inhaltsverzeichnis (Übersetzung) wird generiert …")
                        generate_toc(trl_path, language=tgt, title=title_raw,
                                     output_dir=output_dir, base_name=trl_base)
                    except ImportError:
                        warn("anthropic-Paket fehlt — TOC nicht verfügbar.")
            else:
                warn("Keine .txt-Datei — txt-Format für Übersetzung aktivieren.")

        if translation_tgt:
            run_translation(translation_src, translation_tgt)
        elif translation_src is None:
            # Erkannte Sprache aus Whisper nutzen statt manuell abfragen
            eff_src = detected_lang if (detected_lang and detected_lang != "?") else None
            if eff_src:
                info(f"Erkannte Sprache für Übersetzung: {eff_src}")
                targets = available_translation_targets(eff_src)
                if targets:
                    tgt_options = [(f"{LANG_NAMES.get(t,t)} ({t})", t) for t in targets] \
                                  + [("Keine Übersetzung", None)]
                    tgt = menu(f"Zielsprache [{LANG_NAMES.get(eff_src,eff_src)}]:",
                               tgt_options, default=len(tgt_options))
                    if tgt and "txt" in formats:
                        run_translation(eff_src, tgt)
                    elif tgt:
                        warn("txt-Format für Übersetzung benötigt.")
                else:
                    info(f"Keine Helsinki-Übersetzung für erkannte Sprache '{eff_src}' verfügbar.")

        _run_api_postprocessing(
            written, detected_lang, lang_choice, task_choice,
            generate_toc_flag, summary_levels or [], summary_langs or [],
            title_raw, output_dir, base_name,
            source_url=source, focus_keywords=focus_keywords
        )
        write_index_md(output_dir, base_name, title_raw, source_url=source)

    return title_raw

# ─── Nachträgliche TOC-Generierung ──────────────────────────────────────────

def interactive_toc(folder_path):
    """Generiert TOC aus vorhandenem Ausgabeordner — bevorzugt SRT, Fallback txt."""
    header("TOC-Generierung (Rerun)")

    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        err(f"Ordner nicht gefunden: {folder}"); sys.exit(1)

    # Dateien suchen
    srt_files = sorted(folder.glob("*.srt"))
    txt_files = [f for f in sorted(folder.glob("*.txt")) if "_toc" not in f.name]
    toc_files = sorted(folder.glob("*_toc.md"))

    if not srt_files and not txt_files:
        err("Keine SRT- oder txt-Datei im Ordner gefunden."); sys.exit(1)

    # Quelle wählen — SRT bevorzugt
    source = srt_files[0] if srt_files else txt_files[0]
    src_type = "SRT (mit Timestamps)" if srt_files else "txt (ohne Timestamps)"
    info(f"Quelle:  {source.name}  [{src_type}]")

    # Vorhandenes TOC anzeigen
    if toc_files:
        warn(f"Vorhandenes TOC: {toc_files[0].name} — wird überschrieben.")

    # Sprache abfragen
    lang = menu("Sprache des Transkripts:", [
        ("Deutsch (de)",              "de"),
        ("Englisch (en)",             "en"),
        ("Französisch (fr)",          "fr"),
        ("Spanisch (es)",             "es"),
        ("Andere (manuell eingeben)", "manual"),
        ("Automatisch (kein Hinweis)",""),
    ], default=2)
    if lang == "manual":
        lang = ask("Sprachcode:").strip().lower()

    title    = folder.name.replace("_", " ").replace("-", " ")
    base     = source.stem.replace("_toc", "")

    confirm = ask(f"TOC generieren für '{title}'? [J/n]:").lower()
    if confirm in ("n", "nein", "no"):
        print("\n  Abgebrochen.\n"); sys.exit(0)

    generate_toc(source, language=lang or None, title=title,
                 output_dir=folder, base_name=base)

# ─── Nachträgliche Übersetzung ───────────────────────────────────────────────

def interactive_translate(txt_path, models_path=None):
    """Übersetzt eine vorhandene .txt-Datei via Helsinki-NLP."""
    header("Nachträgliche Übersetzung")
    info(f"Datei: {txt_path}")

    # Quellsprache
    src = menu("Quellsprache der Datei:", [
        ("Deutsch (de)",              "de"),
        ("Englisch (en)",             "en"),
        ("Französisch (fr)",          "fr"),
        ("Spanisch (es)",             "es"),
        ("Andere (manuell eingeben)", "manual"),
    ], default=1)
    if src == "manual":
        src = ask("Sprachcode (z. B. 'it', 'pl', 'ru'):").strip().lower()

    targets = available_translation_targets(src)
    if not targets:
        err(f"Keine Helsinki-Modelle für '{src}' bekannt."); sys.exit(1)

    tgt_options = [(f"{LANG_NAMES.get(t,t)} ({t})", t) for t in targets]
    tgt = menu(f"Zielsprache [{LANG_NAMES.get(src,src)}]:", tgt_options, default=1)

    with open(txt_path, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]

    if not lines:
        err("Datei ist leer."); sys.exit(1)

    info(f"{len(lines)} Zeilen geladen.")
    confirm = ask("Starten? [J/n]:").lower()
    if confirm in ("n", "nein", "no"):
        print("\n  Abgebrochen.\n"); sys.exit(0)

    output_dir = txt_path.parent
    base_name  = txt_path.stem
    header(f"Übersetze {LANG_NAMES.get(src,src)} → {LANG_NAMES.get(tgt,tgt)} …")
    translate_text(lines, src, tgt, output_dir, base_name, models_path=models_path)

# ─── Nachträgliche Zusammenfassung ──────────────────────────────────────────

def interactive_summary(folder_path):
    """Generiert Zusammenfassungen aus vorhandenem Ausgabeordner (SRT/txt).
    Kombiniert TOC + Zusammenfassung wenn beides gewählt und Sprache matcht.
    Nach jeder Runde wird gefragt ob eine weitere Zusammenfassung gewünscht wird.
    """
    header("Nachträgliche Zusammenfassung")

    path = Path(folder_path)
    if not path.exists():
        err(f"Nicht gefunden: {path}"); sys.exit(1)

    if path.is_file():
        # Direkt eine Datei übergeben — Verzeichnis = Elternordner
        source = path
        folder = path.parent
    else:
        # Verzeichnis: Transkript-Dateien suchen (SRT bevorzugt, _toc/_summary ausschließen)
        folder = path
        srt_files = sorted(folder.glob("*.srt"))
        txt_files = [f for f in sorted(folder.glob("*.txt"))
                     if "_toc" not in f.name and "_summary" not in f.name]

        if not srt_files and not txt_files:
            err("Keine SRT- oder txt-Datei im Ordner gefunden."); sys.exit(1)

        candidates = srt_files + txt_files
        if len(candidates) == 1:
            source = candidates[0]
            info(f"Quelle: {source.name}")
        else:
            opts = [(f.name, f) for f in candidates]
            source = menu("Quelldatei:", opts)

    title = folder.name.replace("_", " ").replace("-", " ")
    base  = source.stem

    # Ursprüngliche URL / Pfad abfragen
    source_url_input = ask("Original-URL oder Pfad (Enter = überspringen):").strip()
    source_url = source_url_input if source_url_input else None

    # ─── Generierungs-Schleife ────────────────────────────────────────────────
    first_run          = True
    last_generated_paths = []   # zuletzt erzeugte Summary-Dateien (für Kontext-Angebot)

    while True:
        if not first_run:
            header("Weitere Zusammenfassung")
            again = ask("Weitere Zusammenfassung generieren? (z.B. Stufe 6 mit Stichworten / Vertiefung) [J/n]:").lower()
            if again in ("n", "nein", "no"):
                break

        first_run = False

        # Stufen abfragen (mit Wiederholung bei ungültiger Eingabe)
        while True:
            print(f"\n  {c('Zusammenfassungs-Stufe(n):', BOLD)}")
            print(f"  {c('[1]', CYAN)} sehr knapp  – Thema, 1–2 Sätze")
            print(f"  {c('[2]', CYAN)} knapp       – Hauptinhalt, 1 Absatz")
            print(f"  {c('[3]', CYAN)} kurz        – Hauptinhalt + Unterpunkte")
            print(f"  {c('[4]', CYAN)} normal      – Hauptinhalt + Unterpunkte + Details")
            print(f"  {c('[5]', CYAN)} tief        – Hauptinhalt + Vertiefung offener Punkte")
            print(f"  {c('[6]', CYAN)} Schwerpunkte – wie tief (Stufe 5), plus Schwerpunkt-Abschnitt zu eigenen Stichworten")
            sum_raw = ask("Stufe(n) [z.B. 2 oder 1+3 oder 2+3+4+5+6]:").strip()
            levels = _parse_multiselect(sum_raw, 6)
            if levels:
                break
            err("Keine gültige Stufe eingegeben — bitte erneut versuchen.")

        focus_keywords = []
        if 6 in levels:
            kw_raw = ask("Schwerpunkte für Stufe 6 (Stichworte, kommagetrennt):").strip()
            focus_keywords = [k.strip() for k in kw_raw.split(",") if k.strip()]

        # Sprachen abfragen (mit Wiederholung bei ungültiger Eingabe)
        _sum_lang_opts = [
            "Deutsch", "Englisch", "Französisch", "Spanisch", "Italienisch", "Russisch",
        ]
        while True:
            print(f"\n  {c('Sprache(n):', BOLD)}")
            for i, lbl in enumerate(_sum_lang_opts, 1):
                print(f"  {c(f'[{i}]', CYAN)} {lbl}")
            lang_raw = ask("Sprache(n) [z.B. 1 oder 1+2]:").strip()
            idxs = _parse_multiselect(lang_raw, len(_sum_lang_opts))
            if idxs:
                break
            err("Keine gültige Sprache eingegeben — bitte erneut versuchen.")
        langs = [_sum_lang_opts[i - 1] for i in idxs]

        # ─── Kontext-Zusammenfassung (optional) ──────────────────────────────
        context_summary_text = None
        context_questions    = []
        all_summaries        = sorted(folder.glob(f"{base}_summary_*.md"))

        if all_summaries:
            if last_generated_paths:
                # Zuletzt erzeugte automatisch anbieten
                last_names = ", ".join(Path(p).name for p in last_generated_paths)
                ctx_auto = ask(f"Zuletzt generiert ({last_names}) als Vertiefungskontext nutzen? [J/n]:").lower()
                if ctx_auto not in ("n", "nein", "no"):
                    # Bei mehreren: die mit der höchsten Stufennummer wählen
                    ctx_path = sorted(last_generated_paths)[-1]
                    with open(ctx_path, encoding="utf-8") as fh:
                        context_summary_text = fh.read()
                    ok(f"Kontext: {Path(ctx_path).name}  ({len(context_summary_text)} Zeichen)")
                else:
                    # Manuell aus allen vorhandenen wählen
                    opts = [(f.name, f) for f in all_summaries] + [("Kein Kontext", None)]
                    chosen = menu("Zusammenfassung als Kontext:", opts, default=len(opts))
                    if chosen:
                        with open(chosen, encoding="utf-8") as fh:
                            context_summary_text = fh.read()
                        ok(f"Kontext: {chosen.name}  ({len(context_summary_text)} Zeichen)")
            else:
                ctx_raw = ask("Vorhandene Zusammenfassung als Vertiefungskontext mitgeben? [j/N]:").lower()
                if ctx_raw in ("j", "ja", "y", "yes"):
                    if len(all_summaries) == 1:
                        ctx_path = all_summaries[0]
                        with open(ctx_path, encoding="utf-8") as fh:
                            context_summary_text = fh.read()
                        ok(f"Kontext: {ctx_path.name}  ({len(context_summary_text)} Zeichen)")
                    else:
                        opts = [(f.name, f) for f in all_summaries]
                        chosen = menu("Welche Zusammenfassung als Kontext?", opts)
                        with open(chosen, encoding="utf-8") as fh:
                            context_summary_text = fh.read()
                        ok(f"Kontext: {chosen.name}  ({len(context_summary_text)} Zeichen)")

            if context_summary_text:
                q_raw = ask("Neue Stich-/Fragepunkte für die Vertiefung (kommagetrennt, Enter = keine):").strip()
                if q_raw:
                    context_questions = [q.strip() for q in q_raw.split(",") if q.strip()]
                    info(f"Stich-/Fragepunkte: {', '.join(context_questions)}")

        # TOC auch (neu) generieren?
        gen_toc = False
        toc_lang_name = None
        if ANTHROPIC_API_KEY:
            toc_raw = ask("Inhaltsverzeichnis (neu) generieren? [j/N]:").lower()
            gen_toc = toc_raw in ("j", "ja", "y", "yes")
            if gen_toc:
                toc_lang_choice = menu("Sprache des Inhaltsverzeichnisses:", [
                    ("Deutsch",     "Deutsch"),
                    ("Englisch",    "Englisch"),
                    ("Französisch", "Französisch"),
                    ("Spanisch",    "Spanisch"),
                    ("Andere",      "manual"),
                ], default=1)
                if toc_lang_choice == "manual":
                    toc_lang_name = ask("Sprache (z.B. 'Italienisch'):").strip()
                else:
                    toc_lang_name = toc_lang_choice

        # Vorhandene Zusammenfassungen anzeigen
        existing = sorted(folder.glob(f"{base}_summary_*.md"))
        if existing:
            warn(f"{len(existing)} vorhandene Zusammenfassung(en) — werden ggf. überschrieben:")
            for ef in existing:
                info(f"  {ef.name}")

        confirm = ask(f"Generieren für '{title}'? [J/n]:").lower()
        if confirm in ("n", "nein", "no"):
            print()
            continue  # → nächste Iteration: fragt ob weitere Zusammenfassung gewünscht

        # Durchführen — TOC für jede Sprache, kombiniert mit Zusammenfassung
        last_generated_paths = []
        for lang in langs:
            if gen_toc:
                header(f"TOC + Zusammenfassung ({lang}) — kombinierter API-Call …")
                _, sp = generate_toc_and_summaries(
                    source, lang, levels, lang,
                    title, folder, base, source_url=source_url,
                    focus_keywords=focus_keywords,
                    context_summary_text=context_summary_text,
                    context_questions=context_questions,
                )
                last_generated_paths.extend(p for p in sp if p)
            else:
                header(f"Zusammenfassung ({lang}) …")
                sp = generate_summaries_multi(
                    source, lang, levels, title, folder, base,
                    source_url=source_url, focus_keywords=focus_keywords,
                    context_summary_text=context_summary_text,
                    context_questions=context_questions,
                )
                last_generated_paths.extend(p for p in sp if p)

        if gen_toc and not langs:
            header("Inhaltsverzeichnis wird generiert …")
            generate_toc(source, language=toc_lang_name, title=title,
                         output_dir=folder, base_name=base, source_url=source_url)

# ─── Audio-Beschnitt ─────────────────────────────────────────────────────────

def _parse_multiselect(raw, max_val):
    """Parst '1', '2+3', '1+3+4' (Trennzeichen + oder ,) → sortierte Liste gültiger ints."""
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
        return int(tc)  # reine Sekundenangabe
    return None

def ask_trim():
    """Fragt Von-Bis-Zeitstempel ab. Gibt (start_sek, end_sek) zurück, je None wenn nicht gesetzt."""
    raw = ask("Beschnitt [Enter = komplett, oder z.B. 00:05:00-01:30:00 bzw. 5:00-1:30:00]:").strip()
    if not raw:
        return None, None
    if "-" in raw:
        parts = raw.split("-", 1)
        start = _parse_timecode(parts[0]) if parts[0].strip() else None
        end   = _parse_timecode(parts[1]) if parts[1].strip() else None
        if (parts[0].strip() and start is None) or (parts[1].strip() and end is None):
            warn("Ungültiges Zeitformat — Beschnitt wird übersprungen.")
            return None, None
        if start is not None and end is not None and end <= start:
            warn(f"Ende ({parts[1].strip()}) liegt vor Start ({parts[0].strip()}) — Beschnitt übersprungen.")
            return None, None
        return start, end
    warn("Format: START-ENDE, z.B. 5:00-1:30:00 — Beschnitt übersprungen.")
    return None, None

def trim_audio(wav_path, start_sec, end_sec, tmp_dir):
    """Trimmt WAV-Datei mit ffmpeg. Gibt Pfad zur getrimmten Datei zurück."""
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

# ─── Interaktives Menü ────────────────────────────────────────────────────────

def interactive_menu(sys_info, params, batch_from_arg=None, models_path=None, recursive=False):
    _init_readline()

    print(f"\n{c('  ╔══════════════════════════════════════╗', CYAN)}")
    print(f"{c('  ║    Whisper Transkriptions-Assistent  ║', CYAN, BOLD)}")
    print(f"{c('  ╚══════════════════════════════════════╝', CYAN)}")

    # 1. Quelle
    source_type = menu("Videoquelle:", [
        ("URL (YouTube, Vimeo, …)",                              "url"),
        ("Lokale Video- oder Audiodatei",                        "local"),
        ("Batch-Modus (batchvt.txt oder Pfad)",                  "batch"),
        ("Nur übersetzen (.txt-Datei)",                          "translate_only"),
        ("Vorhandene Transkription zusammenfassen (Standalone)", "summary_only"),
    ], default=2 if batch_from_arg else None)

    # Translate-only: direkt abzweigen, kein Whisper nötig
    if source_type == "translate_only":
        trl_path = ask_path("Pfad zur .txt-Datei:", must_exist=True,
                            extensions=[".txt"])
        interactive_translate(trl_path, models_path=models_path)
        return

    # Summary-Standalone: Zusammenfassung aus vorhandenem Transkript, kein Whisper nötig
    if source_type == "summary_only":
        if not ANTHROPIC_API_KEY:
            err("ANTHROPIC_API_KEY nicht gesetzt — Zusammenfassung nicht verfügbar.")
            return
        sm_path = ask_path("Pfad zum Ausgabeordner oder Transkript:", must_exist=True)
        interactive_summary(str(sm_path))
        return

    url_id        = None
    auto_title    = ""
    batch_path    = None
    batch_entries = []

    if source_type == "batch":
        if batch_from_arg:
            batch_path = batch_from_arg
            ok(f"Verwende: {batch_path}")
        else:
            _setup_path_completion()
            _raw_bp = ask("Pfad zur batchvt.txt oder Ordner [Enter = ./batchvt.txt]:").strip().strip('"').strip("'")
            batch_path = _raw_bp if _raw_bp else "./batchvt.txt"
            if not Path(batch_path).exists():
                err(f"Nicht gefunden: {batch_path}")
                sys.exit(1)
        if Path(batch_path).is_dir():
            _MEDIA_EXTS = {".mp3", ".mp4", ".wav", ".m4a", ".opus", ".webm", ".mkv", ".avi", ".flac"}
            if not recursive:
                _rec_ans = ask("Unterordner einschließen? [j/N]:").lower()
                recursive = _rec_ans in ("j", "ja", "y", "yes")
            if recursive:
                batch_entries = sorted(
                    str(f) for f in Path(batch_path).rglob("*")
                    if f.is_file() and f.suffix.lower() in _MEDIA_EXTS
                )
            else:
                batch_entries = sorted(
                    str(f) for f in Path(batch_path).iterdir()
                    if f.is_file() and f.suffix.lower() in _MEDIA_EXTS
                )
            if not batch_entries:
                err(f"Keine Mediendateien in {batch_path} gefunden."); sys.exit(1)
            ok(f"{len(batch_entries)} Mediendateien gefunden in {batch_path}")
        else:
            batch_entries = load_batchvt(batch_path)
            if not batch_entries:
                err("Batch-Datei ist leer oder enthält nur Kommentare."); sys.exit(1)
            ok(f"{len(batch_entries)} Einträge geladen aus {batch_path}")
        source    = batch_path
        title_raw = f"Batch ({len(batch_entries)} Einträge)"
        base_name = "batch"
    elif source_type == "url":
        source = ask("Video-URL:")
        if not source:
            err("Keine URL eingegeben."); sys.exit(1)
        cleaned = clean_youtube_url(source)
        if cleaned != source:
            info(f"URL bereinigt: {cleaned}")
            source = cleaned
        url_id = extract_url_id(source)
        info("Hole Video-Titel …")
        auto_title = fetch_yt_title(source)
        if auto_title:
            ok(f"Gefundener Titel: {auto_title}")
        title_raw = ask(f"Titel für Ausgabeordner/-dateien [Enter = '{auto_title or 'transkript'}']:")
        title_raw = title_raw or auto_title or "transkript"
    else:
        source = str(ask_path("Pfad zur Video- oder Audiodatei:", must_exist=True))
        default_title = Path(source).stem
        title_raw = ask(f"Titel für Ausgabeordner/-dateien [Enter = '{default_title}']:")
        title_raw = title_raw or default_title

    base_name = slugify(title_raw)
    if not base_name:
        base_name = "transkript"

    # 2. Sprache & Aufgabe
    lang_choice = menu("Sprache des Videos:", [
        ("Deutsch (de)",                                              "de"),
        ("Englisch (en)",                                            "en"),
        ("Französisch (fr)",                                         "fr"),
        ("Spanisch (es)",                                            "es"),
        ("Andere (manuell eingeben)",                                "manual"),
        ("Automatisch erkennen  [Übersetzung erst nach Transkription abfragbar]", None),
    ], default=1)

    if lang_choice == "manual":
        lang_choice = ask("Sprachcode (z. B. 'it', 'pl', 'ru'):")

    task_choice = menu("Aufgabe:", [
        ("Transkribieren (Originalsprache)",                    "transcribe"),
        ("Transkribieren und ins Englische bringen (translate)","translate"),
    ], default=1) if lang_choice != "en" else "transcribe"

    if lang_choice == "en":
        info("Sprache ist Englisch — Whisper-Übersetzung ins Englische wird übersprungen.")

    # 3. Modell
    model_choice = menu(f"Whisper-Modell (Empfehlung: {params['model']}):", [
        ("tiny   – sehr schnell, einfache Sprache",   "tiny"),
        ("base   – schnell, gute Qualität",           "base"),
        ("small  – ausgewogen",                       "small"),
        ("medium – hohe Qualität, mehr RAM/Zeit",     "medium"),
        ("large  – beste Qualität (≥ 10 GB RAM)",     "large-v3"),
    ], default=["tiny","base","small","medium","large-v3"].index(params["model"]) + 1)
    params["model"] = model_choice

    # 4. Akzent-Modus
    MODEL_LADDER = ["tiny", "base", "small", "medium", "large-v3"]

    accent_choice = menu("Akzent-Modus:", [
        ("Standard     – saubere Aussprache, Whisper-Defaults",      "none"),
        ("Mittel       – leichter bis mittlerer Akzent",             "mittel"),
        ("Stark        – deutlicher Akzent, +1 Modell",              "stark"),
        ("Sehr stark   – sehr schwerer Akzent, +2 Modell",           "schwer"),
    ], default=1)

    if accent_choice == "none":
        params["beam_size"] = 5
        params["condition_on_previous_text"] = True
        params["temperature"] = None
    elif accent_choice == "mittel":
        params["beam_size"] = 7
        params["condition_on_previous_text"] = True
        params["temperature"] = None
    elif accent_choice == "stark":
        params["beam_size"] = 10
        params["condition_on_previous_text"] = False
        params["temperature"] = 0
        cur = MODEL_LADDER.index(params["model"]) if params["model"] in MODEL_LADDER else 2
        neu = min(cur + 1, len(MODEL_LADDER) - 1)
        if neu > cur:
            warn(f"Akzent STARK: Modell angehoben  {MODEL_LADDER[cur]} → {MODEL_LADDER[neu]}")
        params["model"] = MODEL_LADDER[neu]
    elif accent_choice == "schwer":
        params["beam_size"] = 15
        params["condition_on_previous_text"] = False
        params["temperature"] = 0
        cur = MODEL_LADDER.index(params["model"]) if params["model"] in MODEL_LADDER else 2
        neu = min(cur + 2, len(MODEL_LADDER) - 1)
        if neu > cur:
            warn(f"Akzent SCHWER: Modell angehoben  {MODEL_LADDER[cur]} → {MODEL_LADDER[neu]}")
        params["model"] = MODEL_LADDER[neu]

    # 5. Ausgabeformate
    fmt_input = menu("Ausgabeformate:", [
        ("txt + srt   – Standard",           "txt_srt"),
        ("Nur Text (.txt)",                  "txt"),
        ("txt + vtt",                        "txt_vtt"),
        ("txt + vtt + srt  – Alle drei",     "all"),
        ("vtt + srt",                        "vtt_srt"),
        ("Nur SRT",                          "srt"),
    ], default=1)

    formats = {
        "txt_srt": {"txt", "srt"},
        "txt":     {"txt"},
        "txt_vtt": {"txt", "vtt"},
        "all":     {"txt", "srt", "vtt"},
        "vtt_srt": {"vtt", "srt"},
        "srt":     {"srt"},
    }[fmt_input]

    # 5b. Quelldatei behalten (nur bei URL oder lokaler Datei, nicht Batch)
    keep_source = None
    if source_type in ("url", "local"):
        keep_choice = menu("Quelldatei behalten?", [
            ("Nein",                                    None),
            ("Audio (opus)",                            "opus"),
            ("Video 480p (direkt von YouTube / ffmpeg)","480p"),
            ("Original behalten",                       "original"),
        ], default=1)
        keep_source = keep_choice

    # 5c. Beschnitt (Von-Bis)
    trim_start, trim_end = None, None
    if source_type in ("url", "local"):
        trim_start, trim_end = ask_trim()

    # 6. Basisverzeichnis → Unterordner wird automatisch angelegt
    base_dir_raw = ask_path("Basisverzeichnis [Enter = aktuelles Verzeichnis]:",
                            must_exist=False, allow_empty_as_cwd=True)
    base_dir   = str(base_dir_raw)
    output_dir = Path(base_dir) / (f"{base_name}-{url_id}" if url_id else base_name)

    # 7. Helsinki-Übersetzung vorab konfigurieren (alle Sprachrichtungen)
    translation_tgt = None
    # Whisper-translate gibt immer Englisch aus → Helsinki-Quelle ist dann "en"
    translation_src = "en" if task_choice == "translate" else lang_choice  # None = auto

    if translation_src:
        targets = available_translation_targets(translation_src)
        if targets:
            tgt_options = [
                (f"{LANG_NAMES.get(t, t)} ({t})", t) for t in targets
            ] + [("Keine Übersetzung", None)]
            translation_tgt = menu(
                f"Übersetzung nach Transkription? [{LANG_NAMES.get(translation_src, translation_src)}]:",
                tgt_options,
                default=len(tgt_options)
            )
            if translation_tgt and "txt" not in formats:
                warn("txt-Format für Übersetzung automatisch aktiviert.")
                formats.add("txt")

    # 8. Live-Vorschau im Editor
    live_editor = False
    editor = find_editor()
    live_raw = ask(f"Transkript live in {editor} öffnen während Transkription? [J/n]:").lower()
    live_editor = live_raw not in ("n", "nein", "no")
    if live_editor and "txt" not in formats:
        warn("txt-Format für Live-Vorschau automatisch aktiviert.")
        formats.add("txt")

    # 9. TOC vorab konfigurieren
    generate_toc_flag = False
    if ANTHROPIC_API_KEY:
        try:
            import anthropic as _a  # noqa — nur Verfügbarkeitsprüfung
            toc_raw = ask("Inhaltsverzeichnis nach Transkription generieren? [J/n]:").lower()
            generate_toc_flag = toc_raw not in ("n", "nein", "no")
            if generate_toc_flag:
                if "srt" not in formats:
                    warn("SRT-Format für TOC-Timestamps automatisch aktiviert.")
                    formats.add("srt")
                if "txt" not in formats:
                    formats.add("txt")
        except ImportError:
            warn("anthropic-Paket fehlt — TOC nicht verfügbar  →  pip install anthropic --break-system-packages")
    else:
        info("TOC: kein API-Key gesetzt (ANTHROPIC_API_KEY) — nicht verfügbar.")

    # 10. Zusammenfassung vorab konfigurieren
    summary_levels = []
    summary_langs  = []
    focus_keywords = []
    if ANTHROPIC_API_KEY:
        try:
            import anthropic as _a  # noqa
            print(f"\n  {c('Zusammenfassung (optional):', BOLD)}")
            print(f"  {c('[1]', CYAN)} sehr knapp  – Thema, 1–2 Sätze")
            print(f"  {c('[2]', CYAN)} knapp       – Hauptinhalt, 1 Absatz")
            print(f"  {c('[3]', CYAN)} kurz        – Hauptinhalt + Unterpunkte")
            print(f"  {c('[4]', CYAN)} normal      – Hauptinhalt + Unterpunkte + Details")
            print(f"  {c('[5]', CYAN)} tief        – Hauptinhalt + Vertiefung offener Punkte")
            print(f"  {c('[6]', CYAN)} Schwerpunkte – wie tief (Stufe 5), plus Schwerpunkt-Abschnitt zu eigenen Stichworten")
            sum_raw = ask("Stufe(n) [Enter = keine, z.B. 2 oder 1+3 oder 2+3+4+5+6]:").strip()
            if sum_raw:
                summary_levels = _parse_multiselect(sum_raw, 6)
            if 6 in summary_levels:
                kw_raw = ask("Schwerpunkte für Stufe 6 (Stichworte, kommagetrennt):").strip()
                focus_keywords = [k.strip() for k in kw_raw.split(",") if k.strip()]
            if summary_levels:
                if "srt" not in formats:
                    warn("SRT-Format für Zusammenfassung automatisch aktiviert.")
                    formats.add("srt")
                if "txt" not in formats:
                    formats.add("txt")
                _sum_lang_opts = [
                    "Deutsch", "Englisch", "Französisch", "Spanisch",
                    "Italienisch", "Russisch", "wie Transkript",
                ]
                print(f"\n  {c('Sprache(n) der Zusammenfassung:', BOLD)}")
                for i, lbl in enumerate(_sum_lang_opts, 1):
                    print(f"  {c(f'[{i}]', CYAN)} {lbl}")
                lang_raw = ask("Sprache(n) [z.B. 1 oder 1+2]:").strip()
                if lang_raw:
                    idxs = _parse_multiselect(lang_raw, len(_sum_lang_opts))
                    for idx in idxs:
                        lbl = _sum_lang_opts[idx - 1]
                        # None als Sentinel für "wie Transkript"
                        summary_langs.append(None if lbl == "wie Transkript" else lbl)
                if not summary_langs:
                    summary_langs = [None]  # Fallback: wie Transkript
        except ImportError:
            warn("anthropic-Paket fehlt — Zusammenfassung nicht verfügbar  →  pip install anthropic --break-system-packages")

    # ── Zusammenfassung ────────────────────────────────────────────────────

    accent_label = {"none": "standard", "mittel": "mittel", "stark": "stark", "schwer": "sehr stark"}[accent_choice]
    beam_info    = f"beam={params['beam_size']}"
    cond_info    = "ctx=an" if params["condition_on_previous_text"] else "ctx=aus"
    temp_info    = f"temp={params['temperature']}" if params["temperature"] is not None else "temp=auto"

    header("Zusammenfassung")
    info(f"Quelle:     {source}")
    info(f"Titel:      {title_raw}")
    info(f"Sprache:    {lang_choice or 'automatisch'}  |  Aufgabe: {task_choice}")
    info(f"Modell:     {params['model']}  |  Gerät: {params['device']}  |  Compute: {params['compute']}")
    info(f"Akzent:     {accent_label}  ({beam_info}, {cond_info}, {temp_info})")
    info(f"Formate:    {', '.join(sorted(formats))}")
    if translation_tgt:
        info(f"Übersetzung: {LANG_NAMES.get(translation_src,translation_src)} → {LANG_NAMES.get(translation_tgt,translation_tgt)}")
    elif translation_src is None:
        info(f"Übersetzung: nach Transkription abfragbar (Sprache: automatisch)")
    else:
        info(f"Übersetzung: keine")
    info(f"TOC:        {'ja (nach Transkription)' if generate_toc_flag else 'nein'}")
    if summary_levels:
        _lvl_str  = "+".join(str(l) for l in summary_levels)
        _lang_str = "+".join(sl if sl else "wie Transkript" for sl in summary_langs)
        _kw_str   = f"  |  Schwerpunkte: {', '.join(focus_keywords)}" if focus_keywords else ""
        info(f"Zusammenfassung: Stufe(n) {_lvl_str}  |  Sprache(n): {_lang_str}{_kw_str}")
    else:
        info(f"Zusammenfassung: keine")
    info(f"Ausgabe:    {output_dir}/")
    info(f"Live-Editor: {editor if live_editor else 'nein'}")
    if keep_source:
        info(f"Quelldatei: behalten als {keep_source}")
    if trim_start is not None or trim_end is not None:
        s_str = fmt_dur(trim_start) if trim_start else "Anfang"
        e_str = fmt_dur(trim_end)   if trim_end   else "Ende"
        info(f"Beschnitt:  {s_str} → {e_str}")

    confirm = ask("Starten? [J/n]:").lower()
    if confirm in ("n", "nein", "no"):
        print("\n  Abgebrochen.\n")
        sys.exit(0)

    # ── Ausführen ──────────────────────────────────────────────────────────

    if source_type == "batch":
        # Modell einmal laden
        from faster_whisper import WhisperModel
        import threading, time

        spinner_chars  = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        spinner_active = True

        def spin():
            i = 0
            while spinner_active:
                print(f"\r  {c(spinner_chars[i % len(spinner_chars)], CYAN, BOLD)} Lade Modell '{params['model']}' …", end="", flush=True)
                time.sleep(0.1)
                i += 1

        t = threading.Thread(target=spin, daemon=True)
        t.start()
        kwargs = {"device": params["device"], "compute_type": params["compute"]}
        if params["threads"]:
            kwargs["cpu_threads"] = params["threads"]
        if models_path:
            kwargs["download_root"] = str(models_path / "whisper")
        try:
            model_instance = WhisperModel(params["model"], **kwargs)
        finally:
            spinner_active = False
            t.join(timeout=0.3)
            print(f"\r  {c('✓', GREEN, BOLD)} Modell geladen — starte Batch ({len(batch_entries)} Einträge).")

        results = []
        for i, entry in enumerate(batch_entries, 1):
            header(f"Eintrag {i}/{len(batch_entries)}: {entry}")
            src_type = resolve_batch_source(entry)
            if src_type == "local" and not Path(entry).exists():
                err(f"Datei nicht gefunden, übersprungen: {entry}")
                results.append((entry, "❌ nicht gefunden"))
                continue
            # Unterordnerstruktur replizieren wenn rekursiv
            if recursive and src_type == "local":
                try:
                    rel_sub = Path(entry).parent.relative_to(Path(batch_path))
                    entry_base_dir = str(Path(base_dir) / rel_sub)
                except ValueError:
                    entry_base_dir = base_dir
            else:
                entry_base_dir = base_dir
            try:
                title = process_single(
                    entry, src_type, params, lang_choice, task_choice,
                    formats, entry_base_dir, translation_src, translation_tgt,
                    model_instance=model_instance, models_path=models_path,
                    live_editor=live_editor, generate_toc_flag=generate_toc_flag,
                    summary_levels=summary_levels, summary_langs=summary_langs,
                    focus_keywords=focus_keywords
                )
                results.append((entry, f"✓ {title}"))
            except Exception as e:
                err(f"Fehler: {e}")
                results.append((entry, f"❌ Fehler: {e}"))

        header("Batch abgeschlossen")
        for entry, status in results:
            short = entry[:60] + "…" if len(entry) > 60 else entry
            print(f"  {status}  {c(short, DIM)}")
        print()

        # Batch-Report schreiben
        import datetime
        report_path = Path(base_dir) / "batch_report.txt"
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(f"Batch-Report  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
                f.write(f"Modell: {params['model']}  |  Sprache: {lang_choice or 'auto'}\n")
                f.write("─" * 60 + "\n")
                ok_count  = sum(1 for _, s in results if s.startswith("✓"))
                err_count = len(results) - ok_count
                for entry, status in results:
                    f.write(f"{status[:1]}  {entry}\n    {status[2:]}\n")
                f.write("─" * 60 + "\n")
                f.write(f"Gesamt: {len(results)}  ✓ {ok_count}  ❌ {err_count}\n")
            ok(f"Batch-Report: {report_path}")
        except Exception as e:
            warn(f"Batch-Report konnte nicht geschrieben werden: {e}")

    else:
        # Einzelne Quelle
        with tempfile.TemporaryDirectory() as tmp_dir:
            if source_type == "url":
                header("Lade Audio herunter …")
                audio_path = download_audio(source, tmp_dir,
                                            keep=keep_source,
                                            output_dir=output_dir)
            else:
                audio_path = extract_audio_local(source, tmp_dir,
                                                 keep=keep_source,
                                                 output_dir=output_dir)

            ok(f"Audio bereit: {audio_path}")
            if trim_start is not None or trim_end is not None:
                audio_path = trim_audio(audio_path, trim_start, trim_end, tmp_dir)
            if task_choice == "translate":
                written_orig, detected_lang, loaded_model = transcribe(
                    audio_path, params, lang_choice, output_dir,
                    base_name + "_orig", formats, task="transcribe",
                    live_editor=live_editor, models_path=models_path
                )
                written_en, _, _ = transcribe(
                    audio_path, params, lang_choice, output_dir,
                    base_name, formats, task="translate",
                    model_instance=loaded_model, models_path=models_path
                )
                written = written_en + written_orig
            else:
                written, detected_lang, _ = transcribe(
                    audio_path, params, lang_choice, output_dir, base_name, formats,
                    task=task_choice, live_editor=live_editor, models_path=models_path
                )

            def run_translation(src, tgt):
                txt_files = [w for w in written if w.endswith(".txt")]
                if txt_files:
                    with open(txt_files[0], encoding="utf-8") as f:
                        lines = [l.strip() for l in f if l.strip()]
                    header(f"Übersetze {LANG_NAMES.get(src,src)} → {LANG_NAMES.get(tgt,tgt)} …")
                    trl_path = translate_text(lines, src, tgt, output_dir, base_name,
                                              models_path=models_path)
                    if generate_toc_flag and ANTHROPIC_API_KEY and trl_path:
                        try:
                            import anthropic as _a  # noqa
                            trl_base = Path(trl_path).stem
                            header("Inhaltsverzeichnis (Übersetzung) wird generiert …")
                            generate_toc(trl_path, language=tgt, title=title_raw,
                                         output_dir=output_dir, base_name=trl_base)
                        except ImportError:
                            warn("anthropic-Paket fehlt — TOC nicht verfügbar.")
                else:
                    warn("Keine .txt-Datei gefunden — txt-Format für Übersetzung aktivieren.")

            if translation_tgt:
                run_translation(translation_src, translation_tgt)
            elif translation_src is None:
                # Erkannte Sprache direkt aus Whisper nutzen
                eff_src = detected_lang if (detected_lang and detected_lang != "?") else None
                if eff_src:
                    info(f"Erkannte Sprache für Übersetzung: {eff_src}")
                    targets = available_translation_targets(eff_src)
                    if targets:
                        tgt_options = [
                            (f"{LANG_NAMES.get(t, t)} ({t})", t) for t in targets
                        ] + [("Keine Übersetzung", None)]
                        tgt = menu(f"Zielsprache [{LANG_NAMES.get(eff_src, eff_src)}]:",
                                   tgt_options, default=len(tgt_options))
                        if tgt and "txt" not in formats:
                            warn("txt-Format für Übersetzung benötigt.")
                        elif tgt:
                            run_translation(eff_src, tgt)
                    else:
                        info(f"Keine Helsinki-Übersetzung für erkannte Sprache '{eff_src}' verfügbar.")

            _run_api_postprocessing(
                written, detected_lang, lang_choice, task_choice,
                generate_toc_flag, summary_levels, summary_langs,
                title_raw, output_dir, base_name,
                source_url=source, focus_keywords=focus_keywords
            )
            write_index_md(output_dir, base_name, title_raw, source_url=source)

# ─── Quick-Mode ──────────────────────────────────────────────────────────────

def run_quickmode(source, lang, models_path, summary_levels=None):
    """
    Quick-Mode: Direkt transkribieren ohne interaktives Menü.
    Feste Einstellungen: Modell small, Akzent Standard, Ausgabe txt+srt,
    Editor öffnen, TOC + Zusammenfassung 1+3+5 wenn API-Key vorhanden.
    Wenn Sprache ≠ Deutsch: Übersetzung ins Deutsche.
    summary_levels: Liste von Stufen 1–6; Standard ist [1,3,5] wenn API-Key gesetzt.
    Stufe 6 fragt interaktiv nach Schwerpunkt-Stichworten.
    """
    header("Quick-Mode")

    if not source:
        err("Quick-Mode: URL oder Dateipfad fehlt.")
        info("Beispiel: python3 whisper_transkriplate.py -qm -de https://youtube.com/...")
        sys.exit(1)

    source_type = "url" if source.startswith(("http://", "https://")) else "local"

    # Unvollständige URL abfangen: '&' ohne Anführungszeichen wird vom Terminal
    # als Hintergrundoperator interpretiert — der Rest der URL geht verloren.
    def _url_looks_truncated(u):
        if "youtube.com/watch" in u and "v=" not in u:
            return True
        # URL endet auf '?' oder '&' — Parameter abgeschnitten
        if u.rstrip().endswith(("?", "&")):
            return True
        return False

    while source_type == "url" and _url_looks_truncated(source):
        warn("URL scheint unvollständig — '&' wird vom Terminal als Hintergrundoperator")
        warn("interpretiert und schneidet den Rest der URL ab.")
        new = ask("Vollständige URL eingeben (oder Enter zum Abbrechen):").strip()
        if not new:
            sys.exit(1)
        source = new
        source_type = "url" if source.startswith(("http://", "https://")) else "local"

    if source_type == "local" and not Path(source).exists():
        err(f"Datei nicht gefunden: {source}"); sys.exit(1)

    summary_levels = summary_levels or []

    # Schwerpunkte abfragen wenn Stufe 6
    focus_keywords = []
    if 6 in summary_levels and ANTHROPIC_API_KEY:
        kw_raw = ask("Schwerpunkte für Zusammenfassung Stufe 6 (Stichworte, kommagetrennt):").strip()
        focus_keywords = [k.strip() for k in kw_raw.split(",") if k.strip()]

    info(f"Quelle:   {source}")
    info(f"Sprache:  {lang or 'automatisch erkennen'}")
    info("Modell:   small  |  Akzent: Standard  |  Formate: txt, srt")
    if ANTHROPIC_API_KEY:
        if summary_levels:
            _lvl_str = "+".join(str(l) for l in summary_levels)
            _kw_info = f"  |  Schwerpunkte: {', '.join(focus_keywords)}" if focus_keywords else ""
            info(f"TOC + Zusammenfassung: Stufe(n) {_lvl_str} (Deutsch){_kw_info}")
        else:
            info("TOC:      wird generiert (API-Key vorhanden)")
    if lang and lang != "de":
        info("Übersetzung: → Deutsch (nach Transkription)")

    sys_info = detect_system()
    params   = recommend_params(sys_info)
    params["model"]                    = "small"
    params["beam_size"]                = 5
    params["condition_on_previous_text"] = True
    params["temperature"]              = None

    formats = {"txt", "srt"}

    if source_type == "url":
        source     = clean_youtube_url(source)
        url_id     = extract_url_id(source)
        info("Hole Video-Titel …")
        auto_title = fetch_yt_title(source)
        title_raw  = auto_title or "transkript"
        if auto_title:
            ok(f"Titel: {title_raw}")
    else:
        title_raw = Path(source).stem
        url_id    = None

    base_name  = slugify(title_raw) or "transkript"
    output_dir = Path(".") / (f"{base_name}-{url_id}" if url_id else base_name)

    with tempfile.TemporaryDirectory() as tmp_dir:
        if source_type == "url":
            header("Lade Audio herunter …")
            audio_path = download_audio(source, tmp_dir)
        else:
            audio_path = extract_audio_local(source, tmp_dir)

        ok(f"Audio bereit: {audio_path}")
        written, detected_lang, _ = transcribe(
            audio_path, params, lang, output_dir, base_name, formats,
            task="transcribe", live_editor=True, models_path=models_path
        )
        eff_lang = lang or (detected_lang if detected_lang != "?" else None)

        # Übersetzung ins Deutsche wenn Sprache bekannt und nicht Deutsch
        trl_path = None
        if eff_lang and eff_lang != "de":
            targets = available_translation_targets(eff_lang)
            if "de" in targets:
                txt_files = [w for w in written if w.endswith(".txt")]
                if txt_files:
                    with open(txt_files[0], encoding="utf-8") as f:
                        lines = [l.strip() for l in f if l.strip()]
                    header(f"Übersetze {LANG_NAMES.get(eff_lang, eff_lang)} → Deutsch …")
                    trl_path = translate_text(lines, eff_lang, "de", output_dir, base_name,
                                              models_path=models_path)
            else:
                warn(f"Keine Helsinki-Übersetzung von '{eff_lang}' → Deutsch verfügbar.")

        # TOC + Zusammenfassung kombiniert — ein API-Call wenn beides aktiv
        if ANTHROPIC_API_KEY:
            try:
                import anthropic as _a  # noqa
                srt_w     = [w for w in written if w.endswith(".srt")]
                txt_w     = [w for w in written if w.endswith(".txt")]
                src_f     = srt_w[0] if srt_w else (txt_w[0] if txt_w else None)
                lang_name = LANG_NAMES.get(eff_lang or "de", "Deutsch")
                if src_f:
                    if summary_levels:
                        lvl_str = "+".join(str(l) for l in summary_levels)
                        header(f"TOC + Zusammenfassung Stufe(n) {lvl_str} — kombinierter API-Call …")
                        generate_toc_and_summaries(
                            src_f, lang_name, summary_levels, "Deutsch",
                            title_raw, output_dir, base_name,
                            source_url=source if source_type == "url" else None,
                            focus_keywords=focus_keywords,
                        )
                    else:
                        header("Inhaltsverzeichnis wird generiert …")
                        generate_toc(src_f, language=lang_name, title=title_raw,
                                     output_dir=output_dir, base_name=base_name,
                                     source_url=source if source_type == "url" else None)
                if trl_path:
                    trl_base = Path(trl_path).stem
                    header("Inhaltsverzeichnis (Übersetzung) wird generiert …")
                    generate_toc(trl_path, language="Deutsch", title=title_raw,
                                 output_dir=output_dir, base_name=trl_base)
            except ImportError:
                warn("anthropic-Paket fehlt — TOC/Zusammenfassung nicht verfügbar  →  pip install anthropic --break-system-packages")

        write_index_md(output_dir, base_name, title_raw, source_url=source if source_type == "url" else None)

# ─── Index-MD ────────────────────────────────────────────────────────────────

def write_index_md(output_dir, base_name, title, source_url=None):
    """Erstellt eine Übersichts-MD aller generierten Dateien im Ausgabeordner."""
    folder = Path(output_dir)
    if not folder.exists():
        return

    _AUDIO_EXT = {".opus", ".mp3", ".mp4", ".webm", ".mkv", ".avi", ".wav", ".m4a", ".flac"}
    index_name = f"{base_name}_index.md"

    groups = {
        "Transkript":        [],
        "Original (Whisper vor Übersetzung)": [],
        "Untertitel":        [],
        "Inhaltsverzeichnis": [],
        "Zusammenfassung":   [],
        "Übersetzung (Helsinki)": [],
        "Audio / Video":     [],
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
            elif any(f"_{c}." in name for c in ("de","en","fr","es","it","ru","zh","pl","nl","pt")):
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

# ─── Einstieg ─────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Whisper Transkriptions-Assistent",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "batch", nargs="?", metavar="BATCHDATEI_oder_URL",
        help="Pfad zu einer batchvt.txt oder im Quick-Mode eine URL/Datei"
    )
    parser.add_argument(
        "--batch", dest="batch_flag", metavar="BATCHDATEI",
        help="Pfad zu einer batchvt.txt"
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="Ordner-Batch: auch Unterordner durchsuchen"
    )
    parser.add_argument(
        "--translate", "-trl", metavar="TEXTDATEI",
        help="Vorhandene .txt-Datei nachträglich übersetzen (kein Whisper)"
    )
    parser.add_argument(
        "--toc", metavar="ORDNER",
        help="TOC aus vorhandenem Ausgabeordner neu generieren (bevorzugt SRT)"
    )
    parser.add_argument(
        "--summary", "-sm", metavar="ORDNER",
        help="Zusammenfassung aus vorhandenem Ausgabeordner generieren (SRT/txt)"
    )
    # Quick-Mode
    parser.add_argument(
        "-qm", "--quickmode", action="store_true",
        help=(
            "Quick-Mode: direkt starten ohne Menü.\n"
            "  Einstellungen: Modell small, Akzent Standard, Ausgabe txt+srt,\n"
            "  Editor öffnen, TOC + Zusammenfassung 1+3+5 wenn API-Key vorhanden,\n"
            "  Übersetzung → DE wenn Sprache ≠ Deutsch.\n"
            "  Sprache via -de/-en/-fr/-es/-it/-ru/-pt, URL/Datei als letztes Argument.\n"
            "  Beispiele:\n"
            "    python3 whisper_transkriplate.py -qm -de https://youtube.com/...\n"
            "    python3 whisper_transkriplate.py -qm -en /pfad/zum/video.mp4"
        )
    )
    parser.add_argument(
        "-zf", "--zusammenfassung", type=int, metavar="STUFE",
        choices=range(1, 7),
        help=(
            "Quick-Mode: Zusätzliche Zusammenfassungs-Stufe (wird zu Standard 1+3+5 addiert).\n"
            "  Besonders nützlich für Stufe 6 (fragt interaktiv nach Schwerpunkt-Stichworten).\n"
            "  Beispiel: python3 whisper_transkriplate.py -qm -de -zf 6 URL"
        )
    )
    # Sprachkürzel für Quick-Mode (auch im normalen Modus nutzbar)
    _lang_group = parser.add_mutually_exclusive_group()
    _lang_group.add_argument("-de", action="store_const", const="de", dest="qm_lang",
        help="Quick-Mode Sprache: Deutsch")
    _lang_group.add_argument("-en", action="store_const", const="en", dest="qm_lang",
        help="Quick-Mode Sprache: Englisch")
    _lang_group.add_argument("-fr", action="store_const", const="fr", dest="qm_lang",
        help="Quick-Mode Sprache: Französisch")
    _lang_group.add_argument("-es", action="store_const", const="es", dest="qm_lang",
        help="Quick-Mode Sprache: Spanisch")
    _lang_group.add_argument("-it", action="store_const", const="it", dest="qm_lang",
        help="Quick-Mode Sprache: Italienisch")
    _lang_group.add_argument("-ru", action="store_const", const="ru", dest="qm_lang",
        help="Quick-Mode Sprache: Russisch")
    _lang_group.add_argument("-pt", action="store_const", const="pt", dest="qm_lang",
        help="Quick-Mode Sprache: Portugiesisch")
    args = parser.parse_args()

    print(f"\n{c('  Abhängigkeiten werden geprüft …', DIM)}")
    if not check_all_deps():
        print(f"\n{c('  Bitte fehlende Pakete installieren, dann erneut starten.', YELLOW)}\n")
        sys.exit(1)
    ok("Alle Abhängigkeiten vorhanden.")

    try:
        models_path = init_models_dir()
    except UserQuit:
        print("\n  Abgebrochen.\n")
        sys.exit(0)

    # -qm / --quickmode
    if args.quickmode:
        qm_source = args.batch  # positionales Argument übernimmt URL/Pfad
        if ANTHROPIC_API_KEY:
            _qm_lvls = sorted({1, 3, 5} | ({args.zusammenfassung} if args.zusammenfassung else set()))
        else:
            _qm_lvls = []
        run_quickmode(qm_source, args.qm_lang, models_path, summary_levels=_qm_lvls)
        return

    # --toc: TOC aus vorhandenem Ordner neu generieren
    if args.toc:
        if not ANTHROPIC_API_KEY:
            err("ANTHROPIC_API_KEY nicht gesetzt — TOC nicht verfügbar.")
            sys.exit(1)
        interactive_toc(args.toc)
        return

    # --summary: Zusammenfassung aus vorhandenem Ordner generieren
    if args.summary:
        if not ANTHROPIC_API_KEY:
            err("ANTHROPIC_API_KEY nicht gesetzt — Zusammenfassung nicht verfügbar.")
            sys.exit(1)
        interactive_summary(args.summary)
        return

    # --translate: direkt zur Übersetzung, kein Systemcheck nötig
    if args.translate:
        trl_path = Path(args.translate)
        # Wenn Ordner übergeben: txt-Datei darin suchen
        if trl_path.is_dir():
            txt_candidates = [f for f in sorted(trl_path.glob("*.txt"))
                              if "_toc" not in f.name]
            if not txt_candidates:
                err(f"Keine .txt-Datei in {trl_path} gefunden."); sys.exit(1)
            if len(txt_candidates) == 1:
                trl_path = txt_candidates[0]
                ok(f"Gefunden: {trl_path.name}")
            else:
                # Mehrere txt — Auswahl anbieten
                opts = [(f.name, f) for f in txt_candidates]
                trl_path = menu("Welche Datei übersetzen?", opts)
        elif not trl_path.exists():
            err(f"Datei nicht gefunden: {trl_path}"); sys.exit(1)
        interactive_translate(trl_path, models_path=models_path)
        return

    sys_info = detect_system()
    params   = recommend_params(sys_info)
    print_system_report(sys_info, params)

    # Batch-Datei oder Ordner aus Argument
    batch_from_arg = None
    batch_src = args.batch_flag or args.batch
    if batch_src:
        p = Path(batch_src)
        if p.is_dir():
            batch_from_arg = batch_src
            ok(f"Batch-Ordner aus Startparameter: {batch_src}")
        elif p.is_file():
            batch_from_arg = batch_src
            ok(f"Batch-Datei aus Startparameter: {batch_src}")
        else:
            err(f"Nicht gefunden: {batch_src}")
            sys.exit(1)

    while True:
        try:
            interactive_menu(sys_info, params, batch_from_arg=batch_from_arg,
                             models_path=models_path, recursive=args.recursive)
            break
        except UserQuit:
            print(f"\n  {c('Abgebrochen — zurück zum Hauptmenü …', DIM)}")

if __name__ == "__main__":
    main()

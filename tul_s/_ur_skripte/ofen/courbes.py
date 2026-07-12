#!/usr/bin/env python3
"""
courbes.py — Ofen-Log Auswertung  v1.7.6
TC707-Format: CSV-Logs → PDF (A3) + HTML (interaktiv) + kWh-Jahresübersicht

Entwicklung: 2025–2026  (Claude Sonnet / Anthropic + Milan)

Version History:
  v1.0   CSV → matplotlib PDF, kWh-Trapezintegration, Dark/Light-Theme
  v1.1   kWhlog, Segmentmarker, Schaltstreifen
  v1.2   Plotly HTML, Tab-Navigation, interaktiver Mouseover
  v1.3   HOLD/ERR States, Event-Parsing, ineffektive Heizphasen (LP0ineff)
  v1.4   Event-Badges mit Streifen, Fußzeilen-Tabelle, Zeitstempel-Ordner
  v1.5   Dateinamen-Konvention _(d)/_(l), Zeitraum+kWh im Namen, kWh-Unterordner
  v1.6   kWhlog zeitliche X-Achse, Sammelsäule, kWhlog-Anhang an PDFs (pypdf)
  v1.7   3-zeilige Event-Badges (kollisionsfrei), Uhrzeiten in Fußzeile,
         2-zeilige Info-Zeile, Dezimal-Eventcodes (z.B. E9.3), E9.3 eingetragen
  v1.7.5 kWhlog-Anhang: glob statt exaktem Dateinamen, nur bei PDF-Ausgabe
  v1.7.6 Kurven-Canvas fix von oben — kein Springen bei unterschiedlicher Event-Zahl

Ordnerstruktur (automatisch):
  <Arbeitsordner>/
    TC707*/       ← CSV-Dateien
    TC707pdf/     ← PDF-Ausgabe (wird erstellt falls nötig)

Verwendung:
  python3 kiln_log_pdf.py [OPTIONEN]

  --batch           Keine interaktiven Fragen, alle Dateien
  --output NAME     Ausgabe-PDF-Name (Standard: kiln_report_YYYYMMDD_HHMM.pdf)
  --workdir PATH    Arbeitsverzeichnis (Standard: aktuelles Verzeichnis)

Einzelauswertung – Cutoff-Eingabe:
  Format:  VOR,NACH   (je hh:mm, Offset ab Dateistart)
  Beispiele:
    2:00,           → erste 2h überspringen, Ende = Dateiende (bzw. Fenster)
    ,1:30           → Anfang behalten, letzte 1,5h abschneiden
    1:00,2:00       → vorne 1h, hinten 2h abschneiden
    [Enter]         → keine Cutoffs
"""

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  KONFIGURATION  –  hier anpassen                                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝

WINDOW_HOURS     = 16    # Standard-Zeitfenster in Stunden
TEMP_MAX         = 1250  # Obere Temperaturgrenze Standard-PDF (°C)
TEMP_MIN         = 0     # Untere Temperaturgrenze (°C)
TEMP_DISPLAY_MAX = 1240  # Freier Kurvenbereich optimiertes PDF (°C) – hier anpassen

# Ofenleistung – für Stromverbrauchsberechnung
# Messung: eine Phase Dreieckschaltung, 21.3 A × 400 V × 3 = 25.6 kW
# Nennwert laut Hersteller: 24.0 kW  →  nach Nachmessung hier anpassen
OFEN_KW      = 27.14     # Nennleistung in kW (bei LP0 = 100%)
OFEN_NAME    = 'chaud'  # Name des Ofens — erscheint in Überschriften

# Segmentwechsel-Marker: Versatz des Labels vom Pfeilpunkt (Punkte)
SEG_OX = 55   # nach rechts

# Ineffektive Heizphasen: Mindestdauer für Erkennung (Sekunden)
# Kurze Temperaturschwankungen werden ignoriert
INEFF_MIN_DURATION_S  = 120  # Mindestdauer der sinkenden Temp (Sekunden)
INEFF_MIN_DROP_C_MIN  = 0.5  # Mindest-Sinkrate °C/min (0.5 = sauber trennend)
INEFF_LP0_MIN         = 20   # LP0-Mindestschwelle % (unter 20% = normales Pendeln)
SEG_OY = 45   # nach oben/unten (wechselnd)

# Kurvenausrichtung: Fenster so verschieben dass eine Zieltemperatur immer
# am selben Offset erscheint (nur statisches Fenster, interaktiv überschreibbar)
ALIGN_TEMP     = 140    # °C — None = deaktiviert; interaktiv mit 0 abschalten
ALIGN_OFFSET_H = 1.0    # h — Zieltemperatur liegt diese Zeit nach Fensterstart

# kWh-Verbrauchsplot Skalen
KWH_Y_MAX        = 150    # Maximale Y-Achse pro Brand (kWh)
KWH_CUM_MAX      = 10000  # Maximale Jahressummen-Achse (kWh)
KWH_TEST_STACK   = 10.0   # Brände unter diesem Wert werden zu einer Sammelsäule gestapelt

# ── Farbthema ────────────────────────────────────────────────────────────────
# THEME = 'dark'   → dunkler Hintergrund (Original)
# THEME = 'light'  → heller Hintergrund, druckfreundlich
# THEME = 'both'   → beide Varianten erzeugen
THEME = 'dark'

# Farbsets
_THEMES = {
    'dark': {
        'BG_FIGURE':          '#1E1E1E',
        'BG_AXES':            '#2A2A2A',
        'COLOR_GRID_MAJOR':   '#404040',
        'COLOR_GRID_MINOR':   '#303030',
        'COLOR_AXIS_TEXT':    '#CCCCCC',
        'COLOR_TICK':         '#888888',
        'COLOR_SPINE':        '#555555',
        'COLOR_TEMP':         '#FFFFFF',   # Ist-Temp: weiß
        'COLOR_SETPOINT':     '#74B9FF',   # Soll-Temp: hellblau
        'COLOR_LP0':          '#FDCB6E',   # Heizleistung: gelb/orange
        'COLOR_FAN':          '#00CEC9',   # Gebläse: türkis
        'COLOR_STATE_RUN':    '#FF7675',
        'COLOR_STATE_STOP':   '#00B4D8',
        'COLOR_STATE_IDLE':   '#636E72',
        'COLOR_STATE_HOLD':   '#663C37',
        'COLOR_STATE_ERR':    '#E74C3C',
        'COLOR_ANNOT':        '#FF6B6B',
        'COLOR_SW_SICHERHEIT':'#B0B0B0',
        'COLOR_SW_LEISTUNG':  '#FDCB6E',
        'COLOR_SW_GEBLAESE':  '#00CEC9',
        'PDF_BG':             '#1E1E1E',   # PDF-Seitenhintergrund
        'PDF_TITLE_COLOR':    '#FFFFFF',
        'ALPHA_LP0':          0.05,
        'ALPHA_FAN':          0.20,
    },
    'light': {
        'BG_FIGURE':          '#F5F5F0',
        'BG_AXES':            '#FFFFFF',
        'COLOR_GRID_MAJOR':   '#CCCCCC',
        'COLOR_GRID_MINOR':   '#E5E5E5',
        'COLOR_AXIS_TEXT':    '#222222',
        'COLOR_TICK':         '#555555',
        'COLOR_SPINE':        '#AAAAAA',
        'COLOR_TEMP':         '#7B0000',   # Ist-Temp: sehr dunkelrot
        'COLOR_SETPOINT':     '#1A5F9E',   # Soll-Temp: dunkelblau
        'COLOR_LP0':          '#E07B00',   # Heizleistung: kräftiges orange
        'COLOR_FAN':          '#007A75',   # Gebläse: dunkles türkis
        'COLOR_STATE_RUN':    '#C0392B',
        'COLOR_STATE_STOP':   '#0077A8',
        'COLOR_STATE_IDLE':   '#95A5A6',
        'COLOR_STATE_HOLD':   '#4A2A27',
        'COLOR_STATE_ERR':    '#C0392B',
        'COLOR_ANNOT':        '#8B0000',
        'COLOR_SW_SICHERHEIT':'#AAAAAA',
        'COLOR_SW_LEISTUNG':  '#D4860A',
        'COLOR_SW_GEBLAESE':  '#007A75',
        'PDF_BG':             '#F5F5F0',
        'PDF_TITLE_COLOR':    '#1A1A1A',
        'ALPHA_LP0':          0.2,
        'ALPHA_FAN':          0.30,
    },
}

# Aktives Farbset laden
_t = _THEMES.get(THEME, _THEMES['dark'])
BG_FIGURE          = _t['BG_FIGURE']
BG_AXES            = _t['BG_AXES']
COLOR_GRID_MAJOR   = _t['COLOR_GRID_MAJOR']
COLOR_GRID_MINOR   = _t['COLOR_GRID_MINOR']
COLOR_AXIS_TEXT    = _t['COLOR_AXIS_TEXT']
COLOR_TICK         = _t['COLOR_TICK']
COLOR_SPINE        = _t['COLOR_SPINE']
COLOR_TEMP         = _t['COLOR_TEMP']
COLOR_SETPOINT     = _t['COLOR_SETPOINT']
COLOR_LP0          = _t['COLOR_LP0']
COLOR_FAN          = _t['COLOR_FAN']
COLOR_STATE_RUN    = _t['COLOR_STATE_RUN']
COLOR_STATE_STOP   = _t['COLOR_STATE_STOP']
COLOR_STATE_IDLE   = _t['COLOR_STATE_IDLE']
COLOR_STATE_HOLD   = _t['COLOR_STATE_HOLD']
COLOR_STATE_ERR    = _t['COLOR_STATE_ERR']
COLOR_ANNOT        = _t['COLOR_ANNOT']
COLOR_SW_SICHERHEIT= _t['COLOR_SW_SICHERHEIT']
COLOR_SW_LEISTUNG  = _t['COLOR_SW_LEISTUNG']
COLOR_SW_GEBLAESE  = _t['COLOR_SW_GEBLAESE']
_PDF_BG            = _t['PDF_BG']
_PDF_TITLE_COLOR   = _t['PDF_TITLE_COLOR']
ALPHA_LP0          = _t['ALPHA_LP0']
ALPHA_FAN          = _t['ALPHA_FAN']

def apply_theme(theme_name):
    """Setzt alle globalen Farbvariablen auf das gewählte Theme ('dark' oder 'light')."""
    import sys
    m = sys.modules[__name__]
    t = _THEMES.get(theme_name, _THEMES['dark'])
    m.BG_FIGURE           = t['BG_FIGURE']
    m.BG_AXES             = t['BG_AXES']
    m.COLOR_GRID_MAJOR    = t['COLOR_GRID_MAJOR']
    m.COLOR_GRID_MINOR    = t['COLOR_GRID_MINOR']
    m.COLOR_AXIS_TEXT     = t['COLOR_AXIS_TEXT']
    m.COLOR_TICK          = t['COLOR_TICK']
    m.COLOR_SPINE         = t['COLOR_SPINE']
    m.COLOR_TEMP          = t['COLOR_TEMP']
    m.COLOR_SETPOINT      = t['COLOR_SETPOINT']
    m.COLOR_LP0           = t['COLOR_LP0']
    m.COLOR_FAN           = t['COLOR_FAN']
    m.COLOR_STATE_RUN     = t['COLOR_STATE_RUN']
    m.COLOR_STATE_STOP    = t['COLOR_STATE_STOP']
    m.COLOR_STATE_IDLE    = t['COLOR_STATE_IDLE']
    m.COLOR_STATE_HOLD    = t['COLOR_STATE_HOLD']
    m.COLOR_STATE_ERR     = t['COLOR_STATE_ERR']
    m.COLOR_ANNOT         = t['COLOR_ANNOT']
    m.COLOR_SW_SICHERHEIT = t['COLOR_SW_SICHERHEIT']
    m.COLOR_SW_LEISTUNG   = t['COLOR_SW_LEISTUNG']
    m.COLOR_SW_GEBLAESE   = t['COLOR_SW_GEBLAESE']
    m._PDF_BG             = t['PDF_BG']
    m._PDF_TITLE_COLOR    = t['PDF_TITLE_COLOR']
    m.ALPHA_LP0           = t['ALPHA_LP0']
    m.ALPHA_FAN           = t['ALPHA_FAN']
    m.STATE_COLORS        = {'RUN': t['COLOR_STATE_RUN'],
                              'STOP': t['COLOR_STATE_STOP'],
                              'IDLE': t['COLOR_STATE_IDLE'],
                              'HOLD': t['COLOR_STATE_HOLD'],
                              'ERR':  t['COLOR_STATE_ERR']}


# Linienstärken
LW_TEMP     = 1.8
LW_SETPOINT = 0.6

# PDF-Vektortext (Titel + Infozeile)
PDF_FONT_TITLE  = 'Helvetica-Bold'
PDF_FONT_INFO   = 'Helvetica'
PDF_SIZE_TITLE  = 16
PDF_SIZE_INFO   = 9

# ╚══════════════════════════════════════════════════════════════════════════╝

import sys
import io
import argparse
from pathlib import Path
from datetime import timedelta

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor, white, Color

STATE_COLORS = {
    'RUN':  COLOR_STATE_RUN,
    'STOP': COLOR_STATE_STOP,
    'IDLE': COLOR_STATE_IDLE,
    'HOLD': COLOR_STATE_HOLD,
    'ERR':  COLOR_STATE_ERR,
}

# ── CSV laden ────────────────────────────────────────────────────────────────

def load_csv(filepath):
    df = pd.read_csv(
        filepath, sep=';', decimal=',',
        on_bad_lines='skip', encoding='utf-8-sig'
    )
    df['datetime'] = pd.to_datetime(
        df['Date'].astype(str) + ' ' + df['Time'].astype(str),
        format='%d.%m.%y %H:%M:%S', errors='coerce'
    )
    df = df.dropna(subset=['datetime']).sort_values('datetime').reset_index(drop=True)

    for col, out in [('IN0(°C)', 'IN0'), ('SP0(°C)', 'SP0')]:
        df[out] = pd.to_numeric(
            df[col].astype(str).str.replace(',', '.', regex=False),
            errors='coerce'
        )
    df['LP0'] = pd.to_numeric(
        df['LP0(%)'].astype(str).str.replace(',', '.', regex=False),
        errors='coerce'
    ).fillna(0.0)

    do0 = df['DO0'].astype(str)
    df['sw_leistung'] = do0.str[0] == '0'   # Pos1: Leistungsschütz
    df['sw_geblaese'] = do0.str[1] == '1'   # Pos2: Gebläse
    df['sw_sicherheit'] = do0.str[2] == '2' # Pos3: Sicherheitsschütz
    df['fan_on']  = df['sw_geblaese']        # Rückwärtskompatibilität
    df['heat_on'] = df['State'] == 'RUN'

    # Events aus PrcsInfo extrahieren
    import re as _re
    df['event'] = df['PrcsInfo'].astype(str).str.extract(r'([AE][0-9]+(?:\.[0-9]+)?)', expand=False).fillna('')

    # Ineffektive Heizphasen: LP0 > 0 aber Temperatur fällt (ΔT < 0)
    # Ineffektive Heizphasen: LP0>5% aber Temperatur fällt
    # Mindestdauer INEFF_MIN_DURATION_S: rolling window über N Schritte
    interval_s = df['datetime'].diff().dt.total_seconds().median()
    if interval_s and interval_s > 0:
        n_steps = max(1, int(INEFF_MIN_DURATION_S / interval_s))
    else:
        n_steps = 4  # Fallback
    # Gleitender Temperaturgradient über n_steps
    df['dT_roll'] = df['IN0'].diff(n_steps)
    # Sinkrate in °C/min umrechnen (n_steps * interval_s Sekunden)
    window_s = n_steps * interval_s
    df['dT_per_min'] = df['dT_roll'] / (window_s / 60) if window_s > 0 else df['dT_roll']
    # Einzelschritt-dT (pro Messintervall) für feingranulare Erkennung
    df['dT_single'] = df['IN0'].diff()
    dt_single_per_min = df['dT_single'] / (interval_s / 60) if interval_s > 0 else df['dT_single']
    df['dT_single_per_min'] = dt_single_per_min

    # Ineffektiv: zwei Modi
    # 1. HOLD/ERR: LP0 hoch + jeder einzelne Schritt sinkend (auch leicht)
    state_not_run = ~df['State'].isin(['RUN'])
    ineff_hold = (state_not_run &
                  (df['LP0'] > INEFF_LP0_MIN) &
                  (df['dT_single_per_min'] < -INEFF_MIN_DROP_C_MIN))
    # 2. RUN: nur bei starker anhaltender Sinkrate (rolling, 3× Schwelle)
    ineff_run  = (df['State'].isin(['RUN']) &
                  (df['LP0'] > INEFF_LP0_MIN) &
                  (df['dT_per_min'] < -(INEFF_MIN_DROP_C_MIN * 3)))
    df['ineff'] = ineff_hold | ineff_run

    # Lücken in HOLD/ERR-Blöcken schliessen:
    # Einzelne False-Zeilen zwischen True-Zeilen im gleichen State füllen
    ineff_filled = df['ineff'].copy()
    for i in range(1, len(df) - 1):
        if (not df['ineff'].iloc[i] and
                df['ineff'].iloc[i-1] and df['ineff'].iloc[i+1] and
                df['State'].iloc[i] not in ['RUN'] and
                df['LP0'].iloc[i] + df.get('LP0ineff', df['LP0']).iloc[i] > INEFF_LP0_MIN):
            ineff_filled.iloc[i] = True
    df['ineff'] = ineff_filled
    # LP0 aufteilen: ineffektive Werte in separate Spalte, aus LP0 entfernen
    df['LP0ineff'] = df['LP0'].where(df['ineff'], 0.0)
    df['LP0']      = df['LP0'].where(~df['ineff'], 0.0)
    df['Seg'] = pd.to_numeric(df['Seg'], errors='coerce').fillna(0).astype(int)
    return df


def bool_to_spans(times, flags):
    spans, start = [], None
    for t, f in zip(times, flags):
        if f and start is None:
            start = t
        elif not f and start is not None:
            spans.append((start, t))
            start = None
    if start is not None and times:
        spans.append((start, times[-1]))
    return spans



def draw_switch_strips(ax, ax2, dv, t_start, t_end, temp_max, fig=None):
    """
    Drei Schaltstreifen auf ax (Temperaturachse), oberhalb temp_max.
    ax wird intern auf temp_max * 1.04 ausgedehnt.
    Anteile Gebläse:Leistung:Sicherheit = 3:2:1.
    Segmentnummern als runde Badges in der Mitte des Sicherheitsstreifens.
    ax2 (LP0) bleibt unberührt bei 0–110.
    """
    # ax nach oben ausdehnen: 10% über temp_max für die Streifen
    ax_top_strips = temp_max * 1.04
    GAP   = temp_max * 0.005
    TOTAL = ax_top_strips - temp_max - GAP
    PARTS = 6                  # 3+2+1
    unit  = TOTAL / PARTS

    y_geb_lo  = temp_max + GAP
    y_geb_hi  = y_geb_lo + 3 * unit
    y_lei_lo  = y_geb_hi
    y_lei_hi  = y_lei_lo + 2 * unit
    y_sic_lo  = y_lei_hi
    y_sic_hi  = ax_top_strips

    ax_top = ax_top_strips
    ax.set_ylim(ax.get_ylim()[0], ax_top)

    BANDS = [
        ('sw_geblaese',   y_geb_lo, y_geb_hi, COLOR_SW_GEBLAESE),
        ('sw_leistung',   y_lei_lo, y_lei_hi, COLOR_SW_LEISTUNG),
        ('sw_sicherheit', y_sic_lo, y_sic_hi, COLOR_SW_SICHERHEIT),
    ]

    for col, ylo, yhi, color in BANDS:
        if col not in dv.columns:
            continue
        spans = bool_to_spans(dv['datetime'].tolist(), dv[col].tolist())
        for s, e in spans:
            ax.axvspan(s, e, ymin=ylo/ax_top, ymax=yhi/ax_top,
                       alpha=0.90, color=color, lw=0, zorder=6,
                       transform=ax.get_xaxis_transform() if False else ax.transData)

    # Segmentnummern als runde Badges im Sicherheitsstreifen
    if 'Seg' not in dv.columns:
        return
    badge_y   = (y_sic_lo + y_sic_hi) / 2   # Mitte Sicherheitsstreifen
    prev_seg  = None
    seg_start = None
    for row in dv[['datetime','Seg']].itertuples(index=False):
        seg = row.Seg
        t   = row.datetime
        if seg != prev_seg:
            if prev_seg is not None and prev_seg > 0 and seg_start is not None:
                t_mid = seg_start + (t - seg_start) / 2
                ax.text(t_mid, badge_y, f'{prev_seg}',
                        ha='center', va='center',
                        fontsize=6, color='#1E1E1E', fontweight='bold',
                        clip_on=False, zorder=8,
                        bbox=dict(boxstyle='round,pad=0.25',
                                  fc='#E8E8E8', ec='#888888',
                                  lw=0.5, alpha=0.85))
            seg_start = t
            prev_seg  = seg
    if prev_seg is not None and prev_seg > 0 and seg_start is not None:
        t_mid = seg_start + (dv['datetime'].iloc[-1] - seg_start) / 2
        ax.text(t_mid, badge_y, f'{prev_seg}',
                ha='center', va='center',
                fontsize=6, color='#1E1E1E', fontweight='bold',
                clip_on=False, zorder=8,
                bbox=dict(boxstyle='round,pad=0.25',
                          fc='#E8E8E8', ec='#888888',
                          lw=0.5, alpha=0.85))


def calc_kwh(dv, ofen_kw=None):
    """Stromverbrauch per Trapezintegration der LP0-Kurve (kWh).
    Ineffektive Heizphasen (LP0>0 aber Temp faellt) werden herausgerechnet.
    """
    import numpy as np
    if ofen_kw is None:
        ofen_kw = OFEN_KW
    t0    = dv["datetime"].iloc[0]
    times = (dv["datetime"] - t0).dt.total_seconds() / 3600
    lp0   = dv["LP0"].fillna(0.0).copy()
    if 'ineff' in dv.columns:
        lp0[dv['ineff'].fillna(False)] = 0.0
    trapfn = getattr(np, 'trapezoid', None) or getattr(np, 'trapz')
    return float(trapfn(lp0.values / 100.0, times) * ofen_kw)

def configure_xaxis(ax, total_h):
    if total_h < 0.1:
        # Degenerate case: Zeitspanne zu klein → einfachen Formatter, keine Minor-Ticks
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=1))
        ax.xaxis.set_minor_locator(mticker.NullLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.setp(ax.get_xticklabels(), rotation=35, ha='right',
                 fontsize=8, color=COLOR_AXIS_TEXT)
        return
    if total_h <= 10:
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        ax.xaxis.set_minor_locator(mdates.MinuteLocator(byminute=[15, 30, 45]))
        fmt = '%H:%M'
    elif total_h <= 24:
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
        fmt = '%d.%m %H:%M'
    elif total_h <= 48:
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
        fmt = '%d.%m %H:%M'
    else:
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=2))
        fmt = '%d.%m %H:%M'
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
    plt.setp(ax.get_xticklabels(), rotation=35, ha='right',
             fontsize=8, color=COLOR_AXIS_TEXT)


def style_ax(ax):
    ax.set_facecolor(BG_AXES)
    ax.tick_params(colors=COLOR_TICK, which='both')
    ax.yaxis.label.set_color(COLOR_AXIS_TEXT)
    ax.xaxis.label.set_color(COLOR_AXIS_TEXT)
    for spine in ax.spines.values():
        spine.set_edgecolor(COLOR_SPINE)
    ax.tick_params(axis='y', labelcolor=COLOR_AXIS_TEXT, labelsize=9)
    ax.grid(True, which='major', color=COLOR_GRID_MAJOR, ls='--', alpha=0.6, lw=0.6)
    ax.grid(True, which='minor', color=COLOR_GRID_MINOR, ls=':', alpha=0.4, lw=0.4)



# ── Event-Badges & ineffektive Heizphasen ────────────────────────────────────

# Event-Tabelle (aus Hersteller-Dokumentation)
_MON = ['jan','feb','mär','apr','mai','jun','jul','aug','sep','okt','nov','dez']
def _dfmt(d):
    """Datum → YYmmmdd z.B. 26apr03"""
    if d is None:
        from datetime import date as _date
        d = _date.today()
    return f"{str(d.year)[2:]}{_MON[d.month-1]}{d.day:02d}"

EVENT_INFO = {
    # code: (Kurztext, Langtext, Farbe)
 'A1':('Messfühler-Fehler',  'Regelkanal wegen Fehler des Prozesswertes abgeschaltet. Rücksetzen über die ?-Taste.','#E74C3C'),
 'A3':('Brennvorgang Sicherheit',  'Brennvorgang beendet: max. Temperatur um mehr als 20°C überschritten, Sicherheitsschütz abgeschaltet. Zumeist defektes Regelschütz.', '#E74C3C'),
 'A4':('Gradientenfehler/Netz', 'Zu geringes Aufheizen trotz maximaler Heizleistung. Problem der Netzversorgung oder Leistungsteil. Überprüfen Sie Heizspiralen, Netzphasen, Schütz. Heizspiralen, Netzphasen, Schütz prüfen.', '#E74C3C'),
 'A5':('HOLD automatisch', 'Temperatur folgt nicht dem vorgegebenen Anstieg – Regler schaltet automatisch auf HOLD und gibt Zeit zum Aufholen. Bei Misserfolg folgt A6 oder A7.', '#E74C3C'),
 'A6':('Abbruch nach ERR A5','Nach ERR A5 Temperatur-Aufholen fehlgeschlagen – Programm abgebrochen (Log-Eintrag).','#E74C3C'),
 'A7':('Fortsetzung nach ERR A5',  'Nach ERR A5 Temperatur-Aufholen fehlgeschlagen – Programm trotzdem fortgesetzt (Meldung 1 Min., Log-Eintrag).','#E74C3C'),
 'A8':('Segment-Endwert erreicht', 'Segment beendet, da Temperatur aller überwachten Zonen den Endwert erreicht. Regler prüft auf Hängenbleiben.','#E74C3C'),
 'A9':('Emergency Exit',  'Reglerneustart trotz guter Versorgungsspannung. Erdung und externe Störsignale prüfen.',  '#E74C3C'),
 'B1':('Neustart Netzspannung', 'Reglerneustart trotz guter Versorgungsspannung. Erdung und externe Störsignale prüfen.',  '#E67E22'),
 'B2':('Programm fortgesetzt',  'Nach Wiederkehr der Netzspannung wurde das Programm automatisch fortgesetzt.','#E67E22'),
 'B3':('Programm nicht fortges.',  'Nach Netzwiederkehr nicht fortgesetzt: 1=Konfig verboten, 2=DO inaktiv, 3=Maximalzeit, 4=Temp-Abfall, aus Sicherheitsgründen beendet.',  '#E67E22'),
 'B4':('SmartCheck-Fehler',  'Heizleistung unzureichend (SmartCheck). Bewertung über das erlernte Aufheizverhalten bei neuem Ofen oder Echtstrom-/Spannungsmessung (PM3 Modul in IOBox).',  '#E67E22'),
 'B5':('IOBox-Fehler', 'IOBox hat ein Problem gemeldet. Weitere Angaben für Details (X.Y > IOBox X Modul Y).', '#E67E22'),
 'B6':('Autotune aktiv',  'Autotune (Selbstoptimierungszyklus) aktiv.','#3498DB'),
 'B7':('Autotune abgebrochen',  'Autotune abgebrochen, da Regelkanal im Fehlerzustand. Ermittelte B6/B8-Parameter verwerfen.','#3498DB'),
 'B8':('Autotune fertig', 'Autotune abgeschlossen; Parameter wurden evaluiert. Ggf. als nicht geeignet befunden (B9). Parameter als korrekt bewertet und übernommen.',  '#3498DB'),
 'C1':('Messverstärker-Defekt', 'Internes technisches Problem: Messsignal-Verstärker defekt. Kundendienst kontaktieren.', '#9B59B6'),
 'C2':('Messverstärker-Problem','Internes technisches Problem: Messsignal-Verstärker ungenau. Kundendienst kontaktieren.', '#9B59B6'),
 'C3':('IOBox-Problem','IOBox hat ein Problem gemeldet. Weitere Angaben für Details.', '#9B59B6'),
 'E1':('Start',  'Programm gestartet.','#27AE60'),
 'E2':('Ende',  'Programm beendet.','#27AE60'),
 'E4':('HOLD manuell',  'Programm manuell auf HOLD geschaltet.','#663C37'),
 'E8':('USB-Fehler','Fehler USB-Operation: Falscher Schlüssel.', '#95A5A6'),
 'E9.3': ('Konfig-Neustart/Abbruch', 'Neuladen der Steuerungskonfiguration — Programm abgebrochen.',  '#E67E22'),
 'SKIP': ('Segment übersprungen',  'Direkter Wechsel zum nächsten Segment.',  '#F39C12'),
}
EVENT_LINK = 'https://noc.milan.how/s/x3KPsYay5moBdbX'

def draw_event_badges(ax, ax2, dv):
    """Deprecated: Badges werden via draw_event_strip() gezeichnet."""
    pass


def draw_event_strip(fig, ax, dv):
    """
    Zeichnet einen eigenen dünnen Axes-Streifen direkt über den Schaltstreifen.
    Die Axes hat ihre eigenen Koordinaten → kein Clipping-Problem.
    """
    if 'event' not in dv.columns:
        return
    events_df = dv[dv['event'] != '']
    if events_df.empty:
        return

    # Position der Haupt-Axes in Figure-Koordinaten
    pos = ax.get_position()  # [x0, y0, width, height]

    # Streifen: gleiche Breite wie Haupt-Axes, 2% der Figure-Höhe über dem Top
    strip_h = 0.055   # Höhe in Figure-Koordinaten (3 Zeilen)
    strip_y = pos.y1  # direkt über der Haupt-Axes

    ax_ev = fig.add_axes([pos.x0, strip_y, pos.width, strip_h],
                         facecolor='#1A1A1A')
    ax_ev.set_xlim(ax.get_xlim())
    ax_ev.set_ylim(0, 1)
    ax_ev.axis('off')

    # Trennlinie oben
    ax_ev.axhline(1, color='#555555', lw=0.5, alpha=0.7)

    # Badges: jedes Event nur beim ersten Auftreten
    # SKIP-Events bekommen Pfeil auf Temperaturkurve (kein Streifen)
    # 3 Zeilen alternieren um Überlappungen zu vermeiden
    import matplotlib.dates as _mdates
    xlim = ax.get_xlim()
    seen = set()
    badge_idx = 0
    Y_ROWS = [1/6, 3/6, 5/6]  # 3 Zeilen von unten nach oben

    for _, row in events_df.iterrows():
        ev = row['event']
        if ev in seen:
            continue
        seen.add(ev)

        # Farbe aus EVENT_INFO, Fallback rot
        _info = EVENT_INFO.get(ev, ('', '', '#E74C3C'))
        badge_color = _info[2]

        if ev == 'SKIP':
            # SKIP: Pfeil von Badge auf Temperaturkurve (wie Segmentmarker)
            try:
                T = float(row['IN0'])
            except Exception:
                T = 0.0
            ax.annotate(f'↷ {ev}',
                        xy=(row['datetime'], max(T, 0)),
                        xytext=(SEG_OX, SEG_OY), textcoords='offset points',
                        ha='left', va='bottom',
                        fontsize=7, color='white', fontweight='bold',
                        zorder=11, clip_on=False,
                        arrowprops=dict(arrowstyle='->', color=badge_color,
                                        lw=1.0, shrinkB=3),
                        bbox=dict(boxstyle='round,pad=0.3',
                                  fc=badge_color, ec=badge_color,
                                  lw=0.8, alpha=0.92))
        else:
            # Normales Event: Badge im Streifen, alternierend auf 3 Zeilen
            t_num = _mdates.date2num(row['datetime'])
            x_frac = (t_num - xlim[0]) / (xlim[1] - xlim[0])
            y_frac = Y_ROWS[badge_idx % 3]
            badge_idx += 1
            ax_ev.text(x_frac, y_frac, ev,
                       ha='center', va='center',
                       fontsize=6.5, color='white', fontweight='bold',
                       transform=ax_ev.transAxes,
                       zorder=9,
                       bbox=dict(boxstyle='round,pad=0.3',
                                 fc=badge_color, ec=badge_color,
                                 lw=0.8, alpha=0.92))


def draw_ineff_overlay(ax2, dv):
    """
    Graue LP0ineff-Fläche für ineffektive Heizphasen (separate Spalte, kein Overlap).
    """
    if 'LP0ineff' not in dv.columns:
        return
    if dv['LP0ineff'].max() > 0:
        ax2.fill_between(dv['datetime'], 0, dv['LP0ineff'],
                         color='#888888', alpha=0.65, lw=0,
                         label='Leistung ineffektiv', zorder=2)
        ax2.plot(dv['datetime'], dv['LP0ineff'],
                 color='#888888', lw=0.6, alpha=0.5, zorder=2)

# ── Segmentwechsel-Marker ───────────────────────────────────────────────────

def draw_segment_markers(ax, dv, t_zero):
    """
    Orangegelber Pfeil + Text bei jedem Segmentwechsel auf der IN0-Kurve.
    Text: T=xxx°C / hh:mm (vergangene Zeit seit t_zero)
    Pfeile wechseln zwischen oben/unten um Überlappungen zu reduzieren.
    """
    if 'Seg' not in dv.columns:
        return
    COLOR_SEG = '#F0A500'   # Orangegelb

    # Startlabel: erster Datenpunkt (00:00)
    valid_start = dv['IN0'].notna()
    if valid_start.any():
        t0_row = dv.loc[valid_start].iloc[0]
        T0     = t0_row['IN0']
        ax.annotate(f'{T0:.0f}°C  00:00',
                    xy=(t0_row['datetime'], T0),
                    xytext=(-SEG_OX//2, SEG_OY), textcoords='offset points',
                    ha='right', va='bottom',
                    fontsize=7, color=COLOR_SEG, fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color=COLOR_SEG,
                                   lw=1.0, shrinkB=3),
                    bbox=dict(boxstyle='round,pad=0.2',
                              fc='#1E1E1E' if _PDF_BG == '#1E1E1E' else '#F5F5F0',
                              ec=COLOR_SEG, lw=0.6, alpha=0.80),
                    zorder=7, clip_on=False)

    # Ersten Segmentstart überspringen — nur echte Wechsel markieren
    # Dazu: prev_seg mit dem allerersten Seg-Wert initialisieren
    first_seg = dv['Seg'].iloc[0] if len(dv) > 0 else 0
    prev_seg  = first_seg
    flip      = -1   # Start mit -1 damit erstes Wechsel-Label oben steht

    for _, row in dv.iterrows():
        seg = row['Seg']
        if seg == prev_seg or seg <= 0:
            continue

        t   = row['datetime']
        T   = row['IN0']
        try:
            if __import__('math').isnan(float(T)):
                prev_seg = seg
                continue
        except (TypeError, ValueError):
            prev_seg = seg
            continue

        elapsed = (t - t_zero).total_seconds()
        hh      = int(elapsed // 3600)
        mm      = int((elapsed % 3600) // 60)
        label   = f'{T:.0f}°C  {hh:02d}:{mm:02d}'

        # Position: rechts vom Pfeilpunkt, oben oder unten wechselnd
        ox =  SEG_OX
        oy =  SEG_OY * flip
        ax.annotate(label,
                    xy=(t, T),
                    xytext=(ox, oy), textcoords='offset points',
                    ha='left', va='bottom' if flip > 0 else 'top',
                    fontsize=7, color=COLOR_SEG, fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color=COLOR_SEG,
                                   lw=1.0, shrinkB=3),
                    bbox=dict(boxstyle='round,pad=0.2',
                              fc='#1E1E1E' if _PDF_BG == '#1E1E1E' else '#F5F5F0',
                              ec=COLOR_SEG, lw=0.6, alpha=0.80),
                    zorder=7, clip_on=False)
        flip    *= -1
        prev_seg = seg


# ── Plot zeichnen (PNG, ohne Titel – der kommt als Vektortext ins PDF) ───────

def draw_plot(dv, t_start, t_end, temp_max, temp_min):
    """
    Zeichnet nur den Daten-Plot.
    Gibt (png_bytes, max_temp_in_window, fan_h) zurück.
    """
    total_h   = (t_end - t_start).total_seconds() / 3600
    fan_spans = bool_to_spans(dv['datetime'].tolist(), dv['fan_on'].tolist())

    # Etwas weniger hoch als A3 – Platz für Vektortext oben bleibt im PDF
    fig, ax = plt.subplots(figsize=(16.54, 9.80), dpi=120)
    fig.patch.set_facecolor(BG_FIGURE)
    fig.subplots_adjust(top=0.91, bottom=0.14, left=0.06, right=0.93)
    style_ax(ax)

    ax2 = ax.twinx()
    ax2.set_facecolor(BG_AXES)
    ax2.set_ylim(-5, 110)
    ax2.set_ylabel('Heizleistung / Gebläse (%)', color=COLOR_AXIS_TEXT, fontsize=10)
    ax2.tick_params(axis='y', labelcolor=COLOR_AXIS_TEXT, labelsize=9,
                    colors=COLOR_TICK)
    for spine in ax2.spines.values():
        spine.set_edgecolor(COLOR_SPINE)

    # Z=1 · Schaltstreifen oben (Sicherheitsschütz / Leistungsschütz / Gebläse)
    draw_switch_strips(ax, ax2, dv, t_start, t_end, temp_max)

    # Z=2 · Heizleistung LP0
    ax2.fill_between(dv['datetime'], 0, dv['LP0'],
                     color=COLOR_LP0, alpha=ALPHA_LP0, lw=0,
                     label='Heizleistung LP0 (%)', zorder=2)
    ax2.plot(dv['datetime'], dv['LP0'],
             color=COLOR_LP0, lw=0.6, alpha=0.5, zorder=2)

    # Ineffektive Heizphasen grau überlagern
    draw_ineff_overlay(ax2, dv)

    # Z=3 · Solltemperatur
    sp_ok = dv['SP0'].notna() & (dv['SP0'] > 0)
    if sp_ok.any():
        ax.plot(dv.loc[sp_ok, 'datetime'], dv.loc[sp_ok, 'SP0'],
                color=COLOR_SETPOINT, lw=LW_SETPOINT, ls='--', alpha=0.9,
                label='Soll SP0 (°C)', zorder=3)

    # Z=4 · Ist-Temperatur
    valid = dv['IN0'].notna()
    ax.plot(dv.loc[valid, 'datetime'], dv.loc[valid, 'IN0'],
            color=COLOR_TEMP, lw=LW_TEMP,
            label='Ist-Temp. IN0 (°C)', zorder=4)

    # Z=5 · State-Streifen
    prev_t, prev_s = None, None
    for _, row in dv.iterrows():
        t = row['datetime']
        s = row['State']
        if prev_t is not None:
            ax.axvspan(prev_t, t,
                       ymin=0, ymax=0.015,
                       color=STATE_COLORS.get(prev_s, COLOR_STATE_IDLE),
                       alpha=0.95, lw=0, zorder=5)
        prev_t, prev_s = t, s


    # Achsen (ymax wird in draw_switch_strips auf temp_max*1.04 gesetzt)
    ax.set_ylim(temp_min, ax.get_ylim()[1])
    ax.set_ylabel('Temperatur (°C)', color=COLOR_AXIS_TEXT, fontsize=10)
    ax.set_xlim(t_start, t_end)
    configure_xaxis(ax, total_h)

    # Annotation T-Maximum (nur wenn > 100 °C)
    max_temp_val = dv.loc[valid, 'IN0'].max() if valid.any() else float('nan')
    if valid.any():
        idx_max = dv.loc[valid, 'IN0'].idxmax()
        t_max   = dv.loc[idx_max, 'datetime']
        ax.annotate(f'{max_temp_val:.0f} °C',
                    xy=(t_max, max_temp_val),
                    xytext=(12, -28), textcoords='offset points',
                    fontsize=10, color=COLOR_ANNOT, fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color=COLOR_ANNOT, lw=1.3),
                    zorder=10)

    # Segmentwechsel-Marker
    draw_segment_markers(ax, dv, t_start)

    # Legende
    handles, labels = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    state_patches = [
        mpatches.Patch(color=c, label=f'State: {s}', alpha=0.85)
        for s, c in STATE_COLORS.items()
    ]
    sw_patches = [
        mpatches.Patch(color=COLOR_SW_SICHERHEIT, alpha=0.9, label='Sicherheitsschütz'),
        mpatches.Patch(color=COLOR_SW_LEISTUNG,   alpha=0.9, label='Leistungsschütz'),
        mpatches.Patch(color=COLOR_SW_GEBLAESE,   alpha=0.9, label='Gebläse'),
        mpatches.Patch(color='#888888',            alpha=0.55, label='Leistung ineffektiv'),
    ]
    ax.legend(handles=handles + h2 + state_patches + sw_patches,
              loc='upper right', fontsize=9, framealpha=0.25,
              facecolor='#333333', edgecolor='#555555',
              labelcolor=COLOR_AXIS_TEXT,
              bbox_to_anchor=(1.0, 1.0/1.04),
              bbox_transform=ax.transAxes)

    fan_h = sum((e - s).total_seconds() / 3600 for s, e in fan_spans)

    draw_event_strip(fig, ax, dv)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120,
                facecolor=BG_FIGURE)
    plt.close(fig)
    buf.seek(0)
    return buf.read(), max_temp_val, fan_h


# ── Optimierter Plot (Achsen an Daten angepasst) ─────────────────────────────

def draw_plot_optimized(dv, temp_padding_pct=0.08):
    """
    Wie draw_plot(), aber Zeitachse = exakte Datendauer,
    T-Achse = Daten-Maximum + Puffer.
    Gibt (png_bytes, max_temp_val, fan_h, duration_h) zurück.
    """
    t_start = dv['datetime'].iloc[0]
    t_end   = dv['datetime'].iloc[-1]
    total_h = (t_end - t_start).total_seconds() / 3600
    if total_h == 0:
        # Nur ein Zeitstempel vorhanden — minimale Spanne setzen
        from datetime import timedelta as _td
        t_end   = t_start + _td(minutes=1)
        total_h = 1/60

    valid      = dv['IN0'].notna()
    max_t_data = dv.loc[valid, 'IN0'].max() if valid.any() else TEMP_MAX
    # T-Achse: 0 … max_temp + Puffer, mindestens 50 °C Spanne
    t_axis_max = max(max_t_data * (1 + temp_padding_pct), max_t_data + 20, 50)
    # auf nächste 50er runden, mindestens TEMP_DISPLAY_MAX
    t_axis_max = max((int(t_axis_max / 50) + 1) * 50, TEMP_DISPLAY_MAX)

    fan_spans = bool_to_spans(dv['datetime'].tolist(), dv['fan_on'].tolist())

    fig, ax = plt.subplots(figsize=(16.54, 9.80), dpi=120)
    fig.patch.set_facecolor(BG_FIGURE)
    fig.subplots_adjust(top=0.91, bottom=0.14, left=0.06, right=0.93)
    style_ax(ax)

    ax2 = ax.twinx()
    ax2.set_facecolor(BG_AXES)
    ax2.set_ylim(-5, 110)
    ax2.set_ylabel('Heizleistung / Gebläse (%)', color=COLOR_AXIS_TEXT, fontsize=10)
    ax2.tick_params(axis='y', labelcolor=COLOR_AXIS_TEXT, labelsize=9,
                    colors=COLOR_TICK)
    for spine in ax2.spines.values():
        spine.set_edgecolor(COLOR_SPINE)

    # Z=1 · Schaltstreifen oben (draw_plot_optimized)
    draw_switch_strips(ax, ax2, dv, t_start, t_end, t_axis_max)

    ax2.fill_between(dv['datetime'], 0, dv['LP0'],
                     color=COLOR_LP0, alpha=ALPHA_LP0, lw=0,
                     label='Heizleistung LP0 (%)', zorder=2)
    ax2.plot(dv['datetime'], dv['LP0'],
             color=COLOR_LP0, lw=0.6, alpha=0.5, zorder=2)

    # Ineffektive Heizphasen grau überlagern
    draw_ineff_overlay(ax2, dv)

    sp_ok = dv['SP0'].notna() & (dv['SP0'] > 0)
    if sp_ok.any():
        ax.plot(dv.loc[sp_ok, 'datetime'], dv.loc[sp_ok, 'SP0'],
                color=COLOR_SETPOINT, lw=LW_SETPOINT, ls='--', alpha=0.9,
                label='Soll SP0 (°C)', zorder=3)

    ax.plot(dv.loc[valid, 'datetime'], dv.loc[valid, 'IN0'],
            color=COLOR_TEMP, lw=LW_TEMP,
            label='Ist-Temp. IN0 (°C)', zorder=4)

    prev_t, prev_s = None, None
    for _, row in dv.iterrows():
        t = row['datetime']
        s = row['State']
        if prev_t is not None:
            ax.axvspan(prev_t, t,
                       ymin=0, ymax=0.015,
                       color=STATE_COLORS.get(prev_s, COLOR_STATE_IDLE),
                       alpha=0.95, lw=0, zorder=5)
        prev_t, prev_s = t, s

    # ymax wurde in draw_switch_strips gesetzt
    ax.set_ylim(TEMP_MIN, ax.get_ylim()[1])
    ax.set_ylabel('Temperatur (°C)', color=COLOR_AXIS_TEXT, fontsize=10)
    ax.set_xlim(t_start, t_end)
    configure_xaxis(ax, total_h)

    if valid.any():
        idx_max = dv.loc[valid, 'IN0'].idxmax()
        t_max   = dv.loc[idx_max, 'datetime']
        ax.annotate(f'{max_t_data:.0f} °C',
                    xy=(t_max, max_t_data),
                    xytext=(12, -28), textcoords='offset points',
                    fontsize=10, color=COLOR_ANNOT, fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color=COLOR_ANNOT, lw=1.3),
                    zorder=10)

    # Segmentwechsel-Marker
    draw_segment_markers(ax, dv, dv['datetime'].iloc[0])

    handles, labels = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    state_patches = [
        mpatches.Patch(color=c, label=f'State: {s}', alpha=0.85)
        for s, c in STATE_COLORS.items()
    ]
    sw_patches = [
        mpatches.Patch(color=COLOR_SW_SICHERHEIT, alpha=0.9, label='Sicherheitsschütz'),
        mpatches.Patch(color=COLOR_SW_LEISTUNG,   alpha=0.9, label='Leistungsschütz'),
        mpatches.Patch(color=COLOR_SW_GEBLAESE,   alpha=0.9, label='Gebläse'),
        mpatches.Patch(color='#888888',            alpha=0.55, label='Leistung ineffektiv'),
    ]
    ax.legend(handles=handles + h2 + state_patches + sw_patches,
              loc='upper right', fontsize=9, framealpha=0.25,
              facecolor='#333333', edgecolor='#555555',
              labelcolor=COLOR_AXIS_TEXT,
              bbox_to_anchor=(1.0, 1.0/1.04),
              bbox_transform=ax.transAxes)

    fan_h = sum((e - s).total_seconds() / 3600 for s, e in fan_spans)

    draw_event_strip(fig, ax, dv)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120,
                facecolor=BG_FIGURE)
    plt.close(fig)
    buf.seek(0)
    return buf.read(), max_t_data, fan_h, total_h


def process_file_optimized(csvfile, ofen_kw=None, ofen_name=None):
    """
    Wie process_file(), aber ohne Fenster-Beschränkung:
    Zeitachse = gesamte Dateidauer, T-Achse = Daten-Maximum.
    Gibt page_dict zurück (clipped immer False) oder None.
    """
    df = load_csv(csvfile)
    if df.empty:
        return None

    dv = df.copy().reset_index(drop=True)
    if dv.empty:
        return None

    if len(dv) < 2:
        return None
    png, max_temp_val, fan_h, duration_h = draw_plot_optimized(dv)
    kwh = calc_kwh(dv, ofen_kw)

    t_start = dv['datetime'].iloc[0]
    t_end   = dv['datetime'].iloc[-1]

    # Dauer als hh:mm
    dur_total_min = int(round(duration_h * 60))
    dur_hh = dur_total_min // 60
    dur_mm = dur_total_min % 60

    # Titel: Dateiname + kompakte Kennwerte
    _name = ofen_name or OFEN_NAME
    _kw   = ofen_kw   or OFEN_KW
    title = (f"{_name}  ·  {csvfile.stem}   │   "
             f"T-max: {max_temp_val:.0f} °C   │   "
             f"Dauer: {dur_hh:02d}:{dur_mm:02d} h   │   "
             f"∼ {kwh:.1f} kWh")

    info = (f"Start: {t_start.strftime('%d.%m.%Y %H:%M')}  │  "
            f"Ende:  {t_end.strftime('%d.%m.%Y %H:%M')}  │  "
            f"Gebläse: {fan_h:.1f} h  │  "
            f"Zeitskala: {duration_h:.1f} h  (optimiert auf Datendauer)  │  "
            f"Nennleistung: {_kw:.1f} kW  │  "
            f"Events: {EVENT_LINK}")

    # Events die in diesem Brand vorkommen
    events_occurred = []
    if 'event' in dv.columns:
        seen = set()
        for _, row in dv[dv['event'] != ''].iterrows():
            ev = row['event']
            if ev not in seen:
                seen.add(ev)
                events_occurred.append((ev, row['datetime']))
    return dict(png_bytes=png, title=title, info_line=info,
                clipped=False, events=events_occurred)


# ── PDF mit Vektortext ───────────────────────────────────────────────────────


# ── HTML/Plotly Ausgabe ──────────────────────────────────────────────────────

def _plotly_theme(theme_name):
    """Gibt Plotly-Farbwerte für das gewählte Theme zurück."""
    if theme_name == 'light':
        return dict(
            bg_paper   = '#F5F5F0',
            bg_plot    = '#FFFFFF',
            grid       = '#CCCCCC',
            axis_text  = '#222222',
            temp       = '#7B0000',
            setpoint   = '#1A5F9E',
            lp0        = '#E07B00',
            fan        = '#007A75',
            state_run  = '#C0392B',
            state_stop = '#0077A8',
            state_idle = '#95A5A6',
            sw_sicher  = '#AAAAAA',
            sw_leist   = '#D4860A',
            sw_gebl    = '#007A75',
            annot      = '#8B0000',
            seg_col    = '#C07000',
        )
    else:  # dark
        return dict(
            bg_paper   = '#1E1E1E',
            bg_plot    = '#2A2A2A',
            grid       = '#404040',
            axis_text  = '#CCCCCC',
            temp       = '#FFFFFF',
            setpoint   = '#74B9FF',
            lp0        = '#FDCB6E',
            fan        = '#00CEC9',
            state_run  = '#FF7675',
            state_stop = '#00B4D8',
            state_idle = '#636E72',
            sw_sicher  = '#B0B0B0',
            sw_leist   = '#FDCB6E',
            sw_gebl    = '#00CEC9',
            annot      = '#FF6B6B',
            seg_col    = '#F0A500',
        )


def draw_plot_plotly(dv, title, info_line, theme_name='dark', x_end=None):
    """
    Erzeugt eine Plotly-Figur analog zum matplotlib-Plot.
    Gibt ein plotly.graph_objects.Figure-Objekt zurück.
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        raise ImportError("Plotly nicht installiert. Bitte: pip install plotly")

    c = _plotly_theme(theme_name)
    t0 = dv['datetime'].iloc[0]

    # ── Hilfsfunktion: Bool-Spans für Schaltstreifen ──────────────────────
    def spans(col):
        if col not in dv.columns:
            return []
        result, start = [], None
        for t, f in zip(dv['datetime'], dv[col]):
            if f and start is None:
                start = t
            elif not f and start is not None:
                result.append((start, t))
                start = None
        if start is not None:
            result.append((start, dv['datetime'].iloc[-1]))
        return result

    fig = go.Figure()

    # ── Ist-Temperatur (zuerst → oben in Hover-Legende) ──────────────────
    valid = dv['IN0'].notna()
    fig.add_trace(go.Scatter(
        x=dv.loc[valid, 'datetime'], y=dv.loc[valid, 'IN0'],
        mode='lines', line=dict(color=c['temp'], width=1.8),
        name='Ist-Temp IN0 (°C)',
        customdata=[
            f"+{int((dv.loc[valid,'datetime'].iloc[i]-t0).total_seconds()//3600):02d}:{int(((dv.loc[valid,'datetime'].iloc[i]-t0).total_seconds()%3600)//60):02d}"
            for i in range(valid.sum())
        ],
        hovertemplate='T: %{y:.1f}°C  %{customdata}<extra></extra>'
    ))

    # ── Solltemperatur ────────────────────────────────────────────────────
    sp_ok = dv['SP0'].notna() & (dv['SP0'] > 0)
    if sp_ok.any():
        fig.add_trace(go.Scatter(
            x=dv.loc[sp_ok, 'datetime'], y=dv.loc[sp_ok, 'SP0'],
            mode='lines', line=dict(color=c['setpoint'], width=1.2, dash='dash'),
            name='Soll SP0 (°C)',
            hovertemplate='SP0: %{y:.0f}°C<extra></extra>'
        ))

    # ── LP0-Fläche (sekundäre Y-Achse) ───────────────────────────────────
    lp0_valid = dv['LP0'].fillna(0)
    fig.add_trace(go.Scatter(
        x=dv['datetime'], y=lp0_valid,
        fill='tozeroy', mode='lines',
        line=dict(color=c['lp0'], width=0.8),
        fillcolor=c['lp0'].replace('#', 'rgba(').rstrip(')') if False else
                  f"rgba({int(c['lp0'][1:3],16)},{int(c['lp0'][3:5],16)},{int(c['lp0'][5:7],16)},0.35)",
        name='Heizleistung LP0 (%)',
        yaxis='y2',
        hovertemplate='LP0: %{y:.1f}%<extra></extra>'
    ))

    # ── LP0ineff-Fläche (ineffektive Heizphasen, grau) ──────────────────
    if 'LP0ineff' in dv.columns and dv['LP0ineff'].max() > 0:
        fig.add_trace(go.Scatter(
            x=dv['datetime'], y=dv['LP0ineff'].fillna(0),
            fill='tozeroy', mode='lines',
            line=dict(color='#888888', width=0.8),
            fillcolor='rgba(136,136,136,0.45)',
            name='Leistung ineffektiv',
            yaxis='y2',
            hovertemplate='LP0 ineff: %{y:.1f}%<extra></extra>'
        ))

    # ── Schaltstreifen als Shapes ─────────────────────────────────────────
    STRIP_COLS = [
        ('sw_geblaese',   c['sw_gebl'],   'Gebläse'),
        ('sw_leistung',   c['sw_leist'],  'Leistungsschütz'),
        ('sw_sicherheit', c['sw_sicher'], 'Sicherheitsschütz'),
    ]
    # Streifen auf y2 (0–110), oberhalb 100: 100.5–103 / 103.5–106.5 / 109–110
    STRIP_Y = {
        'sw_geblaese':   (100.5, 103.0),
        'sw_leistung':   (103.5, 106.5),
        'sw_sicherheit': (109.0, 110.0),
    }
    shapes = []
    for col, color, label in STRIP_COLS:
        if col not in dv.columns:
            continue
        y0, y1 = STRIP_Y[col]
        for s, e in spans(col):
            shapes.append(dict(
                type='rect', xref='x', yref='y2',
                x0=s, x1=e, y0=y0, y1=y1,
                fillcolor=color, opacity=0.90,
                line=dict(width=0), layer='above'
            ))

    # ── State-Leiste als Shapes (y2: -2 bis 0) ───────────────────────────
    STATE_C = {'RUN': c['state_run'], 'STOP': c['state_stop'], 'IDLE': c['state_idle'],
               'HOLD': COLOR_STATE_HOLD, 'ERR': COLOR_STATE_ERR}
    prev_t, prev_s = None, None
    for _, row in dv.iterrows():
        t = row['datetime']
        s = row['State']
        if prev_t is not None:
            shapes.append(dict(
                type='rect', xref='x', yref='y2',
                x0=prev_t, x1=t, y0=-2, y1=0,
                fillcolor=STATE_C.get(prev_s, c['state_idle']),
                opacity=0.95, line=dict(width=0), layer='above'
            ))
        prev_t, prev_s = t, s

    # ── Legendeneinträge für Schaltstreifen + State (unsichtbare Traces) ──
    for col, color, label in STRIP_COLS:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode='markers',
            marker=dict(size=10, color=color, symbol='square'),
            name=label, showlegend=True,
            hoverinfo='skip', yaxis='y2'
        ))
    for state, color in STATE_C.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode='markers',
            marker=dict(size=10, color=color, symbol='square'),
            name=f'State: {state}', showlegend=True,
            hoverinfo='skip'
        ))

    # ── Event-Badges als Shapes + Annotationen (y2: 111–114) ────────────
    if 'event' in dv.columns:
        seen_ev = set()
        for _, row in dv[dv['event'] != ''].iterrows():
            ev = row['event']
            _ei = EVENT_INFO.get(ev, ('', '', '#E74C3C'))
            badge_col = _ei[2]
            t = row['datetime']
            # Hintergrund-Rechteck für Badge
            shapes.append(dict(
                type='rect', xref='x', yref='y2',
                x0=t, x1=t, y0=111, y1=114,
                fillcolor=badge_col, opacity=0, line=dict(width=0)
            ))
            if ev not in seen_ev:
                seen_ev.add(ev)
                short_desc = _ei[0]
                long_desc  = _ei[1]
                hover_text = f'<b>{ev}</b> – {short_desc}'
                if long_desc:
                    hover_text += f'<br><i>{long_desc}</i>'
                # Badge als unsichtbarer Scatter mit Text
                fig.add_trace(go.Scatter(
                    x=[t], y=[112.5],
                    mode='markers+text',
                    marker=dict(size=14, color=badge_col, symbol='square'),
                    text=[ev], textposition='middle center',
                    textfont=dict(size=8, color='white'),
                    name=f'Event {ev}', showlegend=False,
                    yaxis='y2',
                    hovertemplate=hover_text + '<extra></extra>'
                ))
        # Streifen-Hintergrund
        if seen_ev:
            shapes.append(dict(
                type='rect', xref='paper', yref='y2',
                x0=0, x1=1, y0=110.3, y1=114.2,
                fillcolor='rgba(26,26,26,0.7)',
                line=dict(color='#444444', width=0.5), layer='below'
            ))

    # ── Legendeneintrag Leistung ineffektiv ──────────────────────────────
    if 'LP0ineff' in dv.columns and dv['LP0ineff'].max() > 0:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode='markers',
            marker=dict(size=10, color='#888888', symbol='square'),
            name='Leistung ineffektiv', showlegend=True,
            hoverinfo='skip', yaxis='y2'
        ))

    # ── Segmentwechsel-Annotationen ───────────────────────────────────────
    annotations = []

    # Startlabel: erster Datenpunkt (00:00)
    valid_start = dv['IN0'].notna()
    if valid_start.any():
        t0_row = dv.loc[valid_start].iloc[0]
        T0     = float(t0_row['IN0'])
        annotations.append(dict(
            x=t0_row['datetime'], y=T0,
            xref='x', yref='y',
            text=f'{T0:.0f}°C  00:00',
            showarrow=True, arrowhead=2,
            arrowcolor=c['seg_col'], ax=-SEG_OX//2, ay=-SEG_OY,
            font=dict(size=9, color=c['seg_col']),
            bgcolor=c['bg_paper'],
            bordercolor=c['seg_col'],
            borderwidth=1, borderpad=3,
            opacity=0.88
        ))

    first_seg = dv['Seg'].iloc[0] if len(dv) > 0 else 0
    prev_seg  = first_seg
    flip      = 1
    for _, row in dv.iterrows():
        seg = row['Seg']
        if seg == prev_seg or seg <= 0:
            continue
        T = row['IN0']
        try:
            import math
            if math.isnan(float(T)):
                prev_seg = seg
                continue
        except (TypeError, ValueError):
            prev_seg = seg
            continue
        elapsed = (row['datetime'] - t0).total_seconds()
        hh = int(elapsed // 3600)
        mm = int((elapsed % 3600) // 60)
        label = f"{T:.0f}°C  {hh:02d}:{mm:02d}"
        annotations.append(dict(
            x=row['datetime'], y=float(T),
            xref='x', yref='y',
            text=label,
            showarrow=True,
            arrowhead=2, arrowsize=1, arrowwidth=1.2,
            arrowcolor=c['seg_col'],
            ax=SEG_OX, ay=-SEG_OY * flip,
            font=dict(size=9, color=c['seg_col']),
            bgcolor=c['bg_paper'],
            bordercolor=c['seg_col'],
            borderwidth=1, borderpad=3,
            opacity=0.88
        ))
        flip *= -1
        prev_seg = seg

    # ── T-Maximum-Annotation ──────────────────────────────────────────────
    if valid.any():
        idx_max   = dv.loc[valid, 'IN0'].idxmax()
        t_max     = dv.loc[idx_max, 'datetime']
        max_t_val = dv.loc[idx_max, 'IN0']
        annotations.append(dict(
            x=t_max, y=float(max_t_val),
            xref='x', yref='y',
            text=f"<b>{max_t_val:.0f} °C</b>",
            showarrow=True, arrowhead=2,
            arrowcolor=c['annot'], ax=15, ay=30,
            font=dict(size=11, color=c['annot']),
            bgcolor=c['bg_paper'],
            bordercolor=c['annot'],
            borderwidth=1, borderpad=3,
            opacity=0.88
        ))

    # ── Layout ────────────────────────────────────────────────────────────
    t_axis_max = max(
        dv.loc[valid, 'IN0'].max() * 1.04 if valid.any() else TEMP_DISPLAY_MAX,
        TEMP_DISPLAY_MAX)
    t_axis_max = max((int(t_axis_max / 50) + 1) * 50, TEMP_DISPLAY_MAX)

    fig.update_layout(
        title=dict(text=f"<b>{title}</b><br><sup>{info_line}</sup>",
                   font=dict(size=14, color=c['axis_text']),
                   x=0.5),
        paper_bgcolor=c['bg_paper'],
        plot_bgcolor =c['bg_plot'],
        hovermode   ='x',
        hoverlabel  =dict(
            bgcolor  =f"rgba({{}},{{}},{{}},0.60)".format(
                int(c['bg_paper'][1:3],16),
                int(c['bg_paper'][3:5],16),
                int(c['bg_paper'][5:7],16)),
            bordercolor=c['grid'],
            font=dict(color=c['axis_text'], size=10),
        ),
        shapes      = shapes,
        annotations = annotations,
        legend=dict(
            orientation='v', x=1.07, y=0.95,
            bgcolor=c['bg_paper'],
            bordercolor=c['grid'], borderwidth=1,
            font=dict(color=c['axis_text'], size=9)
        ),
        xaxis=dict(
            showgrid=True, gridcolor=c['grid'], gridwidth=0.5,
            tickfont=dict(color=c['axis_text'], size=9),
            tickformat='%d.%m %H:%M',
            **({'range': [dv['datetime'].iloc[0], x_end]} if x_end is not None else {}),
        ),
        yaxis=dict(
            title=dict(text='Temperatur (°C)', font=dict(color=c['axis_text'])),
            range=[TEMP_MIN, t_axis_max * 1.04],
            showgrid=True, gridcolor=c['grid'], gridwidth=0.5,
            tickfont=dict(color=c['axis_text'], size=9),
        ),
        yaxis2=dict(
            title=dict(text='Heizleistung / Gebläse (%)', font=dict(color=c['axis_text'])),
            range=[-2, 115],
            overlaying='y', side='right',
            showgrid=False,
            tickfont=dict(color=c['axis_text'], size=9),
        ),
        margin=dict(l=60, r=120, t=80, b=60),
        height=850,  # wird via CSS auf 85vh gesetzt
    )
    fig.update_xaxes(showline=True, linecolor=c['grid'])
    fig.update_yaxes(showline=True, linecolor=c['grid'])

    return fig


def build_html(figs_and_titles, output_path, theme_name='dark', events=None):
    """
    Schreibt eine self-contained HTML-Datei mit allen Plotly-Figuren.
    figs_and_titles: Liste von (fig, tab_title)
    """
    try:
        from plotly.io import to_html
    except ImportError:
        raise ImportError("Plotly nicht installiert. Bitte: pip install plotly")

    c = _plotly_theme(theme_name)
    bg = c['bg_paper']
    fg = c['axis_text']
    tab_bg_act = c['lp0']
    tab_fg_act = '#1E1E1E'

    # Jede Figur als div, Navigation via einfachen JS-Tab-Switcher
    divs   = []
    tabs   = []
    for i, (fig, tab_title) in enumerate(figs_and_titles):
        display = 'block' if i == 0 else 'none'
        fig_html = to_html(fig, full_html=False, include_plotlyjs=(i == 0), config={'responsive': True})
        divs.append(
            f'<div id="fig{i}" class="fig-panel" style="display:{display}">' +
            fig_html + '</div>'
        )
        active = 'class="tab active"' if i == 0 else 'class="tab"'
        tabs.append(f'<button {active} onclick="showFig({i})">{tab_title}</button>')

    tabs_html = '\n'.join(tabs)
    divs_html = '\n'.join(divs)

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>{output_path.stem}</title>
<style>
  body   {{ background:{bg}; color:{fg}; font-family:sans-serif; margin:0; padding:8px; }}
  .plotly-graph-div {{ height:85vh !important; }}
  .tabs  {{ display:flex; flex-wrap:wrap; gap:4px; margin-bottom:8px; }}
  .tab   {{ background:{c['bg_plot']}; color:{fg}; border:1px solid {c['grid']};
            padding:5px 14px; cursor:pointer; border-radius:4px; font-size:12px; }}
  .tab.active {{ background:{tab_bg_act}; color:{tab_fg_act}; font-weight:bold; }}
  .tab:hover  {{ opacity:0.85; }}
</style>
</head>
<body>
<div class="tabs">{tabs_html}</div>
{divs_html}
<script>
function showFig(n) {{
  document.querySelectorAll('.fig-panel').forEach((d,i) => d.style.display = i===n?'block':'none');
  document.querySelectorAll('.tab').forEach((b,i) => b.classList.toggle('active', i===n));
  // Plotly neu rendern damit die Canvas-Breite korrekt berechnet wird
  var panel = document.getElementById('fig'+n);
  var plots = panel ? panel.querySelectorAll('.plotly-graph-div') : [];
  plots.forEach(function(p) {{ Plotly.relayout(p, {{autosize: true}}); }});
}}
</script>
{{event_block}}
</body>
</html>"""

    # Event-Block
    if events:
        evt_rows = []
        for ev in events:
            _ei = EVENT_INFO.get(ev, (ev, '', '#888888'))
            short_d, long_d, col = _ei[0], _ei[1], _ei[2]
            long_html = f' <span style="color:#666;font-size:0.85em">({long_d})</span>' if long_d else ''
            evt_rows.append(
                f'<span style="display:inline-block;width:10px;height:10px;'
                f'border-radius:3px;background:{col};margin-right:5px;vertical-align:middle"></span>'
                f'<b style="color:{col}">{ev}</b>'
                f' <span style="color:{fg}">– {short_d}</span>{long_html}')
        link_html = (f'<a href="{EVENT_LINK}" target="_blank" '
                     f'style="color:#555;font-size:0.8em;float:right">'
                     f'Event-Tabelle ↗</a>')
        event_block_html = (
            f'<div style="background:{bg};padding:8px 16px 10px 16px;'
            f'border-top:1px solid #444;font-family:monospace;font-size:0.88em;line-height:1.8">'
            f'{link_html}' +
            '<br>'.join(evt_rows) +
            '</div>')
    else:
        event_block_html = ''

    html = html.replace('{event_block}', event_block_html)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)



# ── kWh-Log & Verbrauchsplot ─────────────────────────────────────────────────

def update_kwh_log(out_dir, csvfile, kwh_val):
    """
    Aktualisiert kWh.log im out_dir.
    Format: Datum\tDateiname\tkWh
    Kein Duplikat — vorhandener Eintrag wird überschrieben.
    """
    log_path = out_dir / 'kWh.log'
    entries  = {}

    if log_path.exists():
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('\t')
                if len(parts) >= 3:
                    entries[parts[1]] = (parts[0], parts[2])

    d = date_from_filename(csvfile)
    date_str = d.strftime('%Y-%m-%d') if d else 'unbekannt'
    entries[csvfile.name] = (date_str, f'{kwh_val:.2f}')

    with open(log_path, 'w', encoding='utf-8') as f:
        f.write('# Datum\tDateiname\tkWh\n')
        for fname, (ds, kw) in sorted(entries.items()):
            f.write(f'{ds}\t{fname}\t{kw}\n')


def build_kwh_plot(out_dir, theme_name='dark', ofen_name=None, ofen_kw=None, zr_info='', thr_str=''):
    """
    Liest kWh.log und erstellt kWhlog_dark.pdf / kWhlog_light.pdf.
    Layout: A3 Querformat, eine Seite pro Jahr.
    Pro Seite 3 Streifen à 4 Monate (Jan–Apr / Mai–Aug / Sep–Dez).
    Balken pro Brand.
    """
    log_path = out_dir / 'kWh.log'
    if not log_path.exists():
        return

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.backends.backend_pdf import PdfPages
    from datetime import date as _date
    import numpy as np

    # Log einlesen
    records = []
    with open(log_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 3:
                continue
            try:
                d   = _date.fromisoformat(parts[0])
                kwh = float(parts[2])
                records.append((d, parts[1], kwh))
            except (ValueError, IndexError):
                continue

    if not records:
        return

    # Theme-Farben
    apply_theme(theme_name)
    c_bg     = BG_FIGURE
    c_axes   = BG_AXES
    c_grid   = COLOR_GRID_MAJOR
    c_text   = COLOR_AXIS_TEXT
    c_bar    = COLOR_LP0
    c_spine  = COLOR_SPINE

    # Nach Jahr gruppieren
    from collections import defaultdict
    by_year = defaultdict(list)
    for d, fname, kwh in sorted(records):
        by_year[d.year].append((d, fname, kwh))

    MONTH_GROUPS = [(1,4), (5,8), (9,12)]
    MONTH_NAMES  = ['Jan','Feb','Mär','Apr','Mai','Jun',
                    'Jul','Aug','Sep','Okt','Nov','Dez']

    _suffix = ''
    if zr_info and zr_info not in ('Batch', 'Einzelauswertung'):
        _suffix += f'_{zr_info}'
    if thr_str:
        _suffix += f'_{thr_str}'
    out_path = out_dir / f'kWhlog_{theme_name}{_suffix}.pdf'

    with PdfPages(str(out_path)) as pdf:
        for year in sorted(by_year.keys()):
            entries = by_year[year]
            fig = plt.figure(figsize=(16.54, 11.69))  # A3 landscape
            fig.patch.set_facecolor(c_bg)
            _oname = ofen_name or OFEN_NAME
            _okw   = ofen_kw   or OFEN_KW
            fig.suptitle(f'Stromverbrauch  {_oname}  ·  {_okw:.2f} kW  ·  {year}',
                         color=c_text, fontsize=16, fontweight='bold', y=0.97)

            total_year = sum(k for _,_,k in entries)
            fig.text(0.5, 0.93,
                     f'Gesamt: {total_year:.1f} kWh  |  {len(entries)} Brände',
                     ha='center', color=COLOR_ANNOT, fontsize=10)
            if zr_info or thr_str:
                info_parts = [p for p in [zr_info, thr_str] if p]
                fig.text(0.98, 0.93, '  │  '.join(info_parts),
                         ha='right', color=c_grid, fontsize=8, alpha=0.7)

            axes = []
            for i, (m_from, m_to) in enumerate(MONTH_GROUPS):
                ax = fig.add_subplot(3, 1, i+1)
                ax.set_facecolor(c_axes)
                for spine in ax.spines.values():
                    spine.set_edgecolor(c_spine)
                ax.tick_params(colors=c_text, which='both')
                ax.yaxis.label.set_color(c_text)
                ax.xaxis.label.set_color(c_text)
                ax.grid(True, axis='y', color=c_grid, ls='--', alpha=0.5, lw=0.5)

                # Einträge für diesen 4-Monats-Block
                block = [(d, fn, kw) for d, fn, kw in entries
                         if m_from <= d.month <= m_to]

                # Kumulierte Jahressumme bis Ende dieses Blocks
                cum_all   = [(d, kw) for d, _, kw in entries]
                cum_dates = [d for d,_ in cum_all]
                cum_vals  = []
                running   = 0
                for d, kw in cum_all:
                    running += kw
                    cum_vals.append(running)

                # Sekundärachse für Jahressumme
                ax_cum = ax.twinx()
                ax_cum.set_ylim(0, KWH_CUM_MAX)
                ax_cum.set_ylabel('Jahressumme kWh', color=c_grid, fontsize=7)
                ax_cum.tick_params(axis='y', labelcolor=c_grid, labelsize=7)
                for spine in ax_cum.spines.values():
                    spine.set_edgecolor(c_spine)

                # Zeitliche X-Achse: Tag des Monats × Monat (1..122)
                # 4 Monate à max 31 Tage = 0..123
                def _xpos_time(d, m_from):
                    """X-Position: Tage seit Beginn des ersten Monats im Block"""
                    from datetime import date as _d2
                    block_start = _d2(d.year, m_from, 1)
                    return (d - block_start).days

                x_max = sum(
                    31 if m in (1,3,5,7,8,10,12) else
                    30 if m in (4,6,9,11) else 29
                    for m in range(m_from, m_to+1))

                # Kumulierte Linie über alle Jahreseinträge bis m_to
                all_in_range = [(d,fn,kw) for d,fn,kw in sorted(entries)
                                if d.month <= m_to]
                cum_running = 0
                cum_xs, cum_ys = [], []
                for d2, fn2, kw2 in all_in_range:
                    cum_running += kw2
                    xp = _xpos_time(d2, 1)  # relativ zu Jan
                    if d2.month >= m_from:
                        xp = _xpos_time(d2, m_from)
                        cum_xs.append(xp)
                        cum_ys.append(cum_running)
                    elif cum_xs:
                        # Einträge vor diesem Block: letzten Wert aktualisieren
                        pass

                # Alle Einträge kumuliert (auch vor Block) für Linie
                cum_running2 = 0
                cum_xs2, cum_ys2 = [], []
                for d2, fn2, kw2 in sorted(entries):
                    cum_running2 += kw2
                    if m_from <= d2.month <= m_to:
                        cum_xs2.append(_xpos_time(d2, m_from))
                        cum_ys2.append(cum_running2)

                if cum_xs2:
                    ax_cum.plot(cum_xs2, cum_ys2,
                                color=c_grid, lw=1.2, alpha=0.35, zorder=2)
                    ax_cum.text(cum_xs2[-1] + 0.5, cum_ys2[-1],
                                f' {cum_ys2[-1]:.0f}',
                                color=c_grid, fontsize=6.5, va='center', alpha=0.6)

                ax.set_xlim(-1, x_max + 1)
                ax.set_ylim(0, KWH_Y_MAX)

                # Monatstrennlinien
                import re as _re
                x_sep = 0
                for m in range(m_from, m_to):
                    days_in_m = 31 if m in (1,3,5,7,8,10,12) else 30 if m in (4,6,9,11) else 29
                    x_sep += days_in_m
                    ax.axvline(x_sep, color=c_spine, lw=0.5, alpha=0.4, zorder=1)

                if block:
                    # Testbrände (< KWH_TEST_STACK) zu Sammelsäule am Anfang
                    tests  = [(d,fn,kw) for d,fn,kw in block if kw < KWH_TEST_STACK]
                    normal = [(d,fn,kw) for d,fn,kw in block if kw >= KWH_TEST_STACK]
                    test_sum = sum(kw for _,_,kw in tests)

                    bar_width = max(0.4, min(1.5, x_max / 60))

                    # Sammelsäule bei x=-0.5 (vor Tag 1)
                    if tests:
                        ax.bar([-0.5], [min(test_sum, KWH_Y_MAX)],
                               color=c_bar, alpha=0.45, width=bar_width*0.8, zorder=3)
                        ax.text(-0.5, min(test_sum, KWH_Y_MAX) + 0.5,
                                f'Σ{test_sum:.1f}', ha='center', va='bottom',
                                fontsize=5.5, color=c_text)
                        ax.text(-0.5, -KWH_Y_MAX * 0.06,
                                f'Tests\n({len(tests)}×)', ha='center', va='top',
                                fontsize=5.5, color=c_text,
                                transform=ax.get_xaxis_transform() if False else ax.transData)

                    # Normale Brände zeitlich platziert
                    for d, fn, kw in normal:
                        xp = _xpos_time(d, m_from)
                        col = c_bar
                        bar = ax.bar([xp], [min(kw, KWH_Y_MAX)],
                                     color=col, alpha=0.75, width=bar_width, zorder=3)
                        label = f'{kw:.1f}' if kw <= KWH_Y_MAX else f'▲{kw:.1f}'
                        ax.text(xp, min(kw, KWH_Y_MAX) + 0.5, label,
                                ha='center', va='bottom', fontsize=6,
                                color=c_text if kw <= KWH_Y_MAX else COLOR_ANNOT,
                                rotation=90 if kw > 10 else 0)

                    # X-Ticks: Monatserste
                    tick_xs, tick_ls = [], []
                    x_off = 0
                    for m in range(m_from, m_to+1):
                        tick_xs.append(x_off)
                        tick_ls.append(MONTH_NAMES[m-1])
                        days_in_m = 31 if m in (1,3,5,7,8,10,12) else 30 if m in (4,6,9,11) else 29
                        x_off += days_in_m
                    ax.set_xticks(tick_xs)
                    ax.set_xticklabels(tick_ls, fontsize=8, color=c_text)
                else:
                    ax.set_xticks([])
                    ax.text(0.5, 0.5, '— keine Brände —',
                            ha='center', va='center', transform=ax.transAxes,
                            color=c_grid, fontsize=9)

                # Monatsnamen als Hintergrund-Label
                month_label = '  '.join(MONTH_NAMES[m_from-1:m_to])
                ax.set_title(month_label, color=c_text, fontsize=9,
                             loc='left', pad=4)
                ax.set_ylabel('kWh / Brand', color=c_text, fontsize=8)
                ax.tick_params(axis='y', labelcolor=c_text, labelsize=8)

                axes.append(ax)

            fig.tight_layout(rect=[0, 0, 1, 0.91])
            pdf.savefig(fig, facecolor=c_bg, bbox_inches='tight')
            plt.close(fig)

    print(f"✓ kWh-Plot [{theme_name}]: {out_path.resolve()}")


def append_pdf(base_path, append_path):
    """Hängt append_path an base_path an (in-place). Nutzt pypdf wenn verfügbar."""
    try:
        from pypdf import PdfWriter, PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfWriter, PdfReader
        except ImportError:
            print("  ⚠ pypdf nicht installiert — kWhlog nicht angehängt (pip install pypdf)")
            return
    writer = PdfWriter()
    for path in [base_path, append_path]:
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
    with open(str(base_path), 'wb') as f:
        writer.write(f)


def build_pdf(pages_data, output_path, zr_info='', thr_str=''):
    """
    pages_data: Liste von dicts mit keys:
        png_bytes, title, info_line, clipped
    """
    c  = rl_canvas.Canvas(str(output_path), pagesize=landscape(A3))
    pw, ph = landscape(A3)

    # PDF-Metadaten
    from datetime import datetime as _dt
    c.setTitle(f'{OFEN_NAME}  ·  {_dt.now().strftime("%Y-%m-%d")}')
    c.setSubject(f'Zeitraum: {zr_info}  │  {thr_str}')
    c.setAuthor(OFEN_NAME)
    c.setSubject(f'Ofen-Log Auswertung  ·  {OFEN_NAME}')
    c.setCreator('courbes.py')


    # Platzeinteilung (Punkte, 1pt = 1/72 inch)
    TEXT_AREA_H  = 68   # pt oben für Titel + 2-zeilige Info
    EVENT_LINE_H = 15   # pt pro Event-Zeile
    PLOT_Y_BASE  = 8    # pt unterster Rand
    # Fixer unterer Rand für Plot: max. Event-Bereich reservieren (6 Events)
    PLOT_Y_FIXED = PLOT_Y_BASE + 6 * EVENT_LINE_H + 4
    PLOT_H_FIXED = ph - TEXT_AREA_H - PLOT_Y_FIXED

    for pd_ in pages_data:
        # Hintergrund
        c.setFillColor(HexColor(_PDF_BG))
        c.rect(0, 0, pw, ph, fill=1, stroke=0)

        # Event-Zeilen berechnen (für Fußzeile)
        events = pd_.get('events', [])
        n_evt  = len(events)
        evt_area_h = (n_evt * EVENT_LINE_H + (4 if n_evt else 0))

        # Plot-PNG: immer auf fixer Position (oben unter Textkopf)
        # Canvas-Oberkante bleibt konstant — nur Unterkante kann variieren
        img    = ImageReader(io.BytesIO(pd_['png_bytes']))
        iw, ih = img.getSize()
        scale  = min(pw / iw, PLOT_H_FIXED / ih)
        img_w  = iw * scale
        img_h  = ih * scale
        img_x  = (pw - img_w) / 2
        img_y  = ph - TEXT_AREA_H - img_h   # immer von oben platziert
        c.drawImage(img, img_x, img_y, img_w, img_h, mask='auto')

        # Trennlinie zwischen Plot und Textkopf
        c.setStrokeColor(HexColor(COLOR_SPINE))
        c.setLineWidth(0.5)
        c.line(20, ph - TEXT_AREA_H, pw - 20, ph - TEXT_AREA_H)

        # Titelzeile
        title_color = HexColor('#FDCB6E') if pd_['clipped'] else HexColor(_PDF_TITLE_COLOR)
        c.setFillColor(title_color)
        c.setFont(PDF_FONT_TITLE, PDF_SIZE_TITLE)
        c.drawCentredString(pw / 2, ph - 22, pd_['title'])

        # Info-Zeile 1: Kurven-Info (aufgeteilt in zwei Zeilen wenn zu lang)
        info_color = HexColor('#555555') if _PDF_BG.startswith('#F') else HexColor('#BBBBBB')
        c.setFillColor(info_color)
        info_size = PDF_SIZE_INFO + 2  # 2 Stufen größer
        c.setFont(PDF_FONT_INFO, info_size)
        # Info-Zeile aufteilen: alles bis erstem │ in Zeile 1, Rest in Zeile 2
        info = pd_['info_line']
        parts = info.split('  │  ')
        mid = len(parts) // 2
        info_line1 = '  │  '.join(parts[:mid]) if mid > 0 else info
        info_line2 = '  │  '.join(parts[mid:]) if mid > 0 and mid < len(parts) else ''
        c.drawCentredString(pw / 2, ph - 40, info_line1)
        if info_line2:
            c.drawCentredString(pw / 2, ph - 54, info_line2)

        # Auswertungs-Info (Zeitraum + Schwellwert) — rechts oben
        if zr_info or thr_str:
            report_str = '  │  '.join(filter(None, [
                f'Zeitraum: {zr_info}' if zr_info else '',
                thr_str if thr_str else ''
            ]))
            c.setFont(PDF_FONT_INFO, PDF_SIZE_INFO - 1)
            c.drawRightString(pw - 20, ph - 40, report_str)

        # Event-Zeilen unterhalb des Plots
        if events:
            from reportlab.lib.colors import HexColor as _HC
            y_evt = PLOT_Y_BASE + evt_area_h - 2  # Fußzeile von unten
            c.setFont('Helvetica', 6.5)
            for evt_item in events:
                # events kann (ev, datetime) tuple oder nur ev-string sein
                if isinstance(evt_item, tuple):
                    ev, evt_time = evt_item
                else:
                    ev, evt_time = evt_item, None
                _ei = EVENT_INFO.get(ev, (ev, '', '#888888'))
                desc, long_desc, badge_col = _ei[0], _ei[1], _ei[2]
                # Farbpunkt
                c.setFillColor(_HC(badge_col))
                c.circle(22, y_evt + 3.0, 3.5, fill=1, stroke=0)
                # Event-ID fett + Uhrzeit
                c.setFillColor(_HC(badge_col))
                c.setFont('Helvetica-Bold', 7.5)
                time_str = f" {evt_time.strftime('%H:%M')}" if evt_time else ''
                c.drawString(28, y_evt, ev + time_str)
                # Beschreibung dezent grau
                c.setFillColor(_HC('#888888'))
                c.setFont('Helvetica', 7.5)
                x_after_id = 28 + c.stringWidth(ev + time_str, 'Helvetica-Bold', 7.5) + 4
                short_str = f'– {desc}'
                c.drawString(x_after_id, y_evt, short_str)
                if long_desc:
                    x_long = x_after_id + c.stringWidth(short_str, 'Helvetica', 7.5) + 4
                    c.setFillColor(_HC('#606060'))
                    c.setFont('Helvetica', 7.0)
                    c.drawString(x_long, y_evt, f'({long_desc})')
                    c.setFont('Helvetica', 7.5)
                y_evt -= EVENT_LINE_H
            # Link auf Event-Tabelle
            c.setFillColor(_HC('#555555'))
            c.setFont('Helvetica', 5.5)
            c.drawRightString(pw - 20, PLOT_Y_BASE,
                              f'Event-Tabelle: {EVENT_LINK}')

        c.showPage()

    c.save()


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def parse_hhmm(s):
    """'hh:mm' → Stunden als float. None bei leerem String."""
    s = s.strip()
    if not s:
        return None
    try:
        parts = s.split(':')
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        return h + m / 60.0
    except Exception:
        return None


def parse_cutoffs(raw):
    """
    'VOR,NACH' → (cutoff_front_h, cutoff_back_h), je None wenn leer.
    Akzeptiert auch nur 'VOR,' oder ',NACH' oder ''.
    """
    if not raw.strip():
        return None, None
    parts = raw.split(',')
    front = parse_hhmm(parts[0]) if len(parts) > 0 else None
    back  = parse_hhmm(parts[1]) if len(parts) > 1 else None
    return front, back


def find_csv_dir(workdir):
    matches = sorted(workdir.glob('TC707*'))
    dirs    = [m for m in matches if m.is_dir()]
    return dirs[0] if dirs else workdir


def date_from_filename(path):
    """
    Versucht ein Datum aus dem Dateinamen zu lesen.
    Unterstützt: 2026-03-15_2155_P05.csv  oder  2026_03_15_...
    Gibt datetime.date oder None zurück.
    """
    import re
    from datetime import date as _date
    stem = path.stem
    m = re.match(r'(\d{4})[-_](\d{2})[-_](\d{2})', stem)
    if m:
        try:
            return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def find_all_csv(workdir, date_from=None, date_to=None):
    """
    Sucht rekursiv alle *.csv unterhalb von workdir (oder TC707*-Unterordner).
    Filtert optional nach Datum aus Dateiname.
    Gibt sortierte Liste von Path-Objekten zurück.
    """
    # Wurzel: TC707*-Ordner falls vorhanden, sonst workdir
    matches = sorted(workdir.glob('TC707*'))
    dirs    = [m for m in matches if m.is_dir()]
    root    = dirs[0] if dirs else workdir

    all_csv = sorted(root.rglob('*.csv'))

    if date_from is None and date_to is None:
        return all_csv

    result = []
    for f in all_csv:
        d = date_from_filename(f)
        if d is None:
            result.append(f)   # kein Datum im Namen → immer einschließen
            continue
        if date_from and d < date_from:
            continue
        if date_to and d > date_to:
            continue
        result.append(f)
    return result


def parse_date_range(raw):
    """
    Parst Zeitraum-Eingabe: '1.2.25-' / '-3.3.26' / '1.2.25-3.3.26' / ''
    Gibt (date_from, date_to) zurück, je None wenn offen.
    Zweistellige Jahre werden als 20xx interpretiert.
    """
    from datetime import date as _date
    import re

    def parse_date(s):
        s = s.strip()
        if not s:
            return None
        m = re.match(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})$', s)
        if not m:
            return None
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return _date(y, mo, d)
        except ValueError:
            return None

    raw = raw.strip()
    if not raw:
        return None, None
    if '-' not in raw:
        d = parse_date(raw)
        return d, d
    parts = raw.split('-', 1)
    return parse_date(parts[0]), parse_date(parts[1])


def ask_single_file(csv_files, threshold=0.0, ofen_kw=None):
    """Zeigt nur Logs oberhalb des Schwellwerts an."""
    # Vorab filtern wenn Schwellwert gesetzt
    if threshold > 0:
        filtered = []
        for f in csv_files:
            try:
                df = load_csv(f)
                kwh = calc_kwh(df, ofen_kw) if not df.empty else 0
                if kwh >= threshold:
                    filtered.append((f, kwh))
            except Exception:
                filtered.append((f, 0))
        display = filtered
    else:
        display = [(f, None) for f in csv_files]

    print()
    print("  Verfügbare Log-Dateien:")
    for i, (f, kwh) in enumerate(display, 1):
        kwh_str = f"  ({kwh:.1f} kWh)" if kwh is not None else ''
        print(f"    [{i:2d}]  {f.name}{kwh_str}")
    print()
    while True:
        raw = input(f"  Nummer wählen (1–{len(display)}): ").strip()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(display):
                return display[idx][0]
        except ValueError:
            pass
        print(f"  Bitte eine Zahl zwischen 1 und {len(display)} eingeben.")


def _ask_align():
    """Alignment-Abfrage: Zieltemperatur + Offset. Gibt (align_temp, align_offset_h) zurück.
    Enter = konfigurierter Standard übernehmen; 0 = Ausrichtung deaktivieren."""
    hint = f"{ALIGN_TEMP:.0f} °C" if ALIGN_TEMP is not None else "deaktiviert"
    raw = input(f"  Kurvenausrichtung: Zieltemperatur °C [Standard: {hint}, 0=keine]: ").strip()
    if not raw:
        return ALIGN_TEMP, ALIGN_OFFSET_H
    try:
        at = float(raw.replace(',', '.'))
    except ValueError:
        return ALIGN_TEMP, ALIGN_OFFSET_H
    if at == 0:
        return None, ALIGN_OFFSET_H
    raw_o = input(f"  Offset hh:mm [Standard: {ALIGN_OFFSET_H:.1f} h]: ").strip()
    ao = parse_hhmm(raw_o) if raw_o else ALIGN_OFFSET_H
    return at, ao


def ask_params():
    """Fenster, T-max, Cutoffs und Alignment abfragen.
    Gibt (window_h, temp_max, front_h, back_h, align_temp, align_offset_h) zurück."""
    raw_h = input(
        f"  Zeitfenster hh:mm [Standard {int(WINDOW_HOURS):02d}:00]: "
    ).strip()
    window_h = parse_hhmm(raw_h) or WINDOW_HOURS

    raw_t = input(f"  Temperatur-Maximum °C [Standard {TEMP_MAX}]: ").strip()
    try:
        temp_max = float(raw_t)
    except ValueError:
        temp_max = TEMP_MAX

    print("  Cutoffs (Offset ab Dateistart, Format: VOR,NACH  z.B. '2:00,' oder ',1:30' oder '1:00,0:30')")
    raw_c = input("  Cutoffs [Enter = keine]: ").strip()
    front_h, back_h = parse_cutoffs(raw_c)

    align_temp, align_offset_h = _ask_align()

    return window_h, temp_max, front_h, back_h, align_temp, align_offset_h


# ── Verarbeitung einer Datei ─────────────────────────────────────────────────

def process_file(csvfile, window_h, temp_max, front_h=None, back_h=None, ofen_kw=None, ofen_name=None,
                 align_temp=None, align_offset_h=1.0):
    """
    Lädt CSV, wendet Cutoffs an, zeichnet Plot.
    Gibt page_dict zurück oder None bei Fehler.
    clipped = True wenn das hintere Ende der Datei über window_h hinausgeht
              (nach Anwendung der Cutoffs).
    align_temp: Zieltemperatur °C für Fensterausrichtung (None = deaktiviert)
    align_offset_h: Zieltemperatur liegt diese Zeit nach Fensterstart
    """
    df = load_csv(csvfile)
    if df.empty:
        return None

    t_file_start = df['datetime'].iloc[0]
    t_file_end   = df['datetime'].iloc[-1]

    # Cutoff vorne: Zeitachse beginnt hier
    if front_h is not None:
        t_start = t_file_start + timedelta(hours=front_h)
    else:
        t_start = t_file_start

    # Kurvenausrichtung: Fenster so verschieben dass align_temp am Offset liegt
    aligned = False
    if align_temp is not None:
        above = df.loc[df['IN0'].notna() & (df['IN0'] >= align_temp), 'datetime']
        if not above.empty:
            t_cross = above.iloc[0]
            t_start = t_cross - timedelta(hours=align_offset_h)
            aligned = True

    # Cutoff hinten: festes Ende (Offset ab Dateistart)
    # Fenster-Ende: t_start + window_h
    t_window_end = t_start + timedelta(hours=window_h)

    if back_h is not None:
        t_back_cut = t_file_start + timedelta(hours=back_h)
        # hinten abschneiden = alles nach (t_file_end - back_h) weglassen
        t_back_cut = t_file_end - timedelta(hours=back_h)
        t_end = min(t_window_end, t_back_cut)
    else:
        t_end = t_window_end

    # Wurde das Fenster durch Daten überschritten?
    clipped = t_file_end > t_window_end and back_h is None

    mask = (df['datetime'] >= t_start) & (df['datetime'] <= t_end)
    dv   = df.loc[mask].copy().reset_index(drop=True)

    if dv.empty:
        return None

    png, max_temp_val, fan_h = draw_plot(dv, t_start, t_end, temp_max, TEMP_MIN)

    # Infozeile
    dur_h = (dv['datetime'].iloc[-1] - t_start).total_seconds() / 3600
    kwh   = calc_kwh(dv, ofen_kw)

    cutoff_parts = []
    if front_h is not None:
        cutoff_parts.append(f"▶ +{front_h:.1f}h")
    if back_h is not None:
        cutoff_parts.append(f"◀ -{back_h:.1f}h")
    cutoff_str = f"  │  Cutoff: {', '.join(cutoff_parts)}" if cutoff_parts else ""
    align_str  = f"  │  ⌖ {align_temp:.0f} °C @ +{align_offset_h:.1f} h" if aligned else ""

    clip_str = "  ⚠ ABGESCHNITTEN" if clipped else ""
    _name = ofen_name or OFEN_NAME
    title = f"{_name}  ·  {csvfile.stem}{clip_str}   │   ∼ {kwh:.1f} kWh"

    info = (f"Start: {t_start.strftime('%d.%m.%Y %H:%M')}  │  "
            f"Ende: {dv['datetime'].iloc[-1].strftime('%d.%m.%Y %H:%M')}  │  "
            f"Dauer: {dur_h:.1f} h  │  "
            f"T-max: {max_temp_val:.0f} °C  │  "
            f"Gebläse: {fan_h:.1f} h  │  "
            f"∼ {kwh:.1f} kWh  │  "
            f"Fenster: {window_h:.0f} h / {temp_max:.0f} °C"
            f"{cutoff_str}{align_str}")

    # Events die in diesem Brand vorkommen
    events_occurred = []
    if 'event' in dv.columns:
        seen = set()
        for _, row in dv[dv['event'] != ''].iterrows():
            ev = row['event']
            if ev not in seen:
                seen.add(ev)
                events_occurred.append((ev, row['datetime']))
    return dict(png_bytes=png, title=title, info_line=info,
                clipped=clipped, events=events_occurred)


# ── Hauptprogramm ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Ofen-Log CSV → PDF (Dark Theme)')
    parser.add_argument('--batch',   action='store_true',
                        help='Keine interaktiven Fragen, alle Dateien')
    parser.add_argument('--output',  default=None)
    parser.add_argument('--workdir', default=None)
    args = parser.parse_args()

    from datetime import datetime as dt
    workdir   = Path(args.workdir) if args.workdir else Path.cwd()
    timestamp = dt.now().strftime('%Y%m%d_%H%M')
    out_dir   = workdir / f'pdf_log_TC707_{timestamp}'
    out_dir.mkdir(parents=True, exist_ok=True)
    kwh_dir   = out_dir / 'pdf_log_kWh'
    kwh_dir.mkdir(parents=True, exist_ok=True)

    # Alle CSV rekursiv laden (noch ohne Datumsfilter für Einzelauswahl)
    csv_files_all = find_all_csv(workdir)
    if not csv_files_all:
        print(f"Keine CSV-Dateien in '{workdir}' gefunden.")
        sys.exit(1)

    print(f"\n{'═'*62}")
    print(f"  Ofen-Log Auswertung")
    print(f"  Quelle : {workdir}  ({len(csv_files_all)} Datei(en) gesamt)")
    print(f"{'═'*62}")
    csv_files = csv_files_all

    default_name = None  # wird nach Abfragen gesetzt

    # Ofenname-Abfrage
    active_ofen_name = OFEN_NAME
    if not args.batch:
        raw_name = input(f"\n  Ofenname [Standard: {OFEN_NAME}]: ").strip()
        if raw_name:
            active_ofen_name = raw_name

    # Ofenleistung-Abfrage
    active_ofen_kw = OFEN_KW
    if not args.batch:
        raw_kw = input(f"\n  Ofenleistung kW [Standard: {OFEN_KW}]: ").strip()
        if raw_kw:
            try:
                active_ofen_kw = float(raw_kw.replace(',', '.'))
            except ValueError:
                print(f"  Ungültiger Wert, verwende {OFEN_KW} kW")

    # Testbrand-Schwellwert
    test_threshold = 20.0  # Standard: Brände unter 20 kWh nicht plotten
    if not args.batch:
        raw_thr = input(f"  Testbrände ausschließen unter kWh? [0=alle, Standard: {test_threshold:.0f}]: ").strip()
        if raw_thr:
            try:
                test_threshold = float(raw_thr.replace(',', '.'))
            except ValueError:
                pass

    is_einzel = False
    active_align_temp    = None
    active_align_offset_h = ALIGN_OFFSET_H
    if args.batch:
        jobs     = [(f, WINDOW_HOURS, TEMP_MAX, None, None) for f in csv_files]
        thr_str  = f'ab{test_threshold:g}kWh' if test_threshold > 0 else 'alle'
        zr_info  = 'Einzelauswertung'
        default_name = args.output or f'kiln_report_{timestamp}_{thr_str}.pdf'
        out_path = out_dir / default_name
    else:
        ew = input("\n  Einzelauswertung? (j/N): ").strip().lower()
        if ew == 'j':
            is_einzel = True
            chosen                                          = ask_single_file(csv_files, test_threshold, active_ofen_kw)
            win_h, t_max, front_h, back_h, align_t, align_o = ask_params()
            active_align_temp    = align_t
            active_align_offset_h = align_o
            jobs     = [(chosen, win_h, t_max, front_h, back_h)]
            thr_str  = f'ab{test_threshold:g}kWh' if test_threshold > 0 else 'alle'
            zr_info  = 'Einzelauswertung'
            out_path = out_dir / f"{chosen.stem}_einzel_{timestamp}.pdf"
            co_info  = []
            if front_h: co_info.append(f"vorne +{front_h:.1f}h")
            if back_h:  co_info.append(f"hinten -{back_h:.1f}h")
            print(f"\n  → {chosen.name}")
            print(f"     Fenster: {win_h:.1f} h  |  T-max: {t_max:.0f} °C"
                  + (f"  |  Cutoffs: {', '.join(co_info)}" if co_info else ""))
        else:
            # Zeitraum-Abfrage
            from datetime import date as _date, timedelta as _td
            default_from = (_date.today().replace(day=1) - _td(days=1)).replace(day=1)
            default_from = (default_from - _td(days=1)).replace(day=1)  # 2 Monate zurück
            default_str  = f"{default_from.day}.{default_from.month}.{str(default_from.year)[2:]}-"
            print()
            raw_zr = input(f"  Zeitraum? [Standard: {default_str}]  "
                          f"(z.B. 1.2.25-  /  -3.3.26  /  1.2.25-3.3.26): ").strip()
            if raw_zr:
                zr_from, zr_to = parse_date_range(raw_zr)
            else:
                zr_from, zr_to = default_from, None

            csv_files = find_all_csv(workdir, zr_from, zr_to)
            if not csv_files:
                print(f"  Keine Dateien im Zeitraum gefunden.")
                sys.exit(1)
            zr_info = (f"{zr_from.strftime('%d.%m.%Y') if zr_from else '?'}"
                       f" – {zr_to.strftime('%d.%m.%Y') if zr_to else 'heute'}")
            print(f"  → {len(csv_files)} Datei(en) im Zeitraum {zr_info}")

            # Fenster-Abfrage
            raw_win = input(f"  Zeitfenster hh:mm [Standard {int(WINDOW_HOURS):02d}:00]: ").strip()
            active_window_h = parse_hhmm(raw_win) or WINDOW_HOURS

            # Alignment-Abfrage
            active_align_temp, active_align_offset_h = _ask_align()

            jobs     = [(f, active_window_h, TEMP_MAX, None, None) for f in csv_files]
            # Dateiname: Zeitraum + Schwellwert
            zr_from_str = _dfmt(zr_from)
            zr_to_str   = _dfmt(zr_to)
            thr_str     = f'ab{test_threshold:g}kWh' if test_threshold > 0 else 'alle'
            zr_info     = f"{_dfmt(zr_from)}–{_dfmt(zr_to)}"
            default_name = args.output or f'kiln_report_{timestamp}_{zr_from_str}-{zr_to_str}_{thr_str}.pdf'
            out_path = out_dir / default_name
            print(f"  → Fenster: {active_window_h:.0f} h, T-max: {TEMP_MAX} °C")

    # Theme-Abfrage (nur im interaktiven Modus)
    active_theme = THEME
    if not args.batch:
        tw = input(f"  Farbthema? (d)ark / (l)ight / (b)oth [Standard: {THEME}]: ").strip().lower()
        if tw in ('d', 'dark'):
            active_theme = 'dark'
        elif tw in ('l', 'light'):
            active_theme = 'light'
        elif tw in ('b', 'both'):
            active_theme = 'both'
        # Enter → Standard aus Konfiguration beibehalten
    apply_theme(active_theme if active_theme != 'both' else 'dark')

    # Ausgabeformat-Abfrage
    out_fmt = 'pdf'
    if not args.batch:
        fw = input("  Ausgabeformat? (p)df / (h)tm / (b)oth [Standard: pdf]: ").strip().lower()
        if fw in ('h', 'htm', 'html'):
            out_fmt = 'htm'
        elif fw in ('b', 'both'):
            out_fmt = 'both'

    htm_dir = workdir / f'htm_log_TC707_{timestamp}'
    if out_fmt in ('htm', 'both'):
        htm_dir.mkdir(parents=True, exist_ok=True)

    # Einzelversionen-Abfrage direkt nach Ausgabeformat
    do_einzel_batch = False
    if not args.batch and not is_einzel:
        ev = input("  Einzelne Kombi-Ausgaben (Standard+Optimiert pro Brand)? (j/N): ").strip().lower()
        do_einzel_batch = (ev == 'j')

    print(f"  Ausgabe: {out_path}  [Format: {out_fmt}]\n")

    pages_data      = []
    pages_optimized = []
    clipped_files   = []

    for csvfile, window_h, temp_max, front_h, back_h in jobs:
        print(f"► {csvfile.name}")

        # Schwellwert-Filter VOR dem Rendern prüfen
        try:
            df_pre = load_csv(csvfile)
            kwh_pre = calc_kwh(df_pre, active_ofen_kw) if not df_pre.empty else 0
        except Exception:
            kwh_pre = 0

        if test_threshold > 0 and kwh_pre < test_threshold:
            print(f"  ⏭  Testbrand ({kwh_pre:.1f} kWh < {test_threshold:g} kWh) – übersprungen.")
            try:
                update_kwh_log(kwh_dir, csvfile, kwh_pre)
            except Exception:
                pass
            print()
            continue

        try:
            apply_theme(active_theme if active_theme != 'both' else 'dark')
            page     = process_file(csvfile, window_h, temp_max, front_h, back_h, active_ofen_kw, active_ofen_name,
                                    align_temp=active_align_temp, align_offset_h=active_align_offset_h)
            apply_theme(active_theme if active_theme != 'both' else 'dark')
            page_opt = process_file_optimized(csvfile, active_ofen_kw, active_ofen_name)
        except Exception as e:
            import traceback
            print(f"  FEHLER: {e}")
            traceback.print_exc()
            print()
            continue

        if page is None and page_opt is None:
            print("  Keine verwertbaren Daten – übersprungen.\n")
            continue

        if page is not None:
            page['_sort_key'] = csvfile.stem
            pages_data.append(page)
            clip_note = '  ⚠ abgeschnitten' if page['clipped'] else ''
            print(f"  ✓ Standard{clip_note}")
            if page['clipped']:
                clipped_files.append(csvfile.name)

        if page_opt is not None:
            page_opt['_sort_key'] = csvfile.stem
            pages_optimized.append(page_opt)
            print(f"  ✓ Optimiert")

        # kWh-Log aktualisieren
        try:
            df_kw = load_csv(csvfile)
            if not df_kw.empty:
                kwh_log_val = calc_kwh(df_kw, active_ofen_kw)
                update_kwh_log(kwh_dir, csvfile, kwh_log_val)
        except Exception:
            pass

        print()

    if not pages_data and not pages_optimized:
        print("Keine Seiten erzeugt.")
        sys.exit(1)

    # Seiten nach Datum (Dateiname) sortieren
    pages_data      = sorted(pages_data,      key=lambda p: p.get('_sort_key',''))
    pages_optimized = sorted(pages_optimized, key=lambda p: p.get('_sort_key',''))

    # Bei THEME='both': beide Themes rendern und je eigene PDFs erzeugen
    themes_to_render = ['dark', 'light'] if active_theme == 'both' else [active_theme]

    if out_fmt in ('pdf', 'both'):
        for theme_name in themes_to_render:
          apply_theme(theme_name)
          suffix = f'_(d)' if theme_name == 'dark' else f'_(l)'

          # Seiten neu rendern wenn 'both' ODER 'is_einzel' (Theme muss stimmen)
          if active_theme == 'both' or is_einzel:
              pd2, po2 = [], []
              for csvfile, window_h, temp_max, front_h, back_h in jobs:
                  try:
                      # Schwellwert-Filter auch hier anwenden
                      df_pre2 = load_csv(csvfile)
                      kwh_pre2 = calc_kwh(df_pre2, active_ofen_kw) if not df_pre2.empty else 0
                      if test_threshold > 0 and kwh_pre2 < test_threshold:
                          continue
                      apply_theme(theme_name)  # sicherstellen dass Theme korrekt ist
                      p  = process_file(csvfile, window_h, temp_max, front_h, back_h, active_ofen_kw, active_ofen_name,
                                        align_temp=active_align_temp, align_offset_h=active_align_offset_h)
                      apply_theme(theme_name)  # matplotlib reset nach process_file
                      po = process_file_optimized(csvfile, active_ofen_kw, active_ofen_name)
                      if p:  pd2.append(p)
                      if po: po2.append(po)
                  except Exception:
                      pass
              pages_d = pd2
              pages_o = po2
          else:
              pages_d = pages_data
              pages_o = pages_optimized

          stem_base = out_path.stem
          p_std = out_path.with_name(stem_base + suffix + '.pdf')
          p_opt = out_path.with_name(stem_base + suffix + '_optimiert.pdf')

          if is_einzel:
              combined = []
              if pages_d: combined.append(pages_d[0])
              if pages_o: combined.append(pages_o[0])
              if combined:
                  p_einzel = out_path.with_name(stem_base + suffix + '.pdf')
                  print(f"Erstelle Einzel-PDF [{theme_name}] ({len(combined)} Seite(n)) …")
                  build_pdf(combined, p_einzel, zr_info, thr_str)
                  print(f"✓ Fertig: {p_einzel.resolve()}")
          else:
              if pages_d:
                  print(f"Erstelle Standard-PDF [{theme_name}] mit {len(pages_d)} Seite(n) …")
                  build_pdf(pages_d, p_std, zr_info, thr_str)
                  print(f"✓ Fertig: {p_std.resolve()}")
              if pages_o:
                  print(f"Erstelle Optimiert-PDF [{theme_name}] mit {len(pages_o)} Seite(n) …")
                  build_pdf(pages_o, p_opt, zr_info, thr_str)
                  print(f"✓ Fertig: {p_opt.resolve()}")

    # ── HTML-Ausgabe ──────────────────────────────────────────────────────
    if out_fmt in ('htm', 'both'):
        htm_themes = ['dark', 'light'] if active_theme == 'both' else                      [active_theme] if active_theme != 'both' else ['dark', 'light']

        for theme_name in htm_themes:
            apply_theme(theme_name)
            suffix = f'_(d)' if theme_name == 'dark' else f'_(l)'

            # Seiten pro Log rendern
            for csvfile, window_h, temp_max, front_h, back_h in jobs:
                try:
                    df = __import__('sys').modules[__name__].load_csv(csvfile)
                    if df.empty or len(df) < 2:
                        continue

                    # Schwellwert-Filter
                    kwh_htm = calc_kwh(df, active_ofen_kw)
                    if test_threshold > 0 and kwh_htm < test_threshold:
                        continue

                    # Standard-Fenster
                    if out_fmt != 'htm' or True:  # immer optimiert für HTM
                        dv = df.copy().reset_index(drop=True)
                        t_start = dv['datetime'].iloc[0]
                        dur_total_min = int(round(
                            (dv['datetime'].iloc[-1] - t_start).total_seconds() / 60))
                        dur_hh = dur_total_min // 60
                        dur_mm = dur_total_min % 60
                        valid  = dv['IN0'].notna()
                        max_t  = dv.loc[valid,'IN0'].max() if valid.any() else 0
                        kwh    = calc_kwh(dv, active_ofen_kw)
                        title_opt  = (f"{active_ofen_name}  ·  {csvfile.stem}   │   "
                                      f"T-max: {max_t:.0f} °C   │   "
                                      f"Dauer: {dur_hh:02d}:{dur_mm:02d} h   │   "
                                      f"∼ {kwh:.1f} kWh")
                        info_opt   = (f"Start: {t_start.strftime('%d.%m.%Y %H:%M')}  │  "
                                      f"Ende: {dv['datetime'].iloc[-1].strftime('%d.%m.%Y %H:%M')}  │  "
                                      f"Nennleistung: {OFEN_KW:.1f} kW")

                        fig_opt = draw_plot_plotly(dv, title_opt, info_opt, theme_name)

                        # Standard-Fenster: Alignment anwenden falls aktiv
                        t_std_start = df['datetime'].iloc[0]
                        htm_aligned = False
                        if active_align_temp is not None:
                            above_h = df.loc[df['IN0'].notna() & (df['IN0'] >= active_align_temp), 'datetime']
                            if not above_h.empty:
                                t_std_start = above_h.iloc[0] - __import__('datetime').timedelta(hours=active_align_offset_h)
                                htm_aligned = True
                        t_win_end = t_std_start + __import__('datetime').timedelta(hours=window_h)
                        mask = (df['datetime'] >= t_std_start) & (df['datetime'] <= t_win_end)
                        dv_std = df.loc[mask].copy().reset_index(drop=True)
                        clipped = df['datetime'].iloc[-1] > t_win_end
                        clip_str = '  ⚠ ABGESCHNITTEN' if clipped else ''
                        kwh_std = calc_kwh(dv_std, active_ofen_kw) if len(dv_std) > 1 else 0
                        title_std = f"{active_ofen_name}  ·  {csvfile.stem}{clip_str}   │   ∼ {kwh_std:.1f} kWh"
                        align_str_h = (f"  │  ⌖ {active_align_temp:.0f} °C @ +{active_align_offset_h:.1f} h"
                                       if htm_aligned else "")
                        info_std  = (f"Start: {t_std_start.strftime('%d.%m.%Y %H:%M')}  │  "
                                     f"Fenster: {window_h:.0f} h / {temp_max:.0f} °C{align_str_h}")
                        fig_std = draw_plot_plotly(
                            dv_std if len(dv_std) > 1 else dv,
                            title_std, info_std, theme_name,
                            x_end=t_win_end)

                    figs = [
                        (fig_opt, "Optimiert"),
                        (fig_std, f"Standard ({window_h:.0f}h)"),
                    ]
                    stem = out_path.stem.replace('kiln_report_', '')
                    htm_prefix = "einzel_" if is_einzel else "ausw_"
                    htm_path = htm_dir / f"{htm_prefix}{csvfile.stem}_{timestamp}{suffix}.html"
                    # Events aus dv sammeln
                    htm_events = []
                    if 'event' in df.columns:
                        seen_e = set()
                        for _, r in df[df['event'] != ''].iterrows():
                            if r['event'] not in seen_e:
                                seen_e.add(r['event'])
                                htm_events.append(r['event'])
                    print(f"Erstelle HTML [{theme_name}]: {htm_path.name} …")
                    build_html(figs, htm_path, theme_name, events=htm_events or None)
                    print(f"✓ Fertig: {htm_path.resolve()}")

                except Exception as e:
                    import traceback
                    print(f"  HTML FEHLER {csvfile.name}: {e}")
                    traceback.print_exc()

    # kWh-Plot erstellen (immer dark + light)
    try:
        print("\nErstelle kWh-Verbrauchsplot …")
        for th in ['dark', 'light']:
            build_kwh_plot(kwh_dir, th, active_ofen_name, active_ofen_kw, zr_info, thr_str)
            # kWhlog an alle kiln_report PDFs dieses Themes anhängen
            # kWhlog-Dateiname per glob suchen (enthält Zeitraum+Schwellwert)
            if out_fmt in ('pdf', 'both'):
                kwh_matches = list(kwh_dir.glob(f'kWhlog_{th}*.pdf'))
                if kwh_matches:
                    kwh_pdf = kwh_matches[0]
                    suffix_th = '_(d)' if th == 'dark' else '_(l)'
                    pdfs_found = sorted(out_dir.glob(f'*{suffix_th}*.pdf'))
                    for pdf_path in pdfs_found:
                        try:
                            append_pdf(pdf_path, kwh_pdf)
                            print(f"  + kWhlog → {pdf_path.name}")
                        except Exception as e:
                            print(f"  ⚠ kWhlog-Anhang fehlgeschlagen ({pdf_path.name}): {e}")
                else:
                    print(f"  ⚠ kWhlog_{th}*.pdf nicht gefunden in {kwh_dir}")
    except Exception as e:
        print(f"  kWh-Plot Fehler: {e}")

    if clipped_files:
        print(f"\n⚠  Abgeschnitten (Daten über {WINDOW_HOURS}-h-Fenster hinaus):")
        for fn in clipped_files:
            print(f"     • {fn}")

    # ── Batch-Einzelversionen ─────────────────────────────────────────────
    if do_einzel_batch and not is_einzel and len(jobs) > 1:
        print("\nErstelle Einzelversionen …")
        for csvfile, window_h, temp_max, front_h, back_h in jobs:
            try:
                df_e = load_csv(csvfile)
                if test_threshold > 0 and calc_kwh(df_e, active_ofen_kw) < test_threshold:
                    continue
            except Exception:
                pass
            for theme_name in themes_to_render:
                try:
                    apply_theme(theme_name)
                    pe  = process_file(csvfile, window_h, temp_max, front_h, back_h, active_ofen_kw, active_ofen_name)
                    apply_theme(theme_name)
                    peo = process_file_optimized(csvfile, active_ofen_kw, active_ofen_name)
                except Exception as e:
                    print(f"  FEHLER {csvfile.name}: {e}")
                    continue
                if pe is None and peo is None:
                    continue
                combined = []
                if pe:
                    pe['_sort_key'] = csvfile.stem
                    combined.append(pe)
                if peo:
                    peo['_sort_key'] = csvfile.stem
                    combined.append(peo)
                if combined:
                    suffix = f'_(d)' if theme_name == 'dark' else f'_(l)'
                    einzel_path = out_dir / f"{csvfile.stem}_einzel_{timestamp}{suffix}.pdf"
                    print(f"  → {einzel_path.name}")
                    build_pdf(combined, einzel_path, zr_info, thr_str)
        print("✓ Einzelversionen fertig.")

    print()


if __name__ == '__main__':
    main()

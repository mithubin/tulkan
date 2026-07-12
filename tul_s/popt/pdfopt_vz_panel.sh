#!/bin/bash

# pdf_optimize_advanced.sh
# Optimiert alle PDFs rekursiv, repliziert Verzeichnisbaum als paralleles Geschwisterverzeichnis
# Zielordner: <quellordner>_<suffix> (z.B. "skripte skul_o2"), Dateinamen bleiben gleich

if [[ -n "$1" ]]; then
    CURRENT_DIR="$(realpath "$1")"
else
    CURRENT_DIR="$(pwd)"
fi

# Farben
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   PDF-Optimierung (rekursiv, paralleles VZ)   ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "Quellverzeichnis: ${YELLOW}$CURRENT_DIR${NC}"
echo ""

# PDFs rekursiv zählen
pdf_count=$(find "$CURRENT_DIR" -name "*.pdf" | wc -l)

if [[ $pdf_count -eq 0 ]]; then
    echo -e "${RED}Keine PDFs gefunden!${NC}"
    exit 1
fi

# Qualitäts-Presets
echo "Verfügbare Qualitätsstufen:"
echo "──────────────────────────────────────"
echo -e "1) ${CYAN}screen   ${NC}(72 dpi)       - Suffix: _os    - für Web"
echo -e "2) ${GREEN}ebook    ${NC}(150 dpi)      - Suffix: _oe    - Standard E-Book"
echo -e "3) ${YELLOW}200dpi   ${NC}(200 dpi)      - Suffix: _o2    - ✓ DEFAULT (bester Kompromiss)"
echo -e "4) ${PURPLE}printer  ${NC}(300 dpi)      - Suffix: _op    - für gute Drucke"
echo -e "5) ${RED}prepress ${NC}(300 dpi CMYK) - Suffix: _opp   - professioneller Druck"
echo -e "6) custom   (benutzerdef.)   - Suffix: _ocm   - eigene Einstellungen"
echo ""

read -p "Qualitätsstufe wählen (1-6, Standard: 3): " choice

case $choice in
    1) QUALITY="screen";   SUFFIX="_os"  ;;
    2) QUALITY="ebook";    SUFFIX="_oe"  ;;
    4) QUALITY="printer";  SUFFIX="_op"  ;;
    5) QUALITY="prepress"; SUFFIX="_opp" ;;
    6) QUALITY="custom";   SUFFIX="_ocm" ;;
    *) QUALITY="200dpi";   SUFFIX="_o2"  ;;
esac

# Ausgabeverzeichnis: Geschwisterordner mit Qualitätssuffix
OUTPUT_DIR="${CURRENT_DIR%/}${SUFFIX}"

# Sicherheitscheck: nicht aus dem Zielordner heraus starten
if [[ "$CURRENT_DIR" == "$OUTPUT_DIR" ]]; then
    echo -e "${RED}Fehler: Quell- und Zielverzeichnis sind identisch!${NC}"
    exit 1
fi

# Für custom zusätzliche Einstellungen
if [[ "$QUALITY" == "custom" ]]; then
    echo ""
    echo -e "${YELLOW}Benutzerdefinierte Einstellungen:${NC}"
    read -p "Farbbild-Auflösung (dpi, Standard: 200): "    COLOR_RES
    read -p "Graustufen-Auflösung (dpi, Standard: 200): "  GRAY_RES
    read -p "Schwarz/Weiß-Auflösung (dpi, Standard: 400): " MONO_RES
    read -p "JPEG Qualität (1-100, Standard: 86): "        JPEG_QUALITY
    COLOR_RES=${COLOR_RES:-200}
    GRAY_RES=${GRAY_RES:-200}
    MONO_RES=${MONO_RES:-400}
    JPEG_QUALITY=${JPEG_QUALITY:-86}
fi

mkdir -p "$OUTPUT_DIR"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}        PDF-Optimierung wird gestartet         ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "Qualität:        ${YELLOW}$QUALITY${NC}"
echo -e "PDFs gefunden:   ${YELLOW}$pdf_count${NC}"
echo -e "Zielverzeichnis: ${BLUE}$OUTPUT_DIR${NC}"
echo ""

# Ghostscript-Parameter je Qualität
case $QUALITY in
    "screen")
        GS_PARAMS="-dPDFSETTINGS=/screen -dColorImageResolution=72 -dGrayImageResolution=72 -dMonoImageResolution=72 -dJPEGQ=72 -dColorConversionStrategy=/sRGB -dConvertCMYKImagesToRGB=true"
        ;;
    "ebook")
        GS_PARAMS="-dPDFSETTINGS=/ebook -dColorImageResolution=150 -dGrayImageResolution=150 -dMonoImageResolution=300 -dJPEGQ=80 -dColorConversionStrategy=/LeaveColorUnchanged -dConvertCMYKImagesToRGB=false"
        ;;
    "200dpi")
        GS_PARAMS="-dPDFSETTINGS=/ebook -dColorImageResolution=200 -dGrayImageResolution=200 -dMonoImageResolution=400 -dJPEGQ=86 -dColorConversionStrategy=/LeaveColorUnchanged -dConvertCMYKImagesToRGB=false"
        ;;
    "printer")
        GS_PARAMS="-dPDFSETTINGS=/printer -dColorImageResolution=300 -dGrayImageResolution=300 -dMonoImageResolution=1200 -dJPEGQ=88 -dColorConversionStrategy=/LeaveColorUnchanged -dConvertCMYKImagesToRGB=false"
        ;;
    "prepress")
        GS_PARAMS="-dPDFSETTINGS=/prepress -dColorImageResolution=300 -dGrayImageResolution=300 -dMonoImageResolution=1200 -dJPEGQ=96 -dColorConversionStrategy=/LeaveColorUnchanged -dConvertCMYKImagesToRGB=false"
        ;;
    "custom")
        GS_PARAMS="-dColorImageResolution=$COLOR_RES -dGrayImageResolution=$GRAY_RES -dMonoImageResolution=$MONO_RES -dJPEGQ=$JPEG_QUALITY -dColorConversionStrategy=/LeaveColorUnchanged -dConvertCMYKImagesToRGB=false"
        ;;
esac

# Zähler
processed=0
failed=0
total_original_kb=0
total_optimized_kb=0

# Alle PDFs rekursiv verarbeiten (null-delimited, damit Leerzeichen in Pfaden sicher sind)
while IFS= read -r -d '' pdf; do
    rel_path="${pdf#$CURRENT_DIR/}"
    output_path="$OUTPUT_DIR/$rel_path"
    output_subdir="$(dirname "$output_path")"

    mkdir -p "$output_subdir"

    echo -e "${BLUE}➤ $rel_path${NC}"

    original_kb=$(( $(stat -c%s "$pdf" 2>/dev/null || stat -f%z "$pdf") / 1024 ))
    total_original_kb=$((total_original_kb + original_kb))

    gs -q -dNOPAUSE -dBATCH -dSAFER \
       -sDEVICE=pdfwrite \
       -dCompatibilityLevel=1.5 \
       $GS_PARAMS \
       -dEmbedAllFonts=true \
       -dSubsetFonts=true \
       -dAutoFilterColorImages=true \
       -dAutoFilterGrayImages=true \
       -dColorImageFilter=/DCTEncode \
       -dGrayImageFilter=/DCTEncode \
       -dOptimize=true \
       -dUseFlateCompression=true \
       -sOutputFile="$output_path" \
       "$pdf"

    if [[ $? -eq 0 && -f "$output_path" ]]; then
        new_kb=$(( $(stat -c%s "$output_path" 2>/dev/null || stat -f%z "$output_path") / 1024 ))
        total_optimized_kb=$((total_optimized_kb + new_kb))

        if [[ $original_kb -gt 0 && $new_kb -gt 0 ]]; then
            savings=$((original_kb - new_kb))
            percent=$((savings * 100 / original_kb))
            if [[ $savings -gt 0 ]]; then
                echo -e "  ${GREEN}✓ ${original_kb} KB → ${new_kb} KB (${percent}% kleiner)${NC}"
            else
                echo -e "  ${YELLOW}⚠  ${original_kb} KB → ${new_kb} KB (keine Reduktion)${NC}"
            fi
        else
            echo -e "  ${GREEN}✓ Fertig${NC}"
        fi
        ((processed++))
    else
        echo -e "  ${RED}✗ Fehler bei: $rel_path${NC}"
        ((failed++))
    fi
done < <(find "$CURRENT_DIR" -name "*.pdf" -print0 | sort -z)

# Statistik
echo ""
echo "═══════════════════════════════════════════════"
echo -e "${GREEN}Zusammenfassung:${NC}"
echo "  Verarbeitet:    $processed Dateien"
echo "  Fehlgeschlagen: $failed Dateien"

if [[ $processed -gt 0 ]]; then
    total_savings=$((total_original_kb - total_optimized_kb))
    if [[ $total_original_kb -gt 0 ]]; then
        total_percent=$((total_savings * 100 / total_original_kb))
    else
        total_percent=0
    fi

    echo ""
    echo -e "${CYAN}Gesamtstatistik:${NC}"
    echo "  Original gesamt:  ${total_original_kb} KB"
    echo "  Optimiert gesamt: ${total_optimized_kb} KB"
    if [[ $total_savings -gt 0 ]]; then
        echo -e "  ${GREEN}Ersparnis: ${total_savings} KB (${total_percent}%)${NC}"
        echo "  Durchschnitt pro Datei: $((total_savings / processed)) KB"
    else
        echo -e "  ${YELLOW}Keine Gesamtersparnis${NC}"
    fi
fi

echo ""
echo -e "Qualität:        ${YELLOW}$QUALITY${NC}"
echo -e "Zielverzeichnis: ${BLUE}$OUTPUT_DIR${NC}"
echo "═══════════════════════════════════════════════"

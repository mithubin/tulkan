#!/usr/bin/env bash
# push-tul.sh – Fallback: überträgt den aktuellen Stand per git archive + SSH
# Normalweg: git subtree push --prefix=tul_s nuc master, vom Repo-Root aus (siehe push-nuc.sh)
set -e

NUC=user@yourserver
TUL_REMOTE=~/tul/tools_nuc

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Übertrage tools_nuc nach $NUC:$TUL_REMOTE …"
git -C "$SCRIPT_DIR" archive HEAD | ssh "$NUC" "mkdir -p $TUL_REMOTE && tar -xC $TUL_REMOTE"
echo "✓ Dateien übertragen"
echo ""
echo "Jetzt auf dem NUC ausführen:"
echo "  cd ~/tul && bash tools_nuc/deploy-tul.sh"

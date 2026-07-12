#!/usr/bin/env bash
# push-nuc.sh – deployt tul_s zum NUC via git subtree push.
# Wechselt zuverlässig zum Repo-Root, damit niemand "git push nuc master" aus
# Versehen aus tul_s/ heraus aufruft (das würde seit dem mkan-Merge den ganzen
# kombinierten tulkan-Baum pushen statt nur tul_s/).
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"
echo "Repo-Root: $REPO_ROOT"
echo "Subtree-Push tul_s/ -> nuc master ..."
git subtree push --prefix=tul_s nuc master

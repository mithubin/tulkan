#!/usr/bin/env bash
# deploy-tul.sh – auf dem NUC ausführen
set -e

TUL_DIR=~/tul
NEXCLOC_DIR=~/nexcloc

# ── 1. Verzeichnisse anlegen ──────────────────────────────────────────────────
mkdir -p /mnt/tul/db
mkdir -p /mnt/tul/trskr/models /mnt/tul/trskr/output /mnt/tul/trskr/files
mkdir -p /mnt/tul/lern /mnt/tul/lern/tul_files
mkdir -p /mnt/tul/popt/files
mkdir -p /mnt/tul/bild/files
mkdir -p /mnt/tul/kurv/files
mkdir -p /mnt/tul/nach/files /mnt/tul/nach/tul_files
mkdir -p /mnt/tul/kal-trel/files
mkdir -p $TUL_DIR

# ── 2. .env prüfen ────────────────────────────────────────────────────────────
ENV_FILE=$TUL_DIR/tools_nuc/.env
if [ ! -f "$ENV_FILE" ]; then
    echo ""
    echo "ACHTUNG: $ENV_FILE fehlt. Bitte anlegen:"
    echo "  TUL_SECRET=\$(openssl rand -hex 32)"
    echo "  TUL_BRIDGE_SECRET=\$(openssl rand -hex 32)   # muss identisch in mkan/.env stehen"
    echo "  ADMIN_EMAIL=deine@email.de"
    echo ""
    echo "Dann erneut pushen oder deploy-tul.sh manuell ausführen."
    exit 1
fi
if ! grep -q "TUL_SECRET" "$ENV_FILE"; then
    echo "ACHTUNG: TUL_SECRET fehlt in $ENV_FILE"
    exit 1
fi
if ! grep -q "TUL_BRIDGE_SECRET" "$ENV_FILE"; then
    echo "ACHTUNG: TUL_BRIDGE_SECRET fehlt in $ENV_FILE (nötig für popt/tul-hub <-> mkan-Bridge)"
    echo "  Muss identisch mit TUL_BRIDGE_SECRET in mkan/.env sein."
    exit 1
fi
echo "✓ .env vorhanden"

# ── 3. nginx.conf aufbauen ───────────────────────────────────────────────────
# Strategie: nginx.conf.base ist die unveränderliche Basis (http{} noch offen,
# kein tul-Block). Tul-Block wird immer frisch eingehängt.
# nginx.conf.base wird beim ersten Mal aus der aktuellen nginx.conf extrahiert.
BASE=$NEXCLOC_DIR/nginx.conf.base
CONF=$NEXCLOC_DIR/nginx.conf
TUL_CONF=$TUL_DIR/tools_nuc/nginx_tul.conf

if [ ! -f "$BASE" ]; then
    echo "Erstelle nginx.conf.base aus aktueller nginx.conf..."
    python3 - "$CONF" "$BASE" <<'PY'
import sys, pathlib
conf_path, base_path = sys.argv[1], sys.argv[2]
lines = pathlib.Path(conf_path).read_text().splitlines(keepends=True)
marker_line = None
for i, l in enumerate(lines):
    if l.startswith('# ── tul.yourdomain.example'):
        marker_line = i
        break
if marker_line is None:
    # Kein Marker: letztes uneingeruecktes } entfernen (http-Block-Ende)
    import re
    txt = ''.join(lines)
    m = list(re.finditer(r'^}', txt, re.MULTILINE))
    base = txt[:m[-1].start()] if m else txt
else:
    base = ''.join(lines[:marker_line])
pathlib.Path(base_path).write_text(base)
print(f'nginx.conf.base: {len(base)} bytes, {base.count(chr(10))} Zeilen')
PY
fi

# nginx.conf = base + tul-Block + schließendes } für http{}
python3 - "$BASE" "$TUL_CONF" "$CONF" <<'PY'
import sys, pathlib
base_path, tul_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
base     = pathlib.Path(base_path).read_text()
tul_block = pathlib.Path(tul_path).read_text()
result   = base + tul_block + '}\n'
pathlib.Path(out_path).write_text(result)
print(f'nginx.conf: {len(result)} bytes, {result.count(chr(10))} Zeilen')
PY
echo "✓ nginx.conf: tul-Block eingefügt"

# ── 4. Container bauen und starten ───────────────────────────────────────────
cd $TUL_DIR/tools_nuc
docker compose up -d --build --wait

# ── 5. nginx neu laden – erst nach --wait (alle Healthchecks grün) ────────────
base64 $CONF | docker exec -i nexcloc-nginx-proxy-1 sh -c "base64 -d > /etc/nginx/nginx.conf"
docker exec nexcloc-nginx-proxy-1 nginx -t && docker exec nexcloc-nginx-proxy-1 nginx -s reload
echo "✓ nginx neu geladen"
echo ""
echo "=== tul.yourdomain.example/         → Hub + Login   ==="
echo "=== tul.yourdomain.example/trskr/   → Transkription ==="
echo "=== tul.yourdomain.example/bild/    → Bildseite     ==="
echo "=== tul.yourdomain.example/popt/    → PDF-Opt       ==="
echo "=== tul.yourdomain.example/lern/    → Lernkarten    ==="
echo "=== tul.yourdomain.example/kurv/    → Ofen-Kurven   ==="
echo ""
if ! sqlite3 /mnt/tul/db/tul.sqlite "SELECT COUNT(*) FROM users;" 2>/dev/null | grep -qv '^0$'; then
    echo "HINWEIS: Noch kein User angelegt."
    echo "  → tool.milan.how/setup aufrufen um ersten Admin zu erstellen."
fi

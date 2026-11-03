#!/bin/bash
# Backup Plane (project "plane") before deploying: Postgres dump, MinIO uploads,
# and the current compose/.env/patches.
#
# Usage: ./backup.sh [backup_root]   (default: ~/plane-backups)
#
# Env overrides:
#   PLANE_DIR       old install dir whose config is also saved. Default: ~/plane
#   ENV_FILE        env file holding DATABASE_URL. Default: ./.env next to this script
#   DATABASE_URL    database to dump. Default: DATABASE_URL from ENV_FILE
#   PG_IMAGE        image providing pg_dump; must be >= the server's major
#                   version. Default: postgres:15.7-alpine
#   DOCKER_NETWORK  network the dump runs on, so the local plane-db hostname
#                   also resolves. Default: plane_default
#   UPLOADS_VOLUME  MinIO data volume. Default: plane_uploads

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_ROOT=${1:-$HOME/plane-backups}
PLANE_DIR=${PLANE_DIR:-$HOME/plane}
ENV_FILE=${ENV_FILE:-$SCRIPT_DIR/.env}
PG_IMAGE=${PG_IMAGE:-postgres:15.7-alpine}
DOCKER_NETWORK=${DOCKER_NETWORK:-plane_default}
UPLOADS_VOLUME=${UPLOADS_VOLUME:-plane_uploads}

TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/$TS"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_ROOT" "$BACKUP_DIR"

echo "Backup dir: $BACKUP_DIR"

if [ -z "${DATABASE_URL:-}" ] && [ -f "$ENV_FILE" ]; then
    DATABASE_URL=$(grep -E '^DATABASE_URL=' "$ENV_FILE" | tail -n 1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//')
fi
if [ -z "${DATABASE_URL:-}" ]; then
    echo "Error: DATABASE_URL is not set (checked the environment and $ENV_FILE)"
    exit 1
fi

# Passed by name (-e DATABASE_URL) so the password never shows up in `ps`
export DATABASE_URL

pg() {
    docker run --rm -i --network "$DOCKER_NETWORK" -e DATABASE_URL "$PG_IMAGE" "$@"
}

# 1. Database: custom-format dump (compressed, restorable with pg_restore)
echo "[1/4] Dumping database..."
pg sh -c 'pg_dump -Fc -d "$DATABASE_URL"' > "$BACKUP_DIR/plane-db.dump"

# Fail if the dump is unreadable
TOC=$(pg pg_restore --list < "$BACKUP_DIR/plane-db.dump")
TABLES=$(grep -c "TABLE DATA" <<< "$TOC" || true)
echo "      OK: $(du -h "$BACKUP_DIR/plane-db.dump" | cut -f1), $TABLES tables"

# 2. Uploaded files (MinIO volume)
echo "[2/4] Archiving uploads volume ($UPLOADS_VOLUME)..."
docker run --rm \
    -v "$UPLOADS_VOLUME":/data:ro \
    -v "$BACKUP_DIR":/backup \
    postgres:15.7-alpine \
    tar czf /backup/plane-uploads.tar.gz -C /data .
echo "      OK: $(du -h "$BACKUP_DIR/plane-uploads.tar.gz" | cut -f1)"

# 3. Current config (contains secrets; directory is chmod 700). Saves both the
# old install dir and this deploy dir, whichever exist.
echo "[3/4] Copying compose, .env and patches..."
for src in "$PLANE_DIR" "$SCRIPT_DIR"; do
    dest="$BACKUP_DIR/config/$(basename "$src")"
    mkdir -p "$dest"
    for f in docker-compose.yml .env patches; do
        if [ -e "$src/$f" ]; then
            cp -a "$src/$f" "$dest/"
        fi
    done
    echo "      $src -> config/$(basename "$src")"
done

# 4. Record what was running
echo "[4/4] Recording running images..."
docker ps --filter "label=com.docker.compose.project=plane" \
    --format '{{.Names}}\t{{.Image}}' > "$BACKUP_DIR/running-images.txt"

echo
echo "Backup complete: $BACKUP_DIR"
ls -lh "$BACKUP_DIR"

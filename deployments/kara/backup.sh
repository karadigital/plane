#!/bin/bash
# Backup Plane (project "plane") before deploying: Postgres dump, MinIO uploads,
# and the current compose/.env/patches.
#
# Usage: ./backup.sh [backup_root]   (default: ~/plane-backups)
#
# Env overrides:
#   PLANE_DIR       old install dir whose config is also saved. Default: ~/plane
#   DB_CONTAINER    Postgres container. Default: plane-plane-db-1
#   UPLOADS_VOLUME  MinIO data volume. Default: plane_uploads

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_ROOT=${1:-$HOME/plane-backups}
PLANE_DIR=${PLANE_DIR:-$HOME/plane}
DB_CONTAINER=${DB_CONTAINER:-plane-plane-db-1}
UPLOADS_VOLUME=${UPLOADS_VOLUME:-plane_uploads}

TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/$TS"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_ROOT" "$BACKUP_DIR"

echo "Backup dir: $BACKUP_DIR"

if ! docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
    echo "Error: container $DB_CONTAINER is not running"
    exit 1
fi

# 1. Database: custom-format dump (compressed, restorable with pg_restore)
echo "[1/4] Dumping database..."
docker exec "$DB_CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > "$BACKUP_DIR/plane-db.dump"

# Fail if the dump is unreadable
docker exec -i "$DB_CONTAINER" pg_restore --list < "$BACKUP_DIR/plane-db.dump" > /dev/null
TABLES=$(docker exec -i "$DB_CONTAINER" pg_restore --list < "$BACKUP_DIR/plane-db.dump" | grep -c "TABLE DATA" || true)
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

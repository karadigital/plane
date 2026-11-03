#!/bin/bash
# Move the Plane database from the current DATABASE_URL (in .env) to a new,
# empty Postgres database, then point .env at it.
#
# Usage:
#   ./migrate-db.sh --check     # connectivity, version, empty target, rights
#   ./migrate-db.sh --rehearse  # restore a fresh backup into the target, compare
#                               # every table's row count, then empty the target
#                               # again. Plane keeps running.
#   ./migrate-db.sh             # the real move (downtime): stop writers, final
#                               # backup, restore, compare, switch .env, start
#
# The new database URL is read from NEW_DB, or asked for (hidden) when unset:
#   postgresql://<user>:<url-encoded-password>@<host>:5432/<db>
#
# The old database is never modified. On any failure after the writers are
# stopped, the script puts the previous .env back and restarts Plane on the
# old database.
#
# Env overrides:
#   ENV_FILE        env file holding DATABASE_URL. Default: ./.env next to this script
#   PG_IMAGE        Postgres client image; its major version must be >= both
#                   servers'. Default: postgres:15.7-alpine
#   DOCKER_NETWORK  network the client runs on, so the plane-db hostname
#                   resolves. Default: plane_default
#   HEALTH_URL      checked after the switch.
#                   Default: http://localhost:8000/api/instances/
#   HEALTH_TIMEOUT  seconds to wait for HEALTH_URL. Default: 300

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE=${ENV_FILE:-$SCRIPT_DIR/.env}
PG_IMAGE=${PG_IMAGE:-postgres:15.7-alpine}
DOCKER_NETWORK=${DOCKER_NETWORK:-plane_default}
HEALTH_URL=${HEALTH_URL:-http://localhost:8000/api/instances/}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-300}

WRITERS=(api worker beat-worker web space admin live)

MODE=migrate
case "${1:-}" in
    "") ;;
    --check) MODE=check ;;
    --rehearse) MODE=rehearse ;;
    *)
        echo "Usage: $0 [--check | --rehearse]"
        exit 1
        ;;
esac

if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    COMPOSE_CMD="docker compose"
fi

compose() {
    $COMPOSE_CMD -f "$SCRIPT_DIR/docker-compose.yml" --env-file "$ENV_FILE" "$@"
}

step() { echo; echo "==> $*"; }
fail() { echo "Error: $*" >&2; exit 1; }

# --- inputs -------------------------------------------------------------------

[ -f "$ENV_FILE" ] || fail "env file not found at $ENV_FILE"

OLD_DB=$(grep -E '^DATABASE_URL=' "$ENV_FILE" | tail -n 1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//')
[ -n "$OLD_DB" ] || fail "DATABASE_URL is not set in $ENV_FILE"

if [ -z "${NEW_DB:-}" ]; then
    read -rs -p 'New DATABASE_URL: ' NEW_DB
    echo
fi
[ -n "$NEW_DB" ] || fail "no new DATABASE_URL given"
[ "$NEW_DB" != "$OLD_DB" ] || fail "the new DATABASE_URL is the one already in $ENV_FILE"
case "$NEW_DB" in
    postgresql://* | postgres://*) ;;
    *) fail "the new DATABASE_URL must start with postgresql://" ;;
esac
case "$NEW_DB" in
    *"'"*) fail "the new DATABASE_URL contains a single quote; URL-encode it (%27)" ;;
esac

# Passed to containers by name (-e VAR) so credentials never show up in `ps`
export OLD_DB NEW_DB

# Run SQL against OLD_DB or NEW_DB; prints unaligned tuples only
sql() {
    local target=$1 query=$2
    docker run --rm -i --network "$DOCKER_NETWORK" -e "$target" \
        -e PGOPTIONS="-c client_min_messages=warning" "$PG_IMAGE" \
        sh -c "psql \"\$$target\" -X -q -v ON_ERROR_STOP=1 -tA" <<< "$query"
}

# One "table=rows" line per table in public, sorted
COUNT_QUERY="select table_name || '=' || (xpath('/row/c/text()',
    query_to_xml(format('select count(*) as c from public.%I', table_name), false, true, '')))[1]::text
  from information_schema.tables
 where table_schema = 'public' and table_type = 'BASE TABLE'
 order by 1;"

table_count() { sql "$1" "select count(*) from pg_tables where schemaname = 'public';"; }

# Tables, sequences, views, indexes, types, functions: anything in public
object_count() {
    sql "$1" "select (select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'public')
                   + (select count(*) from pg_type t join pg_namespace n on n.oid = t.typnamespace
                       where n.nspname = 'public' and t.typtype <> 'c' and t.typelem = 0)
                   + (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public');"
}

restore_into_new() {
    docker run --rm -i --network "$DOCKER_NETWORK" -e NEW_DB "$PG_IMAGE" \
        sh -c 'pg_restore --no-owner --no-acl --exit-on-error -d "$NEW_DB"' < "$1"
}

compare_counts() {
    local old new
    old=$(sql OLD_DB "$COUNT_QUERY")
    new=$(sql NEW_DB "$COUNT_QUERY")
    if [ "$old" != "$new" ]; then
        echo "Row counts differ (old vs new):"
        diff <(echo "$old") <(echo "$new") || true
        return 1
    fi
    echo "      OK: $(wc -l <<< "$old" | tr -d ' ') tables, row counts identical"
}

empty_new() {
    sql NEW_DB "drop schema public cascade; create schema public;"
    [ "$(object_count NEW_DB)" = "0" ] || fail "could not empty the new database"
}

# backup.sh writes to ~/plane-backups/<timestamp>/; the newest sorts last
latest_backup() { ls -d "$HOME"/plane-backups/*/ 2> /dev/null | tail -n 1 | sed 's:/$::'; }

# --- preflight (all modes) ----------------------------------------------------

step "Checking the old database"
sql OLD_DB "select '      ' || version();"
sql OLD_DB "select '      size: ' || pg_size_pretty(pg_database_size(current_database()));"
echo "      tables: $(table_count OLD_DB)"

step "Checking the new database"
sql NEW_DB "select '      ' || version();"
sql NEW_DB "select '      connected as ' || current_user || ' to ' || current_database();"
NEW_OBJECTS=$(object_count NEW_DB)
[ "$NEW_OBJECTS" = "0" ] || fail "the new database is not empty ($NEW_OBJECTS objects in schema public)"
sql NEW_DB "create table _plane_migrate_probe (id int); drop table _plane_migrate_probe;"
echo "      empty, and this user can create tables"

command -v curl > /dev/null || fail "curl is required"

if [ "$MODE" = "check" ]; then
    echo
    echo "Check passed. Next: $0 --rehearse"
    exit 0
fi

# --- rehearsal ----------------------------------------------------------------

if [ "$MODE" = "rehearse" ]; then
    # The target was verified empty above, so it is safe to empty it again if
    # anything below fails
    trap 'status=$?; [ "$status" -eq 0 ] || { echo "!!! Rehearsal failed, emptying the new database"; empty_new; }' EXIT

    step "Backing up the old database (Plane keeps running)"
    "$SCRIPT_DIR/backup.sh"
    BACKUP=$(latest_backup)

    step "Restoring into the new database"
    START=$(date +%s)
    restore_into_new "$BACKUP/plane-db.dump"
    echo "      restore took $(($(date +%s) - START))s (roughly the downtime of the real move)"

    # Plane is still writing to the old database, so small differences in busy
    # tables are expected here; the real move compares with writers stopped.
    step "Comparing row counts"
    compare_counts || echo "      (differences are expected while Plane is still running)"

    step "Emptying the new database again"
    empty_new
    echo "      done"
    trap - EXIT
    echo
    echo "Rehearsal finished. When ready for the downtime: $0"
    exit 0
fi

# --- the real move ------------------------------------------------------------

echo
echo "This stops Plane, copies the database and switches $ENV_FILE to the new one."
read -r -p "Type 'migrate' to continue: " CONFIRM
[ "$CONFIRM" = "migrate" ] || fail "aborted"

ENV_BACKUP="$ENV_FILE.before-db-move-$(date +%Y%m%d-%H%M%S)"
RESTORED=0
SWITCHED=0

rollback() {
    local status=$?
    trap - EXIT
    if [ "$status" -ne 0 ]; then
        echo
        echo "!!! Migration failed, going back to the old database"
        if [ "$SWITCHED" = "1" ]; then
            cp -p "$ENV_BACKUP" "$ENV_FILE"
            "$SCRIPT_DIR/deploy.sh" --no-build || true
            echo "!!! Plane is back on the old database. The new database was left as is"
            echo "!!! (Plane may have written to it); empty it before retrying:"
            echo "!!!   drop schema public cascade; create schema public;"
        else
            if [ "$RESTORED" = "1" ]; then
                # Nothing but this script has written to it; it was empty before
                empty_new || echo "!!! Could not empty the new database; do it before retrying"
            fi
            compose start "${WRITERS[@]}" || true
            echo "!!! Plane is back on the old database."
        fi
    fi
    exit "$status"
}
trap rollback EXIT

step "Stopping Plane (the old database keeps running)"
compose stop "${WRITERS[@]}"

step "Final backup of the old database"
"$SCRIPT_DIR/backup.sh"
BACKUP=$(latest_backup)

step "Restoring into the new database"
RESTORED=1
restore_into_new "$BACKUP/plane-db.dump"
echo "      done"

step "Comparing row counts"
compare_counts

step "Switching $ENV_FILE to the new database"
cp -p "$ENV_FILE" "$ENV_BACKUP"
SWITCHED=1
# awk + ENVIRON so the URL is never interpreted as a regex or shell text; single
# quotes keep compose from expanding anything in it
awk 'BEGIN { url = ENVIRON["NEW_DB"] }
     /^DATABASE_URL=/ { print "DATABASE_URL='\''" url "'\''"; next }
     { print }' "$ENV_BACKUP" > "$ENV_FILE"
echo "      previous .env saved as $ENV_BACKUP"

step "Starting Plane on the new database"
"$SCRIPT_DIR/deploy.sh" --no-build

MIGRATOR=$(compose ps -aq migrator)
[ -n "$MIGRATOR" ] || fail "migrator container not found"
MIGRATOR_EXIT=$(docker wait "$MIGRATOR")
[ "$MIGRATOR_EXIT" = "0" ] || fail "migrator exited with $MIGRATOR_EXIT (see: docker compose logs migrator)"
echo "      migrator: OK"

printf "      waiting for %s " "$HEALTH_URL"
DEADLINE=$(($(date +%s) + HEALTH_TIMEOUT))
until curl -fsS -o /dev/null "$HEALTH_URL" 2> /dev/null; do
    [ "$(date +%s)" -lt "$DEADLINE" ] || { echo; fail "API not healthy after ${HEALTH_TIMEOUT}s"; }
    printf "."
    sleep 5
done
echo " OK"

trap - EXIT

cat << EOF

Plane now runs on the new database.

1. Check in the browser: log in, open projects, issues and an attachment.
2. Then retire the old database container (its plane_pgdata volume is kept):
     docker update --restart=no plane-plane-db-1
     docker stop plane-plane-db-1

Rollback: cp -p $ENV_BACKUP $ENV_FILE && ./deploy.sh --no-build
(changes made after the switch only exist in the new database)
EOF

# Kara Digital Plane deployment

Self-hosted Plane on the office server, built from this repo's source.

- `docker-compose.yml` mirrors the server's original `~/plane/docker-compose.yml`
  (project name `plane`, published ports 3000-3003/8000/9000, `minio.local`
  extra host, no proxy service) but builds every Plane image from source.
- `deploy.sh` pulls the latest commit, builds the images one at a time (pruning
  the build cache in between to keep disk usage low) and restarts the stack.
  It stops before touching the running stack if a build fails or Docker's disk
  has less than `MIN_FREE_GB` (default 15) free.
- `backup.sh` dumps the database, archives the uploads volume and saves the
  compose/.env/patches into `~/plane-backups/<timestamp>/`.
- `migrate-db.sh` moves the database to another Postgres server (see below).
- `.env` (not committed) holds the server secrets. `SECRET_KEY`,
  `LIVE_SERVER_SECRET_KEY` and `DATABASE_URL` must be set; compose refuses to
  start without them.
- The database is the external Postgres in `DATABASE_URL`. The bundled
  `plane-db` container only starts with `COMPOSE_PROFILES=local-db` in `.env`
  (with `DATABASE_URL=postgresql://plane:plane@plane-db/plane`).

## First-time migration from the old `~/plane` install

1. Clone the source and back up while the old stack is still running:

   ```bash
   git clone https://github.com/karadigital/plane.git ~/plane-src
   cd ~/plane-src/deployments/kara
   ./backup.sh
   ```

2. Copy the existing env file:

   ```bash
   cp ~/plane/.env ~/plane-src/deployments/kara/.env
   ```

3. Optionally set `APP_RELEASE` in `.env` to the source version (e.g. `v1.4.3`).
   It is only used as the local image tag; nothing is pulled from Docker Hub.
4. Deploy:

   ```bash
   cd ~/plane-src/deployments/kara
   ./deploy.sh
   ```

   The project name stays `plane`, so the existing `plane_pgdata`,
   `plane_uploads`, ... volumes are reused and the old containers are replaced.

Keep `~/plane` as is for rollback: `cd ~/plane && docker compose up -d`
switches back to the upstream v1.4.2 images (also project `plane`). v1.4.3 adds
no database migrations over v1.4.2, so this is safe for the first migration;
re-check before rolling back from later versions. This rollback uses the
bundled `plane-db`, so it only applies before the database is moved (below).

## Moving the database to the external Postgres server

Target: `10.148.0.13:5432`, database `plane-db`, user `plane-db`. The
password lives only in the server's `.env`; URL-encode it if it contains
characters such as `@`, `:`, `/` or `#`.

1. On the database server, make sure `plane-db` is empty and owned by the
   `plane-db` role (Postgres 15+ only lets the owner create tables in `public`):

   ```sql
   ALTER DATABASE "plane-db" OWNER TO "plane-db";
   ALTER SCHEMA public OWNER TO "plane-db";
   ```

   Allow the Plane server's IP in `pg_hba.conf` / the firewall, and raise
   `max_connections` if needed (the bundled container used 1000).

2. On the Plane server, run `migrate-db.sh`. It asks for the new
   `DATABASE_URL` (hidden input, never written to shell history or `ps`):
   `postgresql://<user>:<url-encoded-password>@<host>:5432/<db>`. If the new
   server is newer than Postgres 15, prefix every command with a matching
   client image, e.g. `PG_IMAGE=postgres:16-alpine`.

   ```bash
   cd ~/plane-src/deployments/kara
   ./migrate-db.sh --check      # connectivity, versions, target empty, can create tables
   ./migrate-db.sh --rehearse   # Plane keeps running: backup, restore, compare, empty again
   ```

   The rehearsal prints how long the restore took, which is roughly the
   downtime of the real move.

3. During the downtime window:

   ```bash
   ./migrate-db.sh              # type 'migrate' to confirm
   ```

   It stops the Plane services (the old database keeps running), takes a final
   `backup.sh`, restores it with `--no-owner --no-acl --exit-on-error`, checks
   that every table has the same row count in both databases, saves `.env` as
   `.env.before-db-move-<timestamp>`, switches `DATABASE_URL`, runs
   `./deploy.sh --no-build`, and waits for the migrator to exit 0 and the API to
   answer.

   The old database is never modified. If anything fails, the script puts the
   previous `.env` back and restarts Plane on the old database. A failure
   before the switch also empties the new database again; after the switch it
   is left as is (Plane may have written to it) and the script says how to
   empty it.

4. Log in and check workspaces, projects, issues and attachments. Then retire
   the old container. Its `plane_pgdata` volume is kept for rollback:

   ```bash
   docker update --restart=no plane-plane-db-1   # don't come back after a reboot
   docker stop plane-plane-db-1
   ```

Rollback after a successful move: `docker start plane-plane-db-1` (if it was
stopped), `cp -p .env.before-db-move-<timestamp> .env`, then
`./deploy.sh --no-build`. Changes made after the switch only exist in the
external database.

## Updating

```bash
cd ~/plane-src/deployments/kara
./backup.sh
./deploy.sh             # git pull + build + up
./deploy.sh --no-pull   # rebuild the current checkout
./deploy.sh --no-build  # restart with the existing images (e.g. after editing .env)
```

Don't use a plain `docker compose up -d`: with `pull_policy: build` it rebuilds
every image again, in parallel. Use `./deploy.sh --no-build` instead.

## Restoring a backup

```bash
B=~/plane-backups/<timestamp>
cd ~/plane-src/deployments/kara
docker compose stop api worker beat-worker web space admin live

export DATABASE_URL=$(grep '^DATABASE_URL=' .env | tail -n 1 | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']$//")
docker run --rm -i --network plane_default -e DATABASE_URL postgres:15.7-alpine \
  sh -c 'pg_restore --clean --if-exists --no-owner --no-acl -d "$DATABASE_URL"' < $B/plane-db.dump
docker run --rm -v plane_uploads:/data -v $B:/backup postgres:15.7-alpine \
  sh -c 'tar xzf /backup/plane-uploads.tar.gz -C /data'

./deploy.sh --no-build
```

## Time (solidtime) integration

Work items have a "Time tracked" row that logs time to solidtime
(https://time.shrwt.id) and lists the time already tracked (KARA-30). It stays
hidden until these are set in `.env`, then `./deploy.sh --no-build` (or a full
deploy) restarts the API with them:

```
SOLIDTIME_BASE_URL=https://time.shrwt.id
SOLIDTIME_API_TOKEN=<API token of a solidtime owner/admin>
SOLIDTIME_ORGANIZATION_ID=<organization UUID from solidtime URLs>
```

- The token must belong to an owner/admin: Plane creates entries on behalf of
  other members (matched by email) and reads everyone's entries on a work item.
- A Plane project maps to the solidtime project named after its identifier
  (`KARA`), falling back to the project name (`Sandbox`). Tasks are named
  `[KARA-30] <work item name>` and are created automatically when missing.
- A Plane user whose email is not a solidtime member gets a clear error and
  nothing is created.
- The token must be **long-lived**: Plane reads it from `.env` and never
  rotates it (the old bridge renewed its own token weekly). Record its expiry
  here and renew it before then:
  `SOLIDTIME_API_TOKEN expires: YYYY-MM-DD`

### Project and task sync (KARA-220, replaces solidtime-bridge)

Plane keeps solidtime projects and `[IDENT-N] <work item name>` tasks in step,
so the separate `solidtime-bridge` service is no longer needed:

- Creating a work item creates its task. Renaming the work item, or publishing
  a draft, renames or creates the task. Saves that only change other fields
  (state, sort order, assignees, ...) do nothing.
- Creating a project creates a solidtime project named after its identifier.
  It is public, billable, colour `#6366f1`, and uses `SOLIDTIME_DEFAULT_CLIENT_ID`.
  Changing a project's identifier (`KARA` -> `KARX`) renames that solidtime
  project and every `[KARA-N]` task. Projects matched by name (`Sandbox`)
  keep their name.
- A daily reconcile at UTC 20:00 (03:00 WIB) creates anything missing and
  fixes stale task names, catching bulk edits and outages.
- Deleting or archiving a work item never deletes its solidtime task; time
  entries are kept. Descriptions and states are not synced.
- Archived Plane projects, drafts and deleted work items are skipped.
  Intake/triage and archived work items are synced.

```
SOLIDTIME_SYNC_ENABLED=0                # 1 turns the sync on
SOLIDTIME_SYNC_WORKSPACE_SLUG=kara-digital
SOLIDTIME_DEFAULT_CLIENT_ID=8593681a-1042-4eb3-b068-0ef3b7099b3b   # client "Kara"
```

Manual backfill/repair (replaces `bridge.py sync`):

```bash
docker compose exec api python manage.py solidtime_reconcile --dry-run
docker compose exec api python manage.py solidtime_reconcile [--project KARA] [--pause 0.3]
```

It prints `IDENT: project=existing|created|would_create created=N renamed=N
unchanged=N errors=N` per project and a total line. `--rename-from OLD`
(needs `--project`) first renames `[OLD-N]` tasks, and the `OLD` project if it
is still named that, to the current identifier. Writes are spaced by
`--pause` seconds to stay under solidtime's 200 requests/minute limit, which
this token shares with the "Time tracked" row.

Cutover from the bridge:

1. Deploy with `SOLIDTIME_SYNC_ENABLED=0` and the slug and client id above set.
2. Stop the bridge: `systemctl disable --now solidtime-bridge.service`, remove
   the `renew_token.sh` and `healthcheck.sh` cron jobs, delete the `/_bridge/`
   webhook (Workspace settings -> Webhooks) and the nginx `/_bridge/` location.
3. Run `solidtime_reconcile --dry-run` and check the output. The command
   works while `SOLIDTIME_SYNC_ENABLED=0`; it only needs the slug and the
   `SOLIDTIME_*` credentials. A line starting
   with `!` means a project's tasks still use an old identifier. **ECOM**, for
   example, was `SOPI`, so solidtime holds `[SOPI-N]` tasks with time entries.
   Rename those first, or the reconcile creates duplicate `[ECOM-N]` tasks and
   the history stays on the old ones:
   `solidtime_reconcile --project ECOM --rename-from SOPI --dry-run`, then the
   same command without `--dry-run`. Then run the full reconcile without
   `--dry-run`.
4. Set `SOLIDTIME_SYNC_ENABLED=1` and restart api, worker and beat-worker
   (`./deploy.sh --no-build`).
5. Check end to end:
   - a new work item's task appears;
   - renaming the work item renames the task;
   - a new project appears in solidtime;
   - logging time from the sidebar updates "Time tracked".
6. Once stable, archive `/opt/solidtime-bridge` and revoke the bridge's old
   solidtime token and Plane API key.

### Time per work item in the public API (KARA-219)

API-key clients (client-kara) read the time logged per work item with:

```
GET /api/v1/workspaces/<slug>/projects/<project_id>/time-summary/
X-API-Key: <Plane API key of a project member>

200 {"configured": true, "total_seconds": 780,
     "work_items": [{"id": "<uuid>", "sequence_id": 1, "seconds": 660}, ...]}
```

- **What it counts:** every finished time entry on a task named `[IDENT-N] …`,
  billable or not. Running timers are not counted.
  - Duplicate `[IDENT-N]` tasks are summed together.
  - Only work items with time are listed; a work item that is missing has 0.
- **Configuration:** it uses the same `SOLIDTIME_*` settings as above, with no new
  variables. Without them the response is
  `{"configured": false, "total_seconds": 0, "work_items": []}`.
- **Freshness and cost:** results are cached for 60 s per project. Each refresh
  makes 2–3 solidtime requests, which count against the token's limit of 200 requests per minute.
- **When solidtime fails:** if solidtime is down, rate-limited or rejects the token, the response is
  `502 {"code": "solidtime_unavailable"}`.

## Kara-specific code changes

Changes previously applied as bind-mounted patches now live in source:

- Completed cycles can change `start_date` / `end_date` (reopen/extend) and
  `sort_order`; all other fields stay locked
  (`apps/api/plane/app/views/cycle/base.py`, `apps/api/plane/api/views/cycle.py`).

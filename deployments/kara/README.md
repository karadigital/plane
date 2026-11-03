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

2. On the Plane server, check connectivity and the server version. If it is
   newer than 15, use a matching client image (e.g. `PG_IMAGE=postgres:16-alpine`)
   in all commands below and for `backup.sh`:

   ```bash
   read -rs -p 'New DATABASE_URL: ' NEW_DB && export NEW_DB && echo
   # e.g. postgresql://plane-db:<url-encoded-password>@10.148.0.13:5432/plane-db
   docker run --rm --network plane_default -e NEW_DB postgres:15.7-alpine \
     sh -c 'psql "$NEW_DB" -c "select version()"'
   ```

   `read -s` keeps the password out of the shell history, and `-e NEW_DB`
   (passed by name) keeps it out of `ps`.

3. Stop everything that writes to the database, then take the final dump of
   the bundled database. Compose now requires `DATABASE_URL`, so if `.env`
   does not have it yet, first add the current one:
   `DATABASE_URL=postgresql://plane:plane@plane-db/plane`.

   ```bash
   cd ~/plane-src/deployments/kara
   docker compose stop api worker beat-worker web space admin live
   DATABASE_URL=postgresql://plane:plane@plane-db/plane ./backup.sh
   ```

4. Restore that dump into the external database. `--no-owner --no-acl` makes
   every object owned by `plane-db`:

   ```bash
   B=~/plane-backups/<timestamp>
   docker run --rm -i --network plane_default -e NEW_DB postgres:15.7-alpine \
     sh -c 'pg_restore --no-owner --no-acl --exit-on-error -d "$NEW_DB"' < $B/plane-db.dump
   ```

5. Point `.env` at the external database and recreate the containers. No
   rebuild is needed, only the env changes:

   ```bash
   DATABASE_URL=postgresql://plane-db:<url-encoded-password>@10.148.0.13:5432/plane-db
   ```

   ```bash
   ./deploy.sh --no-build
   docker compose logs -f migrator api   # migrator should report no new migrations
   ```

   Log in and check that workspaces, projects and issues are all there.

6. Stop the old container. Its `plane_pgdata` volume is kept for rollback:

   ```bash
   docker update --restart=no plane-plane-db-1   # don't come back after a reboot
   docker stop plane-plane-db-1
   ```

Rollback: set `COMPOSE_PROFILES=local-db` and
`DATABASE_URL=postgresql://plane:plane@plane-db/plane` in `.env`, then
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

## Kara-specific code changes

Changes previously applied as bind-mounted patches now live in source:

- Completed cycles can change `start_date` / `end_date` (reopen/extend) and
  `sort_order`; all other fields stay locked
  (`apps/api/plane/app/views/cycle/base.py`, `apps/api/plane/api/views/cycle.py`).

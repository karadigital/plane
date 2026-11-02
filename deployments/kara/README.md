# Kara Digital Plane deployment

Self-hosted Plane on the office server, built from this repo's source.

- `docker-compose.yml` mirrors the server's original `~/plane/docker-compose.yml`
  (project name `plane`, published ports 3000-3003/8000/9000, `minio.local`
  extra host, no proxy service) but builds every Plane image from source.
- `deploy.sh` pulls the latest commit, builds the images and restarts the stack.
- `.env` (not committed) holds the server secrets. `SECRET_KEY` and
  `LIVE_SERVER_SECRET_KEY` must be set; compose refuses to start without them.

## First-time migration from the old `~/plane` install

1. Back up the database and volumes.
2. Clone the source and copy the existing env file:

   ```bash
   git clone https://github.com/karadigital/plane.git ~/plane-src
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
re-check before rolling back from later versions.

## Updating

```bash
cd ~/plane-src/deployments/kara
./deploy.sh            # git pull + build + up
./deploy.sh --no-pull  # rebuild the current checkout
```

## Kara-specific code changes

Changes previously applied as bind-mounted patches now live in source:

- Completed cycles can change `start_date` / `end_date` (reopen/extend) and
  `sort_order`; all other fields stay locked
  (`apps/api/plane/app/views/cycle/base.py`, `apps/api/plane/api/views/cycle.py`).

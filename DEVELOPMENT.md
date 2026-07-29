# Development Guide

How to run this project on your computer.

This is our company fork of [Plane](https://github.com/makeplane/plane).

---

## Table of contents

1. [Summary: what we changed in this fork](#1-summary-what-we-changed-in-this-fork)
2. [What you need](#2-what-you-need)
3. [First time setup](#3-first-time-setup)
4. [Normal day: how to start](#4-normal-day-how-to-start)
5. [The 4 web apps](#5-the-4-web-apps)
6. [Start and stop web apps](#6-start-and-stop-web-apps)
7. [The Docker containers](#7-the-docker-containers)
8. [Start and stop Docker](#8-start-and-stop-docker)
9. [All ports](#9-all-ports)
10. [If you have 8 GB RAM](#10-if-you-have-8-gb-ram)
11. [Problems and fixes](#11-problems-and-fixes)
12. [Git: branches and pull requests](#12-git-branches-and-pull-requests)

---

## 1. Summary: what we changed in this fork

We changed **6 files**. We changed **no code**. Nothing in `apps/` or `packages/` is
different from Plane.

### Deleted (3 files)

| File                                  | Why we deleted it                                                                                                                              |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `CODEOWNERS`                          | It asked Plane's team to review our pull requests. They are not in our company.                                                                |
| `CONTRIBUTING.md`                     | It explained how to help the public Plane project. We do not need that. This file replaces it.                                                 |
| `.github/workflows/check-version.yml` | It blocked every pull request into `master` until someone changed the version number in `package.json`. Nothing in our code reads that number. |

### Changed (3 files)

In these 3 files we changed **one word**: `preview` → `develop`.

- `.github/workflows/copyright-check.yml`
- `.github/workflows/pull-request-build-lint-api.yml`
- `.github/workflows/pull-request-build-lint-web-apps.yml`

**Why:** Plane runs its tests on a branch called `preview`. Our fork has no `preview`
branch. So our tests never ran. Now they run on `develop`.

### Test results on a Mac with 8 GB RAM

We tested the full setup. It works.

| Step                       | Time                               | Result |
| -------------------------- | ---------------------------------- | ------ |
| Build the API Docker image | 3 minutes                          | OK     |
| `pnpm install`             | 37 seconds                         | OK     |
| Start the containers       | 105 seconds until the API answered | OK     |
| Start the 4 web apps       | 85 seconds                         | OK     |

Memory used by Docker: **1.43 GB** out of the 3.83 GB that Docker gets.

---

## 2. What you need

| Thing          | Version                      | How to check |
| -------------- | ---------------------------- | ------------ |
| Docker Desktop | any recent                   | `docker -v`  |
| Node.js        | 22.18.0 or newer             | `node -v`    |
| pnpm           | 10.32.1                      | `pnpm -v`    |
| RAM            | 8 GB works. 16 GB is better. | —            |
| Free disk      | about 15 GB                  | `df -h /`    |

### If `pnpm -v` says "command not found"

```bash
corepack enable pnpm
```

Corepack comes with Node.js. It installs the correct pnpm version for this project.

> **Note:** The old `CONTRIBUTING.md` said Node 20. That was wrong.
> `package.json` needs **Node 22.18.0 or newer**.

---

## 3. First time setup

Do this **one time only**.

### Step 1 — Create the config files

```bash
./setup.sh
```

This does 3 things:

1. Copies 6 `.env.example` files to 6 `.env` files
2. Creates a secret password for Django (`SECRET_KEY`)
3. Runs `pnpm install`

The 6 `.env` files are here:

```
.env
apps/web/.env
apps/admin/.env
apps/space/.env
apps/live/.env
apps/api/.env
```

> **These files hold passwords. Never send them to GitHub.**
> They are already in `.gitignore`, so Git ignores them. This is correct.
> Do not change this.

You do not need to edit these files. The default values work.

### Step 2 — Start the containers

```bash
docker compose -f docker-compose-local.yml up -d
```

**The first time is slow.** Docker builds the API image. This takes about 3 minutes.
After that, it starts in a few seconds.

`-d` means "run in the background". Your terminal stays free.

Wait about 2 minutes. The database needs to create its tables first.

Check if the API is ready:

```bash
curl -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/instances/
```

When you see `200`, it is ready.

### Step 3 — Start the web apps

```bash
pnpm dev
```

Wait about 90 seconds.

### Step 4 — Create your admin user

Open this address in your browser:

```
http://localhost:3001/god-mode/
```

Fill the form. This creates the **instance admin** — the boss user of the whole system.

**You must do this first.** The database is empty. There is no user yet.

### Step 5 — Log in

Open:

```
http://localhost:3000
```

Log in with the **same email and password** from step 4.

Done. You can now use Plane.

---

## 4. Normal day: how to start

After the first setup, you only need 2 commands:

```bash
# 1. Start the backend (database, API, workers)
docker compose -f docker-compose-local.yml up -d

# 2. Start the web apps
pnpm dev
```

Then open `http://localhost:3000`.

---

## 5. The 4 web apps

This project has 4 separate web apps. They are **not** the same program.

| App       | Port | Address                         | What it is for                                                                                                                           |
| --------- | ---- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **web**   | 3000 | http://localhost:3000           | The main app. Projects, tasks, cycles, modules. This is what users see every day.                                                        |
| **admin** | 3001 | http://localhost:3001/god-mode/ | System settings for the whole server. Create the first admin, set up email, turn login methods on and off. Normal users never open this. |
| **space** | 3002 | http://localhost:3002/spaces/   | Public pages. When you share a project with people outside your company, they see it here. No login needed.                              |
| **live**  | 3100 | http://localhost:3100/live      | Not a website. It is a background server. It lets two people edit the same document at the same time and see each other typing.          |

### Which ones do you really need?

| You are working on                       | Start these     |
| ---------------------------------------- | --------------- |
| Normal features (tasks, projects, views) | `web`           |
| The first setup, or server settings      | `web` + `admin` |
| Editing documents together               | `web` + `live`  |
| Public sharing                           | `web` + `space` |

**You do not need all 4 every day.** Starting fewer apps uses less memory.

---

## 6. Start and stop web apps

### Start all 4

```bash
pnpm dev
```

### Start only one

```bash
pnpm turbo run dev --filter=web
```

Change `web` to `admin`, `space`, or `live`.

### Start two or three

```bash
pnpm turbo run dev --filter=web --filter=admin
```

Add one `--filter=` for each app you want.

To check what will start before you start it, add `--dry`:

```bash
pnpm turbo run dev --filter=web --filter=admin --dry
```

It prints `Packages in scope: admin, web` and then stops. It starts nothing.

### Stop all web apps

Press **`Ctrl` + `C`** in the terminal where they run.

### Stop only one web app

This is the problem: `pnpm dev` runs all 4 apps in **one** terminal. `Ctrl+C` stops all
of them together. You cannot stop one.

**Two ways to fix this:**

**Way 1 (better) — one terminal for each app**

Open a separate terminal window for each app:

```bash
# terminal 1
pnpm turbo run dev --filter=web

# terminal 2
pnpm turbo run dev --filter=admin
```

Now `Ctrl+C` in terminal 2 stops only `admin`. `web` keeps running.

**Way 2 — kill by port number**

If everything runs in one terminal, find the app by its port and stop it:

```bash
lsof -ti:3001 | xargs kill
```

This stops the app on port 3001 (`admin`).

Change the number for a different app:

| App   | Command                       |
| ----- | ----------------------------- |
| web   | `lsof -ti:3000 \| xargs kill` |
| admin | `lsof -ti:3001 \| xargs kill` |
| space | `lsof -ti:3002 \| xargs kill` |
| live  | `lsof -ti:3100 \| xargs kill` |

> **Warning:** the tool that runs the apps (turbo) may notice one app died and stop the
> others too. Way 1 is safer.

### Check which apps are running

```bash
lsof -ti:3000 -ti:3001 -ti:3002 -ti:3100
```

Or check one port:

```bash
curl -o /dev/null -w "%{http_code}\n" http://localhost:3000
```

`000` means nothing is running there.

---

## 7. The Docker containers

The backend runs in Docker. There are 8 containers.

| Container     | What it is                                                                                    | Stays running? |
| ------------- | --------------------------------------------------------------------------------------------- | -------------- |
| `plane-db`    | PostgreSQL database. All your data lives here.                                                | Yes            |
| `plane-redis` | Valkey (same as Redis). Fast temporary memory, and live updates.                              | Yes            |
| `plane-mq`    | RabbitMQ. A queue. It passes jobs to the workers.                                             | Yes            |
| `plane-minio` | File storage. Images and attachments you upload.                                              | Yes            |
| `api`         | The Django backend. All the API endpoints.                                                    | Yes            |
| `worker`      | Celery worker. Slow jobs in the background: send email, export files, notifications.          | Yes            |
| `beat-worker` | Celery beat. A clock. It starts jobs at fixed times.                                          | Yes            |
| `migrator`    | Creates and updates the database tables. **It runs one time, then it stops. This is normal.** | No             |

So after startup you will see **7** containers running, not 8. Do not worry about
`migrator`. It finished its job.

### How much memory they use

Measured on a Mac with 8 GB RAM:

| Container     | Memory            |
| ------------- | ----------------- |
| `worker`      | 697 MB            |
| `api`         | 225 MB            |
| `beat-worker` | 162 MB            |
| `plane-mq`    | 143 MB            |
| `plane-minio` | 138 MB            |
| `plane-db`    | 89 MB             |
| `plane-redis` | 12 MB             |
| **Total**     | **about 1.43 GB** |

---

## 8. Start and stop Docker

### Start everything

```bash
docker compose -f docker-compose-local.yml up -d
```

### Stop everything (keep your data)

```bash
docker compose -f docker-compose-local.yml down
```

Your database is safe. Next time you start, your projects and tasks are still there.

### Stop everything and DELETE ALL DATA

```bash
docker compose -f docker-compose-local.yml down -v
```

> **Careful.** `-v` deletes the database, the uploaded files, everything.
> You will need to create your admin user again from step 4.
> Use this only when you want to start clean.

### See what is running

```bash
docker compose -f docker-compose-local.yml ps
```

### See the logs

```bash
# all containers
docker compose -f docker-compose-local.yml logs -f

# only the API
docker compose -f docker-compose-local.yml logs -f api
```

Press `Ctrl+C` to stop watching. This does not stop the container.

### Start or stop one container

```bash
docker compose -f docker-compose-local.yml stop worker
docker compose -f docker-compose-local.yml start worker
```

### Rebuild the API image

Do this when someone changes the Python libraries
(`apps/api/requirements.txt` or `apps/api/requirements/`):

```bash
docker compose -f docker-compose-local.yml build api
docker compose -f docker-compose-local.yml up -d
```

> **You do not need to rebuild when you change Python code.** Your `apps/api` folder is
> connected directly into the container. Django sees your changes and restarts by itself.

---

## 9. All ports

| Port | What           |
| ---- | -------------- |
| 3000 | web app        |
| 3001 | admin app      |
| 3002 | space app      |
| 3100 | live server    |
| 8000 | Django API     |
| 5432 | PostgreSQL     |
| 6379 | Valkey / Redis |
| 9000 | MinIO (files)  |
| 9090 | MinIO web page |

If a port is already used by another program, that app will not start.

---

## 10. If you have 8 GB RAM

It works, but your computer will be slow. Here is what helps.

### Start fewer web apps

This is the biggest help:

```bash
pnpm turbo run dev --filter=web --filter=admin
```

2 apps instead of 4.

### Use fewer Celery workers

The `worker` container uses the most memory (697 MB). It starts one process for every
CPU core. On an 8-core Mac, that is 8 processes.

To use less, create a file called `docker-compose.override.yml` in the main folder:

```yaml
services:
  worker:
    command: >
      bash -c "python manage.py wait_for_db &&
               python manage.py wait_for_migrations &&
               celery -A plane worker -l info --concurrency=2"
```

Docker reads this file automatically. This saves about 400 MB.

> Put this file in `.gitignore`. It is your personal setting, not a project setting.
> Do not change `apps/api/bin/docker-entrypoint-worker.sh` — that file belongs to Plane,
> and changing it makes every future update harder.

### Do not run without Docker

You may think: "Docker uses memory. Let me run Python directly."

**Do not do this.** We tested it. You would need to:

- Install Python 3.12 (macOS comes with 3.9, too old)
- Run `brew install libpq` to build one library
- Load the `.env` file by hand in **every** terminal, because the Python code has no
  `dotenv` library and does not read `.env` by itself

You would save 3 minutes, one time. It is not worth it.

---

## 11. Problems and fixes

### The web app cannot reach the API

Check the API:

```bash
curl -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/instances/
```

- `200` → the API is fine. The problem is in the web app.
- `000` → the API is not running. Start Docker.

### The API container starts and stops again

It is probably waiting for the database. Look at the logs:

```bash
docker compose -f docker-compose-local.yml logs api
```

### The web apps stop for no reason, with no error message

Your Mac ran out of memory and killed them. When macOS kills a program, the program has
no time to write an error. So you see a stop with no reason.

Fix: start fewer apps (see [section 10](#10-if-you-have-8-gb-ram)).

### Realtime notifications do not show up

A mention or a new assignment should show a popup while you work. If nothing appears:

1. **Open `http://localhost:3000`, not `http://127.0.0.1:3000`.** They look the same but
   the browser treats them as two different sites. Your login cookie is sent to
   `localhost` only, so the notification stream gets a 401 and stays quiet.
2. **The `live` app must be running.** Start it with
   `pnpm turbo run dev --filter=live`.
3. **Check `CORS_ALLOWED_ORIGINS` in `apps/live/.env`.** It must list the address of the
   web app (`http://localhost:3000`). `./setup.sh` already puts it there.
4. **Check the live server is connected to Redis:**

   ```bash
   curl http://localhost:3100/live/health
   ```

   You want `"redis":"connected"` and `"notifications":"enabled"`. `"disabled"` means the
   push is off — the notification tray still works, only the popup is missing.

### `pnpm dev` fails after you pull new code

Someone added a new library. Install it:

```bash
pnpm install
```

### I cannot log in — it says no user exists

You skipped step 4. Go to `http://localhost:3001/god-mode/` and create the admin user
first.

### Docker uses too much disk

```bash
docker system df           # see how much
docker builder prune -af   # delete old build files
```

### Start completely fresh

```bash
docker compose -f docker-compose-local.yml down -v
docker compose -f docker-compose-local.yml up -d
```

Remember: `-v` deletes all your data.

---

## 12. Git: branches and pull requests

### Our branches

```
develop   ← send all pull requests here
master    ← same as Plane. Only for releases.
```

### Make a new feature

```bash
git checkout develop
git pull
git checkout -b feature/my-new-thing

# write your code

git add .
git commit -m "feat(web): add my new thing"
git push -u origin feature/my-new-thing
```

Then open a pull request into `develop` on GitHub.

### Commit message style

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): short description
```

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`

Examples:

```
feat(web): add filter by assignee
fix(api): correct date in export
chore(ci): update node version
```

### Get updates from the real Plane project

Every person must run this **one time** on their own computer:

```bash
git remote add upstream https://github.com/makeplane/plane.git
```

> Git remotes live on your computer only. They are not saved on GitHub.
> So every new developer must add `upstream` themselves.

Then, to get Plane's new code:

```bash
git fetch upstream
git checkout master
git merge upstream/master
```

### Before you commit

```bash
pnpm check      # check format, lint, and types
pnpm fix        # fix format and lint automatically
pnpm test       # run the unit tests (live, web, propel, codemods)
```

A Git hook also checks your files when you commit. If it finds a problem, the commit
stops.

### Which tests run on GitHub

When you open a pull request into `develop`:

| Test                               | What it checks                |
| ---------------------------------- | ----------------------------- |
| `pull-request-build-lint-api`      | The Python code               |
| `pull-request-build-lint-web-apps` | The web code                  |
| `copyright-check`                  | The copyright header in files |

---

## Quick command list

```bash
# ---------- first time only ----------
corepack enable pnpm
./setup.sh

# ---------- every day ----------
docker compose -f docker-compose-local.yml up -d     # start backend
pnpm dev                                             # start all 4 web apps

# ---------- use less memory ----------
pnpm turbo run dev --filter=web --filter=admin       # start only 2

# ---------- stop ----------
Ctrl + C                                             # stop web apps
docker compose -f docker-compose-local.yml down      # stop backend

# ---------- check ----------
docker compose -f docker-compose-local.yml ps        # what is running
docker compose -f docker-compose-local.yml logs -f api
```

| Address                         | What            |
| ------------------------------- | --------------- |
| http://localhost:3000           | Main app        |
| http://localhost:3001/god-mode/ | Server settings |
| http://localhost:3002/spaces/   | Public pages    |
| http://localhost:8000           | API             |

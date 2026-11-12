# KARA-220 Native Plane → solidtime Task Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the external `solidtime-bridge` service with native Plane code that keeps solidtime projects and `[IDENT-N]` tasks in step with Plane projects and work items.

**Architecture:**

- The sync reuses the KARA-30 solidtime client and its naming-convention matching. There is no ID mapping table.
- `post_save` signals on `Issue` and `Project` enqueue Celery tasks with `transaction.on_commit`, but only when a relevant field changed.
- A pure sync service (`plane/utils/solidtime/sync.py`) creates and renames projects and tasks.
- A daily beat job and a `solidtime_reconcile` management command run the same per-project diff as a safety net and for the cutover backfill.

**Tech Stack:** Django signals + `ChangeTrackerMixin`, Celery (`shared_task`, beat), `requests`, pytest + pytest-mock + pytest-django (docker test stack).

**Spec:**

- `/Users/karadigital/Documents/projects/solidtime-bridge/migration/01-plane-prompt.md` (requirements)
- `/Users/karadigital/Documents/projects/solidtime-bridge/migration/00-overview-cutover.md` (cutover)

Work item: KARA-220 "Replace plane bridge".

**Branch:** `feature/KARA-220-solidtime-sync`, cut from `feature/KARA-30-solidtime-time-logging`, because PR #8 (KARA-30) is not merged yet. Open the PR against that branch, and retarget it to `master` once #8 merges.

## Design decisions (made here, binding for the tasks)

- **Hook = Option A, `post_save` signals.**
  - `Issue` already uses `ChangeTrackerMixin`. Adding `name`, `project_id`, `sequence_id` and `is_draft` to `TRACKED_FIELDS` lets the receiver read `instance._changes_on_save` with no extra query.
  - `ChangeTrackerMixin.save` sets `_changes_on_save` before calling `super().save()` and resets tracking only after it. So `post_save` still sees the changed field names and `old_values`.
  - Every ORM `save()` fires the signal: the web app, the public API, intake, and duplicate.
  - Option B (`issue_activity`) only covers paths that remember to call it, and it would need us to parse each endpoint's `requested_data` JSON.
  - Neither option catches `bulk_create` or `QuerySet.update`. The daily reconcile catches those.
- **`Project`** gets `ChangeTrackerMixin` with `TRACKED_FIELDS = ["identifier"]` (no migration). The receiver passes `instance.old_values["identifier"]` when the identifier changed.
- **Receivers** live in `plane/utils/solidtime/signals.py` and are registered in a new `DbConfig.ready()`.
- **The signal does the cheap gate** (`sync_enabled()`, `created`/changed fields). **The Celery task does the workspace and draft checks**, so request handlers run no extra queries.
- **Scope:**
  - Projects: those in `SOLIDTIME_SYNC_WORKSPACE_SLUG` with `archived_at IS NULL`. The bridge also listed only live projects through the Plane API.
  - Issues: `Issue.objects` (soft-delete aware) with `is_draft=False`, in every state group including triage/intake, archived issues included.
- **New solidtime projects:**
  - `name = identifier`, `color = "#6366f1"` (the bridge's colour), `is_billable = True`, `client_id = SOLIDTIME_DEFAULT_CLIENT_ID or None`.
  - `is_public = True`: solidtime employees can only track time on public projects or projects they are members of, and existing Kara projects such as `KARA` are public.
- **Project PUT must resend current fields.** `ProjectController::update` always overwrites `client_id` and `billable_rate` from the request, and nulling them recalculates every time entry. So `update_project` first GETs the project and resends `name`, `color`, `is_billable`, `is_public`, `client_id` and `billable_rate`. It omits `estimated_time` and `is_archived`, which are preserved when absent.
- **`find_project` order:** exact identifier → exact name → case-insensitive identifier → case-insensitive name. With this order, `WILL` beats the junk `will`.
- **Rate limit:** solidtime pages 500 rows (`PAGINATION_PER_PAGE_DEFAULT=500`), so reads are cheap. Writes in `reconcile_project` sleep `pause_seconds` between calls. The command defaults to `0.3` s (≤ 200/min); the beat job uses the same.
- **Beat slot:** UTC 20:00 (03:00 WIB). It is free in `plane/celery.py`, and nobody is tracking time then.
- **Retry:** only `SolidtimeError.code == "unavailable"` retries, with `countdown = 60 * 2**retries` and `max_retries = 5` (60 s → 16 min, about 31 min in total). Other codes are logged once with `log_exception(e, warning=True)` and dropped.

## Global Constraints

- New settings (in `settings/common.py` next to `SOLIDTIME_ORGANIZATION_ID`, plus `.env.example`, `deployments/kara/docker-compose.yml` `x-app-env`, and `deployments/kara/README.md`):
  - `SOLIDTIME_SYNC_ENABLED`: bool, default False, parsed as `os.environ.get(...,"0").lower() in ("1","true","yes")`.
  - `SOLIDTIME_SYNC_WORKSPACE_SLUG`: default `""`.
  - `SOLIDTIME_DEFAULT_CLIENT_ID`: default `""`.
- Sync is off unless `SOLIDTIME_SYNC_ENABLED` is true, `SOLIDTIME_SYNC_WORKSPACE_SLUG` is non-blank, and `SolidtimeClient.from_settings()` is not None. KARA-30 logging must behave exactly as before in every case.
- Task name is `task_name(issue)` from KARA-30: `"[IDENT-N] name"`, truncated to 255. Task match is `find_task` on the prefix `[IDENT-N]`.
- Never delete or archive solidtime tasks or projects. Never sync descriptions or state. Never post comments.
- The token never appears in logs or exceptions (the KARA-30 client already guarantees this; keep it).
- Tests: `docker compose -f docker-compose-test.yml run --rm api-tests pytest <path> -v` from the repo root. Python is checked with ruff inside the container (`pip install -q ruff; ruff check …; ruff format --check …`).
- Commit messages: `feat(time): … (KARA-220)` / `fix(time): … (KARA-220)`. New files carry the neighbouring license header.

## Review Focus

1. **Renaming a solidtime project silently wipes its client and billable rate** (the bridge's PUT did this). Covered: Task 1 `test_update_project_resends_current_fields`.
2. **A signal fired inside a transaction that later rolls back** must not enqueue a sync for a work item that doesn't exist. Covered: Task 4 `test_rolled_back_create_enqueues_nothing`.
3. **First cutover reconcile with many writes hits the 200/min limit, or one task fails.** The rest of the project must still sync, and the failure must be counted, not raised. Covered: Task 2 `test_reconcile_counts_errors_and_continues`, Task 2 `test_reconcile_pauses_between_writes`.
4. **Rename target already taken** (solidtime 422 "name already exists", e.g. a manual duplicate). Covered: Task 2 `test_identifier_rename_counts_collisions`.
5. **Intake/triage work items** are synced too, matching the bridge, and drafts and soft-deleted items are not. Covered: Task 3 `test_issues_for_sync_scope`.

---

### Task 1: Settings + client write methods + `find_project` exact-first

**Files:**

- Modify: `apps/api/plane/settings/common.py` (after `SOLIDTIME_ORGANIZATION_ID`)
- Modify: `apps/api/.env.example`
- Modify: `apps/api/plane/utils/solidtime/client.py`
- Modify: `apps/api/plane/utils/solidtime/service.py` (`find_project`)
- Test: `apps/api/plane/tests/unit/utils/test_solidtime_client.py`, `apps/api/plane/tests/unit/utils/test_solidtime_service.py`

**Interfaces:**

- Produces, on `SolidtimeClient`:
  - `PROJECT_COLOR = "#6366f1"` (module constant)
  - `get_project(project_id: str) -> dict`: `GET /projects/{id}`, returns `body["data"]`.
  - `create_project(name: str, client_id: str | None = None, is_billable: bool = True) -> dict`: `POST /projects` with json `{name, color: PROJECT_COLOR, is_billable, is_public: True, client_id}`. Invalidates the `projects` cache.
  - `update_project(project_id: str, **changes) -> dict`: GET current, then `PUT /projects/{id}` with `{name, color, is_billable, is_public, client_id, billable_rate}` from current, overlaid by `changes`. Invalidates the `projects` cache.
  - `update_task(task_id: str, name: str) -> dict`: `PUT /tasks/{id}` with json `{"name": name}`.
  - `invalidate_projects_cache() -> None`: deletes the `solidtime:{org}:projects` key used by `_cached`.
- Produces, in `service.find_project(projects, project)`, the new match order: exact identifier, exact name, case-insensitive identifier, case-insensitive name. Same signature.

- [ ] **Step 1: Write failing tests**
  - Client tests (`@pytest.mark.unit`, reuse `_client`/`_response` and the autouse cache-clear fixture):
    - `test_create_project_posts_identifier_with_defaults`: json equals `{"name": "NEWP", "color": "#6366f1", "is_billable": True, "is_public": True, "client_id": "c1"}`, and the method is POST to `{BASE}/projects`.
    - `test_create_project_invalidates_projects_cache`: list_projects (1 call), create_project, list_projects again → 3 requests in total.
    - `test_update_project_resends_current_fields`: the GET returns `{"id":"p1","name":"KARA","color":"#ef5350","is_billable":True,"is_public":True,"client_id":"c1","billable_rate":15000,"estimated_time":None}`. `update_project("p1", name="KARX")` makes a PUT with json `{"name":"KARX","color":"#ef5350","is_billable":True,"is_public":True,"client_id":"c1","billable_rate":15000}`.
    - `test_update_task_puts_name`: PUT `{BASE}/tasks/t1` with json `{"name": "[KARX-1] A"}`.
  - Service test:
    - `test_find_project_prefers_exact_case`: projects `[{"name":"will"},{"name":"WILL"}]` with identifier `WILL` → the `WILL` row. Projects `[{"name":"Kara"}]` with identifier `KARA` → still matched case-insensitively.
    - The KARA-30 case `test_find_project_prefers_identifier_then_name` must still pass.

- [ ] **Step 2: Run, expect FAIL**
      Run: `docker compose -f docker-compose-test.yml run --rm api-tests pytest plane/tests/unit/utils/test_solidtime_client.py plane/tests/unit/utils/test_solidtime_service.py -v`
      Expected: the five new tests fail (AttributeError / wrong match); the old ones pass.

- [ ] **Step 3: Implement** the client methods, the `find_project` order, and the three settings plus `.env.example` lines (empty values, comment: sync is off unless enabled).

- [ ] **Step 4: Run, expect PASS** (same command; all KARA-30 tests still green). Then run ruff check and format check on the touched files.

- [ ] **Step 5: Commit** `feat(time): add solidtime project/task write calls and exact project match (KARA-220)`

---

### Task 2: Sync service (`ensure_project`, `sync_issue_task`, `reconcile_project`, identifier rename)

**Files:**

- Create: `apps/api/plane/utils/solidtime/sync.py` (re-export the public names from `plane/utils/solidtime/__init__.py`)
- Test: `apps/api/plane/tests/unit/utils/test_solidtime_sync.py`

**Interfaces:**

- Consumes: Task 1 client methods; KARA-30 `find_project`, `find_task`, `task_name`, `task_prefix`, `_find_or_create_task`.
- Produces (`plane_project` has `.identifier` and `.name`; `issue` has `.name`, `.sequence_id` and `.project`):
  - `sync_enabled() -> bool`: True when `settings.SOLIDTIME_SYNC_ENABLED` is truthy and `SOLIDTIME_SYNC_WORKSPACE_SLUG` is non-blank.
  - `get_sync_client() -> SolidtimeClient | None`: None unless `sync_enabled()`; otherwise `SolidtimeClient.from_settings()`.
  - `ensure_project(client, plane_project) -> dict`: `find_project(client.list_projects(), plane_project)`. If nothing matches, `client.create_project(plane_project.identifier, client_id=settings.SOLIDTIME_DEFAULT_CLIENT_ID or None)`.
  - `sync_issue_task(client, issue) -> str`: returns `"created" | "renamed" | "unchanged"`.
    - It calls `ensure_project`, then finds the task by prefix.
    - Missing task → `_find_or_create_task` (keeps the 422 re-list). Name differs from `task_name(issue)` → `update_task`. Otherwise it makes no write.
  - `reconcile_project(client, plane_project, issues, *, dry_run=False, pause_seconds=0.0, sleep=time.sleep) -> dict` returns `{"project": "existing"|"created"|"would_create", "created": int, "renamed": int, "unchanged": int, "errors": int}`.
    - It calls `list_tasks` **once** and diffs in memory.
    - With `dry_run`, it makes no write call; when the project is missing, every issue counts as `created`.
    - A `SolidtimeError` on one write increments `errors` and the loop continues.
    - It calls `sleep(pause_seconds)` after each write when `pause_seconds > 0`.
  - `rename_project_identifier(client, plane_project, old_identifier: str) -> dict` returns `{"project_renamed": bool, "tasks_renamed": int, "errors": int}`.
    - Project step:
      - If `find_project` already matches the new identifier or name, use that project.
      - Otherwise, if a project is named exactly `old_identifier`, call `update_project(id, name=plane_project.identifier)` and set `project_renamed=True`.
      - Otherwise call `ensure_project`.
    - Task step: rename every task in that project matching `^\[{re.escape(old)}-(\d+)\]` to `[NEW-\1]` + the rest of the name, truncated to 255. Each rename failure counts as one error.

- [ ] **Step 1: Write failing tests** (`@pytest.mark.unit`). Use `SimpleNamespace` projects and issues, a `MagicMock(spec=SolidtimeClient)` client, and the `settings` fixture for sync flags.
  - `test_sync_enabled_requires_flag_and_slug`: parametrized over (False,"kara-digital")→False, (True,"")→False, (True,"kara-digital")→True. `get_sync_client()` is None when disabled, even with KARA-30 settings set.
  - `test_ensure_project_reuses_name_match`: Plane `SAND`/"Sandbox" with solidtime "Sandbox" → `create_project` is not called.
  - `test_ensure_project_creates_identifier_with_default_client`: with `settings.SOLIDTIME_DEFAULT_CLIENT_ID="c1"` and no match → `create_project("NEWP", client_id="c1")`.
  - `test_sync_issue_task_creates_missing_task`: → `"created"`, `create_task("p1", "[KARA-30] Title")`. A 300-char title → the created name has length 255.
  - `test_sync_issue_task_renames_stale_task`: task `[KARA-30] Old` → `update_task("t1", "[KARA-30] Title")` and returns `"renamed"`.
  - `test_sync_issue_task_unchanged_makes_no_writes`: `create_task`, `update_task` and `create_project` are not called, and it returns `"unchanged"`.
  - `test_sync_issue_task_prefix_never_collides`: an existing `[KARA-3] X` and issue seq 30 → creates `[KARA-30] …`.
  - `test_sync_issue_task_reuses_after_duplicate_422`: `list_tasks` returns `[]` then `[task]`, and `create_task` raises `invalid_request` → `"created"` path with no exception.
  - `test_reconcile_lists_tasks_once_and_counts`: 3 issues (one missing, one stale, one current) → `list_tasks.call_count == 1`, and the stats are `created=1, renamed=1, unchanged=1, errors=0, project="existing"`.
  - `test_reconcile_dry_run_makes_no_writes`: same data with `dry_run=True` → same counts, and none of `create_task`, `update_task`, `create_project` is called. With no project → `project="would_create"`, `created == len(issues)`, and `list_tasks` is not called.
  - `test_reconcile_counts_errors_and_continues`: `update_task` raises `unavailable` for the first stale task → `errors=1`, and the second stale task is still renamed.
  - `test_reconcile_pauses_between_writes`: 2 writes with `pause_seconds=0.3` and a fake `sleep` → `sleep` called twice with `0.3`. With no writes → not called.
  - `test_identifier_rename_renames_project_and_tasks`: solidtime project `KARA` with tasks `[KARA-1] A`, `[KARA-12] B` and `[KARAX-1] keep`; Plane identifier is now `KARX`. → `update_project("p1", name="KARX")`, `update_task` for `[KARX-1] A` and `[KARX-12] B` only, and `{"project_renamed": True, "tasks_renamed": 2, "errors": 0}`.
  - `test_identifier_rename_keeps_name_matched_project`: Plane `SAND`→`SNDX`, name "Sandbox", solidtime project "Sandbox" → `update_project` is not called, and the tasks are renamed.
  - `test_identifier_rename_counts_collisions`: one `update_task` raises `invalid_request` → `errors=1`, and the others are renamed.

- [ ] **Step 2: Run, expect FAIL**
      Run: `docker compose -f docker-compose-test.yml run --rm api-tests pytest plane/tests/unit/utils/test_solidtime_sync.py -v`
      Expected: collection ImportError.

- [ ] **Step 3: Implement `sync.py`** to the interfaces above.

- [ ] **Step 4: Run, expect PASS.** Run the three solidtime unit files together, then ruff.

- [ ] **Step 5: Commit** `feat(time): add solidtime project and task sync service (KARA-220)`

---

### Task 3: Celery tasks, scope queries and daily beat

**Files:**

- Create: `apps/api/plane/bgtasks/solidtime_sync_task.py`
- Modify: `apps/api/plane/celery.py` (add a `beat_schedule` entry)
- Test: `apps/api/plane/tests/unit/bg_tasks/test_solidtime_sync_task.py`

**Interfaces:**

- Consumes: Task 2 `get_sync_client`, `sync_issue_task`, `ensure_project`, `rename_project_identifier`, `reconcile_project`.
- Produces:
  - `projects_for_sync() -> QuerySet[Project]`: `Project.objects.filter(workspace__slug=settings.SOLIDTIME_SYNC_WORKSPACE_SLUG, archived_at__isnull=True)`.
  - `issues_for_sync(project) -> QuerySet[Issue]`: `Issue.objects.filter(project=project, is_draft=False).select_related("project")`. `Issue.objects` already excludes soft-deleted rows; archived and triage issues are included.
  - `@shared_task(bind=True, max_retries=5) sync_issue_to_solidtime(self, issue_id: str) -> str | None`:
    - Returns None (no client calls) when there is no sync client, or when the issue is missing, a draft, soft-deleted, or outside the workspace slug.
    - Otherwise returns `sync_issue_task(...)`.
    - `SolidtimeError("unavailable")` → `raise self.retry(exc=e, countdown=60 * 2 ** self.request.retries)`. Any other `SolidtimeError` → `log_exception(e, warning=True)`, return None.
  - `@shared_task(bind=True, max_retries=5) sync_project_to_solidtime(self, project_id: str, old_identifier: str | None = None) -> dict | None`:
    - Calls `rename_project_identifier` when `old_identifier` differs from the current identifier; otherwise `ensure_project`.
    - Has the same scope checks (archived or other-workspace projects → None) and the same retry rule.
  - `@shared_task reconcile_solidtime(project_identifier: str | None = None, dry_run: bool = False, pause_seconds: float = 0.3) -> dict[str, dict]`:
    - Keyed by project identifier. Uses `reconcile_project(client, p, list(issues_for_sync(p)), ...)`.
    - A `SolidtimeError` on a whole project is recorded as `{"error": e.message}` for that key, and the loop continues.
    - Returns `{}` when there is no sync client.
  - Beat entry `"solidtime-reconcile-daily": {"task": "plane.bgtasks.solidtime_sync_task.reconcile_solidtime", "schedule": crontab(hour=20, minute=0)}  # UTC 20:00 = 03:00 WIB`.

- [ ] **Step 1: Write failing tests** (`@pytest.mark.unit`, `@pytest.mark.django_db`).
  - Use the `workspace`/`create_user` fixtures from `plane/tests/conftest.py` and a project with identifier `SP`, following `test_issue_solidtime_app.py`.
  - Patch `plane.bgtasks.solidtime_sync_task.get_sync_client` to return a `MagicMock`.
  - Set `settings.SOLIDTIME_SYNC_WORKSPACE_SLUG = workspace.slug`.

  Tests:
  - `test_issues_for_sync_scope`:
    - Included: a normal issue, an archived issue (`archived_at` set), and an issue in a triage state.
    - Excluded: an `is_draft=True` issue and a soft-deleted issue (`issue.delete()`).
  - `test_projects_for_sync_scope`: other-workspace and archived projects are excluded.
  - `test_sync_issue_task_runs_sync`: calling `sync_issue_to_solidtime.run(str(issue.id))` calls `sync_issue_task` with that issue.
  - `test_sync_issue_skips_other_workspace`: with the slug set to `"other"`, `sync_issue_task` is not called.
  - `test_sync_issue_skips_when_disabled`: `get_sync_client` returns None → returns None, and `sync_issue_task` is not called.
  - `test_unavailable_retries_with_backoff`: `sync_issue_task` raises `SolidtimeError("unavailable","x")`, and `mocker.patch.object(sync_issue_to_solidtime, "retry", side_effect=Retry())` is in place. `.run()` raises `Retry`, and `retry` is called with `countdown=60`.
  - `test_invalid_request_is_logged_not_retried`: raises `invalid_request` → returns None, `retry` is not called, and `log_exception` is called once.
  - `test_project_task_renames_on_identifier_change`: `sync_project_to_solidtime.run(str(project.id), old_identifier="OLD")` calls `rename_project_identifier(client, project, "OLD")`. Without `old_identifier` it calls `ensure_project`.
  - `test_reconcile_solidtime_collects_stats_and_errors`: two projects. `reconcile_project` returns stats for the first and raises `SolidtimeError("unavailable","down")` for the second → the result has both keys, the second being `{"error": "down"}`. With `project_identifier="SP"` only `SP` is reconciled.
  - `test_beat_schedule_has_daily_reconcile`: `plane.celery.app.conf.beat_schedule["solidtime-reconcile-daily"]` has task `plane.bgtasks.solidtime_sync_task.reconcile_solidtime` and schedule `crontab(hour=20, minute=0)`.

- [ ] **Step 2: Run, expect FAIL**
      Run: `docker compose -f docker-compose-test.yml run --rm api-tests pytest plane/tests/unit/bg_tasks/test_solidtime_sync_task.py -v`

- [ ] **Step 3: Implement** the task module and the beat entry.

- [ ] **Step 4: Run, expect PASS**, then ruff.

- [ ] **Step 5: Commit** `feat(time): add solidtime sync Celery tasks and daily reconcile (KARA-220)`

---

### Task 4: Signals on Issue and Project

**Files:**

- Modify: `apps/api/plane/db/models/issue.py:105`: `TRACKED_FIELDS = ["state_id", "name", "project_id", "sequence_id", "is_draft"]`
- Modify: `apps/api/plane/db/models/project.py:68`: `class Project(ChangeTrackerMixin, BaseModel)` with `TRACKED_FIELDS = ["identifier"]`. Import `ChangeTrackerMixin` from `plane.db.mixins`.
- Create: `apps/api/plane/utils/solidtime/signals.py`
- Modify: `apps/api/plane/db/apps.py`: add `ready()` that imports `plane.utils.solidtime.signals` (noqa F401)
- Test: `apps/api/plane/tests/unit/bg_tasks/test_solidtime_sync_signals.py`

**Interfaces:**

- Consumes: Task 2 `sync_enabled`; Task 3 `sync_issue_to_solidtime`, `sync_project_to_solidtime` (imported inside the receivers to avoid import cycles).
- Produces:
  - `ISSUE_SYNC_FIELDS = {"name", "project_id", "sequence_id", "is_draft"}`
  - `@receiver(post_save, sender=Issue) enqueue_issue_sync(sender, instance, created, **kwargs)`:
    - Returns if `not sync_enabled()`, if `instance.is_draft`, or if `instance.deleted_at`.
    - Enqueues when `created` or `set(getattr(instance, "_changes_on_save", [])) & ISSUE_SYNC_FIELDS`, using `transaction.on_commit(lambda: sync_issue_to_solidtime.delay(str(instance.id)))`.
  - `@receiver(post_save, sender=Project) enqueue_project_sync(sender, instance, created, **kwargs)`:
    - Returns if `not sync_enabled()`.
    - `created` → `delay(str(id))`.
    - `"identifier" in _changes_on_save` → `delay(str(id), old_identifier=instance.old_values["identifier"])`, inside `on_commit`.

- [ ] **Step 1: Write failing tests** (`@pytest.mark.unit`, `@pytest.mark.django_db`).
  - Setup:
    - `settings.SOLIDTIME_SYNC_ENABLED = True` and `settings.SOLIDTIME_SYNC_WORKSPACE_SLUG = workspace.slug`.
    - Patch `plane.bgtasks.solidtime_sync_task.sync_issue_to_solidtime.delay` and `…sync_project_to_solidtime.delay`.
    - Wrap each save in `django_capture_on_commit_callbacks(execute=True)`.
  - Tests:
    - `test_issue_create_enqueues`: creating an issue → `delay(str(issue.id))` once.
    - `test_issue_rename_enqueues`: reload the issue, set `name`, save → called once.
    - `test_state_or_sort_order_save_does_not_enqueue`: reload, change `sort_order` and `state` to another state, save → not called.
    - `test_publishing_draft_enqueues_and_draft_create_does_not`: create with `is_draft=True` → not called. Set `is_draft=False` and save → called.
    - `test_disabled_sync_enqueues_nothing`: `SOLIDTIME_SYNC_ENABLED=False` → creating and renaming do not call `delay`.
    - `test_rolled_back_create_enqueues_nothing`: create the issue inside `transaction.atomic()` that raises and is caught, inside `django_capture_on_commit_callbacks(execute=True)` → `delay` is not called.
    - `test_project_create_enqueues` → `sync_project_to_solidtime.delay(str(project.id))`.
    - `test_project_identifier_change_passes_old_identifier`: reload, set `identifier="NEWI"`, save → `delay(str(project.id), old_identifier="SP")`.
    - `test_project_other_field_change_does_not_enqueue`: change `name` only → not called.
  - Also run `plane/tests/unit/models` (for the `TRACKED_FIELDS` change) and the KARA-30 contract tests, to prove no regression.

- [ ] **Step 2: Run, expect FAIL**
      Run: `docker compose -f docker-compose-test.yml run --rm api-tests pytest plane/tests/unit/bg_tasks/test_solidtime_sync_signals.py -v`

- [ ] **Step 3: Implement** the tracked fields, the mixin on `Project`, `signals.py` and `DbConfig.ready()`.

- [ ] **Step 4: Run, expect PASS.** Then run all solidtime tests, `plane/tests/unit/models`, and `pytest -m "unit or contract" -q`. Compare failures with `master`: the pre-existing 429 rate-limit failures in `contract/api` are known (KARA-30 ledger), and any other new failure is a regression.

- [ ] **Step 5: Commit** `feat(time): sync work items and projects to solidtime on save (KARA-220)`

---

### Task 5: `solidtime_reconcile` command + deploy docs

**Files:**

- Create: `apps/api/plane/db/management/commands/solidtime_reconcile.py`
- Modify: `deployments/kara/docker-compose.yml` (`x-app-env`: `SOLIDTIME_SYNC_ENABLED: ${SOLIDTIME_SYNC_ENABLED:-0}`, `SOLIDTIME_SYNC_WORKSPACE_SLUG: ${SOLIDTIME_SYNC_WORKSPACE_SLUG:-}`, `SOLIDTIME_DEFAULT_CLIENT_ID: ${SOLIDTIME_DEFAULT_CLIENT_ID:-}`)
- Modify: `deployments/kara/README.md` (extend the "Time (solidtime) integration" section)
- Test: `apps/api/plane/tests/unit/bg_tasks/test_solidtime_reconcile_command.py`

**Interfaces:**

- Consumes: Task 3 `reconcile_solidtime` (called directly, not `.delay`).
- Produces: `python manage.py solidtime_reconcile [--project IDENT] [--dry-run] [--pause SECONDS]` (pause defaults to 0.3).
  - Output lines:
    - one per project: `"{IDENT}: project={project} created={n} renamed={n} unchanged={n} errors={n}"`, or `"{IDENT}: ERROR {message}"`;
    - then the total line `"Total: created=… renamed=… unchanged=… errors=…"`;
    - with `--dry-run`, a first line `"DRY RUN: no changes will be written"`.
  - With sync not configured, it prints `"solidtime sync is not enabled (SOLIDTIME_SYNC_ENABLED / SOLIDTIME_SYNC_WORKSPACE_SLUG / SOLIDTIME_*)"` and exits with code 1 (`CommandError`).
  - The flag check uses `get_sync_client() is None`.

- [ ] **Step 1: Write failing tests** (`@pytest.mark.unit`). Use `call_command` with a `StringIO` stdout and patch `reconcile_solidtime` / `get_sync_client`.
  - `test_command_prints_stats_and_total`: two projects, one with an error → both lines and a total that sums the numeric stats.
  - `test_command_passes_flags`: `--project KARA --dry-run --pause 0` → `reconcile_solidtime(project_identifier="KARA", dry_run=True, pause_seconds=0.0)` and the DRY RUN line.
  - `test_command_fails_when_not_configured` → `CommandError`.

- [ ] **Step 2: Run, expect FAIL**
      Run: `docker compose -f docker-compose-test.yml run --rm api-tests pytest plane/tests/unit/bg_tasks/test_solidtime_reconcile_command.py -v`

- [ ] **Step 3: Implement** the command, the compose env and the README.
  - The README must state:
    - the three new vars and what each does;
    - sync stays off until `SOLIDTIME_SYNC_ENABLED=1`;
    - the cutover order from `00-overview-cutover.md`: deploy disabled → stop bridge → `--dry-run` → real run → enable and restart api/worker/beat → E2E;
    - the token must belong to an owner/admin and **be long-lived**, with a line to record its expiry date (`SOLIDTIME_API_TOKEN expires: YYYY-MM-DD`);
    - the daily reconcile runs at UTC 20:00 (03:00 WIB);
    - deleting a work item never deletes its solidtime task.

- [ ] **Step 4: Run, expect PASS**, then all solidtime tests + ruff.

- [ ] **Step 5: Commit** `feat(time): add solidtime_reconcile command and sync docs (KARA-220)`

---

### Task 6: Local end-to-end check (needs the user)

Uses the local copies (Plane API `build-api-1` / worker `build-worker-1` / beat `build-beat-worker-1` on `apps/api/.env`, and solidtime on `127.0.0.1:8100`). It never touches production.

- [ ] **Step 1: Ask the user** to start local solidtime and add `SOLIDTIME_SYNC_ENABLED=1`, `SOLIDTIME_SYNC_WORKSPACE_SLUG=kara-digital` and `SOLIDTIME_DEFAULT_CLIENT_ID=8593681a-1042-4eb3-b068-0ef3b7099b3b` to `apps/api/.env`. Then recreate api/worker/beat: `docker compose -f build/docker-compose-local.yml -p build up -d --no-deps --no-build api worker beat-worker`. Celery does not autoreload.
- [ ] **Step 2:** `docker exec build-api-1 python manage.py solidtime_reconcile --dry-run`. Record the per-project output for the PR, and check that `WILL` maps to `WILL`, not `will`.
- [ ] **Step 3:** With the user's go-ahead (local copy only), run without `--dry-run`, then run `--dry-run` again: every project should show `created=0 renamed=0`.
- [ ] **Step 4:** In local Plane, create a work item in `SAND`, rename it, and create a throwaway project. Confirm the task and project appear in local solidtime, and confirm the worker logs show no token. Then remove the throwaway data with the user.

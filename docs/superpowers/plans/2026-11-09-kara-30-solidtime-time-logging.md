# KARA-30 Log Time to Solidtime from Plane — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From a Plane work item, a member can log time to Kara's solidtime (https://time.shrwt.id) and see the time already tracked on that work item, without opening the Time app.

**Architecture:** The Plane Django API proxies solidtime with one server-side admin API token. A small solidtime client and a matching service (`plane/utils/solidtime/`) map a Plane work item to a solidtime project and task, auto-creating the task if it is missing. One new issue-scoped endpoint exposes GET (summary + entries) and POST (log time). The web app adds a "Time tracked" row to the work item sidebar and the peek overview. The row opens a modal with the log form and the entry list. The token never reaches the browser.

**Tech Stack:** Django REST Framework, `requests`, pytest + pytest-mock (docker test stack); React, MobX `observer`, SWR, react-hook-form, `@plane/ui` / `@plane/propel`, `@plane/i18n`.

**Spec:** No separate spec document. The spec is work item KARA-30 ("Request to enable submit time in Plane, so that we don't need to open 2 tabs/platforms") plus these decisions, confirmed with the user on 2026-11-09:

1. **Auth:** one solidtime owner/admin API token in Plane's server env. Entries are created for the solidtime member whose email matches the Plane user's email.
2. **UI:** a manual log form (date, start time, duration, description) plus the total and the list of entries already logged on the work item. No start/stop timer.
3. **Missing task:** auto-create the task `[<IDENT>-<N>] <work item name>` in the solidtime project whose name equals the Plane project identifier. If no such project exists, return a clear error.
4. **Billable:** taken from the solidtime project's `is_billable`. The form has no checkbox.

Observed conventions in production solidtime data (local copy, DB `solidtime`): project names equal Plane project identifiers (`KARA`, `MARE`, `FIOS`…, except `Sandbox` for Plane `SAND`), and task names look like `[KARA-217] Deploy Plane from Code`.

Branch: `feature/KARA-30-solidtime-time-logging`

## Global Constraints

- Settings / env vars (same names as client-kara): `SOLIDTIME_BASE_URL`, `SOLIDTIME_API_TOKEN`, `SOLIDTIME_ORGANIZATION_ID`. The feature is "not configured" when any of them is blank.
- Solidtime API base: `{SOLIDTIME_BASE_URL}/api/v1/organizations/{SOLIDTIME_ORGANIZATION_ID}/…`, header `Authorization: Bearer {token}`, `Accept: application/json`.
- Solidtime datetimes are sent as UTC `%Y-%m-%dT%H:%M:%SZ` (e.g. `2026-11-09T02:00:00Z`).
- Task name: `f"[{project.identifier}-{issue.sequence_id}] {issue.name}"`, truncated to 255 chars. Task lookup matches the prefix `[{identifier}-{sequence_id}]` only.
- Duration: integer minutes, 1–1440. A start in the future is rejected.
- Only project ADMIN and MEMBER roles may read or log time. Guests get 403.
- The API token must never appear in any response, log line or frontend bundle.
- New files carry the same license header as their neighbours.
- Backend tests run in docker: `docker compose -f docker-compose-test.yml run --rm api-tests pytest <path> -v` from the repo root.
- `apps/web` has no unit-test runner. Frontend tasks are verified with `pnpm turbo run check:types check:lint --filter=web` and a manual run (Task 5). Do not add a test framework to `apps/web` for this.
- Locale edits: load the `translate` skill first. Add keys to `en` and `id` only; other locales fall back to `en`.

## Review Focus

1. **Plane user not in solidtime** (email differs, or the member is a placeholder): POST returns 400 `member_not_found` with the user's email in the message, and _nothing_ is created in solidtime, not even the task. Covered: Task 2 `test_log_time_member_not_found_creates_nothing`.
2. **Work item renamed after its task exists**, and prefix collisions: `[KARA-30] new title` must reuse the task named `[KARA-30] old title`, and `[KARA-3]` must never match `[KARA-30]`. Covered: Task 2 `test_find_task_matches_prefix_only`.
3. **Timezone:** a user in WIB enters 09:00 and the entry starts at `02:00:00Z`. The browser sends an offset-bearing ISO string and the server converts it. Covered: Task 3 `test_post_converts_offset_to_utc`.
4. **Solidtime down / timeout / bad token:** POST returns 502 `solidtime_unavailable` and the work item page still renders (the row hides on GET error). Covered: Task 1 `test_request_errors_raise_unavailable`, Task 3 `test_post_upstream_failure_returns_502`.
5. **Two people logging the first time on the same work item at once:** creating the task returns solidtime 422 (duplicate name). The service re-lists the tasks and reuses the existing one. Covered: Task 2 `test_log_time_reuses_task_after_duplicate_create`.

---

### Task 1: Solidtime HTTP client + settings

**Files:**

- Create: `apps/api/plane/utils/solidtime/__init__.py` (re-exports `SolidtimeClient`, `SolidtimeError`)
- Create: `apps/api/plane/utils/solidtime/client.py`
- Modify: `apps/api/plane/settings/common.py` (next to `UNSPLASH_ACCESS_KEY`, ~line 356)
- Modify: `apps/api/.env.example` (add the three vars, empty)
- Test: `apps/api/plane/tests/unit/utils/test_solidtime_client.py`

**Interfaces:**

- Produces:
  - `class SolidtimeError(Exception)` with `__init__(self, code: str, message: str)` and attributes `.code`, `.message`. Codes: `"not_configured" | "member_not_found" | "project_not_found" | "unavailable" | "invalid_request"`.
  - `class SolidtimeClient` with:
    - `__init__(self, base_url: str, api_token: str, organization_id: str, session: requests.Session | None = None, timeout: float = 10.0)`. It strips the trailing `/` from `base_url`.
    - `@classmethod from_settings(cls) -> "SolidtimeClient | None"`: returns None if any setting is blank.
    - `list_members() -> list[dict]`: `GET /members`, all pages.
    - `list_projects() -> list[dict]`: `GET /projects`, all pages.
    - `list_tasks(project_id: str) -> list[dict]`: `GET /tasks?project_id=…&done=all`, all pages.
    - `create_task(project_id: str, name: str) -> dict`: `POST /tasks`, returns `body["data"]`.
    - `list_task_time_entries(task_id: str) -> list[dict]`: `GET /time-entries?task_ids[]=…&limit=500`, returns `body["data"]`.
    - `create_time_entry(*, member_id: str, project_id: str, task_id: str, start: datetime, end: datetime, billable: bool, description: str | None) -> dict`: `POST /time-entries`, returns `body["data"]`.
- Paginated lists loop `page=1..` while `meta.current_page < meta.last_page` and concatenate `data`.
- Error mapping, in one private `_request(method, path, *, params=None, json=None) -> dict`:
  - `requests.RequestException`, status 401, 403 or ≥500 → `SolidtimeError("unavailable", …)`. Log with `plane.utils.exception_logger.log_exception`, never logging headers.
  - 422 → `SolidtimeError("invalid_request", body.get("message", …))`.

- [ ] **Step 1: Write the failing tests** using a `MagicMock()` session whose `.request` returns fake responses (`status_code`, `.json()`), marked `@pytest.mark.unit`:
  - `test_from_settings_returns_none_when_any_setting_blank` (use `settings` fixture; blank token → None; all three set → instance)
  - `test_sends_bearer_token_and_org_path`: assert `session.request` called with `"GET"`, `"https://time.example/api/v1/organizations/org-1/members"`, and headers containing `Authorization: "Bearer tok"`. Build the client with `base_url="https://time.example/"` to cover the trailing slash.
  - `test_list_members_follows_pagination`: page 1 `meta {current_page:1,last_page:2}` and page 2 → returns 2 combined rows; second call has `params["page"] == 2`.
  - `test_list_tasks_requests_all_done_states`: params include `project_id` and `done == "all"`.
  - `test_create_time_entry_formats_utc`: start `datetime(2026,11,9,9,0,tzinfo=ZoneInfo("Asia/Jakarta"))` → json `start == "2026-11-09T02:00:00Z"`; also asserts `member_id`, `project_id`, `task_id`, `billable`, `description`, `end`.
  - `test_request_errors_raise_unavailable`: parametrize over `requests.Timeout()` side effect, 401, 503 → `SolidtimeError` with `.code == "unavailable"`; assert `"tok"` not in `str(exc)`.
  - `test_422_raises_invalid_request_with_message`: body `{"message": "The name has already been taken."}` → code `invalid_request`, message equals it.

- [ ] **Step 2: Run, expect FAIL** (import error)
      Run: `docker compose -f docker-compose-test.yml run --rm api-tests pytest plane/tests/unit/utils/test_solidtime_client.py -v`

- [ ] **Step 3: Implement** `client.py` and `__init__.py`. Add to `common.py`: `SOLIDTIME_BASE_URL = os.environ.get("SOLIDTIME_BASE_URL", "")` and the same pattern for `SOLIDTIME_API_TOKEN` and `SOLIDTIME_ORGANIZATION_ID`. Add a one-line comment saying the token is an owner/admin solidtime API token. Add the empty vars to `.env.example`.

- [ ] **Step 4: Run, expect PASS** (same command)

- [ ] **Step 5: Commit**

```bash
git add apps/api/plane/utils/solidtime apps/api/plane/settings/common.py apps/api/.env.example apps/api/plane/tests/unit/utils/test_solidtime_client.py
git commit -m "feat(time): add solidtime API client (KARA-30)"
```

---

### Task 2: Work item ↔ solidtime matching service

**Files:**

- Create: `apps/api/plane/utils/solidtime/service.py` (re-export its public functions from `__init__.py`)
- Test: `apps/api/plane/tests/unit/utils/test_solidtime_service.py`

**Interfaces:**

- Consumes: `SolidtimeClient`, `SolidtimeError` (Task 1).
- Produces (the `issue` argument has `.name`, `.sequence_id`, and `.project.identifier` / `.project.name`; `user` has `.email`):
  - `task_prefix(issue) -> str`, e.g. `"[KARA-30]"`
  - `task_name(issue) -> str`, e.g. `"[KARA-30] Enable submit time in Plane"`, max 255 chars
  - `find_member(members: list[dict], email: str) -> dict | None`: case- and whitespace-insensitive email match; skips rows with `is_placeholder` true
  - `find_project(projects: list[dict], project) -> dict | None`: `name == project.identifier` (case-insensitive) first, then `name == project.name`
  - `find_task(tasks: list[dict], issue) -> dict | None`: `name.startswith(task_prefix(issue))`
  - `serialize_entry(entry: dict, member_names_by_user_id: dict[str, str]) -> dict` returning keys `id, start, end, duration, description, member_name, is_running` (`is_running = entry["end"] is None`)
  - `get_issue_time(client, issue) -> dict` returning `{"total_seconds": int, "entries": list[dict]}`. If there is no project or no task, it returns `{"total_seconds": 0, "entries": []}` and does not create anything. Entries are sorted by `start` descending. The total sums `duration` of non-running entries.
  - `log_issue_time(client, issue, user, start: datetime, duration_minutes: int, description: str | None) -> dict`, which returns a serialized entry. Order matters: (1) resolve the member, else raise `SolidtimeError("member_not_found", f"{user.email} is not a member of the Time organization")`. (2) Resolve the project, else raise `SolidtimeError("project_not_found", f"No Time project named {identifier}")`. (3) Find or create the task. If `create_task` raises `invalid_request`, re-list the tasks once and reuse the match, or re-raise. (4) Call `create_time_entry` with `end = start + timedelta(minutes=duration_minutes)` and `billable = project["is_billable"]`.

- [ ] **Step 1: Write the failing tests** (`@pytest.mark.unit`). Use `SimpleNamespace` stand-ins for issue, project and user. The fake client is a `MagicMock(spec=SolidtimeClient)`.
  - `test_task_name_and_prefix`: identifier `KARA`, seq 30 → `"[KARA-30]"`, `"[KARA-30] Enable submit time in Plane"`; a 300-char name → `len == 255`
  - `test_find_task_matches_prefix_only`: tasks `["[KARA-3] Other", "[KARA-30] Old title"]` → returns the second for seq 30; seq 31 → None
  - `test_find_member_ignores_case_and_placeholders`: `" Akmal@KaraDigital.co "` matches `akmal@karadigital.co`; a placeholder row with the same email is skipped
  - `test_find_project_prefers_identifier_then_name`: Plane `SAND`/`Sandbox` matches solidtime `Sandbox`; `KARA` matches `KARA` even if a project named after `project.name` also exists
  - `test_get_issue_time_without_task_returns_empty_and_creates_nothing`: `client.create_task.assert_not_called()`
  - `test_get_issue_time_totals_and_sorts`: entries of 3600 s and 1800 s plus one running entry → `total_seconds == 5400`; first entry is the latest start; `member_name` resolved through `user_id`; running entry `is_running is True`
  - `test_log_time_creates_missing_task_then_entry`: no task → `create_task(project_id, "[KARA-30] Enable submit time in Plane")`; `create_time_entry` gets `billable=True` (from project), `end - start == timedelta(minutes=90)`
  - `test_log_time_member_not_found_creates_nothing`: raises code `member_not_found`; `create_task` and `create_time_entry` not called
  - `test_log_time_project_not_found`: code `project_not_found`
  - `test_log_time_reuses_task_after_duplicate_create`: `list_tasks` returns `[]` then `[task]`; `create_task` raises `SolidtimeError("invalid_request", …)` → entry created with the existing task's id

- [ ] **Step 2: Run, expect FAIL**
      Run: `docker compose -f docker-compose-test.yml run --rm api-tests pytest plane/tests/unit/utils/test_solidtime_service.py -v`

- [ ] **Step 3: Implement `service.py`** to the interfaces above.

- [ ] **Step 4: Run both solidtime unit test files, expect PASS**
      Run: `docker compose -f docker-compose-test.yml run --rm api-tests pytest plane/tests/unit/utils/test_solidtime_client.py plane/tests/unit/utils/test_solidtime_service.py -v`

- [ ] **Step 5: Commit**

```bash
git add apps/api/plane/utils/solidtime apps/api/plane/tests/unit/utils/test_solidtime_service.py
git commit -m "feat(time): map Plane work items to solidtime tasks (KARA-30)"
```

---

### Task 3: Issue time-entries endpoint + deployment config

**Files:**

- Create: `apps/api/plane/app/views/issue/solidtime.py`
- Modify: `apps/api/plane/app/views/__init__.py` (export the view)
- Modify: `apps/api/plane/app/urls/issue.py` (add path next to `issue-links`, ~line 110)
- Modify: `deployments/kara/docker-compose.yml` (`x-app-env` block, ~line 60: add `SOLIDTIME_BASE_URL: ${SOLIDTIME_BASE_URL:-}`, `SOLIDTIME_API_TOKEN: ${SOLIDTIME_API_TOKEN:-}`, `SOLIDTIME_ORGANIZATION_ID: ${SOLIDTIME_ORGANIZATION_ID:-}`)
- Modify: `deployments/kara/README.md` (short "Time (solidtime) integration" section: the three vars, the token must belong to a solidtime owner/admin because it creates entries for other members, and the org id is the UUID in solidtime URLs)
- Test: `apps/api/plane/tests/contract/app/test_issue_solidtime_app.py`

**Interfaces:**

- Consumes: `SolidtimeClient.from_settings`, `SolidtimeError`, `get_issue_time`, `log_issue_time` (Tasks 1–2).
- Produces: `IssueSolidtimeTimeEntryEndpoint(BaseAPIView)` at `workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/solidtime-time-entries/`, URL name `project-issue-solidtime-time-entries`. Both methods are decorated `@allow_permission([ROLE.ADMIN, ROLE.MEMBER])`. The issue is loaded with `Issue.objects.select_related("project").get(workspace__slug=slug, project_id=project_id, pk=issue_id)`; it returns 404 if missing.
  - `GET` → 200 `{"configured": false}` when `from_settings()` is None; otherwise 200 `{"configured": true, **get_issue_time(...)}`.
  - `POST` body: `start` (ISO 8601 with offset), `duration_minutes` (int 1–1440), `description` (optional, blank allowed, max 5000). Validate with a local `serializers.Serializer`. A start later than `timezone.now()` → 400 `{"start": [...]}`. Success → 201 with the serialized entry.
  - Error responses `{"error": message, "code": code}`: not configured → 503 `solidtime_not_configured`; `member_not_found` / `project_not_found` / `invalid_request` → 400 with that code; `unavailable` → 502 `solidtime_unavailable`. A `SolidtimeError` raised during GET returns the same mapping.

- [ ] **Step 1: Write the failing contract tests** (`@pytest.mark.contract`, `@pytest.mark.django_db`). Use the project/guest fixture pattern from `plane/tests/contract/app/test_issue_list_guest_scope_app.py`: project identifier `SP`, the issue named `Fix login`, created with `issue.save(created_by_id=...)`. Patch `plane.app.views.issue.solidtime.SolidtimeClient.from_settings` with `mocker`. Patch `log_issue_time` / `get_issue_time` where a test only checks HTTP mapping.
  - `test_get_not_configured_returns_flag`: `from_settings` → None → 200, `{"configured": False}`
  - `test_get_returns_total_and_entries`: get_issue_time stub → 200, `configured True`, `total_seconds` passed through
  - `test_post_logs_time`: 201; `log_issue_time` called with the issue, the request user, `duration_minutes=90` and description `"Pairing"`
  - `test_post_converts_offset_to_utc`: start `"2025-01-06T09:00:00+07:00"` → the `start` passed to `log_issue_time` equals `datetime(2025,1,6,2,0,tzinfo=UTC)`. Use a fixed past date so the future-start check never trips.
  - `test_post_rejects_future_start`: start = now + 1 h → 400 with `"start"` key; `log_issue_time` not called
  - `test_post_rejects_bad_duration`: parametrize 0 and 1441 → 400
  - `test_post_member_not_found_returns_400`: `log_issue_time` raises `SolidtimeError("member_not_found", "x")` → 400, `code == "member_not_found"`
  - `test_post_upstream_failure_returns_502`: raises `unavailable` → 502, `code == "solidtime_unavailable"`
  - `test_post_not_configured_returns_503`
  - `test_guest_forbidden`: a project guest's GET and POST → 403

- [ ] **Step 2: Run, expect FAIL**
      Run: `docker compose -f docker-compose-test.yml run --rm api-tests pytest plane/tests/contract/app/test_issue_solidtime_app.py -v`

- [ ] **Step 3: Implement the view, export, URL, compose env, README section.**

- [ ] **Step 4: Run, expect PASS.** Then run the whole unit + contract suite to catch URL or import regressions:
      Run: `docker compose -f docker-compose-test.yml run --rm api-tests pytest -m "unit or contract" -q`
      Expected: all pass (compare the failure count against `master` if pre-existing failures show up).

- [ ] **Step 5: Commit**

```bash
git add apps/api/plane/app/views/issue/solidtime.py apps/api/plane/app/views/__init__.py apps/api/plane/app/urls/issue.py apps/api/plane/tests/contract/app/test_issue_solidtime_app.py deployments/kara/docker-compose.yml deployments/kara/README.md
git commit -m "feat(time): add work item endpoint to log time to solidtime (KARA-30)"
```

---

### Task 4: "Time tracked" row and log-time modal in the web app

**Files:**

- Create: `packages/types/src/issues/issue_solidtime.ts`; export it from `packages/types/src/issues/base.ts`
- Create: `apps/web/core/services/issue/issue_solidtime.service.ts`; export it from `apps/web/core/services/issue/index.ts`
- Create: `apps/web/core/components/issues/issue-detail/solidtime/root.tsx`
- Create: `apps/web/core/components/issues/issue-detail/solidtime/log-time-modal.tsx`
- Create: `apps/web/core/components/issues/issue-detail/solidtime/index.ts`
- Modify: `apps/web/core/components/issues/issue-detail/sidebar.tsx` (after the Labels row, ~line 250)
- Modify: `apps/web/core/components/issues/peek-overview/properties.tsx` (after the Labels row, ~line 245)
- Modify: `packages/i18n/src/locales/en/work-item.json`, `packages/i18n/src/locales/id/work-item.json` (under `issue.solidtime`)

**Interfaces:**

- Consumes: the Task 3 endpoint `…/issues/<issue_id>/solidtime-time-entries/` and its JSON shapes.
- Produces:
  - Types:
    ```ts
    export type TSolidtimeTimeEntry = {
      id: string;
      start: string;
      end: string | null;
      duration: number;
      description: string | null;
      member_name: string | null;
      is_running: boolean;
    };
    export type TIssueSolidtimeTime =
      | { configured: false }
      | { configured: true; total_seconds: number; entries: TSolidtimeTimeEntry[] };
    export type TSolidtimeTimeEntryCreate = { start: string; duration_minutes: number; description?: string };
    ```
  - `class IssueSolidtimeService extends APIService` (pattern: `issue_relation.service.ts`) with `getIssueTime(workspaceSlug, projectId, issueId): Promise<TIssueSolidtimeTime>` and `logTime(workspaceSlug, projectId, issueId, data: TSolidtimeTimeEntryCreate): Promise<TSolidtimeTimeEntry>`. Both rethrow `error?.response?.data`.
  - `IssueSolidtimeProperty` (observer) with props `{ workspaceSlug: string; projectId: string; issueId: string; disabled: boolean }`. It fetches with `useSWR(\`ISSUE*SOLIDTIME_TIME*${issueId}\`, …)`and **returns`null`unless`data?.configured`**. This hides the row for guests (403), on errors and on non-Kara deployments. It renders a `SidebarPropertyListItem`with icon`Timer`from`lucide-react`, label `t("issue.solidtime.label")`, and a button showing the total (`convertMinutesToHoursMinutesString(Math.floor(total_seconds / 60))`from`@plane/utils`, or `"0m"` when empty). The button opens the modal.
  - `IssueSolidtimeLogTimeModal` with props `{ isOpen: boolean; onClose: () => void; workspaceSlug: string; projectId: string; issueId: string; data: Extract<TIssueSolidtimeTime, { configured: true }>; disabled: boolean; onLogged: () => void }`, built with `ModalCore` + react-hook-form (pattern: `issue-detail/links/create-update-link-modal.tsx`). Fields:
    - date (`type="date"`, default today)
    - start time (`type="time"`, default now − 1 h, rounded down to 15 min)
    - hours (default 1) and minutes (default 0)
    - description (optional)

    Submit sends `start: new Date(\`${date}T${time}\`).toISOString()`and`duration_minutes = hours\*60 + minutes`. The client-side checks mirror the server: total 1–1440 and start not in the future. On success it shows a success toast, calls `onLogged()`(SWR`mutate`) and resets the form. On error it shows an error toast with `error?.error ?? t("issue.solidtime.errors.generic")`. Below the form it lists `data.entries`: member name, local date/time, duration, description, and a "running" badge if `is_running`. If there are none, it shows `t("issue.solidtime.no_entries")`. When `disabled` is true, the form is hidden and only the list shows.

  - i18n keys under `issue.solidtime`:
    - `label` "Time tracked"
    - `log_time` "Log time"
    - `modal_title` "Time tracking"
    - `date` "Date"
    - `start_time` "Start time"
    - `hours` "Hours"
    - `minutes` "Minutes"
    - `description` "Description"
    - `description_placeholder` "What did you work on?"
    - `submit` "Submit to Time"
    - `success` "Time logged to Time"
    - `no_entries` "No time logged on this work item yet."
    - `running` "Running"
    - `errors.future` "Start time can't be in the future"
    - `errors.duration` "Duration must be between 1 minute and 24 hours"
    - `errors.generic` "Couldn't log time. Please try again."

    Translate all of them into `id`.

- [ ] **Step 1: Add the types, service and i18n keys** (load the `translate` skill before editing locales). Run `pnpm turbo run check:types --filter=@plane/types`; expect PASS.

- [ ] **Step 2: Build `root.tsx`, `log-time-modal.tsx` and `index.ts`, and add `<IssueSolidtimeProperty … disabled={disabled} />` to both sidebars.**

- [ ] **Step 3: Verify types, lint and format**
      Run: `pnpm turbo run check:types check:lint check:format --filter=web --filter=@plane/types --filter=@plane/i18n`
      Expected: PASS (`pnpm fix:format` first if only formatting fails).

- [ ] **Step 4: Commit**

```bash
git add packages/types/src/issues packages/i18n/src/locales/en/work-item.json packages/i18n/src/locales/id/work-item.json apps/web/core/services/issue apps/web/core/components/issues/issue-detail/solidtime apps/web/core/components/issues/issue-detail/sidebar.tsx apps/web/core/components/issues/peek-overview/properties.tsx
git commit -m "feat(time): log time to solidtime from the work item sidebar (KARA-30)"
```

---

### Task 5: End-to-end check in the running app

Do not log test entries against production `time.shrwt.id` without asking the user first. Prefer a local solidtime (`/Users/karadigital/Documents/projects/solidtime`, `docker compose up`) with an org, an admin API token, a project named after a local Plane project identifier, and a member whose email matches your Plane user.

- [ ] **Step 1:** Set the three `SOLIDTIME_*` vars in `apps/api/.env`, start Plane (`pnpm dev` plus the API), and open a work item as a project member.
- [ ] **Step 2:** Confirm the "Time tracked" row shows `0m`. Log 1 h 30 m with a description. Confirm the success toast, that the total becomes `1h 30m`, and that the entry appears in the modal list. In solidtime, confirm that the task `[<IDENT>-<N>] <name>` was created and the entry has the right local start time and billable flag.
- [ ] **Step 3:** Rename the work item, log again, and confirm no second task was created in solidtime.
- [ ] **Step 4:** Log in as a user whose email is not in solidtime and confirm the error toast names the email. Open the work item as a guest and confirm the row is hidden. Blank the token, restart the API, and confirm the row is hidden for everyone.
- [ ] **Step 5:** Open the same work item in the peek overview and confirm the row works there too.

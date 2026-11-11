# KARA-219: Time per work item in the public API — Implementation Plan

**Goal:** client-kara (which uses Plane's public API with an `X-API-Key`) can show the hours logged per
work item. Plane reads them from solidtime; nothing is stored in Plane.

**Decisions (from the team):** internal use, so no data hiding is needed; only the total per work item;
count every finished time entry on a task linked to a Plane work item (`[IDENT-N] …`), billable or not.

**Architecture:**

- One project-level endpoint, so client-kara needs one request per project.
- Plane makes two or three solidtime calls per request:
  - the projects list (already cached 60 s);
  - `GET /time-entries/aggregate?group=task&project_ids[]=…`, which sums seconds per task inside solidtime;
  - the project's task list, only when the aggregate has any time.
- Task names map back to Plane sequence ids. The result is cached 60 s per Plane project to stay inside
  solidtime's limit of 200 requests per minute, which every Plane user shares through the one admin token.

**Tech stack:** Django/DRF public API (`plane.api`, `APIKeyAuthentication`, `ProjectEntityPermission`),
the existing `plane.utils.solidtime` client and service, and pytest with unit and contract tests.

**Branch:** `feature/KARA-219-solidtime-time-summary`, stacked on `feature/KARA-220-solidtime-sync`.

## API contract

`GET /api/v1/workspaces/{slug}/projects/{project_id}/time-summary/`

- **Auth:** `X-API-Key`. The key's user must be a member of the project (`ProjectEntityPermission`, safe method).
- **200, configured:**
  `{"configured": true, "total_seconds": 5400, "work_items": [{"id": "<uuid>", "sequence_id": 12, "seconds": 5400}]}`
  - `work_items` lists only work items with time > 0, sorted by `sequence_id`. Missing means 0.
  - A work item with more than one `[IDENT-N]` task in solidtime gets the sum of all of them.
  - Running timers are not counted, the same as the KARA-30 panel.
- **200, solidtime not configured on the server:** `{"configured": false, "total_seconds": 0, "work_items": []}`.
- **404:** the project is not in the workspace.
- **502:** `{"error": "...", "code": "solidtime_unavailable"}` when solidtime is down, rate-limited or rejects the token.
- **Freshness:** results can be up to 60 s old.

## Task 1: Client — `aggregate_seconds_by_task(project_id)`

**Files:**

- `apps/api/plane/utils/solidtime/client.py`
- `apps/api/plane/tests/unit/utils/test_solidtime_client.py`

**Test first:** `test_aggregate_seconds_by_task_groups_by_task`

- Expects `GET {BASE}/time-entries/aggregate` with params `{"group": "task", "project_ids[]": "p1"}`.
- Response `{"data": {"seconds": 900, "grouped_data": [{"key": "t1", "seconds": 600}, {"key": null, "seconds": 300}]}}`
  returns `{"t1": 600}`, so entries without a task are dropped.

**Implement:** one `_request` call; read `data.grouped_data`, skip a null `key`, and cast to int.

**Verify:** run `pytest plane/tests/unit/utils/test_solidtime_client.py`.

## Task 2: Service — `project_time_by_sequence(client, plane_project) -> dict[int, int]`

**Files:**

- `apps/api/plane/utils/solidtime/service.py`
- `apps/api/plane/utils/solidtime/__init__.py`
- `apps/api/plane/tests/unit/utils/test_solidtime_service.py`

**Tests first:**

- No solidtime project gives `{}`, and tasks are not listed.
- An aggregate with no time gives `{}`, and tasks are not listed.
- `[SP-1] A` (600) and a duplicate `[SP-1] A old` (60) sum to `{1: 660}`.
- `[SP-10] B` maps to 10 and not to 1.
- Tasks named `[OLD-3] …`, `no prefix`, or with no time are ignored.

**Implement:**

- `find_project`, then `aggregate_seconds_by_task`; return early when it is empty.
- Then `list_tasks`, matching `^\[{re.escape(identifier)}-(\d+)\]`.

**Verify:** run `pytest plane/tests/unit/utils/test_solidtime_service.py`.

## Task 3: Public API endpoint

**Files:**

- `apps/api/plane/api/views/solidtime.py`
- `apps/api/plane/api/urls/solidtime.py`
- `apps/api/plane/api/urls/__init__.py`
- `apps/api/plane/tests/contract/api/test_solidtime_time_summary.py`

**Tests first (contract, `api_key_client`):**

- Not configured: `configured: false`.
- Configured: response shape, total, only existing non-draft work items, sorted.
- Cached: the second request makes no solidtime call.
- Unavailable: 502 `solidtime_unavailable`, and the token is not in the body.
- Not a project member: 403.
- Unknown project: 404.

**Implement:**

- A `BaseAPIView` with `ProjectEntityPermission` and the `work_item_docs` OpenAPI decorator.
- Cache key `solidtime:time-summary:{project.id}:{project.identifier}`, holding the sequence → seconds map, 60 s.
- Map sequence ids to work item ids with
  `Issue.objects.filter(project=project, is_draft=False, sequence_id__in=…)`.

**Verify:** run `pytest plane/tests/contract/api/test_solidtime_time_summary.py`, then the solidtime unit tests.

## Task 4: Docs

- `deployments/kara/README.md`: describe the endpoint and its response, and that it needs the KARA-30 solidtime env
  vars, with no new ones.
- client-kara plan: `client-kara/docs/superpowers/plans/2026-11-11-kara-219-time-tracking.md`. It is written
  for that repo's team, and its code is not changed here.

## Review Focus

- The identifier regex must not let `[SP-1]` match `[SP-10]`.
- Identifiers with regex characters must be escaped.
- The cache key must change when the identifier changes.
- A cached empty result must not hide a real outage: errors are never cached.
- The permission must stop API keys of users who are not members of the project.

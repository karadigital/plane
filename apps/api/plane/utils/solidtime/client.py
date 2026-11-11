# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""HTTP client for the solidtime time tracker (Kara's "Time" app)."""

# Python imports
from datetime import datetime, timezone

# Third party imports
import requests

# Django imports
from django.conf import settings
from django.core.cache import cache

# Module imports
from plane.utils.exception_logger import log_exception

SOLIDTIME_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
TIME_ENTRIES_LIMIT = 500
# Members and projects change rarely; caching them keeps Plane well inside
# solidtime's per-user API rate limit, which every Plane user shares through
# the one admin token.
LOOKUP_CACHE_SECONDS = 60
# Colour for projects Plane creates in solidtime (the old bridge used the same).
PROJECT_COLOR = "#6366f1"
# solidtime's ProjectController::update overwrites these from the request (client_id and
# billable_rate are nulled when missing), so every PUT must resend their current values.
PROJECT_UPDATE_FIELDS = ("name", "color", "is_billable", "is_public", "client_id", "billable_rate")


class SolidtimeError(Exception):
    """A solidtime failure the API can report to the user.

    ``code`` is one of: not_configured, member_not_found, project_not_found,
    unavailable, invalid_request.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime(SOLIDTIME_DATETIME_FORMAT)


class SolidtimeClient:
    def __init__(
        self,
        base_url: str,
        api_token: str,
        organization_id: str,
        session: requests.Session | None = None,
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.organization_id = organization_id
        self.session = session or requests.Session()
        self.timeout = timeout

    @classmethod
    def from_settings(cls) -> "SolidtimeClient | None":
        base_url = getattr(settings, "SOLIDTIME_BASE_URL", "")
        api_token = getattr(settings, "SOLIDTIME_API_TOKEN", "")
        organization_id = getattr(settings, "SOLIDTIME_ORGANIZATION_ID", "")
        if not (base_url and api_token and organization_id):
            return None
        return cls(base_url, api_token, organization_id)

    def _request(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> dict:
        url = f"{self.base_url}/api/v1/organizations/{self.organization_id}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }
        try:
            response = self.session.request(
                method, url, headers=headers, params=params, json=json, timeout=self.timeout
            )
        except requests.RequestException as e:
            log_exception(e, warning=True)
            raise SolidtimeError("unavailable", "Could not reach the Time app. Please try again later.") from e

        if response.status_code in (401, 403, 429) or response.status_code >= 500:
            log_exception(
                Exception(f"solidtime {method} {path} returned HTTP {response.status_code}"),
                warning=True,
            )
            raise SolidtimeError("unavailable", "The Time app rejected the request. Please contact an admin.")

        try:
            body = response.json()
        except ValueError:
            body = {}

        if response.status_code >= 400:
            message = body.get("message") if isinstance(body, dict) else None
            raise SolidtimeError("invalid_request", message or "The Time app rejected the request.")

        return body

    def _list_all_pages(self, path: str, params: dict | None = None) -> list[dict]:
        rows: list[dict] = []
        page = 1
        while True:
            body = self._request("GET", path, params={**(params or {}), "page": page})
            rows.extend(body.get("data", []))
            meta = body.get("meta") or {}
            if meta.get("current_page", page) >= meta.get("last_page", page):
                return rows
            page += 1

    def _cache_key(self, name: str) -> str:
        return f"solidtime:{self.organization_id}:{name}"

    def invalidate_projects_cache(self) -> None:
        cache.delete(self._cache_key("projects"))

    def _cached(self, name: str, fetch) -> list[dict]:
        key = self._cache_key(name)
        rows = cache.get(key)
        if rows is None:
            rows = fetch()
            cache.set(key, rows, LOOKUP_CACHE_SECONDS)
        return rows

    def list_members(self) -> list[dict]:
        return self._cached("members", lambda: self._list_all_pages("/members"))

    def list_projects(self) -> list[dict]:
        return self._cached("projects", lambda: self._list_all_pages("/projects"))

    def get_project(self, project_id: str) -> dict:
        return self._request("GET", f"/projects/{project_id}")["data"]

    def create_project(self, name: str, client_id: str | None = None, is_billable: bool = True) -> dict:
        payload = {
            "name": name,
            "color": PROJECT_COLOR,
            "is_billable": is_billable,
            # Employees can only track time on public projects (or ones they are members of).
            "is_public": True,
            "client_id": client_id,
        }
        project = self._request("POST", "/projects", json=payload)["data"]
        self.invalidate_projects_cache()
        return project

    def update_project(self, project_id: str, **changes) -> dict:
        current = self.get_project(project_id)
        payload = {field: current.get(field) for field in PROJECT_UPDATE_FIELDS}
        payload.update(changes)
        project = self._request("PUT", f"/projects/{project_id}", json=payload)["data"]
        self.invalidate_projects_cache()
        return project

    def update_task(self, task_id: str, name: str) -> dict:
        return self._request("PUT", f"/tasks/{task_id}", json={"name": name})["data"]

    def list_tasks(self, project_id: str) -> list[dict]:
        return self._list_all_pages("/tasks", {"project_id": project_id, "done": "all"})

    def create_task(self, project_id: str, name: str) -> dict:
        return self._request("POST", "/tasks", json={"name": name, "project_id": project_id})["data"]

    def list_task_time_entries(self, task_id: str) -> list[dict]:
        body = self._request("GET", "/time-entries", params={"task_ids[]": task_id, "limit": TIME_ENTRIES_LIMIT})
        return body.get("data", [])

    def aggregate_seconds_by_task(self, project_id: str) -> dict[str, int]:
        """Seconds of finished time entries per task id in one project, summed by solidtime.

        Entries without a task (``key`` null) are dropped; running timers have no end and add nothing.
        """
        body = self._request(
            "GET", "/time-entries/aggregate", params={"group": "task", "project_ids[]": project_id}
        )
        groups = (body.get("data") or {}).get("grouped_data") or []
        return {g["key"]: int(g.get("seconds") or 0) for g in groups if g.get("key")}

    def create_time_entry(
        self,
        *,
        member_id: str,
        project_id: str,
        task_id: str,
        start: datetime,
        end: datetime,
        billable: bool,
        description: str | None,
    ) -> dict:
        payload = {
            "member_id": member_id,
            "project_id": project_id,
            "task_id": task_id,
            "start": _format_datetime(start),
            "end": _format_datetime(end),
            "billable": billable,
            "description": description,
        }
        return self._request("POST", "/time-entries", json=payload)["data"]

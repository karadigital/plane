# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Keep solidtime projects and ``[IDENT-N]`` tasks in step with Plane (replaces solidtime-bridge).

Matching is by naming convention only (no ID mapping): a solidtime project is named after the
Plane project identifier (or its name), and a task starts with ``[IDENT-N]``.
"""

# Python imports
import logging
import re
import time
from collections.abc import Callable, Iterable

# Django imports
from django.conf import settings

# Module imports
from .client import SolidtimeClient, SolidtimeError
from .service import TASK_NAME_MAX_LENGTH, create_task_or_reuse, find_project, find_task, task_name, task_prefix

logger = logging.getLogger("plane.worker")

TASK_PREFIX_PATTERN = re.compile(r"^(\[[^\]]+\])")


def sync_enabled() -> bool:
    return bool(getattr(settings, "SOLIDTIME_SYNC_ENABLED", False)) and bool(
        (getattr(settings, "SOLIDTIME_SYNC_WORKSPACE_SLUG", "") or "").strip()
    )


def get_sync_client(require_enabled: bool = True) -> SolidtimeClient | None:
    """The client for syncing, or None. ``require_enabled=False`` is for the operator's
    ``solidtime_reconcile`` command, which must work before SOLIDTIME_SYNC_ENABLED is turned on
    (cutover dry-run); it still needs the workspace slug and the solidtime settings."""
    if require_enabled and not sync_enabled():
        return None
    if not (getattr(settings, "SOLIDTIME_SYNC_WORKSPACE_SLUG", "") or "").strip():
        return None
    return SolidtimeClient.from_settings()


def _default_client_id() -> str | None:
    return getattr(settings, "SOLIDTIME_DEFAULT_CLIENT_ID", "") or None


def ensure_project(client: SolidtimeClient, plane_project) -> dict:
    project = find_project(client.list_projects(), plane_project)
    if project is not None:
        return project
    return client.create_project(plane_project.identifier, client_id=_default_client_id())


def sync_issue_task(client: SolidtimeClient, issue) -> str:
    """Create or rename the work item's task. Returns "created", "renamed" or "unchanged"."""
    project = ensure_project(client, issue.project)
    task = find_task(client.list_tasks(project["id"]), issue)
    if task is None:
        create_task_or_reuse(client, project, issue)
        return "created"
    wanted = task_name(issue)
    if task.get("name") != wanted:
        client.update_task(task["id"], wanted)
        return "renamed"
    return "unchanged"


TASK_IDENTIFIER_PATTERN = re.compile(r"^\[([A-Za-z0-9]+)-\d+\]")


def _other_prefixes(tasks: list[dict], identifier: str) -> dict[str, int]:
    """Count tasks whose ``[IDENT-N]`` prefix belongs to another identifier (e.g. a renamed project)."""
    counts: dict[str, int] = {}
    for task in tasks:
        match = TASK_IDENTIFIER_PATTERN.match(task.get("name") or "")
        if match and match.group(1) != identifier:
            counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    return counts


def _tasks_by_prefix(tasks: list[dict]) -> dict[str, dict]:
    by_prefix: dict[str, dict] = {}
    for task in tasks:
        match = TASK_PREFIX_PATTERN.match(task.get("name") or "")
        if match:
            by_prefix.setdefault(match.group(1), task)
    return by_prefix


def reconcile_project(
    client: SolidtimeClient,
    plane_project,
    issues: Iterable,
    *,
    dry_run: bool = False,
    pause_seconds: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Create missing tasks and rename stale ones for one project, listing its tasks once."""
    issues = list(issues)
    stats = {"project": "existing", "created": 0, "renamed": 0, "unchanged": 0, "errors": 0}

    project = find_project(client.list_projects(), plane_project)
    if project is None:
        if dry_run:
            stats.update(project="would_create", created=len(issues))
            return stats
        project = client.create_project(plane_project.identifier, client_id=_default_client_id())
        stats["project"] = "created"
        tasks_by_prefix: dict[str, dict] = {}
    else:
        tasks = client.list_tasks(project["id"])
        tasks_by_prefix = _tasks_by_prefix(tasks)
        other_prefixes = _other_prefixes(tasks, plane_project.identifier)
        if other_prefixes:
            stats["other_prefixes"] = other_prefixes

    def write(action: Callable[[], object], counter: str) -> None:
        if dry_run:
            stats[counter] += 1
            return
        try:
            action()
            stats[counter] += 1
        except SolidtimeError:
            stats["errors"] += 1
        if pause_seconds > 0:
            sleep(pause_seconds)

    for issue in issues:
        task = tasks_by_prefix.get(task_prefix(issue))
        wanted = task_name(issue)
        if task is None:
            write(lambda issue=issue: create_task_or_reuse(client, project, issue), "created")
        elif task.get("name") != wanted:
            write(lambda task=task, wanted=wanted: client.update_task(task["id"], wanted), "renamed")
        else:
            stats["unchanged"] += 1
    return stats


def rename_project_identifier(
    client: SolidtimeClient,
    plane_project,
    old_identifier: str,
    dry_run: bool = False,
    pause_seconds: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """After ``OLD`` → ``NEW``: rename the ``OLD`` solidtime project and every ``[OLD-N]`` task.

    Also used at cutover for identifiers changed before the sync existed (ECOM was SOPI).
    With ``dry_run`` it only counts. A solidtime outage or rate limit raises, so the Celery task
    retries; tasks already renamed no longer match ``[OLD-N]``, so a retry picks up where it stopped.
    """
    stats = {"project_renamed": False, "tasks_renamed": 0, "errors": 0}
    new_identifier = plane_project.identifier
    projects = client.list_projects()

    def named(name: str) -> dict | None:
        return next((p for p in projects if (p.get("name") or "").strip() == name), None)

    project = named(old_identifier)
    if project is not None:
        if named(new_identifier) is None:
            stats["project_renamed"] = True
            if not dry_run:
                project = client.update_project(project["id"], name=new_identifier)
        else:
            logger.warning(
                "solidtime project %s kept: a project named %s already exists; renaming its tasks in place",
                old_identifier,
                new_identifier,
            )
    else:
        project = find_project(projects, plane_project)
        if project is None:
            if dry_run:
                return stats
            project = ensure_project(client, plane_project)

    old_prefix = re.compile(rf"^\[{re.escape(old_identifier)}-(\d+)\](.*)$", re.DOTALL)
    for task in client.list_tasks(project["id"]):
        match = old_prefix.match(task.get("name") or "")
        if not match:
            continue
        if dry_run:
            stats["tasks_renamed"] += 1
            continue
        new_name = f"[{new_identifier}-{match.group(1)}]{match.group(2)}"[:TASK_NAME_MAX_LENGTH]
        try:
            client.update_task(task["id"], new_name)
            stats["tasks_renamed"] += 1
        except SolidtimeError as e:
            if e.code == "unavailable":
                raise
            stats["errors"] += 1
        if pause_seconds > 0:
            sleep(pause_seconds)
    return stats

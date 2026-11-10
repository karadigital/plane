# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Map Plane work items to solidtime projects and tasks.

Conventions in Kara's solidtime: a project is named after the Plane project
identifier (e.g. ``KARA``) and a task is named ``[KARA-30] <work item name>``.
"""

# Python imports
from datetime import datetime, timedelta

# Module imports
from .client import SolidtimeClient, SolidtimeError

TASK_NAME_MAX_LENGTH = 255


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def task_prefix(issue) -> str:
    return f"[{issue.project.identifier}-{issue.sequence_id}]"


def task_name(issue) -> str:
    return f"{task_prefix(issue)} {issue.name}"[:TASK_NAME_MAX_LENGTH]


def find_member(members: list[dict], email: str) -> dict | None:
    wanted = _norm(email)
    if not wanted:
        return None
    return next(
        (m for m in members if not m.get("is_placeholder") and _norm(m.get("email")) == wanted),
        None,
    )


def find_project(projects: list[dict], project) -> dict | None:
    """Identifier first (exact, then case-insensitive), then name the same way.

    The exact match comes first so that ``WILL`` picks the ``WILL`` project and not
    a stray ``will`` one; the identifier still beats the project name.
    """
    for wanted in (project.identifier, project.name):
        for exact in (True, False):
            match = next(
                (
                    p
                    for p in projects
                    if ((p.get("name") or "").strip() == wanted if exact else _norm(p.get("name")) == _norm(wanted))
                ),
                None,
            )
            if match:
                return match
    return None


def find_task(tasks: list[dict], issue) -> dict | None:
    prefix = task_prefix(issue)
    return next((t for t in tasks if (t.get("name") or "").startswith(prefix)), None)


def serialize_entry(entry: dict, member_names_by_user_id: dict[str, str]) -> dict:
    return {
        "id": entry["id"],
        "start": entry["start"],
        "end": entry["end"],
        "duration": entry.get("duration") or 0,
        "description": entry.get("description"),
        "member_name": member_names_by_user_id.get(entry.get("user_id")),
        "is_running": entry["end"] is None,
    }


def _member_names(members: list[dict]) -> dict[str, str]:
    return {m["user_id"]: m["name"] for m in members if m.get("user_id")}


def get_issue_time(client: SolidtimeClient, issue) -> dict:
    empty = {"total_seconds": 0, "entries": []}
    project = find_project(client.list_projects(), issue.project)
    if project is None:
        return empty
    task = find_task(client.list_tasks(project["id"]), issue)
    if task is None:
        return empty

    names = _member_names(client.list_members())
    entries = [serialize_entry(e, names) for e in client.list_task_time_entries(task["id"])]
    entries.sort(key=lambda e: e["start"], reverse=True)
    total = sum(e["duration"] for e in entries if not e["is_running"])
    return {"total_seconds": total, "entries": entries}


def _find_or_create_task(client: SolidtimeClient, project: dict, issue) -> dict:
    task = find_task(client.list_tasks(project["id"]), issue)
    if task is not None:
        return task
    try:
        return client.create_task(project["id"], task_name(issue))
    except SolidtimeError as e:
        # Someone else may have created the task between our list and create.
        if e.code != "invalid_request":
            raise
        task = find_task(client.list_tasks(project["id"]), issue)
        if task is None:
            raise
        return task


def log_issue_time(
    client: SolidtimeClient,
    issue,
    user,
    start: datetime,
    duration_minutes: int,
    description: str | None,
) -> dict:
    members = client.list_members()
    member = find_member(members, user.email)
    if member is None:
        raise SolidtimeError("member_not_found", f"{user.email} is not a member of the Time organization")

    project = find_project(client.list_projects(), issue.project)
    if project is None:
        raise SolidtimeError("project_not_found", f"No Time project named {issue.project.identifier}")

    task = _find_or_create_task(client, project, issue)
    entry = client.create_time_entry(
        member_id=member["id"],
        project_id=project["id"],
        task_id=task["id"],
        start=start,
        end=start + timedelta(minutes=duration_minutes),
        billable=bool(project.get("is_billable")),
        description=description,
    )
    return serialize_entry(entry, _member_names(members))

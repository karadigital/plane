# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Celery tasks that keep solidtime projects and tasks in step with Plane (KARA-220)."""

# Third party imports
from celery import shared_task

# Django imports
from django.conf import settings

# Module imports
from plane.db.models import Issue, Project
from plane.utils.exception_logger import log_exception
from plane.utils.solidtime import (
    SolidtimeError,
    ensure_project,
    get_sync_client,
    reconcile_project,
    rename_project_identifier,
    sync_issue_task,
)

RETRY_BASE_SECONDS = 60
MAX_RETRIES = 5


def projects_for_sync():
    return Project.objects.filter(workspace__slug=settings.SOLIDTIME_SYNC_WORKSPACE_SLUG, archived_at__isnull=True)


def issues_for_sync(project):
    # Issue.objects already hides soft-deleted rows; archived and triage/intake issues are synced.
    return Issue.objects.filter(project=project, is_draft=False).select_related("project")


def _handle_error(task, error: SolidtimeError):
    """Retry while solidtime is unavailable (60s, 120s, ... ~31 min in total); log anything else once."""
    if error.code == "unavailable":
        raise task.retry(exc=error, countdown=RETRY_BASE_SECONDS * 2**task.request.retries)
    log_exception(error, warning=True)
    return None


@shared_task(bind=True, max_retries=MAX_RETRIES)
def sync_issue_to_solidtime(self, issue_id: str):
    client = get_sync_client()
    if client is None:
        return None
    issue = (
        Issue.objects.filter(
            pk=issue_id,
            is_draft=False,
            workspace__slug=settings.SOLIDTIME_SYNC_WORKSPACE_SLUG,
            project__archived_at__isnull=True,
        )
        .select_related("project")
        .first()
    )
    if issue is None:
        return None
    try:
        return sync_issue_task(client, issue)
    except SolidtimeError as e:
        return _handle_error(self, e)


@shared_task(bind=True, max_retries=MAX_RETRIES)
def sync_project_to_solidtime(self, project_id: str, old_identifier: str | None = None):
    client = get_sync_client()
    if client is None:
        return None
    project = projects_for_sync().filter(pk=project_id).first()
    if project is None:
        return None
    try:
        if old_identifier and old_identifier != project.identifier:
            return rename_project_identifier(client, project, old_identifier)
        return ensure_project(client, project)
    except SolidtimeError as e:
        return _handle_error(self, e)


@shared_task
def reconcile_solidtime(project_identifier: str | None = None, dry_run: bool = False, pause_seconds: float = 0.3):
    """Daily safety net and cutover backfill: per-project stats keyed by identifier."""
    client = get_sync_client()
    if client is None:
        return {}
    projects = projects_for_sync().order_by("identifier")
    if project_identifier:
        projects = projects.filter(identifier=project_identifier.upper())

    results: dict[str, dict] = {}
    for project in projects:
        try:
            results[project.identifier] = reconcile_project(
                client, project, list(issues_for_sync(project)), dry_run=dry_run, pause_seconds=pause_seconds
            )
        except SolidtimeError as e:
            log_exception(e, warning=True)
            results[project.identifier] = {"error": e.message}
    return results

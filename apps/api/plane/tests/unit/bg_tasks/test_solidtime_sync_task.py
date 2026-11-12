# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import date

import pytest
from celery.exceptions import Retry
from celery.schedules import crontab

from plane.bgtasks import solidtime_sync_task as tasks
from plane.bgtasks.solidtime_sync_task import (
    issues_for_sync,
    projects_for_sync,
    reconcile_solidtime,
    sync_issue_to_solidtime,
    sync_project_to_solidtime,
)
from plane.db.models import Issue, Project, State, Workspace
from plane.utils.solidtime import SolidtimeError


def _make_issue(project, author, name="Fix login", **fields):
    issue = Issue(name=name, project=project, workspace=project.workspace, **fields)
    issue.save(created_by_id=author.id)
    return issue


@pytest.fixture
def project(db, workspace, create_user):
    return Project.objects.create(name="Scoped Project", identifier="SP", workspace=workspace, created_by=create_user)


@pytest.fixture
def scoped(settings, workspace, mocker):
    settings.SOLIDTIME_SYNC_WORKSPACE_SLUG = workspace.slug
    client = mocker.MagicMock()
    mocker.patch.object(tasks, "get_sync_client", return_value=client)
    return client


@pytest.mark.unit
@pytest.mark.django_db
class TestScope:
    def test_issues_for_sync_scope(self, project, create_user):
        triage = State.objects.create(
            name="Triage", group="triage", project=project, workspace=project.workspace, is_triage=True
        )
        normal = _make_issue(project, create_user, "Normal")
        archived = _make_issue(project, create_user, "Archived", archived_at=date(2026, 1, 1))
        in_triage = _make_issue(project, create_user, "Intake", state=triage)
        _make_issue(project, create_user, "Draft", is_draft=True)
        deleted = _make_issue(project, create_user, "Deleted")
        deleted.delete()

        names = set(issues_for_sync(project).values_list("name", flat=True))

        assert names == {normal.name, archived.name, in_triage.name}

    def test_projects_for_sync_scope(self, settings, project, workspace, create_user):
        settings.SOLIDTIME_SYNC_WORKSPACE_SLUG = workspace.slug
        Project.objects.create(
            name="Old", identifier="OLD", workspace=workspace, created_by=create_user, archived_at=date(2026, 1, 1)
        )
        other_ws = Workspace.objects.create(name="Other", slug="other-ws", owner=create_user)
        Project.objects.create(name="Elsewhere", identifier="ELS", workspace=other_ws, created_by=create_user)

        assert list(projects_for_sync().values_list("identifier", flat=True)) == ["SP"]


@pytest.mark.unit
@pytest.mark.django_db
class TestSyncIssueTask:
    def test_sync_issue_task_runs_sync(self, scoped, project, create_user, mocker):
        issue = _make_issue(project, create_user)
        sync = mocker.patch.object(tasks, "sync_issue_task", return_value="created")

        assert sync_issue_to_solidtime.run(str(issue.id)) == "created"

        assert sync.call_args.args[0] is scoped
        assert sync.call_args.args[1] == issue

    def test_sync_issue_skips_other_workspace(self, scoped, settings, project, create_user, mocker):
        settings.SOLIDTIME_SYNC_WORKSPACE_SLUG = "other"
        issue = _make_issue(project, create_user)
        sync = mocker.patch.object(tasks, "sync_issue_task")

        assert sync_issue_to_solidtime.run(str(issue.id)) is None
        sync.assert_not_called()

    def test_sync_issue_skips_drafts_and_missing(self, scoped, project, create_user, mocker):
        draft = _make_issue(project, create_user, is_draft=True)
        sync = mocker.patch.object(tasks, "sync_issue_task")

        assert sync_issue_to_solidtime.run(str(draft.id)) is None
        assert sync_issue_to_solidtime.run("00000000-0000-0000-0000-000000000000") is None
        sync.assert_not_called()

    def test_sync_issue_skips_when_disabled(self, settings, workspace, project, create_user, mocker):
        settings.SOLIDTIME_SYNC_WORKSPACE_SLUG = workspace.slug
        mocker.patch.object(tasks, "get_sync_client", return_value=None)
        issue = _make_issue(project, create_user)
        sync = mocker.patch.object(tasks, "sync_issue_task")

        assert sync_issue_to_solidtime.run(str(issue.id)) is None
        sync.assert_not_called()

    def test_unavailable_retries_with_backoff(self, scoped, project, create_user, mocker):
        issue = _make_issue(project, create_user)
        mocker.patch.object(tasks, "sync_issue_task", side_effect=SolidtimeError("unavailable", "down"))
        retry = mocker.patch.object(sync_issue_to_solidtime, "retry", side_effect=Retry())

        with pytest.raises(Retry):
            sync_issue_to_solidtime.run(str(issue.id))

        assert retry.call_args.kwargs["countdown"] == 60

    def test_invalid_request_is_logged_not_retried(self, scoped, project, create_user, mocker):
        issue = _make_issue(project, create_user)
        mocker.patch.object(tasks, "sync_issue_task", side_effect=SolidtimeError("invalid_request", "bad"))
        retry = mocker.patch.object(sync_issue_to_solidtime, "retry")
        log = mocker.patch.object(tasks, "log_exception")

        assert sync_issue_to_solidtime.run(str(issue.id)) is None
        retry.assert_not_called()
        log.assert_called_once()


@pytest.mark.unit
@pytest.mark.django_db
class TestSyncProjectTask:
    def test_project_task_renames_on_identifier_change(self, scoped, project, mocker):
        rename = mocker.patch.object(tasks, "rename_project_identifier", return_value={"tasks_renamed": 0})
        ensure = mocker.patch.object(tasks, "ensure_project", return_value={"id": "p1"})

        sync_project_to_solidtime.run(str(project.id), old_identifier="OLD")
        rename.assert_called_once_with(scoped, project, "OLD", pause_seconds=0.3)
        ensure.assert_not_called()

        sync_project_to_solidtime.run(str(project.id))
        ensure.assert_called_once_with(scoped, project)

    def test_project_task_skips_archived(self, scoped, project, mocker):
        Project.objects.filter(pk=project.pk).update(archived_at=date(2026, 1, 1))
        ensure = mocker.patch.object(tasks, "ensure_project")

        assert sync_project_to_solidtime.run(str(project.id)) is None
        ensure.assert_not_called()

    def test_project_task_retries_on_unavailable(self, scoped, project, mocker):
        mocker.patch.object(tasks, "ensure_project", side_effect=SolidtimeError("unavailable", "down"))
        retry = mocker.patch.object(sync_project_to_solidtime, "retry", side_effect=Retry())

        with pytest.raises(Retry):
            sync_project_to_solidtime.run(str(project.id))
        assert retry.call_args.kwargs["countdown"] == 60


@pytest.mark.unit
@pytest.mark.django_db
class TestReconcile:
    def test_reconcile_solidtime_collects_stats_and_errors(self, scoped, project, workspace, create_user, mocker):
        Project.objects.create(name="Second", identifier="SEC", workspace=workspace, created_by=create_user)
        stats = {"project": "existing", "created": 1, "renamed": 0, "unchanged": 2, "errors": 0}

        def fake(client, plane_project, issues, **kwargs):
            if plane_project.identifier == "SEC":
                raise SolidtimeError("unavailable", "down")
            return stats

        reconcile = mocker.patch.object(tasks, "reconcile_project", side_effect=fake)

        result = reconcile_solidtime(dry_run=True, pause_seconds=0)

        assert result == {"SP": stats, "SEC": {"error": "down"}}
        assert reconcile.call_args.kwargs == {"dry_run": True, "pause_seconds": 0}

        reconcile.reset_mock()
        assert set(reconcile_solidtime(project_identifier="SP")) == {"SP"}
        assert reconcile.call_count == 1

    def test_reconcile_solidtime_without_client(self, mocker):
        mocker.patch.object(tasks, "get_sync_client", return_value=None)

        assert reconcile_solidtime() == {}

    def test_beat_schedule_has_daily_reconcile(self):
        from plane.celery import app

        entry = app.conf.beat_schedule["solidtime-reconcile-daily"]
        assert entry["task"] == "plane.bgtasks.solidtime_sync_task.reconcile_solidtime"
        assert entry["schedule"] == crontab(hour=20, minute=0)


@pytest.mark.unit
@pytest.mark.django_db
class TestReconcileRenameFrom:
    def test_rename_from_runs_before_reconcile(self, scoped, project, mocker):
        rename_stats = {"project_renamed": False, "tasks_renamed": 3, "errors": 0}
        reconcile_stats = {"project": "existing", "created": 0, "renamed": 0, "unchanged": 3, "errors": 0}
        rename = mocker.patch.object(tasks, "rename_project_identifier", return_value=rename_stats)
        mocker.patch.object(tasks, "reconcile_project", return_value=reconcile_stats)

        result = reconcile_solidtime(project_identifier="SP", rename_from="OLD", pause_seconds=0)

        rename.assert_called_once_with(scoped, project, "OLD", dry_run=False, pause_seconds=0)
        assert result == {"SP": {**reconcile_stats, "renamed_from": {"OLD": rename_stats}}}

    def test_rename_from_dry_run_skips_reconcile(self, scoped, project, mocker):
        rename_stats = {"project_renamed": False, "tasks_renamed": 3, "errors": 0}
        rename = mocker.patch.object(tasks, "rename_project_identifier", return_value=rename_stats)
        reconcile = mocker.patch.object(tasks, "reconcile_project")

        result = reconcile_solidtime(project_identifier="SP", rename_from="OLD", dry_run=True)

        rename.assert_called_once_with(scoped, project, "OLD", dry_run=True, pause_seconds=0.3)
        reconcile.assert_not_called()
        assert result == {"SP": {"renamed_from": {"OLD": rename_stats}}}

    def test_rename_from_requires_project(self, scoped):
        with pytest.raises(ValueError):
            reconcile_solidtime(rename_from="OLD")


@pytest.mark.unit
class TestWorkerRegistration:
    def test_worker_imports_solidtime_tasks(self, settings):
        assert "plane.bgtasks.solidtime_sync_task" in settings.CELERY_IMPORTS


@pytest.mark.unit
@pytest.mark.django_db
class TestOperatorReconcile:
    def test_reconcile_can_run_with_flag_off_when_forced(self, settings, workspace, project, mocker):
        settings.SOLIDTIME_SYNC_ENABLED = False
        settings.SOLIDTIME_SYNC_WORKSPACE_SLUG = workspace.slug
        client = mocker.MagicMock()
        get_client = mocker.patch.object(tasks, "get_sync_client", return_value=client)
        mocker.patch.object(tasks, "reconcile_project", return_value={"project": "existing"})

        reconcile_solidtime(require_enabled=False)

        get_client.assert_called_once_with(require_enabled=False)

    def test_project_task_passes_pause_to_rename(self, scoped, project, mocker):
        rename = mocker.patch.object(tasks, "rename_project_identifier", return_value={"tasks_renamed": 0})

        sync_project_to_solidtime.run(str(project.id), old_identifier="OLD")

        rename.assert_called_once_with(scoped, project, "OLD", pause_seconds=0.3)

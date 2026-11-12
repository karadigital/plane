# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from django.db import transaction

from plane.db.models import Issue, Project, State

TASKS = "plane.bgtasks.solidtime_sync_task"


@pytest.fixture
def sync_on(settings, workspace):
    settings.SOLIDTIME_SYNC_ENABLED = True
    settings.SOLIDTIME_SYNC_WORKSPACE_SLUG = workspace.slug
    return settings


@pytest.fixture
def issue_delay(mocker):
    return mocker.patch(f"{TASKS}.sync_issue_to_solidtime.delay")


@pytest.fixture
def project_delay(mocker):
    return mocker.patch(f"{TASKS}.sync_project_to_solidtime.delay")


@pytest.fixture
def project(db, workspace, create_user):
    return Project.objects.create(name="Scoped Project", identifier="SP", workspace=workspace, created_by=create_user)


def _make_issue(project, author, **fields):
    issue = Issue(name=fields.pop("name", "Fix login"), project=project, workspace=project.workspace, **fields)
    issue.save(created_by_id=author.id)
    return issue


@pytest.mark.unit
@pytest.mark.django_db
class TestIssueSignal:
    def test_issue_create_enqueues(
        self, sync_on, project, create_user, issue_delay, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            issue = _make_issue(project, create_user)

        issue_delay.assert_called_once_with(str(issue.id))

    def test_issue_rename_enqueues(
        self, sync_on, project, create_user, issue_delay, django_capture_on_commit_callbacks
    ):
        issue = _make_issue(project, create_user)
        issue_delay.reset_mock()

        with django_capture_on_commit_callbacks(execute=True):
            loaded = Issue.objects.get(pk=issue.pk)
            loaded.name = "Fix signup"
            loaded.save()

        issue_delay.assert_called_once_with(str(issue.id))

    def test_state_or_sort_order_save_does_not_enqueue(
        self, sync_on, project, create_user, issue_delay, django_capture_on_commit_callbacks
    ):
        other_state = State.objects.create(name="Doing", group="started", project=project, workspace=project.workspace)
        issue = _make_issue(project, create_user)
        issue_delay.reset_mock()

        with django_capture_on_commit_callbacks(execute=True):
            loaded = Issue.objects.get(pk=issue.pk)
            loaded.sort_order = 12345
            loaded.state = other_state
            loaded.save()

        issue_delay.assert_not_called()

    def test_publishing_draft_enqueues_and_draft_create_does_not(
        self, sync_on, project, create_user, issue_delay, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            draft = _make_issue(project, create_user, is_draft=True)
        issue_delay.assert_not_called()

        with django_capture_on_commit_callbacks(execute=True):
            loaded = Issue.objects.get(pk=draft.pk)
            loaded.is_draft = False
            loaded.save()

        issue_delay.assert_called_once_with(str(draft.id))

    def test_disabled_sync_enqueues_nothing(
        self, settings, project, create_user, issue_delay, django_capture_on_commit_callbacks
    ):
        settings.SOLIDTIME_SYNC_ENABLED = False

        with django_capture_on_commit_callbacks(execute=True):
            issue = _make_issue(project, create_user)
            issue.name = "Renamed"
            issue.save()

        issue_delay.assert_not_called()

    def test_rolled_back_create_enqueues_nothing(
        self, sync_on, project, create_user, issue_delay, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            try:
                with transaction.atomic():
                    _make_issue(project, create_user)
                    raise RuntimeError("rollback")
            except RuntimeError:
                pass

        issue_delay.assert_not_called()


@pytest.mark.unit
@pytest.mark.django_db
class TestProjectSignal:
    def test_project_create_enqueues(
        self, sync_on, workspace, create_user, project_delay, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            project = Project.objects.create(name="New", identifier="NEWP", workspace=workspace, created_by=create_user)

        project_delay.assert_called_once_with(str(project.id))

    def test_project_identifier_change_passes_old_identifier(
        self, sync_on, project, project_delay, django_capture_on_commit_callbacks
    ):
        project_delay.reset_mock()

        with django_capture_on_commit_callbacks(execute=True):
            loaded = Project.objects.get(pk=project.pk)
            loaded.identifier = "NEWI"
            loaded.save()

        project_delay.assert_called_once_with(str(project.id), old_identifier="SP")

    def test_project_other_field_change_does_not_enqueue(
        self, sync_on, project, project_delay, django_capture_on_commit_callbacks
    ):
        project_delay.reset_mock()

        with django_capture_on_commit_callbacks(execute=True):
            loaded = Project.objects.get(pk=project.pk)
            loaded.name = "Renamed project"
            loaded.save()

        project_delay.assert_not_called()

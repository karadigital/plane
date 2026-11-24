# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import datetime
import zoneinfo

import pytest
from django.utils import timezone
from freezegun import freeze_time

from plane.db.models import Issue, Project, State, Workspace


@pytest.fixture
def workspace(create_user):
    return Workspace.objects.create(name="Test Workspace", slug="test-workspace", owner=create_user)


@pytest.fixture
def project(workspace, create_user):
    return Project.objects.create(name="Test Project", identifier="TP", workspace=workspace, created_by=create_user)


@pytest.fixture
def backlog_state(project):
    return State.objects.create(name="Backlog", project=project, group="backlog", default=True)


@pytest.fixture
def started_state(project):
    return State.objects.create(name="In Progress", project=project, group="started")


@pytest.fixture
def review_state(project):
    return State.objects.create(name="In Review", project=project, group="started")


@pytest.fixture
def completed_state(project):
    return State.objects.create(name="Done", project=project, group="completed")


def make_issue(workspace, project, state, user, **kwargs):
    return Issue.objects.create(
        name="Item", workspace=workspace, project=project, state=state, created_by=user, **kwargs
    )


def move(issue, state, **save_kwargs):
    issue.state = state
    issue.save(**save_kwargs)
    issue.refresh_from_db()
    return issue


@pytest.mark.unit
class TestIssueAutoStartDate:
    """Issue.save() sets start_date when a work item enters a started-group state"""

    @pytest.mark.django_db
    def test_update_into_started_sets_start_date(self, workspace, project, backlog_state, started_state, create_user):
        issue = make_issue(workspace, project, backlog_state, create_user)
        assert move(issue, started_state).start_date == timezone.localdate()

    @pytest.mark.django_db
    def test_update_into_started_keeps_existing_start_date(
        self, workspace, project, backlog_state, started_state, create_user
    ):
        given = datetime.date(2020, 1, 2)
        issue = make_issue(workspace, project, backlog_state, create_user, start_date=given)
        assert move(issue, started_state).start_date == given

    @pytest.mark.django_db
    def test_create_in_started_sets_start_date(self, workspace, project, started_state, create_user):
        issue = make_issue(workspace, project, started_state, create_user)
        issue.refresh_from_db()
        assert issue.start_date == timezone.localdate()

    @pytest.mark.django_db
    def test_create_in_started_keeps_given_start_date(self, workspace, project, started_state, create_user):
        given = datetime.date(2020, 1, 2)
        issue = make_issue(workspace, project, started_state, create_user, start_date=given)
        assert issue.start_date == given

    @pytest.mark.django_db
    def test_create_with_started_default_state_sets_start_date(self, workspace, project, create_user):
        State.objects.create(name="In Progress", project=project, group="started", default=True)
        issue = make_issue(workspace, project, None, create_user)
        issue.refresh_from_db()
        assert issue.start_date == timezone.localdate()

    @pytest.mark.django_db
    @pytest.mark.parametrize("group", ["backlog", "unstarted", "completed", "cancelled"])
    def test_update_into_other_group_keeps_start_date_empty(
        self, workspace, project, backlog_state, create_user, group
    ):
        issue = make_issue(workspace, project, backlog_state, create_user)
        target = State.objects.create(name=f"State {group}", project=project, group=group)
        assert move(issue, target).start_date is None

    @pytest.mark.django_db
    def test_save_without_state_change_does_not_refill_start_date(self, workspace, project, started_state, create_user):
        issue = make_issue(workspace, project, started_state, create_user)
        issue.start_date = None
        issue.name = "Renamed"
        issue.save()
        issue.refresh_from_db()
        assert issue.start_date is None

    @pytest.mark.django_db
    def test_started_to_started_sets_start_date(self, workspace, project, started_state, review_state, create_user):
        issue = make_issue(workspace, project, started_state, create_user)
        issue.start_date = None
        issue.save()
        assert move(issue, review_state).start_date == timezone.localdate()

    @pytest.mark.django_db
    def test_update_fields_state_persists_start_date(
        self, workspace, project, backlog_state, started_state, create_user
    ):
        issue = make_issue(workspace, project, backlog_state, create_user)
        assert move(issue, started_state, update_fields=["state"]).start_date == timezone.localdate()

    @pytest.mark.django_db
    def test_start_date_set_when_target_date_is_in_the_past(
        self, workspace, project, backlog_state, started_state, create_user
    ):
        issue = make_issue(workspace, project, backlog_state, create_user, target_date=datetime.date(2020, 1, 2))
        assert move(issue, started_state).start_date == timezone.localdate()

    @pytest.mark.django_db
    def test_explicit_start_date_none_with_state_change_stays_empty(
        self, workspace, project, backlog_state, started_state, create_user
    ):
        issue = make_issue(workspace, project, backlog_state, create_user, start_date=datetime.date(2020, 1, 2))
        issue.start_date = None
        assert move(issue, started_state).start_date is None

    @pytest.mark.django_db
    def test_start_date_uses_the_active_timezone(self, workspace, project, backlog_state, started_state, create_user):
        issue = make_issue(workspace, project, backlog_state, create_user)
        with freeze_time("2026-11-24 20:00:00"), timezone.override(zoneinfo.ZoneInfo("Asia/Jakarta")):
            assert move(issue, started_state).start_date == datetime.date(2026, 11, 25)

    @pytest.mark.django_db
    def test_issue_without_state_is_unchanged(self, workspace, project, create_user):
        issue = make_issue(workspace, project, None, create_user)
        assert issue.state is None
        assert issue.start_date is None

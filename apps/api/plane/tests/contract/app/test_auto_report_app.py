# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for the project report endpoint (KARA-107)."""

from datetime import date, datetime, timezone as dt_timezone
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Issue, Project, ProjectMember, State, User, Workspace, WorkspaceMember

URL = "/api/workspaces/{slug}/auto-report/"
PERIOD = {"start_date": "2026-11-01", "end_date": "2026-11-30"}


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Web", identifier="WEB", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def states(project):
    def make(name, group):
        return State.objects.create(name=name, group=group, project=project, color="#000000")

    return {
        "backlog": make("Backlog", "backlog"),
        "todo": make("Todo", "unstarted"),
        "in_progress": make("In Progress", "started"),
        "done": make("Approved", "completed"),
        "cancelled": make("Cancelled", "cancelled"),
    }


def _issue(project, state, user, name="Item", **fields):
    issue = Issue(name=name, project=project, workspace=project.workspace, state=state, **fields)
    issue.save(created_by_id=user.id)
    return issue


def _set_completed_at(issue, value):
    Issue.objects.filter(pk=issue.pk).update(completed_at=value)


def _get(client, workspace, ids, **overrides):
    params = {**PERIOD, "project_ids": ",".join(str(pid) for pid in ids), **overrides}
    params = {key: value for key, value in params.items() if value is not None}
    return client.get(URL.format(slug=workspace.slug), params)


def _ids(response):
    return [item["id"] for item in response.json()["items"]]


def _other_user(email):
    return User.objects.create(email=email, username=email.split("@")[0])


@pytest.mark.contract
@pytest.mark.django_db
class TestAutoReportValidation:
    @pytest.mark.parametrize("missing", ["project_ids", "start_date", "end_date"])
    def test_missing_param_is_400(self, session_client, workspace, project, missing):
        response = _get(session_client, workspace, [project.id], **{missing: None})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("field", ["start_date", "end_date"])
    def test_invalid_date_is_400(self, session_client, workspace, project, field):
        response = _get(session_client, workspace, [project.id], **{field: "2026-13-01"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_start_after_end_is_400(self, session_client, workspace, project):
        response = _get(session_client, workspace, [project.id], start_date="2026-11-30", end_date="2026-11-01")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_period_longer_than_366_days_is_400(self, session_client, workspace, project):
        response = _get(session_client, workspace, [project.id], start_date="2025-01-01", end_date="2026-01-02")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_period_of_366_days_is_allowed(self, session_client, workspace, project):
        response = _get(session_client, workspace, [project.id], start_date="2025-01-01", end_date="2026-01-01")
        assert response.status_code == status.HTTP_200_OK

    def test_date_near_year_9999_is_400(self, session_client, workspace, project):
        response = _get(session_client, workspace, [project.id], start_date="9999-12-30", end_date="9999-12-31")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_uuid_project_id_is_400(self, session_client, workspace, project):
        response = _get(session_client, workspace, [project.id, "not-a-uuid"])
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_more_than_50_project_ids_is_400(self, session_client, workspace, project):
        response = _get(session_client, workspace, [project.id] + [uuid4() for _ in range(50)])
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_duplicate_project_ids_are_counted_once(self, session_client, workspace, project):
        response = _get(session_client, workspace, [project.id, project.id, str(project.id).upper()])
        assert response.status_code == status.HTTP_200_OK
        assert [p["id"] for p in response.json()["projects"]] == [str(project.id)]


@pytest.mark.contract
@pytest.mark.django_db
class TestAutoReportAccess:
    def test_project_from_other_workspace_and_unknown_project_get_same_403(
        self, session_client, workspace, project, create_user
    ):
        other_ws = Workspace.objects.create(name="Other", owner=create_user, slug="other-ws")
        foreign = Project.objects.create(name="Foreign", identifier="FOR", workspace=other_ws, created_by=create_user)
        ProjectMember.objects.create(project=foreign, member=create_user, role=20, is_active=True)

        foreign_response = _get(session_client, workspace, [project.id, foreign.id])
        unknown_response = _get(session_client, workspace, [project.id, uuid4()])

        assert foreign_response.status_code == status.HTTP_403_FORBIDDEN
        assert unknown_response.status_code == status.HTTP_403_FORBIDDEN
        assert foreign_response.json() == unknown_response.json()

    def test_project_guest_is_403(self, session_client, workspace, create_user):
        project = Project.objects.create(name="G", identifier="G", workspace=workspace, created_by=create_user)
        ProjectMember.objects.create(project=project, member=create_user, role=5, is_active=True)
        assert _get(session_client, workspace, [project.id]).status_code == status.HTTP_403_FORBIDDEN

    def test_inactive_project_member_is_403(self, session_client, workspace, create_user):
        project = Project.objects.create(name="I", identifier="I", workspace=workspace, created_by=create_user)
        ProjectMember.objects.create(project=project, member=create_user, role=15, is_active=False)
        assert _get(session_client, workspace, [project.id]).status_code == status.HTTP_403_FORBIDDEN

    def test_archived_project_is_403(self, session_client, workspace, project):
        Project.objects.filter(pk=project.pk).update(archived_at=timezone.now())
        assert _get(session_client, workspace, [project.id]).status_code == status.HTTP_403_FORBIDDEN

    def test_workspace_guest_is_403(self, workspace, project):
        guest = _other_user("guest@plane.so")
        WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
        ProjectMember.objects.create(project=project, member=guest, role=15, is_active=True)
        client = APIClient()
        client.force_authenticate(user=guest)
        assert _get(client, workspace, [project.id]).status_code == status.HTTP_403_FORBIDDEN

    def test_user_outside_workspace_is_403(self, workspace, project):
        client = APIClient()
        client.force_authenticate(user=_other_user("outsider@plane.so"))
        assert _get(client, workspace, [project.id]).status_code == status.HTTP_403_FORBIDDEN

    def test_not_logged_in_is_rejected(self, api_client, workspace, project):
        response = _get(api_client, workspace, [project.id])
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.contract
@pytest.mark.django_db
class TestAutoReportGroups:
    def test_response_shape_and_order(self, session_client, workspace, project, states, create_user):
        second = Project.objects.create(name="Api", identifier="API", workspace=workspace, created_by=create_user)
        ProjectMember.objects.create(project=second, member=create_user, role=15, is_active=True)
        api_state = State.objects.create(name="todo", group="unstarted", project=second, color="#000000")

        done = _issue(
            project,
            states["done"],
            create_user,
            "Done item",
            start_date=date(2026, 11, 3),
            target_date=date(2026, 11, 10),
        )
        _set_completed_at(done, datetime(2026, 11, 9, 4, 12, tzinfo=dt_timezone.utc))
        web_todo = _issue(project, states["todo"], create_user, "Web todo")
        api_todo = _issue(second, api_state, create_user, "Api todo")

        response = _get(session_client, workspace, [project.id, second.id])

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["period"] == {"start": "2026-11-01", "end": "2026-11-30", "pipeline_end": "2026-12-14"}
        assert body["projects"] == [
            {"id": str(second.id), "name": "Api", "identifier": "API"},
            {"id": str(project.id), "name": "Web", "identifier": "WEB"},
        ]
        assert [item["id"] for item in body["items"]] == [str(api_todo.id), str(done.id), str(web_todo.id)]
        assert body["items"][1] == {
            "id": str(done.id),
            "key": f"WEB-{done.sequence_id}",
            "name": "Done item",
            "project_id": str(project.id),
            "state_name": "Approved",
            "state_group": "completed",
            "start_date": "2026-11-03",
            "target_date": "2026-11-10",
            "completed_at": "2026-11-09T04:12:00Z",
            "groups": ["finished"],
        }

    def test_cancelled_item_is_not_returned_even_in_pipeline(
        self, session_client, workspace, project, states, create_user
    ):
        _issue(project, states["cancelled"], create_user, start_date=date(2026, 12, 5))
        assert _ids(_get(session_client, workspace, [project.id])) == []

    def test_completed_before_period_is_not_finished(self, session_client, workspace, project, states, create_user):
        issue = _issue(project, states["done"], create_user)
        _set_completed_at(issue, datetime(2026, 10, 15, tzinfo=dt_timezone.utc))
        assert _ids(_get(session_client, workspace, [project.id])) == []

    def test_completed_at_uses_workspace_timezone(self, session_client, workspace, project, states, create_user):
        Workspace.objects.filter(pk=workspace.pk).update(timezone="Asia/Bangkok")
        late = _issue(project, states["done"], create_user, "Late evening on end date")
        # 23:30 on 2026-11-30 in UTC+7 is 16:30 UTC the same day; 00:30 on 12-01 is 17:30 UTC on 11-30.
        _set_completed_at(late, datetime(2026, 11, 30, 16, 30, tzinfo=dt_timezone.utc))
        after = _issue(project, states["done"], create_user, "Just after end date")
        _set_completed_at(after, datetime(2026, 11, 30, 17, 30, tzinfo=dt_timezone.utc))
        early = _issue(project, states["done"], create_user, "Early on start date")
        # 06:30 on 2026-11-01 in UTC+7 is 23:30 UTC on 10-31.
        _set_completed_at(early, datetime(2026, 10, 31, 23, 30, tzinfo=dt_timezone.utc))

        response = _get(session_client, workspace, [project.id])

        assert set(_ids(response)) == {str(late.id), str(early.id)}
        assert all(item["groups"] == ["finished"] for item in response.json()["items"])

    def test_in_progress_matches_state_name_case_insensitive(self, session_client, workspace, project, create_user):
        lower = State.objects.create(name="todo", group="unstarted", project=project, color="#000")
        upper = State.objects.create(name="IN PROGRESS", group="started", project=project, color="#000")
        spaced = State.objects.create(name="To Do", group="unstarted", project=project, color="#000")
        a = _issue(project, lower, create_user)
        b = _issue(project, upper, create_user)
        _issue(project, spaced, create_user)

        response = _get(session_client, workspace, [project.id])

        assert set(_ids(response)) == {str(a.id), str(b.id)}
        assert all(item["groups"] == ["in_progress"] for item in response.json()["items"])

    def test_pipeline_borders(self, session_client, workspace, project, states, create_user):
        backlog = states["backlog"]
        _issue(project, backlog, create_user, start_date=date(2026, 11, 30))
        last_day = _issue(project, backlog, create_user, start_date=date(2026, 12, 14))
        _issue(project, backlog, create_user, start_date=date(2026, 12, 15))
        first_day = _issue(project, backlog, create_user, start_date=date(2026, 12, 1))

        response = _get(session_client, workspace, [project.id])

        assert set(_ids(response)) == {str(last_day.id), str(first_day.id)}
        assert all(item["groups"] == ["pipeline"] for item in response.json()["items"])

    def test_item_in_several_groups_is_returned_once(self, session_client, workspace, project, states, create_user):
        issue = _issue(project, states["in_progress"], create_user, start_date=date(2026, 12, 2))

        items = _get(session_client, workspace, [project.id]).json()["items"]

        assert [item["id"] for item in items] == [str(issue.id)]
        assert items[0]["groups"] == ["in_progress", "pipeline"]

    def test_archived_draft_deleted_and_triage_items_are_not_returned(
        self, session_client, workspace, project, states, create_user
    ):
        todo = states["todo"]
        _issue(project, todo, create_user, archived_at=date(2026, 11, 2))
        _issue(project, todo, create_user, is_draft=True)
        _issue(project, todo, create_user).delete()
        triage = State.all_state_objects.create(
            name="Triage", group="triage", is_triage=True, project=project, color="#000"
        )
        _issue(project, triage, create_user, start_date=date(2026, 12, 2))

        assert _ids(_get(session_client, workspace, [project.id])) == []

    def test_no_matching_items_returns_empty_list(self, session_client, workspace, project, states, create_user):
        _issue(project, states["backlog"], create_user)

        response = _get(session_client, workspace, [project.id])

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []

    def test_more_than_2000_items_is_400(self, session_client, workspace, project, states):
        Issue.objects.bulk_create(
            [
                Issue(name=f"Item {n}", project=project, workspace=workspace, state=states["todo"], sequence_id=n)
                for n in range(1, 2002)
            ]
        )

        response = _get(session_client, workspace, [project.id])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {"error": "Too many items, select fewer projects or a shorter period"}

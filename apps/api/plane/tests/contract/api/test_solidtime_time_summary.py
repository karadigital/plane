# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from uuid import uuid4

import pytest
from django.core.cache import cache
from rest_framework import status

from plane.api.views import solidtime as views
from plane.db.models import Issue, Project, ProjectMember, User
from plane.utils.solidtime import SolidtimeClient, SolidtimeError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Scoped Project", identifier="SP", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(project=project, member=create_user, role=15, is_active=True)
    return project


@pytest.fixture
def solidtime(mocker):
    client = mocker.MagicMock(spec=SolidtimeClient)
    client.list_projects.return_value = [{"id": "p1", "name": "SP"}]
    client.aggregate_seconds_by_task.return_value = {"t1": 600, "t2": 60, "t3": 120, "t9": 300}
    client.list_tasks.return_value = [
        {"id": "t1", "name": "[SP-1] One"},
        {"id": "t2", "name": "[SP-1] One (old)"},
        {"id": "t3", "name": "[SP-2] Two"},
        {"id": "t9", "name": "[SP-9] Deleted in Plane"},
    ]
    mocker.patch.object(views.SolidtimeClient, "from_settings", return_value=client)
    return client


def _url(workspace, project_id):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project_id}/time-summary/"


def _issue(project, user, name):
    issue = Issue(name=name, project=project, workspace=project.workspace)
    issue.save(created_by_id=user.id)
    return issue


@pytest.mark.contract
@pytest.mark.django_db
class TestTimeSummary:
    def test_returns_seconds_per_work_item(self, api_key_client, workspace, project, create_user, solidtime):
        one = _issue(project, create_user, "One")
        two = _issue(project, create_user, "Two")
        _issue(project, create_user, "No time")
        nine = _issue(project, create_user, "Deleted")
        nine.delete()

        response = api_key_client.get(_url(workspace, project.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            "configured": True,
            "total_seconds": 780,
            "work_items": [
                {"id": str(one.id), "sequence_id": one.sequence_id, "seconds": 660},
                {"id": str(two.id), "sequence_id": two.sequence_id, "seconds": 120},
            ],
        }

    def test_not_configured(self, api_key_client, workspace, project, mocker):
        mocker.patch.object(views.SolidtimeClient, "from_settings", return_value=None)

        response = api_key_client.get(_url(workspace, project.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"configured": False, "total_seconds": 0, "work_items": []}

    def test_result_is_cached(self, api_key_client, workspace, project, create_user, solidtime):
        _issue(project, create_user, "One")

        first = api_key_client.get(_url(workspace, project.id))
        second = api_key_client.get(_url(workspace, project.id))

        assert first.data == second.data
        assert solidtime.aggregate_seconds_by_task.call_count == 1

    def test_identifier_change_bypasses_cache(self, api_key_client, workspace, project, create_user, solidtime):
        _issue(project, create_user, "One")
        api_key_client.get(_url(workspace, project.id))

        Project.objects.filter(pk=project.pk).update(identifier="SQ")
        solidtime.list_projects.return_value = [{"id": "p1", "name": "SQ"}]
        response = api_key_client.get(_url(workspace, project.id))

        assert solidtime.aggregate_seconds_by_task.call_count == 2
        assert response.data["work_items"] == []

    def test_unavailable_returns_502_and_is_not_cached(self, api_key_client, workspace, project, solidtime):
        solidtime.aggregate_seconds_by_task.side_effect = SolidtimeError("unavailable", "Time is unavailable")

        response = api_key_client.get(_url(workspace, project.id))

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.data == {"error": "Time is unavailable", "code": "solidtime_unavailable"}

        solidtime.aggregate_seconds_by_task.side_effect = None
        assert api_key_client.get(_url(workspace, project.id)).status_code == status.HTTP_200_OK

    def test_non_member_is_forbidden(self, api_key_client, workspace, create_user, solidtime):
        other = User.objects.create(email="other@plane.so", username="other")
        hidden = Project.objects.create(name="Hidden", identifier="HID", workspace=workspace, created_by=other)

        response = api_key_client.get(_url(workspace, hidden.id))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        solidtime.list_projects.assert_not_called()

    def test_unknown_project_is_forbidden(self, api_key_client, workspace, project, solidtime):
        # No membership exists for an unknown id, so the permission check answers before any lookup.
        response = api_key_client.get(_url(workspace, uuid4()))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        solidtime.list_projects.assert_not_called()

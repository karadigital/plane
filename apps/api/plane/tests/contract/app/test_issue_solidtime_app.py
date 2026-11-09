# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for logging time to solidtime (Kara's "Time" app) from a work item."""

from datetime import datetime, timedelta, timezone as dt_timezone
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Issue, Project, ProjectMember, User, WorkspaceMember
from plane.utils.solidtime import SolidtimeError

URL = "/api/workspaces/{slug}/projects/{project_id}/issues/{issue_id}/solidtime-time-entries/"
VIEW = "plane.app.views.issue.solidtime"
PAST_START = "2025-01-06T09:00:00+07:00"


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Scoped Project", identifier="SP", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def issue(db, workspace, project, create_user):
    issue = Issue(name="Fix login", project=project, workspace=workspace)
    issue.save(created_by_id=create_user.id)
    return issue


@pytest.fixture
def url(workspace, project, issue):
    return URL.format(slug=workspace.slug, project_id=project.id, issue_id=issue.id)


@pytest.fixture
def client_configured(mocker):
    """Pretend solidtime is configured; returns the fake client."""
    fake = mocker.MagicMock()
    mocker.patch(f"{VIEW}.SolidtimeClient.from_settings", return_value=fake)
    return fake


@pytest.fixture
def guest_client(db, workspace, project):
    unique_id = uuid4().hex[:8]
    user = User.objects.create(email=f"guest-{unique_id}@plane.so", username=f"guest_{unique_id}")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=5)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=5)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


ENTRY = {
    "id": "e1",
    "start": "2025-01-06T02:00:00Z",
    "end": "2025-01-06T03:30:00Z",
    "duration": 5400,
    "description": "Pairing",
    "member_name": "Akmal",
    "is_running": False,
}


@pytest.mark.contract
class TestIssueSolidtimeTimeEntries:
    @pytest.mark.django_db
    def test_get_not_configured_returns_flag(self, session_client, url, mocker):
        mocker.patch(f"{VIEW}.SolidtimeClient.from_settings", return_value=None)

        response = session_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"configured": False}

    @pytest.mark.django_db
    def test_get_returns_total_and_entries(self, session_client, url, issue, client_configured, mocker):
        get_time = mocker.patch(f"{VIEW}.get_issue_time", return_value={"total_seconds": 5400, "entries": [ENTRY]})

        response = session_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"configured": True, "total_seconds": 5400, "entries": [ENTRY]}
        assert get_time.call_args.args == (client_configured, issue)

    @pytest.mark.django_db
    def test_get_upstream_failure_returns_502(self, session_client, url, client_configured, mocker):
        mocker.patch(f"{VIEW}.get_issue_time", side_effect=SolidtimeError("unavailable", "down"))

        response = session_client.get(url)

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.data["code"] == "solidtime_unavailable"

    @pytest.mark.django_db
    def test_post_logs_time(self, session_client, url, issue, create_user, client_configured, mocker):
        log = mocker.patch(f"{VIEW}.log_issue_time", return_value=ENTRY)

        response = session_client.post(
            url, {"start": PAST_START, "duration_minutes": 90, "description": "Pairing"}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data == ENTRY
        args = log.call_args.args
        assert args[0] is client_configured
        assert args[1] == issue
        assert args[2] == create_user
        assert args[4] == 90
        assert args[5] == "Pairing"

    @pytest.mark.django_db
    def test_post_converts_offset_to_utc(self, session_client, url, client_configured, mocker):
        log = mocker.patch(f"{VIEW}.log_issue_time", return_value=ENTRY)

        session_client.post(url, {"start": PAST_START, "duration_minutes": 90}, format="json")

        start = log.call_args.args[3]
        assert start == datetime(2025, 1, 6, 2, 0, tzinfo=dt_timezone.utc)
        assert log.call_args.args[5] is None

    @pytest.mark.django_db
    def test_post_rejects_future_start(self, session_client, url, client_configured, mocker):
        log = mocker.patch(f"{VIEW}.log_issue_time", return_value=ENTRY)
        future = (timezone.now() + timedelta(hours=1)).isoformat()

        response = session_client.post(url, {"start": future, "duration_minutes": 30}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "start" in response.data
        log.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize("minutes", [0, 1441])
    def test_post_rejects_bad_duration(self, session_client, url, client_configured, mocker, minutes):
        log = mocker.patch(f"{VIEW}.log_issue_time", return_value=ENTRY)

        response = session_client.post(url, {"start": PAST_START, "duration_minutes": minutes}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "duration_minutes" in response.data
        log.assert_not_called()

    @pytest.mark.django_db
    def test_post_member_not_found_returns_400(self, session_client, url, client_configured, mocker):
        mocker.patch(f"{VIEW}.log_issue_time", side_effect=SolidtimeError("member_not_found", "x is not a member"))

        response = session_client.post(url, {"start": PAST_START, "duration_minutes": 30}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data == {"error": "x is not a member", "code": "member_not_found"}

    @pytest.mark.django_db
    def test_post_upstream_failure_returns_502(self, session_client, url, client_configured, mocker):
        mocker.patch(f"{VIEW}.log_issue_time", side_effect=SolidtimeError("unavailable", "down"))

        response = session_client.post(url, {"start": PAST_START, "duration_minutes": 30}, format="json")

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.data["code"] == "solidtime_unavailable"

    @pytest.mark.django_db
    def test_post_not_configured_returns_503(self, session_client, url, mocker):
        mocker.patch(f"{VIEW}.SolidtimeClient.from_settings", return_value=None)

        response = session_client.post(url, {"start": PAST_START, "duration_minutes": 30}, format="json")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.data["code"] == "solidtime_not_configured"

    @pytest.mark.django_db
    def test_unknown_issue_returns_404(self, session_client, workspace, project, client_configured):
        url = URL.format(slug=workspace.slug, project_id=project.id, issue_id=uuid4())

        response = session_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_guest_forbidden(self, guest_client, url, client_configured, mocker):
        log = mocker.patch(f"{VIEW}.log_issue_time", return_value=ENTRY)

        assert guest_client.get(url).status_code == status.HTTP_403_FORBIDDEN
        response = guest_client.post(url, {"start": PAST_START, "duration_minutes": 30}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        log.assert_not_called()

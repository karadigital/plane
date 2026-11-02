# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Completed cycles (end_date in the past) can be reopened/extended.

Only start_date, end_date and sort_order may change on a completed cycle; any
other field keeps the cycle locked. Covers both the web app endpoint
(/api/workspaces/...) and the external API endpoint (/api/v1/workspaces/...).
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status

from plane.db.models import Cycle, Project, ProjectMember

APP_URL = "/api/workspaces/{slug}/projects/{project_id}/cycles/{cycle_id}/"
API_URL = "/api/v1/workspaces/{slug}/projects/{project_id}/cycles/{cycle_id}/"

ENDPOINTS = [
    pytest.param("session_client", APP_URL, id="app"),
    pytest.param("api_key_client", API_URL, id="api"),
]


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Completed Cycle Project",
        identifier="CCP",
        workspace=workspace,
        created_by=create_user,
        cycle_view=True,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def completed_cycle(db, project, create_user):
    return Cycle.objects.create(
        name="Completed Cycle",
        description="Already ended",
        start_date=timezone.now() - timedelta(days=14),
        end_date=timezone.now() - timedelta(days=7),
        sort_order=1000,
        project=project,
        workspace=project.workspace,
        owned_by=create_user,
    )


def _url(template, workspace, project, cycle):
    return template.format(slug=workspace.slug, project_id=project.id, cycle_id=cycle.id)


@pytest.mark.contract
class TestCompletedCycleUpdate:
    @pytest.mark.django_db
    @pytest.mark.parametrize("client_fixture,url_template", ENDPOINTS)
    def test_can_extend_dates(self, request, client_fixture, url_template, workspace, project, completed_cycle):
        client = request.getfixturevalue(client_fixture)
        data = {
            "start_date": (timezone.now() - timedelta(days=14)).isoformat(),
            "end_date": (timezone.now() + timedelta(days=7)).isoformat(),
        }

        response = client.patch(_url(url_template, workspace, project, completed_cycle), data, format="json")

        assert response.status_code == status.HTTP_200_OK, response.data
        completed_cycle.refresh_from_db()
        assert completed_cycle.end_date > timezone.now()

    @pytest.mark.django_db
    def test_can_change_sort_order(self, session_client, workspace, project, completed_cycle):
        # Only the app endpoint writes sort_order; the v1 CycleUpdateSerializer
        # does not expose it.
        response = session_client.patch(
            _url(APP_URL, workspace, project, completed_cycle), {"sort_order": 5000}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        completed_cycle.refresh_from_db()
        assert completed_cycle.sort_order == 5000

    @pytest.mark.django_db
    @pytest.mark.parametrize("client_fixture,url_template", ENDPOINTS)
    @pytest.mark.parametrize(
        "data",
        [
            pytest.param({"name": "Renamed"}, id="other-field"),
            pytest.param({"name": "Renamed", "end_date": None}, id="dates-with-other-field"),
            pytest.param({"name": "Renamed", "sort_order": 5000}, id="sort-order-with-other-field"),
            pytest.param({}, id="empty"),
        ],
    )
    def test_other_fields_stay_locked(
        self, request, client_fixture, url_template, data, workspace, project, completed_cycle
    ):
        client = request.getfixturevalue(client_fixture)
        if "end_date" in data:
            data = {**data, "end_date": (timezone.now() + timedelta(days=7)).isoformat()}
        original_end_date = completed_cycle.end_date

        response = client.patch(_url(url_template, workspace, project, completed_cycle), data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error"] == "The Cycle has already been completed so it cannot be edited"
        completed_cycle.refresh_from_db()
        assert completed_cycle.name == "Completed Cycle"
        assert completed_cycle.sort_order == 1000
        assert completed_cycle.end_date == original_end_date

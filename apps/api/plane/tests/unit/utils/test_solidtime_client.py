# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
import requests
from django.core.cache import cache

from plane.utils.solidtime import SolidtimeClient, SolidtimeError

BASE = "https://time.example/api/v1/organizations/org-1"


def _response(status_code=200, body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body if body is not None else {}
    return response


def _client(*responses):
    session = MagicMock()
    session.request.side_effect = list(responses)
    client = SolidtimeClient("https://time.example/", "tok", "org-1", session=session)
    return client, session


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.unit
class TestSolidtimeClient:
    def test_members_and_projects_are_cached_per_organization(self):
        page = {"data": [{"id": "x"}], "meta": {"current_page": 1, "last_page": 1}}
        client, session = _client(_response(body=page), _response(body=page), _response(body=page))

        assert client.list_projects() == [{"id": "x"}]
        assert client.list_projects() == [{"id": "x"}]
        client.list_members()
        client.list_members()
        assert session.request.call_count == 2

        other_org = SolidtimeClient("https://time.example", "tok", "org-2", session=session)
        other_org.list_projects()
        assert session.request.call_count == 3

    def test_from_settings_returns_none_when_any_setting_blank(self, settings):
        settings.SOLIDTIME_BASE_URL = "https://time.example"
        settings.SOLIDTIME_API_TOKEN = ""
        settings.SOLIDTIME_ORGANIZATION_ID = "org-1"
        assert SolidtimeClient.from_settings() is None

        settings.SOLIDTIME_API_TOKEN = "tok"
        assert isinstance(SolidtimeClient.from_settings(), SolidtimeClient)

    def test_sends_bearer_token_and_org_path(self):
        client, session = _client(_response(body={"data": [], "meta": {"current_page": 1, "last_page": 1}}))

        client.list_members()

        args, kwargs = session.request.call_args
        assert args == ("GET", f"{BASE}/members")
        assert kwargs["headers"]["Authorization"] == "Bearer tok"
        assert kwargs["headers"]["Accept"] == "application/json"

    def test_list_members_follows_pagination(self):
        client, session = _client(
            _response(body={"data": [{"id": "m1"}], "meta": {"current_page": 1, "last_page": 2}}),
            _response(body={"data": [{"id": "m2"}], "meta": {"current_page": 2, "last_page": 2}}),
        )

        members = client.list_members()

        assert [m["id"] for m in members] == ["m1", "m2"]
        assert session.request.call_count == 2
        assert session.request.call_args_list[1].kwargs["params"]["page"] == 2

    def test_list_tasks_requests_all_done_states(self):
        client, session = _client(_response(body={"data": [], "meta": {"current_page": 1, "last_page": 1}}))

        client.list_tasks("p1")

        args, kwargs = session.request.call_args
        assert args == ("GET", f"{BASE}/tasks")
        assert kwargs["params"]["project_id"] == "p1"
        assert kwargs["params"]["done"] == "all"

    def test_list_task_time_entries_filters_by_task(self):
        client, session = _client(_response(body={"data": [{"id": "e1"}], "meta": {"total": 1}}))

        entries = client.list_task_time_entries("t1")

        args, kwargs = session.request.call_args
        assert args == ("GET", f"{BASE}/time-entries")
        assert kwargs["params"]["task_ids[]"] == "t1"
        assert kwargs["params"]["limit"] == 500
        assert entries == [{"id": "e1"}]

    def test_create_task_posts_name_and_project(self):
        client, session = _client(_response(201, {"data": {"id": "t1"}}))

        task = client.create_task("p1", "[KARA-30] Title")

        args, kwargs = session.request.call_args
        assert args == ("POST", f"{BASE}/tasks")
        assert kwargs["json"] == {"name": "[KARA-30] Title", "project_id": "p1"}
        assert task == {"id": "t1"}

    def test_create_time_entry_formats_utc(self):
        client, session = _client(_response(201, {"data": {"id": "e1"}}))
        jakarta = ZoneInfo("Asia/Jakarta")

        entry = client.create_time_entry(
            member_id="m1",
            project_id="p1",
            task_id="t1",
            start=datetime(2026, 11, 9, 9, 0, tzinfo=jakarta),
            end=datetime(2026, 11, 9, 10, 30, tzinfo=jakarta),
            billable=True,
            description="Pairing",
        )

        args, kwargs = session.request.call_args
        assert args == ("POST", f"{BASE}/time-entries")
        assert kwargs["json"] == {
            "member_id": "m1",
            "project_id": "p1",
            "task_id": "t1",
            "start": "2026-11-09T02:00:00Z",
            "end": "2026-11-09T03:30:00Z",
            "billable": True,
            "description": "Pairing",
        }
        assert entry == {"id": "e1"}

    @pytest.mark.parametrize(
        "outcome",
        [
            requests.Timeout("timed out"),
            _response(401),
            _response(429, {"message": "Too Many Attempts."}),
            _response(503),
        ],
        ids=["timeout", "401", "429", "503"],
    )
    def test_request_errors_raise_unavailable(self, outcome):
        client, _ = _client(outcome)

        with pytest.raises(SolidtimeError) as exc_info:
            client.list_projects()

        assert exc_info.value.code == "unavailable"
        assert "tok" not in str(exc_info.value)

    def test_422_raises_invalid_request_with_message(self):
        client, _ = _client(_response(422, {"message": "The name has already been taken."}))

        with pytest.raises(SolidtimeError) as exc_info:
            client.create_task("p1", "dup")

        assert exc_info.value.code == "invalid_request"
        assert exc_info.value.message == "The name has already been taken."


@pytest.mark.unit
class TestSolidtimeClientWrites:
    def test_create_project_posts_identifier_with_defaults(self):
        client, session = _client(_response(201, {"data": {"id": "p9"}}))

        project = client.create_project("NEWP", client_id="c1")

        args, kwargs = session.request.call_args
        assert args == ("POST", f"{BASE}/projects")
        assert kwargs["json"] == {
            "name": "NEWP",
            "color": "#6366f1",
            "is_billable": True,
            "is_public": True,
            "client_id": "c1",
        }
        assert project == {"id": "p9"}

    def test_create_project_invalidates_projects_cache(self):
        page = {"data": [], "meta": {"current_page": 1, "last_page": 1}}
        client, session = _client(_response(body=page), _response(201, {"data": {"id": "p9"}}), _response(body=page))

        client.list_projects()
        client.create_project("NEWP")
        client.list_projects()

        assert session.request.call_count == 3

    def test_update_project_resends_current_fields(self):
        current = {
            "id": "p1",
            "name": "KARA",
            "color": "#ef5350",
            "is_billable": True,
            "is_public": True,
            "client_id": "c1",
            "billable_rate": 15000,
            "estimated_time": None,
        }
        client, session = _client(
            _response(body={"data": current}), _response(body={"data": {**current, "name": "KARX"}})
        )

        client.update_project("p1", name="KARX")

        get_call, put_call = session.request.call_args_list
        assert get_call.args == ("GET", f"{BASE}/projects/p1")
        assert put_call.args == ("PUT", f"{BASE}/projects/p1")
        assert put_call.kwargs["json"] == {
            "name": "KARX",
            "color": "#ef5350",
            "is_billable": True,
            "is_public": True,
            "client_id": "c1",
            "billable_rate": 15000,
        }

    def test_update_project_invalidates_projects_cache(self):
        page = {"data": [], "meta": {"current_page": 1, "last_page": 1}}
        current = {
            "id": "p1",
            "name": "KARA",
            "color": "#ef5350",
            "is_billable": True,
            "is_public": True,
            "client_id": None,
            "billable_rate": None,
        }
        client, session = _client(
            _response(body=page),
            _response(body={"data": current}),
            _response(body={"data": current}),
            _response(body=page),
        )

        client.list_projects()
        client.update_project("p1", name="KARX")
        client.list_projects()

        assert session.request.call_count == 4

    def test_update_task_puts_name(self):
        client, session = _client(_response(body={"data": {"id": "t1"}}))

        client.update_task("t1", "[KARX-1] A")

        args, kwargs = session.request.call_args
        assert args == ("PUT", f"{BASE}/tasks/t1")
        assert kwargs["json"] == {"name": "[KARX-1] A"}


@pytest.mark.unit
class TestSolidtimeClientAggregate:
    def test_aggregate_seconds_by_task_groups_by_task(self):
        body = {
            "data": {
                "seconds": 900,
                "grouped_type": "task",
                "grouped_data": [{"key": "t1", "seconds": 600}, {"key": None, "seconds": 300}],
            }
        }
        client, session = _client(_response(body=body))

        assert client.aggregate_seconds_by_task("p1") == {"t1": 600}

        args, kwargs = session.request.call_args
        assert args == ("GET", f"{BASE}/time-entries/aggregate")
        assert kwargs["params"] == {"group": "task", "project_ids[]": "p1", "active": "false"}

    def test_aggregate_seconds_by_task_without_entries(self):
        client, _ = _client(_response(body={"data": {"seconds": 0, "grouped_data": []}}))

        assert client.aggregate_seconds_by_task("p1") == {}

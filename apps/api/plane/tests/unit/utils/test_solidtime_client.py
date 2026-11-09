# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
import requests

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


@pytest.mark.unit
class TestSolidtimeClient:
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
        [requests.Timeout("timed out"), _response(401), _response(503)],
        ids=["timeout", "401", "503"],
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

# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from plane.utils.solidtime import (
    SolidtimeClient,
    SolidtimeError,
    find_member,
    find_project,
    find_task,
    get_issue_time,
    log_issue_time,
    project_time_by_sequence,
    task_name,
    task_prefix,
)

START = datetime(2025, 1, 6, 2, 0, tzinfo=timezone.utc)
MEMBER = {"id": "m1", "user_id": "u1", "name": "Akmal", "email": "akmal@karadigital.co", "is_placeholder": False}
PROJECT = {"id": "p1", "name": "KARA", "is_billable": True}
TASK = {"id": "t1", "name": "[KARA-30] Enable submit time in Plane", "project_id": "p1"}


def _issue(sequence_id=30, name="Enable submit time in Plane", identifier="KARA", project_name="KARA"):
    project = SimpleNamespace(identifier=identifier, name=project_name)
    return SimpleNamespace(name=name, sequence_id=sequence_id, project=project)


def _user(email="akmal@karadigital.co"):
    return SimpleNamespace(email=email)


def _entry(entry_id, start, duration, end="set", user_id="u1", description=None):
    return {
        "id": entry_id,
        "start": start,
        "end": None if end is None else start,
        "duration": duration,
        "description": description,
        "task_id": "t1",
        "project_id": "p1",
        "user_id": user_id,
    }


def _client(members=None, projects=None, tasks=None, entries=None):
    client = MagicMock(spec=SolidtimeClient)
    client.list_members.return_value = [MEMBER] if members is None else members
    client.list_projects.return_value = [PROJECT] if projects is None else projects
    client.list_tasks.return_value = [TASK] if tasks is None else tasks
    client.list_task_time_entries.return_value = entries or []
    client.create_task.return_value = TASK
    client.create_time_entry.return_value = _entry("e1", "2025-01-06T02:00:00Z", 5400)
    return client


@pytest.mark.unit
class TestMatching:
    def test_task_name_and_prefix(self):
        assert task_prefix(_issue()) == "[KARA-30]"
        assert task_name(_issue()) == "[KARA-30] Enable submit time in Plane"
        assert len(task_name(_issue(name="x" * 300))) == 255

    def test_find_task_matches_prefix_only(self):
        tasks = [{"name": "[KARA-3] Other"}, {"name": "[KARA-30] Old title"}]

        assert find_task(tasks, _issue(sequence_id=30)) == {"name": "[KARA-30] Old title"}
        assert find_task(tasks, _issue(sequence_id=31)) is None

    def test_find_member_ignores_case_and_placeholders(self):
        placeholder = {**MEMBER, "id": "ph", "is_placeholder": True}

        assert find_member([placeholder, MEMBER], " Akmal@KaraDigital.co ") == MEMBER
        assert find_member([placeholder], "akmal@karadigital.co") is None

    def test_find_project_prefers_identifier_then_name(self):
        sandbox = {"id": "s", "name": "Sandbox"}
        by_name = {"id": "n", "name": "Kara Digital"}
        by_identifier = {"id": "k", "name": "kara"}

        assert find_project([sandbox], SimpleNamespace(identifier="SAND", name="Sandbox")) == sandbox
        assert find_project([by_name, by_identifier], SimpleNamespace(identifier="KARA", name="Kara Digital")) == (
            by_identifier
        )
        assert find_project([sandbox], SimpleNamespace(identifier="KARA", name="KARA")) is None

    def test_find_project_prefers_exact_case(self):
        junk = {"id": "j", "name": "will"}
        will = {"id": "w", "name": "WILL"}
        kara = {"id": "k", "name": "Kara"}

        assert find_project([junk, will], SimpleNamespace(identifier="WILL", name="WILL")) == will
        assert find_project([kara], SimpleNamespace(identifier="KARA", name="KARA")) == kara


@pytest.mark.unit
class TestGetIssueTime:
    def test_get_issue_time_without_task_returns_empty_and_creates_nothing(self):
        client = _client(tasks=[])

        assert get_issue_time(client, _issue()) == {"total_seconds": 0, "entries": []}
        client.create_task.assert_not_called()

    def test_get_issue_time_without_project_returns_empty(self):
        client = _client(projects=[])

        assert get_issue_time(client, _issue()) == {"total_seconds": 0, "entries": []}
        client.list_tasks.assert_not_called()

    def test_get_issue_time_totals_and_sorts(self):
        client = _client(
            entries=[
                _entry("old", "2025-01-01T02:00:00Z", 3600),
                _entry("new", "2025-01-03T02:00:00Z", 1800, user_id="u2"),
                _entry("running", "2025-01-02T02:00:00Z", 0, end=None),
            ],
            members=[MEMBER, {**MEMBER, "id": "m2", "user_id": "u2", "name": "Budi"}],
        )

        result = get_issue_time(client, _issue())

        assert result["total_seconds"] == 5400
        assert [e["id"] for e in result["entries"]] == ["new", "running", "old"]
        assert result["entries"][0]["member_name"] == "Budi"
        assert result["entries"][1]["is_running"] is True
        assert result["entries"][2]["is_running"] is False
        assert set(result["entries"][0]) == {
            "id",
            "start",
            "end",
            "duration",
            "description",
            "member_name",
            "is_running",
        }


@pytest.mark.unit
class TestLogIssueTime:
    def test_log_time_uses_existing_task(self):
        client = _client()

        log_issue_time(client, _issue(), _user(), START, 90, "Pairing")

        client.create_task.assert_not_called()
        assert client.create_time_entry.call_args.kwargs["task_id"] == "t1"
        assert client.create_time_entry.call_args.kwargs["description"] == "Pairing"

    def test_log_time_creates_missing_task_then_entry(self):
        client = _client(tasks=[])

        result = log_issue_time(client, _issue(), _user(), START, 90, None)

        client.create_task.assert_called_once_with("p1", "[KARA-30] Enable submit time in Plane")
        kwargs = client.create_time_entry.call_args.kwargs
        assert kwargs["member_id"] == "m1"
        assert kwargs["project_id"] == "p1"
        assert kwargs["task_id"] == "t1"
        assert kwargs["billable"] is True
        assert kwargs["start"] == START
        assert kwargs["end"] - kwargs["start"] == timedelta(minutes=90)
        assert result["id"] == "e1"
        assert result["member_name"] == "Akmal"

    def test_log_time_billable_follows_project(self):
        client = _client(projects=[{**PROJECT, "is_billable": False}])

        log_issue_time(client, _issue(), _user(), START, 30, None)

        assert client.create_time_entry.call_args.kwargs["billable"] is False

    def test_log_time_member_not_found_creates_nothing(self):
        client = _client(members=[])

        with pytest.raises(SolidtimeError) as exc_info:
            log_issue_time(client, _issue(), _user("someone@else.co"), START, 90, None)

        assert exc_info.value.code == "member_not_found"
        assert "someone@else.co" in exc_info.value.message
        client.create_task.assert_not_called()
        client.create_time_entry.assert_not_called()

    def test_log_time_project_not_found(self):
        client = _client(projects=[])

        with pytest.raises(SolidtimeError) as exc_info:
            log_issue_time(client, _issue(), _user(), START, 90, None)

        assert exc_info.value.code == "project_not_found"
        assert "KARA" in exc_info.value.message
        client.create_time_entry.assert_not_called()

    def test_log_time_reuses_task_after_duplicate_create(self):
        client = _client()
        client.list_tasks.side_effect = [[], [TASK]]
        client.create_task.side_effect = SolidtimeError("invalid_request", "The name has already been taken.")

        log_issue_time(client, _issue(), _user(), START, 90, None)

        assert client.create_time_entry.call_args.kwargs["task_id"] == "t1"

    def test_log_time_reraises_when_duplicate_task_still_missing(self):
        client = _client(tasks=[])
        client.create_task.side_effect = SolidtimeError("invalid_request", "bad")

        with pytest.raises(SolidtimeError) as exc_info:
            log_issue_time(client, _issue(), _user(), START, 90, None)

        assert exc_info.value.code == "invalid_request"
        client.create_time_entry.assert_not_called()


@pytest.mark.unit
class TestDuplicatePrefixes:
    def test_find_task_prefers_exact_name_among_duplicates(self):
        stale = {"id": "old", "name": "[KARA-30] Add"}
        exact = {"id": "new", "name": "[KARA-30] Enable submit time in Plane"}

        assert find_task([stale, exact], _issue()) == exact
        assert find_task([stale], _issue()) == stale


def _project(identifier="SP", name="Scoped Project"):
    return SimpleNamespace(identifier=identifier, name=name)


@pytest.mark.unit
class TestProjectTimeBySequence:
    def test_no_solidtime_project_returns_empty(self):
        client = _client(projects=[])

        assert project_time_by_sequence(client, _project()) == {}
        client.aggregate_seconds_by_task.assert_not_called()
        client.list_tasks.assert_not_called()

    def test_no_time_skips_task_listing(self):
        client = _client(projects=[{"id": "p1", "name": "SP"}])
        client.aggregate_seconds_by_task.return_value = {}

        assert project_time_by_sequence(client, _project()) == {}
        client.aggregate_seconds_by_task.assert_called_once_with("p1")
        client.list_tasks.assert_not_called()

    def test_sums_per_sequence_id(self):
        tasks = [
            {"id": "t1", "name": "[SP-1] A"},
            {"id": "t2", "name": "[SP-1] A old"},
            {"id": "t3", "name": "[SP-10] B"},
            {"id": "t4", "name": "[OLD-3] C"},
            {"id": "t5", "name": "no prefix"},
            {"id": "t6", "name": "[SP-2] untracked"},
            {"id": "t7", "name": "[SP-1x] not a work item"},
        ]
        client = _client(projects=[{"id": "p1", "name": "SP"}], tasks=tasks)
        client.aggregate_seconds_by_task.return_value = {
            "t1": 600,
            "t2": 60,
            "t3": 120,
            "t4": 999,
            "t5": 999,
            "t7": 999,
        }

        assert project_time_by_sequence(client, _project()) == {1: 660, 10: 120}
        client.list_tasks.assert_called_once_with("p1")

    def test_identifier_is_matched_literally(self):
        tasks = [{"id": "t1", "name": "[A.B-1] X"}, {"id": "t2", "name": "[AxB-1] Y"}]
        client = _client(projects=[{"id": "p1", "name": "A.B"}], tasks=tasks)
        client.aggregate_seconds_by_task.return_value = {"t1": 60, "t2": 30}

        assert project_time_by_sequence(client, _project(identifier="A.B")) == {1: 60}

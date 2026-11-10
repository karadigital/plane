# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from plane.utils.solidtime import (
    SolidtimeClient,
    SolidtimeError,
    ensure_project,
    get_sync_client,
    reconcile_project,
    rename_project_identifier,
    sync_enabled,
    sync_issue_task,
)

PROJECT = {"id": "p1", "name": "KARA", "is_billable": True}


def _plane_project(identifier="KARA", name="KARA"):
    return SimpleNamespace(identifier=identifier, name=name)


def _issue(sequence_id=30, name="Title", project=None):
    return SimpleNamespace(name=name, sequence_id=sequence_id, project=project or _plane_project())


def _task(task_id, name):
    return {"id": task_id, "name": name, "project_id": "p1"}


def _client(projects=None, tasks=None):
    client = MagicMock(spec=SolidtimeClient)
    client.list_projects.return_value = [PROJECT] if projects is None else projects
    client.list_tasks.return_value = [] if tasks is None else tasks
    client.create_project.side_effect = lambda name, client_id=None: {"id": "new", "name": name}
    client.create_task.side_effect = lambda project_id, name: _task("t-new", name)
    return client


@pytest.fixture
def sync_settings(settings):
    settings.SOLIDTIME_SYNC_ENABLED = True
    settings.SOLIDTIME_SYNC_WORKSPACE_SLUG = "kara-digital"
    settings.SOLIDTIME_DEFAULT_CLIENT_ID = ""
    settings.SOLIDTIME_BASE_URL = "https://time.example"
    settings.SOLIDTIME_API_TOKEN = "tok"
    settings.SOLIDTIME_ORGANIZATION_ID = "org-1"
    return settings


@pytest.mark.unit
class TestSyncSettings:
    @pytest.mark.parametrize(
        "enabled,slug,expected",
        [(False, "kara-digital", False), (True, "", False), (True, "kara-digital", True)],
    )
    def test_sync_enabled_requires_flag_and_slug(self, sync_settings, enabled, slug, expected):
        sync_settings.SOLIDTIME_SYNC_ENABLED = enabled
        sync_settings.SOLIDTIME_SYNC_WORKSPACE_SLUG = slug

        assert sync_enabled() is expected
        assert (get_sync_client() is not None) is expected

    def test_get_sync_client_none_without_solidtime_settings(self, sync_settings):
        sync_settings.SOLIDTIME_API_TOKEN = ""

        assert get_sync_client() is None


@pytest.mark.unit
class TestEnsureProject:
    def test_ensure_project_reuses_name_match(self, sync_settings):
        sandbox = {"id": "s", "name": "Sandbox"}
        client = _client(projects=[sandbox])

        assert ensure_project(client, _plane_project("SAND", "Sandbox")) == sandbox
        client.create_project.assert_not_called()

    def test_ensure_project_creates_identifier_with_default_client(self, sync_settings):
        sync_settings.SOLIDTIME_DEFAULT_CLIENT_ID = "c1"
        client = _client(projects=[])

        ensure_project(client, _plane_project("NEWP", "New project"))

        client.create_project.assert_called_once_with("NEWP", client_id="c1")

    def test_ensure_project_without_default_client(self, sync_settings):
        client = _client(projects=[])

        ensure_project(client, _plane_project("NEWP", "New project"))

        client.create_project.assert_called_once_with("NEWP", client_id=None)


@pytest.mark.unit
class TestSyncIssueTask:
    def test_sync_issue_task_creates_missing_task(self, sync_settings):
        client = _client()

        assert sync_issue_task(client, _issue()) == "created"
        client.create_task.assert_called_once_with("p1", "[KARA-30] Title")

        client = _client()
        sync_issue_task(client, _issue(name="x" * 300))
        assert len(client.create_task.call_args.args[1]) == 255

    def test_sync_issue_task_renames_stale_task(self, sync_settings):
        client = _client(tasks=[_task("t1", "[KARA-30] Old")])

        assert sync_issue_task(client, _issue()) == "renamed"
        client.update_task.assert_called_once_with("t1", "[KARA-30] Title")

    def test_sync_issue_task_unchanged_makes_no_writes(self, sync_settings):
        client = _client(tasks=[_task("t1", "[KARA-30] Title")])

        assert sync_issue_task(client, _issue()) == "unchanged"
        client.create_task.assert_not_called()
        client.update_task.assert_not_called()
        client.create_project.assert_not_called()

    def test_sync_issue_task_prefix_never_collides(self, sync_settings):
        client = _client(tasks=[_task("t3", "[KARA-3] X")])

        assert sync_issue_task(client, _issue(sequence_id=30)) == "created"
        client.create_task.assert_called_once_with("p1", "[KARA-30] Title")
        client.update_task.assert_not_called()

    def test_sync_issue_task_reuses_after_duplicate_422(self, sync_settings):
        client = _client()
        client.list_tasks.side_effect = [[], [_task("t1", "[KARA-30] Title")]]
        client.create_task.side_effect = SolidtimeError("invalid_request", "The name has already been taken.")

        assert sync_issue_task(client, _issue()) == "created"
        client.update_task.assert_not_called()


@pytest.mark.unit
class TestReconcileProject:
    def _issues(self):
        return [_issue(1, "Missing"), _issue(2, "New title"), _issue(3, "Current")]

    def _tasks(self):
        return [_task("t2", "[KARA-2] Old title"), _task("t3", "[KARA-3] Current"), _task("t20", "[KARA-20] Other")]

    def test_reconcile_lists_tasks_once_and_counts(self, sync_settings):
        client = _client(tasks=self._tasks())

        stats = reconcile_project(client, _plane_project(), self._issues())

        assert client.list_tasks.call_count == 1
        assert stats == {"project": "existing", "created": 1, "renamed": 1, "unchanged": 1, "errors": 0}
        client.create_task.assert_called_once_with("p1", "[KARA-1] Missing")
        client.update_task.assert_called_once_with("t2", "[KARA-2] New title")

    def test_reconcile_dry_run_makes_no_writes(self, sync_settings):
        client = _client(tasks=self._tasks())

        stats = reconcile_project(client, _plane_project(), self._issues(), dry_run=True)

        assert stats == {"project": "existing", "created": 1, "renamed": 1, "unchanged": 1, "errors": 0}
        client.create_task.assert_not_called()
        client.update_task.assert_not_called()
        client.create_project.assert_not_called()

        client = _client(projects=[])
        stats = reconcile_project(client, _plane_project(), self._issues(), dry_run=True)

        assert stats == {"project": "would_create", "created": 3, "renamed": 0, "unchanged": 0, "errors": 0}
        client.list_tasks.assert_not_called()
        client.create_project.assert_not_called()

    def test_reconcile_creates_missing_project(self, sync_settings):
        client = _client(projects=[])

        stats = reconcile_project(client, _plane_project(), [_issue(1, "A")])

        assert stats["project"] == "created"
        assert stats["created"] == 1
        client.create_project.assert_called_once_with("KARA", client_id=None)
        client.create_task.assert_called_once_with("new", "[KARA-1] A")

    def test_reconcile_counts_errors_and_continues(self, sync_settings):
        client = _client(tasks=[_task("t1", "[KARA-1] Old"), _task("t2", "[KARA-2] Old")])
        client.update_task.side_effect = [SolidtimeError("unavailable", "down"), _task("t2", "[KARA-2] B")]

        stats = reconcile_project(client, _plane_project(), [_issue(1, "A"), _issue(2, "B")])

        assert stats["errors"] == 1
        assert stats["renamed"] == 1
        assert client.update_task.call_args_list[1] == call("t2", "[KARA-2] B")

    def test_reconcile_pauses_between_writes(self, sync_settings):
        sleep = MagicMock()
        client = _client(tasks=[_task("t2", "[KARA-2] Old")])

        reconcile_project(client, _plane_project(), [_issue(1, "A"), _issue(2, "B")], pause_seconds=0.3, sleep=sleep)
        assert sleep.call_args_list == [call(0.3), call(0.3)]

        sleep = MagicMock()
        client = _client(tasks=[_task("t1", "[KARA-1] A")])
        reconcile_project(client, _plane_project(), [_issue(1, "A")], pause_seconds=0.3, sleep=sleep)
        sleep.assert_not_called()


@pytest.mark.unit
class TestRenameProjectIdentifier:
    def test_identifier_rename_renames_project_and_tasks(self, sync_settings):
        client = _client(tasks=[_task("t1", "[KARA-1] A"), _task("t12", "[KARA-12] B"), _task("tx", "[KARAX-1] keep")])

        stats = rename_project_identifier(client, _plane_project("KARX", "KARX"), "KARA")

        client.update_project.assert_called_once_with("p1", name="KARX")
        assert client.update_task.call_args_list == [call("t1", "[KARX-1] A"), call("t12", "[KARX-12] B")]
        assert stats == {"project_renamed": True, "tasks_renamed": 2, "errors": 0}

    def test_identifier_rename_keeps_name_matched_project(self, sync_settings):
        sandbox = {"id": "s", "name": "Sandbox"}
        client = _client(projects=[sandbox], tasks=[_task("t1", "[SAND-1] A")])

        stats = rename_project_identifier(client, _plane_project("SNDX", "Sandbox"), "SAND")

        client.update_project.assert_not_called()
        client.update_task.assert_called_once_with("t1", "[SNDX-1] A")
        assert stats == {"project_renamed": False, "tasks_renamed": 1, "errors": 0}

    def test_identifier_rename_counts_collisions(self, sync_settings):
        client = _client(tasks=[_task("t1", "[KARA-1] A"), _task("t2", "[KARA-2] B")])
        client.update_task.side_effect = [SolidtimeError("invalid_request", "taken"), _task("t2", "[KARX-2] B")]

        stats = rename_project_identifier(client, _plane_project("KARX", "KARX"), "KARA")

        assert stats == {"project_renamed": True, "tasks_renamed": 1, "errors": 1}


@pytest.mark.unit
class TestLegacyPrefixes:
    def test_identifier_rename_dry_run_makes_no_writes(self, sync_settings):
        client = _client(tasks=[_task("t1", "[KARA-1] A"), _task("t2", "[KARA-2] B")])

        stats = rename_project_identifier(client, _plane_project("KARX", "KARX"), "KARA", dry_run=True)

        assert stats == {"project_renamed": True, "tasks_renamed": 2, "errors": 0}
        client.update_project.assert_not_called()
        client.update_task.assert_not_called()

    def test_reconcile_reports_other_prefixes(self, sync_settings):
        client = _client(
            tasks=[
                _task("s1", "[SOPI-1] A"),
                _task("s2", "[SOPI-2] B"),
                _task("k1", "[KARA-1] A"),
                _task("x", "No prefix at all"),
            ]
        )

        stats = reconcile_project(client, _plane_project(), [_issue(1, "A")], dry_run=True)

        assert stats["other_prefixes"] == {"SOPI": 2}
        assert stats["unchanged"] == 1


@pytest.mark.unit
class TestRenameFixes:
    def test_identifier_rename_renames_project_still_named_old_identifier(self, sync_settings):
        client = _client(tasks=[_task("t1", "[KARA-1] A")])

        stats = rename_project_identifier(client, _plane_project("KARX", "KARA"), "KARA")

        client.update_project.assert_called_once_with("p1", name="KARX")
        client.update_task.assert_called_once_with("t1", "[KARX-1] A")
        assert stats == {"project_renamed": True, "tasks_renamed": 1, "errors": 0}

    def test_identifier_rename_when_new_name_taken_renames_tasks_in_old_project(self, sync_settings):
        old = {"id": "p1", "name": "KARA"}
        taken = {"id": "p2", "name": "KARX"}
        client = _client(projects=[old, taken], tasks=[_task("t1", "[KARA-1] A")])

        stats = rename_project_identifier(client, _plane_project("KARX", "KARX"), "KARA")

        client.update_project.assert_not_called()
        client.list_tasks.assert_called_once_with("p1")
        client.update_task.assert_called_once_with("t1", "[KARX-1] A")
        assert stats == {"project_renamed": False, "tasks_renamed": 1, "errors": 0}

    def test_identifier_rename_raises_when_unavailable(self, sync_settings):
        client = _client(tasks=[_task("t1", "[KARA-1] A"), _task("t2", "[KARA-2] B")])
        client.update_task.side_effect = SolidtimeError("unavailable", "rate limited")

        with pytest.raises(SolidtimeError):
            rename_project_identifier(client, _plane_project("KARX", "KARX"), "KARA")
        assert client.update_task.call_count == 1

    def test_identifier_rename_pauses_between_writes(self, sync_settings):
        sleep = MagicMock()
        client = _client(tasks=[_task("t1", "[KARA-1] A"), _task("t2", "[KARA-2] B")])

        rename_project_identifier(client, _plane_project("KARX", "KARX"), "KARA", pause_seconds=0.3, sleep=sleep)

        assert sleep.call_args_list == [call(0.3), call(0.3)]

    def test_get_sync_client_for_operator_ignores_flag_but_needs_slug(self, sync_settings):
        sync_settings.SOLIDTIME_SYNC_ENABLED = False
        assert get_sync_client() is None
        assert get_sync_client(require_enabled=False) is not None

        sync_settings.SOLIDTIME_SYNC_WORKSPACE_SLUG = ""
        assert get_sync_client(require_enabled=False) is None


@pytest.mark.unit
class TestDuplicatePrefixTasks:
    def test_reconcile_treats_exact_duplicate_as_unchanged(self, sync_settings):
        client = _client(tasks=[_task("old", "[KARA-9] Add"), _task("new", "[KARA-9] Catch up")])

        stats = reconcile_project(client, _plane_project(), [_issue(9, "Catch up")])

        assert stats == {"project": "existing", "created": 0, "renamed": 0, "unchanged": 1, "errors": 0}
        client.update_task.assert_not_called()

    def test_sync_issue_task_treats_exact_duplicate_as_unchanged(self, sync_settings):
        client = _client(tasks=[_task("old", "[KARA-9] Add"), _task("new", "[KARA-9] Catch up")])

        assert sync_issue_task(client, _issue(9, "Catch up")) == "unchanged"
        client.update_task.assert_not_called()


@pytest.mark.unit
class TestEnsureProjectRace:
    def test_ensure_project_reuses_project_created_concurrently(self, sync_settings):
        created_elsewhere = {"id": "p9", "name": "TEMPX"}
        client = _client()
        client.list_projects.side_effect = [[], [created_elsewhere]]
        client.create_project.side_effect = SolidtimeError("invalid_request", "The name has already been taken.")

        assert ensure_project(client, _plane_project("TEMPX", "TEMPX")) == created_elsewhere
        client.invalidate_projects_cache.assert_called_once()

    def test_ensure_project_reraises_when_still_missing(self, sync_settings):
        client = _client(projects=[])
        client.create_project.side_effect = SolidtimeError("invalid_request", "bad")

        with pytest.raises(SolidtimeError):
            ensure_project(client, _plane_project("TEMPX", "TEMPX"))

    def test_sync_issue_task_survives_project_create_race(self, sync_settings):
        created_elsewhere = {"id": "p9", "name": "TEMPX"}
        client = _client()
        client.list_projects.side_effect = [[], [created_elsewhere]]
        client.create_project.side_effect = SolidtimeError("invalid_request", "The name has already been taken.")

        issue = _issue(1, "First Task", project=_plane_project("TEMPX", "TEMPX"))

        assert sync_issue_task(client, issue) == "created"
        client.create_task.assert_called_once_with("p9", "[TEMPX-1] First Task")

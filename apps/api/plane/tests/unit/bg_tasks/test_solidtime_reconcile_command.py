# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

COMMAND = "plane.db.management.commands.solidtime_reconcile"


@pytest.fixture
def configured(mocker):
    return mocker.patch(f"{COMMAND}.get_sync_client", return_value=mocker.MagicMock())


def _run(*args):
    out = StringIO()
    call_command("solidtime_reconcile", *args, stdout=out)
    return out.getvalue()


@pytest.mark.unit
class TestSolidtimeReconcileCommand:
    def test_command_prints_stats_and_total(self, configured, mocker):
        mocker.patch(
            f"{COMMAND}.reconcile_solidtime",
            return_value={
                "KARA": {"project": "existing", "created": 2, "renamed": 1, "unchanged": 7, "errors": 0},
                "SAND": {"project": "would_create", "created": 3, "renamed": 0, "unchanged": 0, "errors": 1},
                "WILL": {"error": "down"},
            },
        )

        output = _run()

        assert "KARA: project=existing created=2 renamed=1 unchanged=7 errors=0" in output
        assert "SAND: project=would_create created=3 renamed=0 unchanged=0 errors=1" in output
        assert "WILL: ERROR down" in output
        assert output.strip().splitlines()[-1] == "Total: created=5 renamed=1 unchanged=7 errors=1"
        assert "DRY RUN" not in output

    def test_command_passes_flags(self, configured, mocker):
        reconcile = mocker.patch(f"{COMMAND}.reconcile_solidtime", return_value={})

        output = _run("--project", "KARA", "--dry-run", "--pause", "0")

        reconcile.assert_called_once_with(project_identifier="KARA", dry_run=True, pause_seconds=0.0)
        assert output.splitlines()[0] == "DRY RUN: no changes will be written"

    def test_command_defaults(self, configured, mocker):
        reconcile = mocker.patch(f"{COMMAND}.reconcile_solidtime", return_value={})

        _run()

        reconcile.assert_called_once_with(project_identifier=None, dry_run=False, pause_seconds=0.3)

    def test_command_fails_when_not_configured(self, mocker):
        mocker.patch(f"{COMMAND}.get_sync_client", return_value=None)

        with pytest.raises(CommandError, match="solidtime sync is not enabled"):
            _run()

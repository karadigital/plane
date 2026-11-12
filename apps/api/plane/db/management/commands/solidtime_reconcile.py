# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Backfill/repair solidtime projects and [IDENT-N] tasks from Plane (replaces `bridge.py sync`)."""

# Django imports
from django.core.management import BaseCommand, CommandError

# Module imports
from plane.bgtasks.solidtime_sync_task import reconcile_solidtime
from plane.utils.solidtime import get_sync_client

COUNTERS = ("created", "renamed", "unchanged", "errors")


class Command(BaseCommand):
    help = "Create missing solidtime projects/tasks and rename stale tasks for the synced Plane workspace."

    def add_arguments(self, parser):
        parser.add_argument("--project", type=str, default=None, help="Only this Plane project identifier")
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing")
        parser.add_argument("--pause", type=float, default=0.3, help="Seconds to wait after each write")
        parser.add_argument(
            "--rename-from",
            type=str,
            default=None,
            help="Old identifier: rename [OLD-N] tasks to the project's current identifier first (needs --project)",
        )

    def handle(self, *args, **options):
        # Runs even while SOLIDTIME_SYNC_ENABLED is off: the cutover dry-run happens before the flip.
        if get_sync_client(require_enabled=False) is None:
            raise CommandError(
                "solidtime sync is not configured "
                "(SOLIDTIME_SYNC_WORKSPACE_SLUG / SOLIDTIME_BASE_URL / SOLIDTIME_API_TOKEN / SOLIDTIME_ORGANIZATION_ID)"
            )
        rename_from = options["rename_from"].upper() if options["rename_from"] else None
        if rename_from and not options["project"]:
            raise CommandError("--rename-from needs --project")
        if options["dry_run"]:
            self.stdout.write("DRY RUN: no changes will be written")

        results = reconcile_solidtime(
            project_identifier=options["project"],
            dry_run=options["dry_run"],
            pause_seconds=options["pause"],
            rename_from=rename_from,
            require_enabled=False,
        )

        totals = dict.fromkeys(COUNTERS, 0)
        for identifier, stats in results.items():
            if "error" in stats:
                self.stdout.write(f"{identifier}: ERROR {stats['error']}")
                continue
            for old, renamed in stats.get("renamed_from", {}).items():
                self.stdout.write(
                    f"{identifier}: renamed from {old}: project_renamed={renamed['project_renamed']} "
                    f"tasks_renamed={renamed['tasks_renamed']} errors={renamed['errors']}"
                )
                totals["errors"] += renamed["errors"]
            if "project" not in stats:
                continue
            counts = " ".join(f"{key}={stats[key]}" for key in COUNTERS)
            self.stdout.write(f"{identifier}: project={stats['project']} {counts}")
            for key in COUNTERS:
                totals[key] += stats[key]
            other = stats.get("other_prefixes") or {}
            if other:
                listed = ", ".join(f"{prefix}={count}" for prefix, count in sorted(other.items()))
                hints = " / ".join(
                    f"solidtime_reconcile --project {identifier} --rename-from {prefix}" for prefix in sorted(other)
                )
                self.stdout.write(
                    f"  ! {identifier}: {sum(other.values())} task(s) use another prefix ({listed}). "
                    f"If the identifier was changed, run: {hints}"
                )
        self.stdout.write("Total: " + " ".join(f"{key}={totals[key]}" for key in COUNTERS))

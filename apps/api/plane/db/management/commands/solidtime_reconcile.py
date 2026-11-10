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

    def handle(self, *args, **options):
        if get_sync_client() is None:
            raise CommandError(
                "solidtime sync is not enabled (SOLIDTIME_SYNC_ENABLED / SOLIDTIME_SYNC_WORKSPACE_SLUG / SOLIDTIME_*)"
            )
        if options["dry_run"]:
            self.stdout.write("DRY RUN: no changes will be written")

        results = reconcile_solidtime(
            project_identifier=options["project"], dry_run=options["dry_run"], pause_seconds=options["pause"]
        )

        totals = dict.fromkeys(COUNTERS, 0)
        for identifier, stats in results.items():
            if "error" in stats:
                self.stdout.write(f"{identifier}: ERROR {stats['error']}")
                continue
            counts = " ".join(f"{key}={stats[key]}" for key in COUNTERS)
            self.stdout.write(f"{identifier}: project={stats['project']} {counts}")
            for key in COUNTERS:
                totals[key] += stats[key]
        self.stdout.write("Total: " + " ".join(f"{key}={totals[key]}" for key in COUNTERS))

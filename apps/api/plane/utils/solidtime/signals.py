# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Enqueue solidtime syncs when a work item or project changes in a way solidtime cares about.

Uses the ChangeTrackerMixin on Issue/Project: ``_changes_on_save`` and ``old_values`` still hold
the pre-save state while post_save runs. Dispatch waits for the transaction to commit, so a
rolled-back create never reaches Celery. bulk_create/QuerySet.update are not seen here; the
daily reconcile picks those up.
"""

# Django imports
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

# Module imports
from plane.db.models import Issue, Project

from .sync import sync_enabled

ISSUE_SYNC_FIELDS = {"name", "project_id", "sequence_id", "is_draft"}


def _changed(instance) -> set[str]:
    return set(getattr(instance, "_changes_on_save", None) or [])


@receiver(post_save, sender=Issue, dispatch_uid="solidtime_enqueue_issue_sync")
def enqueue_issue_sync(sender, instance, created, **kwargs):
    if not sync_enabled() or instance.is_draft or instance.deleted_at:
        return
    if not created and not (_changed(instance) & ISSUE_SYNC_FIELDS):
        return
    from plane.bgtasks.solidtime_sync_task import sync_issue_to_solidtime

    issue_id = str(instance.id)
    transaction.on_commit(lambda: sync_issue_to_solidtime.delay(issue_id))


@receiver(post_save, sender=Project, dispatch_uid="solidtime_enqueue_project_sync")
def enqueue_project_sync(sender, instance, created, **kwargs):
    if not sync_enabled():
        return
    from plane.bgtasks.solidtime_sync_task import sync_project_to_solidtime

    project_id = str(instance.id)
    if created:
        transaction.on_commit(lambda: sync_project_to_solidtime.delay(project_id))
    elif "identifier" in _changed(instance):
        old_identifier = instance.old_values.get("identifier")
        transaction.on_commit(lambda: sync_project_to_solidtime.delay(project_id, old_identifier=old_identifier))

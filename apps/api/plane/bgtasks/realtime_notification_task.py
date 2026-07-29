# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Pushes freshly created in-app notifications to the live server over Redis pub/sub.

The live server holds one event stream per browser tab and fans a message out to the
matching receiver. Delivery is at-most-once on purpose: Redis pub/sub keeps nothing, so a
disconnected browser simply misses the push. Postgres stays the source of truth and the
notification tray still shows everything over REST.

This module is owned by this fork. Keep the hook inside the upstream
``notification_task`` down to a single call so merges stay clean.
"""

import json

from django.core.serializers.json import DjangoJSONEncoder

from plane.settings.redis import redis_instance
from plane.utils.exception_logger import log_exception

# Every live replica subscribes to this one channel and filters by receiver in-process.
REALTIME_NOTIFICATION_CHANNEL = "plane:realtime:notifications"

MENTION_KIND = "mention"
ASSIGNED_KIND = "assigned"


def get_realtime_kind(notification):
    """Return the event kind if this notification should be pushed, else ``None``.

    Only two events qualify. ``sender`` cannot be used to detect an assignment: it records
    the receiver's relationship to the work item and is stamped on every activity, so it
    reads "assigned" for unrelated property changes too.

    A real assignment is the ``assignees`` activity carrying the receiver's id in
    ``new_identifier``. That check also excludes assignee *removal* (which carries
    ``old_identifier`` instead) and the other subscribers who receive the same activity.
    """
    sender = notification.sender or ""
    if "mentioned" in sender:
        return MENTION_KIND

    activity = (notification.data or {}).get("issue_activity") or {}
    if (
        activity.get("field") == "assignees"
        and activity.get("verb") == "updated"
        and activity.get("new_identifier")
        and str(activity.get("new_identifier")) == str(notification.receiver_id)
    ):
        return ASSIGNED_KIND

    return None


def build_realtime_payload(notification, kind, triggered_by):
    """Shape one notification the way the web client expects it.

    Mirrors ``NotificationSerializer`` for the fields the toast and the tray read.
    ``read_at`` must stay an explicit ``None`` because the UI compares it with ``=== null``.

    ``triggered_by`` is passed in rather than read off the notification: the whole batch
    shares one actor, so resolving it here would be one query per receiver.
    """
    return {
        "receiver_id": str(notification.receiver_id),
        "workspace_id": str(notification.workspace_id),
        "kind": kind,
        "notification": {
            "id": str(notification.id),
            "title": notification.title,
            "data": notification.data,
            "entity_identifier": (str(notification.entity_identifier) if notification.entity_identifier else None),
            "entity_name": notification.entity_name,
            "message": notification.message,
            "message_html": notification.message_html,
            "message_stripped": notification.message_stripped,
            "sender": notification.sender,
            "read_at": None,
            "snoozed_till": None,
            "archived_at": None,
            "workspace": str(notification.workspace_id),
            "project": (str(notification.project_id) if notification.project_id else None),
            "triggered_by": (str(notification.triggered_by_id) if notification.triggered_by_id else None),
            "triggered_by_details": (
                {
                    "id": str(triggered_by.id),
                    "first_name": triggered_by.first_name,
                    "last_name": triggered_by.last_name,
                    "avatar": triggered_by.avatar,
                    "avatar_url": triggered_by.avatar_url,
                    "is_bot": triggered_by.is_bot,
                    "display_name": triggered_by.display_name,
                }
                if triggered_by
                else None
            ),
            # Annotated by the REST list endpoint, not stored on the model. The client
            # needs the mention flag, so derive it; the intake flags stay unset.
            "is_mentioned_notification": kind == MENTION_KIND,
            "created_at": notification.created_at,
            "updated_at": notification.updated_at,
        },
    }


def publish_realtime_notifications(notifications):
    """Publish the eligible notifications. Never raises: a push is a nice-to-have.

    ``notifications`` are the in-memory objects handed to ``bulk_create``. Their primary
    keys are UUIDs generated in Python before the INSERT, so no re-query is needed.
    """
    try:
        payloads = []
        # One actor triggers the whole batch, so the User row is fetched at most once.
        actors = {}
        for notification in notifications or []:
            kind = get_realtime_kind(notification)
            if not kind:
                continue

            actor_id = notification.triggered_by_id
            if actor_id is not None and actor_id not in actors:
                actors[actor_id] = notification.triggered_by
            payloads.append(build_realtime_payload(notification, kind, actors.get(actor_id)))

        if not payloads:
            return

        ri = redis_instance()
        for payload in payloads:
            ri.publish(
                REALTIME_NOTIFICATION_CHANNEL,
                json.dumps(payload, cls=DjangoJSONEncoder),
            )
    except Exception as e:
        # A failed push must never break notification creation.
        log_exception(e)
        return

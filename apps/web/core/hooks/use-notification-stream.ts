/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef } from "react";
import { useNavigate } from "react-router";
import { LIVE_BASE_PATH, LIVE_BASE_URL } from "@plane/constants";
import { useLocalStorage } from "@plane/hooks";
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TRealtimeNotificationEvent } from "@plane/types";
import { generateWorkItemLink } from "@plane/utils";
import { showDesktopNotification } from "@/lib/desktop-notification";
import { useWorkspaceNotifications } from "@/hooks/store/notifications";
import { useUser } from "@/hooks/store/user";
import { useWorkspace } from "@/hooks/store/use-workspace";

/** Long enough to outlive a toast, short enough to stay small. */
const SEEN_IDS_LIMIT = 200;

/** Notification toasts sit longer than the 5s default: a queued one must survive the wait. */
const NOTIFICATION_TOAST_TIMEOUT = 10_000;

/** First delay after the server closes the stream for good. Doubles up to the cap. */
const RECONNECT_BASE_DELAY_MS = 5_000;

/** A logged-out tab then costs one request every five minutes, and heals after re-login. */
const RECONNECT_MAX_DELAY_MS = 5 * 60_000;

export const REALTIME_NOTIFICATIONS_ENABLED_KEY = "plane_realtime_notifications_enabled";

const buildStreamUrl = (workspaceId: string): string => {
  const base = LIVE_BASE_URL?.trim() || window.location.origin;
  const url = new URL(base);
  url.pathname = `${LIVE_BASE_PATH}/notifications/stream`;
  url.searchParams.set("workspace_id", workspaceId);
  return url.toString();
};

/**
 * Subscribes to the live server's notification stream for the signed-in user and the
 * workspace they currently have open.
 *
 * Delivery is at-most-once: anything published while the browser is disconnected is gone.
 * That is fine because Postgres holds every notification and the tray reads it over REST.
 * To keep the badge honest, the unread count is refetched whenever the stream connects.
 */
export const useNotificationStream = () => {
  const { data: currentUser } = useUser();
  const { currentWorkspace } = useWorkspace();
  // Reactive, so turning the switch off closes the stream straight away.
  const { storedValue: isEnabled } = useLocalStorage<boolean>(REALTIME_NOTIFICATIONS_ENABLED_KEY, true);
  const { notifications, mutateNotifications, setUnreadNotificationsCount, getUnreadNotificationsCount } =
    useWorkspaceNotifications();
  const { t } = useTranslation();
  const navigate = useNavigate();

  const seenIdsRef = useRef<Set<string>>(new Set());
  // Keeps the latest callbacks reachable without re-opening the stream on every render.
  const handlersRef = useRef({
    notifications,
    mutateNotifications,
    setUnreadNotificationsCount,
    getUnreadNotificationsCount,
    t,
    navigate,
  });
  handlersRef.current = {
    notifications,
    mutateNotifications,
    setUnreadNotificationsCount,
    getUnreadNotificationsCount,
    t,
    navigate,
  };

  const userId = currentUser?.id;
  const workspaceId = currentWorkspace?.id;
  const workspaceSlug = currentWorkspace?.slug;

  useEffect(() => {
    if (!userId || !workspaceId || !workspaceSlug) return;
    if (isEnabled === false) return;

    let source: EventSource | undefined;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let disposed = false;

    const openWorkItem = async (event: TRealtimeNotificationEvent) => {
      const { notification } = event;
      const issue = notification.data?.issue;
      const link = generateWorkItemLink({
        workspaceSlug,
        projectId: notification.project,
        issueId: issue?.id,
        projectIdentifier: issue?.identifier,
        sequenceId: issue?.sequence_id,
      });
      handlersRef.current.navigate(link);

      // Best effort: a failed mark-read must never block navigation.
      try {
        await handlersRef.current.notifications[notification.id]?.markNotificationAsRead(workspaceSlug);
      } catch (error) {
        console.error("useNotificationStream -> markRead -> error", error);
      }
      // markNotificationAsRead decrements whichever counter matches the open tab, which is
      // not necessarily the one this notification incremented. Resync instead of guessing.
      handlersRef.current.getUnreadNotificationsCount(workspaceSlug).catch(() => undefined);
    };

    const handleEvent = (raw: MessageEvent<string>) => {
      let event: TRealtimeNotificationEvent;
      try {
        event = JSON.parse(raw.data) as TRealtimeNotificationEvent;
      } catch (error) {
        console.error("useNotificationStream -> parse -> error", error);
        return;
      }

      // The stream is per-user and spans workspaces. Anything for another workspace must be
      // dropped before it reaches the store, or the per-workspace counters go wrong.
      if (event.workspace_id !== workspaceId) return;

      const notificationId = event.notification?.id;
      if (!notificationId || seenIdsRef.current.has(notificationId)) return;
      seenIdsRef.current.add(notificationId);
      if (seenIdsRef.current.size > SEEN_IDS_LIMIT) {
        const oldest = seenIdsRef.current.values().next().value;
        if (oldest) seenIdsRef.current.delete(oldest);
      }

      handlersRef.current.mutateNotifications([event.notification]);
      handlersRef.current.setUnreadNotificationsCount("increment", 1, event.kind === "mention" ? "mentions" : "all");

      const actor = event.notification.triggered_by_details?.display_name ?? "Someone";
      const issue = event.notification.data?.issue;
      const title =
        event.kind === "mention"
          ? handlersRef.current.t("notification.realtime.mentioned_you", { actor })
          : handlersRef.current.t("notification.realtime.assigned_you", { actor });
      const message = issue ? `${issue.identifier}-${issue.sequence_id} ${issue.name ?? ""}`.trim() : undefined;

      if (document.visibilityState === "visible") {
        setToast({
          type: TOAST_TYPE.INFO,
          title,
          message,
          timeout: NOTIFICATION_TOAST_TIMEOUT,
          onClick: () => openWorkItem(event),
        });
      } else {
        showDesktopNotification({
          title,
          body: message,
          tag: notificationId,
          onClick: () => openWorkItem(event),
        });
      }
    };

    const closeSource = () => {
      source?.removeEventListener("notification", handleEvent as EventListener);
      source?.close();
      source = undefined;
    };

    // A non-200 response puts EventSource in CLOSED for good, so re-opening is on us.
    // The connection also has a 30-minute server-side lifetime, which makes a re-open
    // part of every long session rather than an edge case.
    const scheduleReconnect = () => {
      if (disposed || reconnectTimer) return;
      const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** attempt, RECONNECT_MAX_DELAY_MS);
      attempt += 1;
      // Jitter keeps a restarted live server from being hit by every tab at once.
      reconnectTimer = setTimeout(
        () => {
          reconnectTimer = undefined;
          closeSource();
          connect();
        },
        delay + Math.random() * delay * 0.3
      );
    };

    const connect = () => {
      if (disposed) return;

      try {
        source = new EventSource(buildStreamUrl(workspaceId), { withCredentials: true });
      } catch (error) {
        console.error("useNotificationStream -> open -> error", error);
        scheduleReconnect();
        return;
      }

      source.addEventListener("notification", handleEvent as EventListener);

      source.addEventListener("open", () => {
        attempt = 0;
        // Resync the badge so anything missed while disconnected is corrected.
        handlersRef.current.getUnreadNotificationsCount(workspaceSlug).catch(() => undefined);
      });

      source.addEventListener("error", () => {
        // EventSource reconnects on its own from every other state.
        if (source?.readyState === EventSource.CLOSED) scheduleReconnect();
      });
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      closeSource();
    };
  }, [userId, workspaceId, workspaceSlug, isEnabled]);
};

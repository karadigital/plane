/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Redis } from "ioredis";
import { logger } from "@plane/logger";
import { notificationRegistry } from "@/lib/notification-registry";
import { redisManager } from "@/redis";

/** Must match REALTIME_NOTIFICATION_CHANNEL in plane/bgtasks/realtime_notification_task.py */
export const REALTIME_NOTIFICATION_CHANNEL = "plane:realtime:notifications";

type TRealtimeEnvelope = {
  receiver_id?: string;
  workspace_id?: string;
  kind?: string;
  notification?: { id?: string };
};

let subscriber: Redis | undefined;

const handleMessage = (raw: string): void => {
  let envelope: TRealtimeEnvelope;
  try {
    envelope = JSON.parse(raw) as TRealtimeEnvelope;
  } catch (error) {
    logger.error("NOTIFICATIONS: dropped an unparseable message", error);
    return;
  }

  const receiverId = envelope.receiver_id;
  if (!receiverId) {
    logger.warn("NOTIFICATIONS: dropped a message with no receiver_id");
    return;
  }

  notificationRegistry.broadcastToUser(
    receiverId,
    {
      id: envelope.notification?.id,
      event: "notification",
      data: envelope,
    },
    envelope.workspace_id
  );
};

/**
 * Subscribes on a dedicated connection. A client in subscriber mode cannot run normal
 * commands, so this duplicates the shared client rather than reusing it.
 *
 * Redis is optional for the live server. Without it the streams still open and the tray
 * still works over REST — only the push is missing, which the health endpoint reports.
 */
export const startNotificationSubscriber = async (): Promise<void> => {
  const client = redisManager.getClient();
  if (!client) {
    logger.warn("NOTIFICATIONS: Redis unavailable — real-time notification delivery is disabled");
    return;
  }

  // Never rejects: the live server also runs collaborative editing, and an optional
  // feature failing to subscribe must not take that down with it.
  let connection: Redis | undefined;
  try {
    connection = client.duplicate();
    connection.on("error", (error) => logger.error("NOTIFICATIONS: subscriber connection error", error));
    connection.on("message", (_channel, message) => handleMessage(message));

    // ioredis restores channel subscriptions itself after a reconnect, so this is the
    // only subscribe call the module ever needs.
    await connection.subscribe(REALTIME_NOTIFICATION_CHANNEL);
    subscriber = connection;
    logger.info(`NOTIFICATIONS: subscribed to ${REALTIME_NOTIFICATION_CHANNEL}`);
  } catch (error) {
    logger.error("NOTIFICATIONS: failed to subscribe — real-time notification delivery is disabled", error);
    connection?.disconnect();
  }
};

/** True once the subscribe succeeded. The health endpoint reports it. */
export const isNotificationDeliveryEnabled = (): boolean => subscriber !== undefined;

export const stopNotificationSubscriber = async (): Promise<void> => {
  if (!subscriber) return;
  try {
    await subscriber.quit();
  } catch (error) {
    logger.error("NOTIFICATIONS: error while closing subscriber", error);
    subscriber.disconnect();
  } finally {
    subscriber = undefined;
  }
};

/** Exported for tests. */
export const __handleMessageForTest = handleMessage;

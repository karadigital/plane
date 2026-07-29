/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Redis } from "ioredis";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TSseConnection } from "@/lib/notification-registry";
import { notificationRegistry } from "@/lib/notification-registry";
import {
  REALTIME_NOTIFICATION_CHANNEL,
  __handleMessageForTest,
  isNotificationDeliveryEnabled,
  startNotificationSubscriber,
  stopNotificationSubscriber,
} from "@/lib/notification-subscriber";
import { redisManager } from "@/redis";

vi.mock("@plane/logger", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

vi.mock("@/redis", () => ({
  redisManager: { getClient: vi.fn() },
}));

type TFakeSubscriber = {
  on: ReturnType<typeof vi.fn>;
  subscribe: ReturnType<typeof vi.fn>;
  quit: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
};

const makeFakeClient = (subscribe: () => Promise<unknown>) => {
  const connection: TFakeSubscriber = {
    on: vi.fn(),
    subscribe: vi.fn(subscribe),
    quit: vi.fn(async () => "OK"),
    disconnect: vi.fn(),
  };
  const client = { duplicate: vi.fn(() => connection) };
  vi.mocked(redisManager.getClient).mockReturnValue(client as unknown as Redis);
  return connection;
};

const makeConnection = (userId: string, workspaceId?: string) => {
  const frames: string[] = [];
  const connection: TSseConnection = {
    id: `conn-${userId}`,
    userId,
    workspaceId,
    closed: false,
    write: (chunk: string) => {
      frames.push(chunk);
      return true;
    },
    end: vi.fn(),
    isWritable: () => true,
    onClose: vi.fn(),
  };
  return { connection, frames };
};

describe("startNotificationSubscriber", () => {
  beforeEach(() => {
    vi.mocked(redisManager.getClient).mockReset();
  });

  afterEach(async () => {
    await stopNotificationSubscriber();
  });

  it("stays disabled when Redis is unavailable", async () => {
    vi.mocked(redisManager.getClient).mockReturnValue(null);

    await expect(startNotificationSubscriber()).resolves.toBeUndefined();

    expect(isNotificationDeliveryEnabled()).toBe(false);
  });

  it("degrades to disabled instead of throwing when the subscribe fails", async () => {
    const connection = makeFakeClient(() => Promise.reject(new Error("NOPERM")));

    await expect(startNotificationSubscriber()).resolves.toBeUndefined();

    expect(isNotificationDeliveryEnabled()).toBe(false);
    // The duplicated client would keep reconnecting on its own otherwise.
    expect(connection.disconnect).toHaveBeenCalled();
  });

  it("reports delivery as enabled once subscribed", async () => {
    const connection = makeFakeClient(() => Promise.resolve(1));

    await startNotificationSubscriber();

    expect(connection.subscribe).toHaveBeenCalledWith(REALTIME_NOTIFICATION_CHANNEL);
    expect(isNotificationDeliveryEnabled()).toBe(true);

    await stopNotificationSubscriber();
    expect(isNotificationDeliveryEnabled()).toBe(false);
  });
});

describe("handleMessage", () => {
  beforeEach(() => {
    notificationRegistry.closeAll();
  });

  it("delivers an envelope to the receiver's streams", () => {
    const { connection, frames } = makeConnection("user-1");
    notificationRegistry.add(connection);

    __handleMessageForTest(
      JSON.stringify({
        receiver_id: "user-1",
        workspace_id: "ws-1",
        kind: "mention",
        notification: { id: "notif-1" },
      })
    );

    expect(frames).toHaveLength(1);
    expect(frames[0]).toContain("id: notif-1\nevent: notification\n");
    expect(frames[0]).toContain(`"kind":"mention"`);
  });

  it("skips a stream pinned to another workspace", () => {
    const other = makeConnection("user-1", "ws-2");
    notificationRegistry.add(other.connection);

    __handleMessageForTest(JSON.stringify({ receiver_id: "user-1", workspace_id: "ws-1", notification: { id: "n" } }));

    expect(other.frames).toHaveLength(0);
  });

  it("drops an unparseable message", () => {
    const { connection, frames } = makeConnection("user-1");
    notificationRegistry.add(connection);

    expect(() => __handleMessageForTest("not json")).not.toThrow();

    expect(frames).toHaveLength(0);
  });

  it("drops a message with no receiver_id", () => {
    const { connection, frames } = makeConnection("user-1");
    notificationRegistry.add(connection);

    __handleMessageForTest(JSON.stringify({ workspace_id: "ws-1", notification: { id: "notif-1" } }));

    expect(frames).toHaveLength(0);
  });
});

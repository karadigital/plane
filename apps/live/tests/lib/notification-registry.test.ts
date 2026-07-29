/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TSseConnection } from "@/lib/notification-registry";
import { notificationRegistry } from "@/lib/notification-registry";

type TFakeConnection = TSseConnection & { frames: string[] };

const makeConnection = (userId: string, overrides: Partial<TSseConnection> = {}): TFakeConnection => {
  const frames: string[] = [];
  const connection: TFakeConnection = {
    id: `conn-${Math.random().toString(16).slice(2)}`,
    userId,
    closed: false,
    frames,
    write: (chunk: string) => {
      frames.push(chunk);
      return true;
    },
    end: vi.fn(),
    isWritable: () => true,
    onClose: vi.fn(),
    ...overrides,
  };
  return connection;
};

describe("notificationRegistry", () => {
  beforeEach(() => {
    notificationRegistry.closeAll();
  });

  it("delivers an event to every stream a user has open", () => {
    const first = makeConnection("user-1");
    const second = makeConnection("user-1");
    notificationRegistry.add(first);
    notificationRegistry.add(second);

    const delivered = notificationRegistry.broadcastToUser("user-1", {
      id: "notif-1",
      event: "notification",
      data: { hello: "world" },
    });

    expect(delivered).toBe(2);
    expect(first.frames[0]).toBe(`id: notif-1\nevent: notification\ndata: {"hello":"world"}\n\n`);
    expect(second.frames).toHaveLength(1);
  });

  it("does not deliver to a different user", () => {
    const mine = makeConnection("user-1");
    const theirs = makeConnection("user-2");
    notificationRegistry.add(mine);
    notificationRegistry.add(theirs);

    notificationRegistry.broadcastToUser("user-1", { event: "notification", data: {} });

    expect(mine.frames).toHaveLength(1);
    expect(theirs.frames).toHaveLength(0);
  });

  it("skips connections pinned to a different workspace", () => {
    const workspaceA = makeConnection("user-1", { workspaceId: "ws-a" });
    const workspaceB = makeConnection("user-1", { workspaceId: "ws-b" });
    const unpinned = makeConnection("user-1");
    notificationRegistry.add(workspaceA);
    notificationRegistry.add(workspaceB);
    notificationRegistry.add(unpinned);

    const delivered = notificationRegistry.broadcastToUser("user-1", { event: "notification", data: {} }, "ws-a");

    expect(delivered).toBe(2);
    expect(workspaceB.frames).toHaveLength(0);
  });

  it("drops a dead socket without breaking delivery to the user's other tabs", () => {
    const dead = makeConnection("user-1", {
      write: () => {
        throw new Error("socket closed");
      },
    });
    const alive = makeConnection("user-1");
    notificationRegistry.add(dead);
    notificationRegistry.add(alive);

    const delivered = notificationRegistry.broadcastToUser("user-1", { event: "notification", data: {} });

    expect(delivered).toBe(1);
    expect(alive.frames).toHaveLength(1);
    expect(notificationRegistry.size()).toBe(1);
  });

  it("removes a connection and forgets the user once the last one goes", () => {
    const connection = makeConnection("user-1");
    notificationRegistry.add(connection);
    expect(notificationRegistry.userCount()).toBe(1);

    notificationRegistry.remove(connection);

    expect(notificationRegistry.size()).toBe(0);
    expect(notificationRegistry.userCount()).toBe(0);
  });

  it("evicts the oldest connection once a user hits the cap", () => {
    const connections = Array.from({ length: 8 }, () => makeConnection("user-1"));
    connections.forEach((connection) => notificationRegistry.add(connection));
    expect(notificationRegistry.size()).toBe(8);

    const newest = makeConnection("user-1");
    notificationRegistry.add(newest);

    expect(notificationRegistry.size()).toBe(8);
    expect(connections[0].end).toHaveBeenCalled();
    expect(connections[1].end).not.toHaveBeenCalled();
  });

  it("closeAll ends every stream so the http server can shut down", () => {
    const first = makeConnection("user-1");
    const second = makeConnection("user-2");
    notificationRegistry.add(first);
    notificationRegistry.add(second);

    notificationRegistry.closeAll();

    expect(first.end).toHaveBeenCalled();
    expect(second.end).toHaveBeenCalled();
    expect(notificationRegistry.size()).toBe(0);
  });
});

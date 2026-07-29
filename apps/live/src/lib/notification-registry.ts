/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { logger } from "@plane/logger";

/** One browser tab holding an open event stream. */
export type TSseConnection = {
  id: string;
  userId: string;
  /** Optional server-side prefilter. Never an authorization input — the stream is already scoped to the user. */
  workspaceId?: string;
  write: (chunk: string) => boolean;
  end: () => void;
  isWritable: () => boolean;
  onClose: () => void;
  closed: boolean;
};

export type TSseEvent = {
  /** Frame id, used by the browser to drop duplicates. */
  id?: string;
  event: string;
  data: unknown;
};

/**
 * A user with many tabs open holds many connections. Cap it so one runaway client
 * cannot pin an unbounded number of sockets, each of which costs a Django auth call
 * on every reconnect.
 */
const MAX_CONNECTIONS_PER_USER = 8;

const serializeEvent = (event: TSseEvent): string => {
  const idLine = event.id ? `id: ${event.id}\n` : "";
  return `${idLine}event: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`;
};

class NotificationRegistry {
  private connectionsByUser = new Map<string, Set<TSseConnection>>();

  add(connection: TSseConnection): void {
    let connections = this.connectionsByUser.get(connection.userId);
    if (!connections) {
      connections = new Set();
      this.connectionsByUser.set(connection.userId, connections);
    }

    // A Set preserves insertion order, so the first entry is the oldest.
    while (connections.size >= MAX_CONNECTIONS_PER_USER) {
      const oldest = connections.values().next().value;
      if (!oldest) break;
      connections.delete(oldest);
      this.closeConnection(oldest);
      logger.warn(`NOTIFICATIONS: connection cap reached for user ${connection.userId}, evicted oldest`);
    }

    connections.add(connection);
  }

  remove(connection: TSseConnection): void {
    const connections = this.connectionsByUser.get(connection.userId);
    if (!connections) return;
    connections.delete(connection);
    if (connections.size === 0) this.connectionsByUser.delete(connection.userId);
  }

  /**
   * Writes an event to every stream the user has open. A dead socket is dropped and must
   * never stop delivery to that user's other tabs.
   */
  broadcastToUser(userId: string, event: TSseEvent, workspaceId?: string): number {
    const connections = this.connectionsByUser.get(userId);
    if (!connections || connections.size === 0) return 0;

    const frame = serializeEvent(event);
    let delivered = 0;

    // Deleting from a Set while iterating it is safe: entries removed before being
    // reached are skipped, and removing the current entry does not disturb the iterator.
    for (const connection of connections) {
      if (workspaceId && connection.workspaceId && connection.workspaceId !== workspaceId) continue;
      if (connection.closed || !connection.isWritable()) {
        connections.delete(connection);
        continue;
      }
      try {
        connection.write(frame);
        delivered += 1;
      } catch (error) {
        logger.error("NOTIFICATIONS: failed to write to stream, dropping connection", error);
        connections.delete(connection);
        this.closeConnection(connection);
      }
    }

    if (connections.size === 0) this.connectionsByUser.delete(userId);
    return delivered;
  }

  size(): number {
    let total = 0;
    for (const connections of this.connectionsByUser.values()) total += connections.size;
    return total;
  }

  userCount(): number {
    return this.connectionsByUser.size;
  }

  /**
   * Node's `server.close()` never resolves while keep-alive sockets are open, so every
   * stream must be ended before the HTTP server is asked to shut down.
   */
  closeAll(): void {
    for (const connections of this.connectionsByUser.values()) {
      for (const connection of connections) this.closeConnection(connection);
    }
    this.connectionsByUser.clear();
  }

  private closeConnection(connection: TSseConnection): void {
    try {
      connection.onClose();
      if (connection.isWritable()) connection.end();
    } catch (error) {
      logger.error("NOTIFICATIONS: error while closing stream", error);
    }
  }
}

export const notificationRegistry = new NotificationRegistry();

/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Request, Response } from "express";
import { Controller, Get, Middleware, Post } from "@plane/decorators";
import { logger } from "@plane/logger";
import { resolveCachedUserId } from "@/lib/auth-cache";
import { requireSecretKey } from "@/lib/auth-middleware";
import type { TSseConnection } from "@/lib/notification-registry";
import { notificationRegistry } from "@/lib/notification-registry";
import { UserService } from "@/services/user.service";

const SSE_HEADERS = {
  "Content-Type": "text/event-stream; charset=utf-8",
  // `no-transform` stops compression middleware and intermediary proxies from buffering
  // the body. The compression filter in server.ts covers this too — belt and braces,
  // because either one alone is enough and a future endpoint may forget the header.
  "Cache-Control": "no-cache, no-transform",
  Connection: "keep-alive",
  // nginx-fronted deployments buffer proxied responses by default. Caddy does not.
  "X-Accel-Buffering": "no",
};

/** Below the common 60s idle timeout of load balancers and reverse proxies. */
const HEARTBEAT_INTERVAL_MS = 25_000;

/**
 * Streams are authorized once, at open. Recycling them bounds how long a revoked session
 * can keep receiving events — EventSource reconnects on its own and re-authenticates.
 */
const MAX_CONNECTION_LIFETIME_MS = 30 * 60 * 1000;

const userService = new UserService();

const resolveUserId = async (cookie: string): Promise<string | undefined> =>
  resolveCachedUserId(cookie, async (c) => (await userService.currentUser(c))?.id);

@Controller("/notifications")
export class NotificationController {
  @Get("/stream")
  async stream(req: Request, res: Response) {
    const cookie = req.headers.cookie;
    if (!cookie) {
      res.status(401).json({ message: "Authentication required" });
      return;
    }

    let userId: string | undefined;
    try {
      userId = await resolveUserId(cookie);
    } catch {
      // UserService already logs the underlying failure.
      res.status(401).json({ message: "Authentication failed" });
      return;
    }
    if (!userId) {
      res.status(401).json({ message: "Authentication failed" });
      return;
    }

    const workspaceId = typeof req.query.workspace_id === "string" ? req.query.workspace_id : undefined;

    res.writeHead(200, SSE_HEADERS);
    res.flushHeaders();
    res.socket?.setNoDelay(true);

    let heartbeat: NodeJS.Timeout | undefined;
    let lifetime: NodeJS.Timeout | undefined;

    const connection: TSseConnection = {
      id: crypto.randomUUID(),
      userId,
      workspaceId,
      closed: false,
      write: (chunk) => res.write(chunk),
      end: () => res.end(),
      isWritable: () => !res.writableEnded,
      onClose: () => cleanup(),
    };

    function cleanup() {
      if (connection.closed) return;
      connection.closed = true;
      if (heartbeat) clearInterval(heartbeat);
      if (lifetime) clearTimeout(lifetime);
      notificationRegistry.remove(connection);
      if (!res.writableEnded) res.end();
    }

    req.on("close", cleanup);
    res.on("error", cleanup);

    // Spreading reconnects stops a live restart from bringing every browser back at the
    // same instant, each triggering a Django auth call.
    const retryMs = 10_000 + Math.floor(Math.random() * 10_000);
    res.write(`retry: ${retryMs}\n\n`);
    res.write(`event: connected\ndata: ${JSON.stringify({ user_id: userId })}\n\n`);

    heartbeat = setInterval(() => {
      if (connection.closed || res.writableEnded) return;
      res.write(":ping\n\n");
    }, HEARTBEAT_INTERVAL_MS);
    heartbeat.unref();

    lifetime = setTimeout(cleanup, MAX_CONNECTION_LIFETIME_MS);
    lifetime.unref();

    notificationRegistry.add(connection);
    logger.info(`NOTIFICATIONS: stream opened for user ${userId} (${notificationRegistry.size()} open)`);
  }

  /**
   * Server-to-server injector. Phase 2 delivers the same envelope over Redis; this stays
   * as the manual way to exercise the stream without touching Django.
   */
  @Post("/publish")
  @Middleware(requireSecretKey)
  async publish(req: Request, res: Response) {
    const body = req.body as { receiver_id?: string; workspace_id?: string } | undefined;
    const receiverId = body?.receiver_id;

    if (!receiverId) {
      res.status(400).json({ message: "receiver_id is required" });
      return;
    }

    const delivered = notificationRegistry.broadcastToUser(
      receiverId,
      { event: "notification", data: body },
      body?.workspace_id
    );

    res.status(200).json({ delivered });
  }
}

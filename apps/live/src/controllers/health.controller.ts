/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Request, Response } from "express";
import { Controller, Get } from "@plane/decorators";
import { env } from "@/env";
import { notificationRegistry } from "@/lib/notification-registry";
import { isNotificationDeliveryEnabled } from "@/lib/notification-subscriber";
import { redisManager } from "@/redis";

@Controller("/health")
export class HealthController {
  @Get("/")
  async healthCheck(_req: Request, res: Response) {
    res.status(200).json({
      status: "OK",
      timestamp: new Date().toISOString(),
      version: env.APP_VERSION,
      // Real-time notification delivery is silently disabled without Redis, so surface it.
      // Redis can be connected while the subscribe itself failed, hence the second field.
      redis: redisManager.isClientConnected() ? "connected" : "disabled",
      notifications: isNotificationDeliveryEnabled() ? "enabled" : "disabled",
      sse_connections: notificationRegistry.size(),
      sse_users: notificationRegistry.userCount(),
    });
  }
}

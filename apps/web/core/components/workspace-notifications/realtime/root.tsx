/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// hooks
import { useNotificationStream } from "@/hooks/use-notification-stream";

/**
 * Holds the live notification stream open for the signed-in user. Renders nothing.
 *
 * Mounted inside the workspace layout rather than the app provider so the user and the
 * workspace are both known — the app provider also runs on sign-in and onboarding, where
 * there is no workspace and every connection would 401.
 */
export const NotificationRealtimeListener = observer(function NotificationRealtimeListener() {
  useNotificationStream();
  return null;
});

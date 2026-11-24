/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TIssue, TStateGroups } from "@plane/types";

/**
 * Returns the start date to send along with a state change, or undefined when none should be added.
 * Mirrors the backend rule in Issue._sync_start_date so the screen updates before the response.
 */
export const getAutoStartDate = (
  issue: TIssue | undefined,
  data: Partial<TIssue>,
  stateGroup: TStateGroups | undefined,
  today: string
): string | undefined => {
  if (!issue || !data.state_id || data.state_id === issue.state_id) return undefined;
  if (stateGroup !== "started" || issue.start_date || "start_date" in data) return undefined;
  if (data.target_date && data.target_date < today) return undefined;
  return today;
};

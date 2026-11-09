/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/** A time entry in solidtime (Kara's "Time" app) logged against a work item. */
export type TSolidtimeTimeEntry = {
  id: string;
  start: string;
  end: string | null;
  /** Seconds. */
  duration: number;
  description: string | null;
  member_name: string | null;
  is_running: boolean;
};

export type TIssueSolidtimeTime =
  | { configured: false }
  | { configured: true; total_seconds: number; entries: TSolidtimeTimeEntry[] };

export type TSolidtimeTimeEntryCreate = {
  /** ISO 8601 with offset. */
  start: string;
  duration_minutes: number;
  description?: string;
};

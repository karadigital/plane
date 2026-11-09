/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { convertMinutesToHoursMinutesString, renderFormattedDate, renderFormattedTime } from "@plane/utils";

export const MAX_DURATION_MINUTES = 24 * 60;

/** "1h 30m", or "0m" for less than a minute. */
export const formatTrackedSeconds = (seconds: number): string =>
  convertMinutesToHoursMinutesString(Math.floor(seconds / 60)).trim() || "0m";

const pad = (value: number) => String(value).padStart(2, "0");

/** Local date ("YYYY-MM-DD") and time ("HH:mm") one hour ago, rounded down to 15 minutes. */
export const getDefaultStart = (now: Date = new Date()): { date: string; time: string } => {
  const start = new Date(now.getTime() - 60 * 60 * 1000);
  start.setMinutes(Math.floor(start.getMinutes() / 15) * 15, 0, 0);
  return {
    date: `${start.getFullYear()}-${pad(start.getMonth() + 1)}-${pad(start.getDate())}`,
    time: `${pad(start.getHours())}:${pad(start.getMinutes())}`,
  };
};

/**
 * An entry's start ("2026-11-09T23:00:00Z") as local date and time, e.g. "Nov 10, 2026 06:00" in WIB.
 * renderFormattedDate must get a Date: given a string it takes the UTC calendar date.
 */
export const formatEntryStart = (start: string): string => {
  const date = new Date(start);
  return `${renderFormattedDate(date) ?? ""} ${renderFormattedTime(date)}`.trim();
};

/** Local date + time inputs → ISO 8601 (UTC) string, or null when invalid. */
export const toStartIso = (date: string, time: string): string | null => {
  const start = new Date(`${date}T${time}`);
  return Number.isNaN(start.getTime()) ? null : start.toISOString();
};

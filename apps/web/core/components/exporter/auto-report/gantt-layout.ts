/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TGanttInput = { id: string; start_date: string | null; target_date: string | null };
export type TGanttRow = { id: string; leftPct: number; widthPct: number; isMarker: boolean };
export type TGanttTick = { date: string; leftPct: number };
export type TGanttLayout = { rows: TGanttRow[]; ticks: TGanttTick[]; noDateCount: number; outOfRangeCount: number };

const DAY_MS = 24 * 60 * 60 * 1000;

// "YYYY-MM-DD" parsed as a UTC day number, so the browser timezone cannot shift it.
const toDay = (value: string) => Math.round(Date.parse(`${value}T00:00:00Z`) / DAY_MS);
const toDateString = (day: number) => new Date(day * DAY_MS).toISOString().slice(0, 10);

export function buildGanttLayout(items: TGanttInput[], axisStart: string, axisEnd: string): TGanttLayout {
  const first = toDay(axisStart);
  const last = toDay(axisEnd);
  const totalDays = last - first + 1;
  const pct = (day: number) => ((day - first) / totalDays) * 100;

  const rows: TGanttRow[] = [];
  let noDateCount = 0;
  let outOfRangeCount = 0;
  for (const item of items) {
    const startValue = item.start_date ?? item.target_date;
    if (!startValue) {
      noDateCount++;
      continue;
    }
    const start = toDay(startValue);
    const due = item.start_date && item.target_date ? toDay(item.target_date) : start;
    const isMarker = due <= start;
    const end = isMarker ? start : due;
    if (end < first || start > last) {
      outOfRangeCount++;
      continue;
    }
    const left = Math.max(start, first);
    const right = Math.min(end, last) + 1;
    rows.push({ id: item.id, leftPct: pct(left), widthPct: pct(right) - pct(left), isMarker });
  }

  const ticks: TGanttTick[] = [];
  for (let day = first; day <= last; day += 7) ticks.push({ date: toDateString(day), leftPct: pct(day) });

  return { rows, ticks, noDateCount, outOfRangeCount };
}

export const collapseWhitespace = (value: string) => value.replace(/\s+/g, " ").trim();

export function formatRowLabel(key: string, name: string, maxLength = 60): string {
  const label = collapseWhitespace(`${key} ${name}`);
  return label.length > maxLength ? `${label.slice(0, maxLength - 1)}…` : label;
}

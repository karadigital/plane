/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { afterEach, describe, expect, it } from "vitest";
import { buildGanttLayout, collapseWhitespace, formatRowLabel } from "@/components/exporter/auto-report/gantt-layout";

// 30-day axis: one day is 100 / 30 percent wide.
const AXIS_START = "2026-11-01";
const AXIS_END = "2026-11-30";
const DAY = 100 / 30;

const item = (id: string, start_date: string | null, target_date: string | null) => ({ id, start_date, target_date });

describe("buildGanttLayout", () => {
  const originalTz = process.env.TZ;
  afterEach(() => {
    process.env.TZ = originalTz;
  });

  it("draws a bar from start to due date", () => {
    const { rows } = buildGanttLayout([item("a", "2026-11-03", "2026-11-05")], AXIS_START, AXIS_END);
    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe("a");
    expect(rows[0].isMarker).toBe(false);
    expect(rows[0].leftPct).toBeCloseTo(2 * DAY);
    expect(rows[0].widthPct).toBeCloseTo(3 * DAY);
  });

  it("draws a one-day marker when only the start date is set", () => {
    const { rows } = buildGanttLayout([item("a", "2026-11-10", null)], AXIS_START, AXIS_END);
    expect(rows).toHaveLength(1);
    expect(rows[0].isMarker).toBe(true);
    expect(rows[0].leftPct).toBeCloseTo(9 * DAY);
    expect(rows[0].widthPct).toBeCloseTo(DAY);
  });

  it("draws a one-day marker when only the due date is set", () => {
    const { rows } = buildGanttLayout([item("a", null, "2026-11-30")], AXIS_START, AXIS_END);
    expect(rows).toHaveLength(1);
    expect(rows[0].isMarker).toBe(true);
    expect(rows[0].leftPct).toBeCloseTo(29 * DAY);
    expect(rows[0].widthPct).toBeCloseTo(DAY);
  });

  it("does not draw an item without dates and counts it", () => {
    const layout = buildGanttLayout([item("a", null, null), item("b", "2026-11-02", null)], AXIS_START, AXIS_END);
    expect(layout.rows.map((row) => row.id)).toEqual(["b"]);
    expect(layout.noDateCount).toBe(1);
    expect(layout.outOfRangeCount).toBe(0);
  });

  it("draws a one-day marker at the start date when the due date is before it", () => {
    const { rows } = buildGanttLayout([item("a", "2026-11-10", "2026-11-04")], AXIS_START, AXIS_END);
    expect(rows).toHaveLength(1);
    expect(rows[0].isMarker).toBe(true);
    expect(rows[0].leftPct).toBeCloseTo(9 * DAY);
    expect(rows[0].widthPct).toBeCloseTo(DAY);
  });

  it("clips a bar that is partly outside the axis", () => {
    const { rows } = buildGanttLayout(
      [item("before", "2026-10-20", "2026-11-02"), item("after", "2026-11-29", "2026-12-20")],
      AXIS_START,
      AXIS_END
    );
    expect(rows).toHaveLength(2);
    expect(rows[0].leftPct).toBeCloseTo(0);
    expect(rows[0].widthPct).toBeCloseTo(2 * DAY);
    expect(rows[1].leftPct).toBeCloseTo(28 * DAY);
    expect(rows[1].widthPct).toBeCloseTo(2 * DAY);
  });

  it("does not draw a range fully before or after the axis and counts it", () => {
    const layout = buildGanttLayout(
      [item("before", "2026-10-01", "2026-10-31"), item("after", "2026-12-01", null), item("in", "2026-11-01", null)],
      AXIS_START,
      AXIS_END
    );
    expect(layout.rows.map((row) => row.id)).toEqual(["in"]);
    expect(layout.outOfRangeCount).toBe(2);
    expect(layout.noDateCount).toBe(0);
  });

  it("returns week ticks from the axis start", () => {
    const { ticks } = buildGanttLayout([], AXIS_START, AXIS_END);
    expect(ticks.map((tick) => tick.date)).toEqual([
      "2026-11-01",
      "2026-11-08",
      "2026-11-15",
      "2026-11-22",
      "2026-11-29",
    ]);
    expect(ticks[1].leftPct).toBeCloseTo(7 * DAY);
  });

  it("returns an empty layout for no items", () => {
    const layout = buildGanttLayout([], AXIS_START, AXIS_END);
    expect(layout.rows).toEqual([]);
    expect(layout.noDateCount).toBe(0);
    expect(layout.outOfRangeCount).toBe(0);
  });

  it.each(["America/Los_Angeles", "Asia/Bangkok"])("parses dates as UTC days in timezone %s", (tz) => {
    process.env.TZ = tz;
    const { rows, ticks } = buildGanttLayout([item("a", "2026-11-03", "2026-11-05")], AXIS_START, AXIS_END);
    expect(ticks[0].date).toBe(AXIS_START);
    expect(rows).toHaveLength(1);
    expect(rows[0].leftPct).toBeCloseTo(2 * DAY);
    expect(rows[0].widthPct).toBeCloseTo(3 * DAY);
  });
});

describe("formatRowLabel", () => {
  it("joins key and name", () => {
    expect(formatRowLabel("WEB-1", "Login page")).toBe("WEB-1 Login page");
  });

  it("collapses newlines, CRLF and repeated spaces into one line", () => {
    expect(formatRowLabel("WEB-1", "Line one\r\nLine  two\nthree")).toBe("WEB-1 Line one Line two three");
  });

  it("truncates a long name", () => {
    const label = formatRowLabel("WEB-1", "x".repeat(100), 20);
    expect(label).toHaveLength(20);
    expect(label.endsWith("…")).toBe(true);
    expect(label.startsWith("WEB-1 x")).toBe(true);
  });
});

describe("collapseWhitespace", () => {
  it("collapses newlines, CRLF and repeated spaces and trims", () => {
    expect(collapseWhitespace("  Line one\r\nLine  two\nthree ")).toBe("Line one Line two three");
  });
});

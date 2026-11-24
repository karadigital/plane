/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { describe, expect, it } from "vitest";
import type { TIssue } from "@plane/types";
import { getAutoStartDate } from "@/store/issue/helpers/auto-start-date";

const TODAY = "2026-11-24";
const issue = { id: "i1", state_id: "todo", start_date: null } as unknown as TIssue;

describe("getAutoStartDate", () => {
  it("returns today when the item moves into a started state with no start date", () => {
    expect(getAutoStartDate(issue, { state_id: "doing" }, "started", TODAY)).toBe(TODAY);
  });

  it("returns undefined when the item already has a start date", () => {
    const withDate = { ...issue, start_date: "2026-01-01" } as TIssue;
    expect(getAutoStartDate(withDate, { state_id: "doing" }, "started", TODAY)).toBeUndefined();
  });

  it("returns undefined when data carries start_date, even null", () => {
    expect(getAutoStartDate(issue, { state_id: "doing", start_date: null }, "started", TODAY)).toBeUndefined();
    expect(getAutoStartDate(issue, { state_id: "doing", start_date: "2026-02-02" }, "started", TODAY)).toBeUndefined();
  });

  it("returns undefined when data carries a target_date before today", () => {
    expect(getAutoStartDate(issue, { state_id: "doing", target_date: "2026-11-23" }, "started", TODAY)).toBeUndefined();
  });

  it("returns today when data carries a target_date of today or later", () => {
    expect(getAutoStartDate(issue, { state_id: "doing", target_date: TODAY }, "started", TODAY)).toBe(TODAY);
    expect(getAutoStartDate(issue, { state_id: "doing", target_date: "2026-12-01" }, "started", TODAY)).toBe(TODAY);
  });

  it("returns undefined when data has no state_id", () => {
    expect(getAutoStartDate(issue, { name: "x" }, "started", TODAY)).toBeUndefined();
  });

  it("returns undefined when the state_id does not change", () => {
    expect(getAutoStartDate(issue, { state_id: "todo" }, "started", TODAY)).toBeUndefined();
  });

  it("returns undefined when the state group is unknown", () => {
    expect(getAutoStartDate(issue, { state_id: "doing" }, undefined, TODAY)).toBeUndefined();
  });

  it("returns undefined when the target group is not started", () => {
    expect(getAutoStartDate(issue, { state_id: "done" }, "completed", TODAY)).toBeUndefined();
  });

  it("returns undefined when the issue is not in the store", () => {
    expect(getAutoStartDate(undefined, { state_id: "doing" }, "started", TODAY)).toBeUndefined();
  });
});

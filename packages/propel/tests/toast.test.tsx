/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TOAST_TYPE, Toast, setToast, updateToast } from "../src/toast/toast";

const TIMEOUT = 1_000;

const advance = (ms: number) => act(() => vi.advanceTimersByTime(ms));

const fire = (title: string, timeout?: number) =>
  act(() => {
    setToast({ type: TOAST_TYPE.INFO, title, ...(timeout === undefined ? {} : { timeout }) });
  });

describe("Toast auto-dismiss", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("dismisses a toast once its own timeout elapses", () => {
    render(<Toast theme="light" />);

    fire("Only toast", TIMEOUT);
    expect(screen.getByText("Only toast")).toBeDefined();

    advance(TIMEOUT + 100);

    expect(screen.queryByText("Only toast")).toBeNull();
  });

  it("keeps a queued toast until it is actually visible", () => {
    render(<Toast theme="light" limit={3} />);

    // Five at once: the three newest are shown, the two oldest are queued behind the limit.
    for (let i = 1; i <= 5; i++) fire(`Toast ${i}`, TIMEOUT);
    expect(document.querySelectorAll("[data-limited]")).toHaveLength(2);

    // The visible three expire. The queued two must still be there — their countdown only
    // starts now that they are on screen.
    advance(TIMEOUT + 100);

    expect(screen.getByText("Toast 1")).toBeDefined();
    expect(screen.getByText("Toast 2")).toBeDefined();
    expect(document.querySelectorAll("[data-limited]")).toHaveLength(0);

    advance(TIMEOUT + 100);

    expect(screen.queryByText("Toast 1")).toBeNull();
    expect(screen.queryByText("Toast 2")).toBeNull();
  });

  it("keeps a toast with timeout 0 until it is dismissed", () => {
    render(<Toast theme="light" />);

    fire("Sticky toast", 0);
    advance(60_000);

    expect(screen.getByText("Sticky toast")).toBeDefined();
  });

  it("pauses the countdown while the toast is hovered", () => {
    render(<Toast theme="light" />);

    fire("Hovered toast", TIMEOUT);
    const root = screen.getByText("Hovered toast").closest("[data-starting-style], div");
    expect(root).not.toBeNull();

    act(() => fireEvent.mouseEnter(root as Element));
    advance(TIMEOUT * 3);
    expect(screen.getByText("Hovered toast")).toBeDefined();

    act(() => fireEvent.mouseLeave(root as Element));
    advance(TIMEOUT + 100);

    expect(screen.queryByText("Hovered toast")).toBeNull();
  });

  it("falls back to the provider timeout when the caller sets none", () => {
    render(<Toast theme="light" timeout={2_000} />);

    fire("Default timeout toast");

    advance(1_000);
    expect(screen.getByText("Default timeout toast")).toBeDefined();

    advance(1_500);
    expect(screen.queryByText("Default timeout toast")).toBeNull();
  });

  it("shows how many toasts are queued behind the limit", () => {
    render(<Toast theme="light" limit={3} />);

    for (let i = 1; i <= 5; i++) fire(`Toast ${i}`, 0);

    expect(screen.getByText("+2 more")).toBeDefined();
  });

  it("swaps the content of an existing toast", () => {
    render(<Toast theme="light" />);

    let id = "";
    act(() => {
      id = setToast({ type: TOAST_TYPE.LOADING, title: "Working..." }) ?? "";
    });
    expect(screen.getByText("Working...")).toBeDefined();

    act(() => updateToast(id, { type: TOAST_TYPE.SUCCESS, title: "Done", message: "All good" }));

    expect(screen.queryByText("Working...")).toBeNull();
    expect(screen.getByText("Done")).toBeDefined();
    expect(screen.getByText("All good")).toBeDefined();
  });
});

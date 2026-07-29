/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { showDesktopNotification } from "@/lib/desktop-notification";
import { setToast } from "@plane/propel/toast";
import { FakeEventSource, setVisibility } from "../utils/fake-event-source";

const WORKSPACE_ID = "ws-1";
const WORKSPACE_SLUG = "acme";

const mutateNotifications = vi.fn();
const setUnreadNotificationsCount = vi.fn();
const getUnreadNotificationsCount = vi.fn(async () => undefined);
const navigate = vi.fn();
const markNotificationAsRead = vi.fn(async () => undefined);

let storedValue: boolean | undefined = true;
let currentWorkspace: { id: string; slug: string } | undefined = { id: WORKSPACE_ID, slug: WORKSPACE_SLUG };

vi.mock("@plane/constants", () => ({ LIVE_BASE_URL: "https://live.plane.test", LIVE_BASE_PATH: "/live" }));
vi.mock("@plane/hooks", () => ({ useLocalStorage: () => ({ storedValue, setValue: vi.fn() }) }));
vi.mock("@plane/i18n", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@plane/propel/toast", () => ({ setToast: vi.fn(), TOAST_TYPE: { INFO: "info" } }));
vi.mock("@plane/utils", () => ({ generateWorkItemLink: () => "/acme/browse/KARA-1/" }));
vi.mock("react-router", () => ({ useNavigate: () => navigate }));
vi.mock("@/lib/desktop-notification", () => ({ showDesktopNotification: vi.fn() }));
vi.mock("@/hooks/store/user", () => ({ useUser: () => ({ data: { id: "user-1" } }) }));
vi.mock("@/hooks/store/use-workspace", () => ({ useWorkspace: () => ({ currentWorkspace }) }));
vi.mock("@/hooks/store/notifications", () => ({
  useWorkspaceNotifications: () => ({
    notifications: { "notif-1": { markNotificationAsRead } },
    mutateNotifications,
    setUnreadNotificationsCount,
    getUnreadNotificationsCount,
  }),
}));

// Imported after the mocks so the hook picks them up.
const { useNotificationStream } = await import("@/hooks/use-notification-stream");

const buildEvent = (overrides: Record<string, unknown> = {}) => ({
  receiver_id: "user-1",
  workspace_id: WORKSPACE_ID,
  kind: "mention",
  notification: {
    id: "notif-1",
    project: "project-1",
    data: { issue: { id: "issue-1", identifier: "KARA", sequence_id: 1, name: "Fix the stream" } },
    triggered_by_details: { display_name: "William" },
  },
  ...overrides,
});

describe("useNotificationStream", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    FakeEventSource.install();
    storedValue = true;
    currentWorkspace = { id: WORKSPACE_ID, slug: WORKSPACE_SLUG };
    setVisibility("visible");
  });

  afterEach(() => {
    FakeEventSource.restore();
    vi.useRealTimers();
  });

  it("opens one stream for the workspace and resyncs the badge when it connects", () => {
    renderHook(() => useNotificationStream());

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.last().url).toContain(`workspace_id=${WORKSPACE_ID}`);
    expect(FakeEventSource.last().url).toContain("/live/notifications/stream");

    act(() => FakeEventSource.last().emitOpen());

    expect(getUnreadNotificationsCount).toHaveBeenCalledWith(WORKSPACE_SLUG);
  });

  it("opens no stream while the feature is switched off", () => {
    storedValue = false;

    renderHook(() => useNotificationStream());

    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("stores a notification and shows a toast while the tab is visible", () => {
    renderHook(() => useNotificationStream());

    act(() => FakeEventSource.last().emitNotification(buildEvent()));

    expect(mutateNotifications).toHaveBeenCalledTimes(1);
    expect(setUnreadNotificationsCount).toHaveBeenCalledWith("increment", 1, "mentions");
    expect(setToast).toHaveBeenCalledTimes(1);
    expect(showDesktopNotification).not.toHaveBeenCalled();
  });

  it("shows a desktop notification instead while the tab is hidden", () => {
    setVisibility("hidden");
    renderHook(() => useNotificationStream());

    act(() => FakeEventSource.last().emitNotification(buildEvent({ kind: "assigned" })));

    expect(setUnreadNotificationsCount).toHaveBeenCalledWith("increment", 1, "all");
    expect(showDesktopNotification).toHaveBeenCalledTimes(1);
    expect(setToast).not.toHaveBeenCalled();
  });

  it("drops an event meant for another workspace", () => {
    renderHook(() => useNotificationStream());

    act(() => FakeEventSource.last().emitNotification(buildEvent({ workspace_id: "ws-2" })));

    expect(mutateNotifications).not.toHaveBeenCalled();
    expect(setToast).not.toHaveBeenCalled();
  });

  it("drops a notification it has already handled", () => {
    renderHook(() => useNotificationStream());

    act(() => FakeEventSource.last().emitNotification(buildEvent()));
    act(() => FakeEventSource.last().emitNotification(buildEvent()));

    expect(setToast).toHaveBeenCalledTimes(1);
  });

  it("ignores an unparseable frame", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    renderHook(() => useNotificationStream());

    act(() => FakeEventSource.last().emitRaw("notification", "not json"));

    expect(mutateNotifications).not.toHaveBeenCalled();
    expect(consoleError).toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it("re-opens the stream after the server closes it for good", () => {
    vi.useFakeTimers();
    renderHook(() => useNotificationStream());

    // A non-200 leaves EventSource CLOSED, and it never retries by itself.
    act(() => FakeEventSource.last().failPermanently());
    expect(FakeEventSource.instances).toHaveLength(1);

    act(() => vi.advanceTimersByTime(7_000));

    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });

  it("backs off further on each failed re-open", () => {
    vi.useFakeTimers();
    renderHook(() => useNotificationStream());

    act(() => FakeEventSource.last().failPermanently());
    act(() => vi.advanceTimersByTime(7_000));
    expect(FakeEventSource.instances).toHaveLength(2);

    act(() => FakeEventSource.last().failPermanently());
    // The second wait is longer than the first, so the same delay changes nothing yet.
    act(() => vi.advanceTimersByTime(7_000));
    expect(FakeEventSource.instances).toHaveLength(2);

    act(() => vi.advanceTimersByTime(10_000));
    expect(FakeEventSource.instances).toHaveLength(3);
  });

  it("stops re-opening once the component unmounts", () => {
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useNotificationStream());

    act(() => FakeEventSource.last().failPermanently());
    unmount();
    act(() => vi.advanceTimersByTime(60_000));

    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("closes the stream when the component unmounts", () => {
    renderHook(() => useNotificationStream()).unmount();

    expect(FakeEventSource.last().closed).toBe(true);
  });
});

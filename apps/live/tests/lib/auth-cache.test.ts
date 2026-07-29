/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authCacheSize, clearAuthCache, resolveCachedUserId } from "@/lib/auth-cache";

const TTL_MS = 60_000;
const MAX_ENTRIES = 500;

describe("resolveCachedUserId", () => {
  beforeEach(() => {
    clearAuthCache();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("serves a second lookup of the same cookie from the cache", async () => {
    const load = vi.fn(async () => "user-1");

    expect(await resolveCachedUserId("cookie-a", load)).toBe("user-1");
    expect(await resolveCachedUserId("cookie-a", load)).toBe("user-1");

    expect(load).toHaveBeenCalledTimes(1);
  });

  it("looks the cookie up again once the entry expires", async () => {
    const load = vi.fn(async () => "user-1");

    await resolveCachedUserId("cookie-a", load);
    vi.advanceTimersByTime(TTL_MS + 1);
    await resolveCachedUserId("cookie-a", load);

    expect(load).toHaveBeenCalledTimes(2);
  });

  it("never caches a cookie that resolves to no user", async () => {
    const load = vi.fn(async () => undefined);

    expect(await resolveCachedUserId("cookie-a", load)).toBeUndefined();

    expect(authCacheSize()).toBe(0);
  });

  it("purges expired entries before growing past the cap", async () => {
    const load = vi.fn(async () => "user-1");
    // Sequential on purpose: eviction is oldest-first, so insertion order is the thing
    // under test. Promise.all would make it non-deterministic.
    // eslint-disable-next-line no-await-in-loop
    for (let i = 0; i < MAX_ENTRIES; i++) await resolveCachedUserId(`cookie-${i}`, load);
    expect(authCacheSize()).toBe(MAX_ENTRIES);

    vi.advanceTimersByTime(TTL_MS + 1);
    await resolveCachedUserId("cookie-fresh", load);

    expect(authCacheSize()).toBe(1);
  });

  it("stays bounded when every entry is still fresh", async () => {
    const load = vi.fn(async () => "user-1");

    // eslint-disable-next-line no-await-in-loop
    for (let i = 0; i < MAX_ENTRIES + 50; i++) await resolveCachedUserId(`cookie-${i}`, load);

    expect(authCacheSize()).toBe(MAX_ENTRIES);
  });
});

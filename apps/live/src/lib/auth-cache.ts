/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { createHash } from "crypto";

/** Short enough that a revoked session still stops within a minute. */
const AUTH_CACHE_TTL_MS = 60_000;

/**
 * Cookie headers churn — session rotation, rotating CSRF tokens, users who never come
 * back — so every unique header would otherwise stay in the map for the life of the
 * process. The cap bounds it; the TTL means it is almost never reached.
 */
const AUTH_CACHE_MAX_ENTRIES = 500;

const cache = new Map<string, { userId: string; expiresAt: number }>();

/** Keyed on a hash so raw session cookies are not held in a long-lived map. */
const cookieKey = (cookie: string): string => createHash("sha256").update(cookie).digest("hex");

const makeRoom = (now: number): void => {
  if (cache.size < AUTH_CACHE_MAX_ENTRIES) return;

  for (const [key, entry] of cache) {
    if (entry.expiresAt <= now) cache.delete(key);
  }

  // A Map keeps insertion order, so the first keys are the oldest.
  for (const key of cache.keys()) {
    if (cache.size < AUTH_CACHE_MAX_ENTRIES) break;
    cache.delete(key);
  }
};

/**
 * Resolves the user behind a session cookie, caching the answer for a minute.
 *
 * `load` is only called on a miss. A lookup that resolves to no user is never cached, so a
 * signed-out cookie cannot pin an entry.
 */
export const resolveCachedUserId = async (
  cookie: string,
  load: (cookie: string) => Promise<string | undefined>
): Promise<string | undefined> => {
  const key = cookieKey(cookie);
  const now = Date.now();
  const cached = cache.get(key);
  if (cached && cached.expiresAt > now) return cached.userId;
  if (cached) cache.delete(key);

  const userId = await load(cookie);
  if (!userId) return undefined;

  makeRoom(Date.now());
  cache.set(key, { userId, expiresAt: Date.now() + AUTH_CACHE_TTL_MS });
  return userId;
};

/** Exported for tests. */
export const clearAuthCache = (): void => cache.clear();

/** Exported for tests. */
export const authCacheSize = (): number => cache.size;

/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/** jsdom has no EventSource, and the tests need to drive its states by hand anyway. */
export class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  static instances: FakeEventSource[] = [];
  private static original: unknown;

  readyState: number = FakeEventSource.CONNECTING;
  closed = false;
  private listeners = new Map<string, Set<(event: unknown) => void>>();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  static install(): void {
    FakeEventSource.instances = [];
    FakeEventSource.original = (globalThis as Record<string, unknown>).EventSource;
    (globalThis as Record<string, unknown>).EventSource = FakeEventSource;
  }

  static restore(): void {
    (globalThis as Record<string, unknown>).EventSource = FakeEventSource.original;
    FakeEventSource.instances = [];
  }

  static last(): FakeEventSource {
    const instance = FakeEventSource.instances.at(-1);
    if (!instance) throw new Error("no EventSource was opened");
    return instance;
  }

  addEventListener(type: string, callback: (event: unknown) => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)?.add(callback);
  }

  removeEventListener(type: string, callback: (event: unknown) => void): void {
    this.listeners.get(type)?.delete(callback);
  }

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
    this.closed = true;
  }

  emitRaw(type: string, data: string): void {
    this.listeners.get(type)?.forEach((callback) => callback({ data }));
  }

  emitNotification(payload: unknown): void {
    this.emitRaw("notification", JSON.stringify(payload));
  }

  emitOpen(): void {
    this.readyState = FakeEventSource.OPEN;
    this.listeners.get("open")?.forEach((callback) => callback({}));
  }

  /** What a non-200 response looks like: CLOSED, with no retry of its own. */
  failPermanently(): void {
    this.readyState = FakeEventSource.CLOSED;
    this.listeners.get("error")?.forEach((callback) => callback({}));
  }
}

export const setVisibility = (state: DocumentVisibilityState): void => {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
};

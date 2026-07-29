/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TDesktopNotificationOptions = {
  title: string;
  body?: string;
  icon?: string;
  /** Notifications sharing a tag replace each other, so several open tabs show only one. */
  tag?: string;
  onClick?: () => void;
};

const openNotifications = new Set<Notification>();

let isRefocusListenerRegistered = false;

export const isDesktopNotificationSupported = (): boolean => typeof window !== "undefined" && "Notification" in window;

export const getDesktopNotificationPermission = (): NotificationPermission | undefined =>
  isDesktopNotificationSupported() ? Notification.permission : undefined;

/** Must be called from a user gesture. Browsers reject or silently deny otherwise. */
export const requestDesktopNotificationPermission = async (): Promise<NotificationPermission | undefined> => {
  if (!isDesktopNotificationSupported()) return undefined;
  if (Notification.permission !== "default") return Notification.permission;
  try {
    return await Notification.requestPermission();
  } catch (error) {
    console.error("desktopNotification -> requestPermission -> error", error);
    return undefined;
  }
};

export const closeAllDesktopNotifications = (): void => {
  openNotifications.forEach((notification) => notification.close());
  openNotifications.clear();
};

/**
 * Closes anything we opened once the user is back on the tab: they are looking at the app
 * now, and the in-app toast covers the same event.
 *
 * Registered lazily on first use so importing this module has no side effect during SSR.
 */
const registerRefocusListener = (): void => {
  if (isRefocusListenerRegistered || typeof document === "undefined") return;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") closeAllDesktopNotifications();
  });
  isRefocusListenerRegistered = true;
};

export const showDesktopNotification = (options: TDesktopNotificationOptions): Notification | undefined => {
  const { title, body, icon, tag, onClick } = options;

  if (!isDesktopNotificationSupported() || Notification.permission !== "granted") return undefined;
  // A visible tab already gets the toast, so a native notification would duplicate it.
  if (document.visibilityState === "visible") return undefined;

  registerRefocusListener();

  try {
    const notification = new Notification(title, { body, icon, tag });
    openNotifications.add(notification);

    notification.addEventListener("click", () => {
      window.focus();
      notification.close();
      openNotifications.delete(notification);
      onClick?.();
    });
    notification.addEventListener("close", () => openNotifications.delete(notification));
    notification.addEventListener("error", () => openNotifications.delete(notification));

    return notification;
  } catch (error) {
    // Some platforms throw when a service worker is registered. The toast is the fallback.
    console.error("desktopNotification -> show -> error", error);
    return undefined;
  }
};

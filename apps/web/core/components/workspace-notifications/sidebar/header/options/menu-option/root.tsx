/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState, type ReactNode } from "react";
import { observer } from "mobx-react";
import { Bell, BellOff, CheckCircle, Clock, MonitorSmartphone, MoreVertical } from "lucide-react";
import { useLocalStorage } from "@plane/hooks";
import { useTranslation } from "@plane/i18n";
// plane imports
import { ArchiveIcon, CheckIcon } from "@plane/propel/icons";
import type { TNotificationFilter } from "@plane/types";
import { PopoverMenu } from "@plane/ui";
// hooks
import { useWorkspaceNotifications } from "@/hooks/store/notifications";
import { REALTIME_NOTIFICATIONS_ENABLED_KEY } from "@/hooks/use-notification-stream";
import { getDesktopNotificationPermission, requestDesktopNotificationPermission } from "@/lib/desktop-notification";
// local imports
import { NotificationMenuOptionItem } from "./menu-item";
import { IconButton } from "@plane/propel/icon-button";

export type TPopoverMenuOptions = {
  key: string;
  type: string;
  label?: string | undefined;
  isActive?: boolean | undefined;
  prependIcon?: ReactNode | undefined;
  appendIcon?: ReactNode | undefined;
  onClick?: (() => void) | undefined;
};

export const NotificationHeaderMenuOption = observer(function NotificationHeaderMenuOption() {
  // hooks
  const { filters, updateFilters, updateBulkFilters } = useWorkspaceNotifications();
  const { t } = useTranslation();
  const { storedValue: arePopupsEnabled, setValue: setPopupsEnabled } = useLocalStorage<boolean>(
    REALTIME_NOTIFICATIONS_ENABLED_KEY,
    true
  );

  // Per-device on/off, matching browser notification permission which is also per-device.
  const popupsEnabled = arePopupsEnabled !== false;
  // Held in state so granting permission re-renders the menu. `undefined` means the browser
  // has no Notification API, or it has not been read yet.
  const [desktopPermission, setDesktopPermission] = useState<NotificationPermission | undefined>(undefined);

  // Read after mount: the API does not exist while the page is rendered on the server.
  useEffect(() => setDesktopPermission(getDesktopNotificationPermission()), []);

  const handleFilterChange = (filterType: keyof TNotificationFilter, filterValue: boolean) =>
    updateFilters(filterType, filterValue);

  const handleBulkFilterChange = (filter: Partial<TNotificationFilter>) => updateBulkFilters(filter);

  const popoverMenuOptions: TPopoverMenuOptions[] = [
    {
      key: "menu-unread",
      type: "menu-item",
      label: t("notification.options.show_unread"),
      isActive: filters?.read,
      prependIcon: <CheckCircle className="h-3 w-3 flex-shrink-0" />,
      appendIcon: filters?.read ? <CheckIcon className="h-3 w-3" /> : undefined,
      onClick: () => handleFilterChange("read", !filters?.read),
    },
    {
      key: "menu-archived",
      type: "menu-item",
      label: t("notification.options.show_archived"),
      isActive: filters?.archived,
      prependIcon: <ArchiveIcon className="h-3 w-3 flex-shrink-0" />,
      appendIcon: filters?.archived ? <CheckIcon className="h-3 w-3" /> : undefined,
      onClick: () =>
        handleBulkFilterChange({
          archived: !filters?.archived,
          snoozed: false,
        }),
    },
    {
      key: "menu-snoozed",
      type: "menu-item",
      label: t("notification.options.show_snoozed"),
      isActive: filters?.snoozed,
      prependIcon: <Clock className="h-3 w-3 flex-shrink-0" />,
      appendIcon: filters?.snoozed ? <CheckIcon className="h-3 w-3" /> : undefined,
      onClick: () =>
        handleBulkFilterChange({
          snoozed: !filters?.snoozed,
          archived: false,
        }),
    },
    {
      key: "menu-realtime-popups",
      type: "menu-item",
      label: popupsEnabled ? t("notification.realtime.turn_off") : t("notification.realtime.turn_on"),
      isActive: popupsEnabled,
      prependIcon: popupsEnabled ? (
        <BellOff className="h-3 w-3 flex-shrink-0" />
      ) : (
        <Bell className="h-3 w-3 flex-shrink-0" />
      ),
      onClick: () => setPopupsEnabled(!popupsEnabled),
    },
  ];

  // Permission can only be requested from a user gesture, so it lives behind this click.
  if (desktopPermission === "default" || desktopPermission === "denied") {
    popoverMenuOptions.push({
      key: "menu-desktop-permission",
      type: "menu-item",
      label:
        desktopPermission === "denied"
          ? t("notification.realtime.browser_notifications_blocked")
          : t("notification.realtime.enable_browser_notifications"),
      prependIcon: <MonitorSmartphone className="h-3 w-3 flex-shrink-0" />,
      onClick:
        desktopPermission === "denied"
          ? undefined
          : () => void requestDesktopNotificationPermission().then(setDesktopPermission),
    });
  }

  return (
    <PopoverMenu
      data={popoverMenuOptions}
      button={<IconButton size="base" variant="ghost" icon={MoreVertical} />}
      keyExtractor={(item: TPopoverMenuOptions) => item.key}
      panelClassName="p-0 py-2 rounded-md border border-subtle bg-surface-1 space-y-1"
      render={(item: TPopoverMenuOptions) => <NotificationMenuOptionItem {...item} />}
    />
  );
});

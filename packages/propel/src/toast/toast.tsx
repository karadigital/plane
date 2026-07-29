/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import * as React from "react";
import { Toast as BaseToast } from "@base-ui-components/react/toast";
import { AlertTriangle, CheckIcon, InfoIcon, XIcon } from "lucide-react";
import { CloseIcon } from "../icons/actions/close-icon";
// spinner
import { CircularBarSpinner } from "../spinners/circular-bar-spinner";
import { cn } from "../utils/classname";

export enum TOAST_TYPE {
  SUCCESS = "success",
  ERROR = "error",
  INFO = "info",
  WARNING = "warning",
  LOADING = "loading",
  LOADING_TOAST = "loading-toast",
}

type SetToastProps =
  | {
      type: TOAST_TYPE.LOADING;
      title?: string;
    }
  | {
      id?: string | number;
      type: Exclude<TOAST_TYPE, TOAST_TYPE.LOADING>;
      title: string;
      message?: string;
      actionItems?: React.ReactNode;
      /**
       * Auto-dismiss delay in ms for this toast. `0` keeps it until dismissed. Defaults to
       * the provider's timeout. An explicit value is timed by this component, not by the
       * toast library, so the countdown starts when the toast is really on screen.
       */
      timeout?: number;
      /** Makes the title and message activatable. The close button and action items keep their own clicks. */
      onClick?: () => void;
    };

type PromiseToastCallback<ToastData> = (data: ToastData) => string;
type ActionItemsPromiseToastCallback<ToastData> = (data: ToastData) => React.ReactNode;

type PromiseToastData<ToastData> = {
  title: string;
  message?: PromiseToastCallback<ToastData>;
  actionItems?: ActionItemsPromiseToastCallback<ToastData>;
};

type PromiseToastOptions<ToastData> = {
  loading?: string;
  success: PromiseToastData<ToastData>;
  error: PromiseToastData<ToastData>;
};

/** Matches the underlying toast provider's own default, kept explicit so the badge can rely on it. */
export const DEFAULT_TOAST_LIMIT = 3;

export type ToastProps = {
  theme: "light" | "dark" | "system";
  /** How many toasts are visible at once. Extras stay queued and are counted in the "+N more" badge. */
  limit?: number;
  /** Default auto-dismiss delay in ms. `0` disables auto-dismiss. */
  timeout?: number;
};

const toastManager = BaseToast.createToastManager();

export function Toast(props: ToastProps) {
  const { theme, limit = DEFAULT_TOAST_LIMIT, timeout } = props;

  return (
    <BaseToast.Provider toastManager={toastManager} limit={limit} timeout={timeout}>
      <BaseToast.Portal>
        <BaseToast.Viewport data-theme={theme}>
          <ToastList />
        </BaseToast.Viewport>
      </BaseToast.Portal>
    </BaseToast.Provider>
  );
}

const TOAST_DATA = {
  [TOAST_TYPE.SUCCESS]: {
    icon: <CheckIcon width={12} height={12} className="text-on-color" />,
    iconBgClassName: "bg-success-primary",
    backgroundColorClassName: "!bg-surface-1",
    borderColorClassName: "border-subtle",
  },
  [TOAST_TYPE.ERROR]: {
    icon: <XIcon width={12} height={12} className="text-on-color" />,
    iconBgClassName: "bg-danger-primary",
    backgroundColorClassName: "bg-surface-1",
    borderColorClassName: "border-subtle",
  },
  [TOAST_TYPE.WARNING]: {
    icon: <AlertTriangle width={12} height={12} className="text-on-color" />,
    iconBgClassName: "bg-warning-primary",
    backgroundColorClassName: "bg-surface-1",
    borderColorClassName: "border-subtle",
  },
  [TOAST_TYPE.INFO]: {
    icon: <InfoIcon width={12} height={12} className="text-on-color" />,
    iconBgClassName: "bg-accent-primary",
    backgroundColorClassName: "bg-surface-1",
    borderColorClassName: "border-subtle",
  },
  [TOAST_TYPE.LOADING]: {
    icon: <CircularBarSpinner className="text-on-color" />,
    iconBgClassName: "bg-layer-2",
    backgroundColorClassName: "bg-surface-1",
    borderColorClassName: "border-subtle",
  },
  [TOAST_TYPE.LOADING_TOAST]: {
    icon: <CircularBarSpinner className="text-on-color" />,
    iconBgClassName: "bg-layer-2",
    backgroundColorClassName: "bg-surface-1",
    borderColorClassName: "border-subtle",
  },
};

function ToastList() {
  const { toasts } = BaseToast.useToastManager();
  // Toasts past the limit are not dropped: they stay in the list flagged as `limited` and
  // surface again as the ones in front close. Counting them gives the "+N more" total.
  const overflowCount = toasts.filter((toast) => toast.limited && toast.transitionStatus !== "ending").length;

  return toasts.map((toast, index) => (
    <ToastRender key={toast.id} id={toast.id} toast={toast} overflowCount={index === 0 ? overflowCount : 0} />
  ));
}

function ToastRender({
  id,
  toast,
  overflowCount,
}: {
  id: React.Key;
  toast: BaseToast.Root.ToastObject;
  overflowCount: number;
}) {
  const toastData = toast.data as SetToastProps;
  const type = toastData.type as TOAST_TYPE;
  const data = TOAST_DATA[type];
  const onClick = toastData.type === TOAST_TYPE.LOADING ? undefined : toastData.onClick;
  const timeout = toastData.type === TOAST_TYPE.LOADING ? 0 : (toastData.timeout ?? 0);
  const [isHovered, setIsHovered] = React.useState(false);

  // The toast library schedules its dismiss timer in `add()` for every toast, including the
  // ones queued behind the limit, so a hidden toast expires before anyone sees it. A toast
  // with an explicit timeout opts out of that timer in `setToast` and is timed here, where
  // `limited` says whether it is actually on screen.
  React.useEffect(() => {
    if (!timeout || toast.limited || isHovered || toast.transitionStatus === "ending") return;
    // Leaving the toast restarts the full delay instead of resuming the remainder, and only
    // the hovered toast pauses. Both are deliberate: the difference is not perceptible.
    const timer = setTimeout(() => toastManager.close(toast.id), timeout);
    return () => clearTimeout(timer);
  }, [timeout, toast.limited, toast.transitionStatus, toast.id, isHovered]);

  const title = (
    <BaseToast.Title className="text-h6-medium text-primary">
      {toastData.type === TOAST_TYPE.LOADING ? (toastData.title ?? "Loading...") : toastData.title}
    </BaseToast.Title>
  );

  // Rendered bare unless there is overflow, so untouched call sites keep today's layout.
  const titleRow =
    overflowCount > 0 ? (
      <div className="flex min-w-0 items-start gap-2">
        <div className="min-w-0 flex-1">{title}</div>
        <span className="mt-0.5 flex-shrink-0 rounded-full bg-layer-2 px-1.5 py-0.5 text-caption-sm-regular text-secondary">
          +{overflowCount} more
        </span>
      </div>
    ) : (
      title
    );

  const description = toastData.type !== TOAST_TYPE.LOADING && toastData.message && (
    <BaseToast.Description className="text-body-xs-regular text-tertiary">{toastData.message}</BaseToast.Description>
  );

  return (
    <BaseToast.Root
      toast={toast}
      key={id}
      className={cn(
        // Base layout and positioning
        "group flex w-[350px] items-center rounded-lg border shadow-raised-200",
        "absolute right-3 bottom-3 z-[calc(1000-var(--toast-index))]",
        "ease-&lsqb;cubic-bezier(0.22,1,0.36,1)&rsqb; transition-[opacity,transform] duration-500 select-none",

        // Default transform with stacking and scaling
        "[transform:translateX(var(--toast-swipe-movement-x))_translateY(calc(var(--toast-swipe-movement-y)+calc(min(var(--toast-index),10)*-10px)))_scale(calc(max(0,1-(var(--toast-index)*0.1))))]",

        // Pseudo-element for gap spacing
        "after:absolute after:bottom-full after:left-0 after:h-[calc(var(--gap)+1px)] after:w-full after:content-['']",

        // State-based opacity
        "data-[ending-style]:opacity-0 data-[limited]:opacity-0",

        // Starting animation
        "data-[starting-style]:[transform:translateY(150%)]",

        // Expanded state transform
        "data-[expanded]:[transform:translateX(var(--toast-swipe-movement-x))_translateY(calc(var(--toast-offset-y)*-1+calc(var(--toast-index)*var(--gap)*-1)+var(--toast-swipe-movement-y)))]",

        // Swipe direction endings - consolidated
        "data-[ending-style]:data-[swipe-direction=down]:[transform:translateY(calc(var(--toast-swipe-movement-y)+150%))]",
        "data-[ending-style]:data-[swipe-direction=up]:[transform:translateY(calc(var(--toast-swipe-movement-y)-150%))]",
        "data-[ending-style]:data-[swipe-direction=left]:[transform:translateX(calc(var(--toast-swipe-movement-x)-150%))_translateY(var(--offset-y))]",
        "data-[ending-style]:data-[swipe-direction=right]:[transform:translateX(calc(var(--toast-swipe-movement-x)+150%))_translateY(var(--offset-y))]",

        // Default ending transform for non-limited toasts
        "data-[ending-style]:[&:not([data-limited])]:[transform:translateY(150%)]",

        data.backgroundColorClassName,
        data.borderColorClassName
      )}
      style={{
        ["--gap" as string]: "1rem",
        ["--offset-y" as string]:
          "calc(var(--toast-offset-y) * -1 + (var(--toast-index) * var(--gap) * -1) + var(--toast-swipe-movement-y))",
      }}
      onMouseDown={(e) => {
        e.stopPropagation();
        e.preventDefault();
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <BaseToast.Close className="absolute top-3 right-3 cursor-pointer text-icon-secondary hover:text-icon-tertiary">
        <CloseIcon strokeWidth={1.5} width={16} height={16} />
      </BaseToast.Close>
      <div className="flex w-full items-start gap-2 p-4">
        <div className="py-1">
          {data.icon && (
            <div
              className={cn("flex size-4 flex-shrink-0 items-center justify-center rounded-full", data.iconBgClassName)}
            >
              {data.icon}
            </div>
          )}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          {onClick ? (
            // A real button rather than a click handler on the toast body: it is keyboard
            // operable, announced correctly, and the toast library already ignores swipe
            // gestures that start on a button. Action items stay outside so buttons never nest.
            <button
              type="button"
              onClick={onClick}
              className="flex w-full min-w-0 cursor-pointer flex-col gap-1 text-left"
            >
              {titleRow}
              {description}
            </button>
          ) : (
            <>
              {titleRow}
              {description}
            </>
          )}
          {toastData.type !== TOAST_TYPE.LOADING && toastData.actionItems && (
            <div className="flex items-center gap-2">{toastData.actionItems}</div>
          )}
        </div>
      </div>
    </BaseToast.Root>
  );
}

// Static toast component for Storybook and documentation
export type ToastStaticProps = {
  type: TOAST_TYPE;
  title: string;
  message?: string;
  actionItems?: React.ReactNode;
  theme?: "light" | "dark";
};

export function ToastStatic({ type, title, message, actionItems, theme = "light" }: ToastStaticProps) {
  const data = TOAST_DATA[type];

  return (
    <div data-theme={theme} className="inline-block">
      <div
        className={cn(
          // Base layout and positioning
          "group flex w-[350px] items-start rounded-lg border border-subtle-1 shadow-overlay-100",
          "relative",
          data.backgroundColorClassName,
          data.borderColorClassName
        )}
      >
        <div className="absolute top-1 right-1 cursor-default text-icon-tertiary">
          <CloseIcon strokeWidth={1.5} width={14} height={14} />
        </div>
        <div className="flex w-full items-start gap-3 p-4">
          <div className="py-1">
            {data.icon && (
              <div
                className={cn(
                  "flex size-4 flex-shrink-0 items-center justify-center rounded-full",
                  data.iconBgClassName
                )}
              >
                {data.icon}
              </div>
            )}
          </div>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="text-h6-medium text-primary">
              {type === TOAST_TYPE.LOADING ? (title ?? "Loading...") : title}
            </div>
            {type !== TOAST_TYPE.LOADING && message && (
              <div className="text-body-xs-regular text-tertiary">{message}</div>
            )}
            {type !== TOAST_TYPE.LOADING && actionItems && <div className="flex items-center gap-2">{actionItems}</div>}
          </div>
        </div>
      </div>
    </div>
  );
}

export const setToast = (props: SetToastProps) => {
  let toastId: string | undefined;
  if (props.type !== TOAST_TYPE.LOADING) {
    toastId = toastManager.add({
      // `0` stops the library from scheduling its own timer: ToastRender owns the delay so
      // it can start when the toast leaves the queue. `undefined` keeps the default timer.
      timeout: props.timeout === undefined ? undefined : 0,
      data: {
        type: props.type,
        title: props.title,
        message: props.message,
        actionItems: props.actionItems,
        onClick: props.onClick,
        timeout: props.timeout,
      },
    });
  } else {
    toastId = toastManager.add({
      data: {
        type: props.type,
        title: props.title,
      },
    });
  }
  return toastId;
};

/** Keeps the union intact while dropping a key from each member. */
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;

/**
 * `timeout` is not accepted: the library's `update()` only merges the toast object, it
 * never (re)schedules a dismissal, so the value would be silently ignored.
 */
export const updateToast = (id: string, props: DistributiveOmit<SetToastProps, "timeout">) => {
  toastManager.update(id, {
    data:
      props.type === TOAST_TYPE.LOADING
        ? {
            type: TOAST_TYPE.LOADING,
            title: props.title,
          }
        : {
            type: props.type,
            title: props.title,
            message: props.message,
            actionItems: props.actionItems,
            onClick: props.onClick,
          },
  });
};

export const setPromiseToast = <ToastData,>(
  promise: Promise<ToastData>,
  options: PromiseToastOptions<ToastData>
): void => {
  toastManager.promise(promise, {
    loading: {
      data: {
        title: options.loading ?? "Loading...",
        type: TOAST_TYPE.LOADING,
        message: undefined,
        actionItems: undefined,
      },
    },
    success: (data) => ({
      data: {
        type: TOAST_TYPE.SUCCESS,
        title: options.success.title,
        message: options.success.message?.(data),
        actionItems: options.success.actionItems?.(data),
      },
    }),
    error: (data) => ({
      data: {
        type: TOAST_TYPE.ERROR,
        title: options.error.title,
        message: options.error.message?.(data),
        actionItems: options.error.actionItems?.(data),
      },
    }),
  });
};

export const dismissToast = (tId: string) => {
  toastManager.close(tId);
};

/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { Controller, useForm } from "react-hook-form";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TIssueSolidtimeTime } from "@plane/types";
import { EModalPosition, EModalWidth, Input, ModalCore } from "@plane/ui";
// services
import { IssueSolidtimeService } from "@/services/issue";
// local
import {
  MAX_DURATION_MINUTES,
  addMinutesToTime,
  formatEntryStart,
  formatTrackedSeconds,
  getDefaultStart,
  minutesBetweenTimes,
  toStartIso,
} from "./helpers";

const issueSolidtimeService = new IssueSolidtimeService();

type TLogTimeForm = {
  date: string;
  time: string;
  endTime: string;
  hours: string;
  minutes: string;
  description: string;
};

type Props = {
  isOpen: boolean;
  onClose: () => void;
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  data: Extract<TIssueSolidtimeTime, { configured: true }>;
  disabled: boolean;
  onLogged: () => void;
};

const DEFAULT_DURATION_MINUTES = 60;

const getDefaultValues = (): TLogTimeForm => {
  const start = getDefaultStart();
  return {
    ...start,
    endTime: addMinutesToTime(start.time, DEFAULT_DURATION_MINUTES) ?? "",
    hours: String(DEFAULT_DURATION_MINUTES / 60),
    minutes: "0",
    description: "",
  };
};

const toDurationMinutes = (hours: string, minutes: string) => (Number(hours) || 0) * 60 + (Number(minutes) || 0);

export const IssueSolidtimeLogTimeModal = observer(function IssueSolidtimeLogTimeModal(props: Props) {
  const { isOpen, onClose, workspaceSlug, projectId, issueId, data, disabled, onLogged } = props;
  const { t } = useTranslation();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    control,
    handleSubmit,
    reset,
    getValues,
    setValue,
    formState: { isSubmitting },
  } = useForm<TLogTimeForm>({ defaultValues: getDefaultValues() });

  useEffect(() => {
    if (isOpen) {
      reset(getDefaultValues());
      setFormError(null);
    }
  }, [isOpen, reset]);

  // Start time, end time and duration stay in sync: editing the end time sets the duration,
  // editing the start time or the duration moves the end time.
  const syncEndTime = () => {
    const { time, hours, minutes } = getValues();
    const endTime = addMinutesToTime(time, toDurationMinutes(hours, minutes));
    if (endTime !== null) setValue("endTime", endTime);
  };

  const syncDuration = () => {
    const { time, endTime } = getValues();
    const duration = minutesBetweenTimes(time, endTime);
    if (duration === null) return;
    setValue("hours", String(Math.floor(duration / 60)));
    setValue("minutes", String(duration % 60));
  };

  const onSubmit = async (form: TLogTimeForm) => {
    const durationMinutes = toDurationMinutes(form.hours, form.minutes);
    if (!Number.isInteger(durationMinutes) || durationMinutes < 1 || durationMinutes > MAX_DURATION_MINUTES) {
      setFormError(t("issue.solidtime.errors.duration"));
      return;
    }
    const start = toStartIso(form.date, form.time);
    if (!start || new Date(start).getTime() > Date.now()) {
      setFormError(t("issue.solidtime.errors.future"));
      return;
    }
    setFormError(null);

    try {
      await issueSolidtimeService.logTime(workspaceSlug, projectId, issueId, {
        start,
        duration_minutes: durationMinutes,
        description: form.description.trim() || undefined,
      });
      setToast({ type: TOAST_TYPE.SUCCESS, title: t("issue.solidtime.success") });
      onLogged();
      reset(getDefaultValues());
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: TOAST_TYPE.ERROR, title: message ?? t("issue.solidtime.errors.generic") });
    }
  };

  const fieldClass = "w-full";
  const labelClass = "mb-1 block text-body-xs-regular text-secondary";

  return (
    <ModalCore isOpen={isOpen} handleClose={onClose} position={EModalPosition.TOP} width={EModalWidth.XL}>
      {/* The modal is portaled outside the peek overview; without this, clicks inside it close the peek. */}
      <div data-prevent-outside-click>
        <div className="space-y-5 p-5">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-h4-medium text-secondary">{t("issue.solidtime.modal_title")}</h3>
            <span className="text-body-sm-medium text-primary">{formatTrackedSeconds(data.total_seconds)}</span>
          </div>

          {!disabled && (
            <form id="solidtime-log-time" onSubmit={handleSubmit(onSubmit)} className="space-y-3">
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label htmlFor="solidtime-date" className={labelClass}>
                    {t("issue.solidtime.date")}
                  </label>
                  <Controller
                    control={control}
                    name="date"
                    render={({ field }) => <Input id="solidtime-date" type="date" className={fieldClass} {...field} />}
                  />
                </div>
                <div>
                  <label htmlFor="solidtime-time" className={labelClass}>
                    {t("issue.solidtime.start_time")}
                  </label>
                  <Controller
                    control={control}
                    name="time"
                    render={({ field }) => (
                      <Input
                        id="solidtime-time"
                        type="time"
                        className={fieldClass}
                        {...field}
                        onChange={(e) => {
                          field.onChange(e);
                          syncEndTime();
                        }}
                      />
                    )}
                  />
                </div>
                <div>
                  <label htmlFor="solidtime-end-time" className={labelClass}>
                    {t("issue.solidtime.end_time")}
                  </label>
                  <Controller
                    control={control}
                    name="endTime"
                    render={({ field }) => (
                      <Input
                        id="solidtime-end-time"
                        type="time"
                        className={fieldClass}
                        {...field}
                        onChange={(e) => {
                          field.onChange(e);
                          syncDuration();
                        }}
                      />
                    )}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="solidtime-hours" className={labelClass}>
                    {t("issue.solidtime.hours")}
                  </label>
                  <Controller
                    control={control}
                    name="hours"
                    render={({ field }) => (
                      <Input
                        id="solidtime-hours"
                        type="number"
                        min={0}
                        max={24}
                        className={fieldClass}
                        {...field}
                        onChange={(e) => {
                          field.onChange(e);
                          syncEndTime();
                        }}
                      />
                    )}
                  />
                </div>
                <div>
                  <label htmlFor="solidtime-minutes" className={labelClass}>
                    {t("issue.solidtime.minutes")}
                  </label>
                  <Controller
                    control={control}
                    name="minutes"
                    render={({ field }) => (
                      <Input
                        id="solidtime-minutes"
                        type="number"
                        min={0}
                        max={59}
                        className={fieldClass}
                        {...field}
                        onChange={(e) => {
                          field.onChange(e);
                          syncEndTime();
                        }}
                      />
                    )}
                  />
                </div>
              </div>
              <div>
                <label htmlFor="solidtime-description" className={labelClass}>
                  {t("issue.solidtime.description")}
                  <span className="ml-1 text-caption-xs-regular text-tertiary">{t("common.optional")}</span>
                </label>
                <Controller
                  control={control}
                  name="description"
                  render={({ field }) => (
                    <Input
                      id="solidtime-description"
                      type="text"
                      maxLength={5000}
                      placeholder={t("issue.solidtime.description_placeholder")}
                      className={fieldClass}
                      {...field}
                    />
                  )}
                />
              </div>
              {formError && <p className="text-caption-sm-regular text-danger-primary">{formError}</p>}
            </form>
          )}

          <div className="space-y-2">
            {data.entries.length === 0 ? (
              <p className="text-body-xs-regular text-tertiary">{t("issue.solidtime.no_entries")}</p>
            ) : (
              <ul className="max-h-60 divide-y divide-subtle-1 overflow-y-auto">
                {data.entries.map((entry) => (
                  <li key={entry.id} className="flex items-start justify-between gap-3 py-2">
                    <div className="min-w-0">
                      <p className="text-body-xs-medium text-primary">{entry.member_name ?? "—"}</p>
                      <p className="text-caption-sm-regular text-tertiary">{formatEntryStart(entry.start)}</p>
                      {entry.description && (
                        <p className="truncate text-caption-sm-regular text-secondary">{entry.description}</p>
                      )}
                    </div>
                    <span className="shrink-0 text-body-xs-medium text-secondary">
                      {entry.is_running ? t("issue.solidtime.running") : formatTrackedSeconds(entry.duration)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 border-t-[0.5px] border-subtle px-5 py-4">
          <Button variant="secondary" size="lg" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          {!disabled && (
            <Button variant="primary" size="lg" type="submit" form="solidtime-log-time" loading={isSubmitting}>
              {t("issue.solidtime.submit")}
            </Button>
          )}
        </div>
      </div>
    </ModalCore>
  );
});

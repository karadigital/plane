/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { EUserProjectRoles } from "@plane/types";
import { CustomSearchSelect } from "@plane/ui";
import { renderFormattedPayloadDate } from "@plane/utils";
// components
import { DateRangeDropdown } from "@/components/dropdowns/date-range";
import { SettingsBoxedControlItem } from "@/components/settings/boxed-control-item";
// hooks
import { useProject } from "@/hooks/store/use-project";
// services
import { AutoReportService } from "@/services/auto-report.service";

type Props = {
  workspaceSlug: string;
};

const KEY = "workspace_settings.settings.exports.auto_report";
const autoReportService = new AutoReportService();

export const AutoReportForm = observer(function AutoReportForm(props: Props) {
  const { workspaceSlug } = props;
  // states
  const [projectIds, setProjectIds] = useState<string[]>([]);
  const [range, setRange] = useState<{ from: Date | undefined; to: Date | undefined }>({
    from: undefined,
    to: undefined,
  });
  const [isLoading, setIsLoading] = useState(false);
  // store hooks
  const { joinedProjectIds, getProjectById } = useProject();
  const { t } = useTranslation();
  // derived values
  const startDate = renderFormattedPayloadDate(range.from);
  const endDate = renderFormattedPayloadDate(range.to);
  const canDownload = projectIds.length > 0 && !!startDate && !!endDate && !isLoading;
  // the API only accepts projects where the user is at least a member
  const options = joinedProjectIds.flatMap((projectId) => {
    const project = getProjectById(projectId);
    if (!project || (project.member_role ?? 0) < EUserProjectRoles.MEMBER) return [];
    return [
      {
        value: project.id,
        query: `${project.name} ${project.identifier}`,
        content: (
          <div className="flex items-center gap-2">
            <span className="flex-shrink-0 text-10 text-secondary">{project.identifier}</span>
            <span className="truncate">{project.name}</span>
          </div>
        ),
      },
    ];
  });

  const handleDownload = async () => {
    if (!canDownload || !startDate || !endDate) return;
    setIsLoading(true);
    try {
      const report = await autoReportService.getReport(workspaceSlug, {
        project_ids: projectIds.join(","),
        start_date: startDate,
        end_date: endDate,
      });
      const [{ pdf }, { AutoReportDocument }] = await Promise.all([
        import("@react-pdf/renderer"),
        import("./report-document"),
      ]);
      const blob = await pdf(<AutoReportDocument report={report} generatedAt={new Date()} t={t} />).toBlob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `project-report-${startDate}-to-${endDate}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (_error) {
      setToast({ type: TOAST_TYPE.ERROR, title: t("error"), message: t(`${KEY}.error`) });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div>
        <h4 className="text-14 font-medium text-primary">{t(`${KEY}.title`)}</h4>
        <p className="text-13 text-secondary">{t(`${KEY}.description`)}</p>
      </div>
      <div className="rounded-lg border border-subtle bg-layer-2">
        <SettingsBoxedControlItem
          className="rounded-none border-0 border-b"
          title={t(`${KEY}.projects`)}
          control={
            <CustomSearchSelect
              value={projectIds}
              onChange={(val: string[]) => setProjectIds(val)}
              options={options}
              input
              label={
                projectIds.length > 0
                  ? projectIds.map((projectId) => getProjectById(projectId)?.identifier).join(", ")
                  : t(`${KEY}.select_projects`)
              }
              optionsClassName="max-w-48 sm:max-w-[532px]"
              placement="bottom-end"
              multiple
            />
          }
        />
        <SettingsBoxedControlItem
          className="rounded-none border-0 border-b"
          title={t(`${KEY}.period`)}
          control={
            <DateRangeDropdown
              buttonVariant="border-with-text"
              className="h-7"
              value={range}
              onSelect={(val) => setRange({ from: val?.from, to: val?.to })}
              placeholder={{ from: t(`${KEY}.start_date`), to: t(`${KEY}.end_date`) }}
              hideIcon={{ to: true }}
              bothRequired
            />
          }
        />
        <div className="px-4 py-3">
          <Button
            variant="primary"
            size="lg"
            type="button"
            loading={isLoading}
            disabled={!canDownload}
            onClick={() => void handleDownload()}
          >
            {isLoading ? `${t(`${KEY}.generating`)}...` : t(`${KEY}.download`)}
          </Button>
        </div>
      </div>
    </div>
  );
});

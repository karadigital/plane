/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Timer } from "lucide-react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { useTranslation } from "@plane/i18n";
// components
import { SidebarPropertyListItem } from "@/components/common/layout/sidebar/property-list-item";
// services
import { IssueSolidtimeService } from "@/services/issue";
// local
import { formatTrackedSeconds } from "./helpers";
import { IssueSolidtimeLogTimeModal } from "./log-time-modal";

const issueSolidtimeService = new IssueSolidtimeService();

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled: boolean;
};

/**
 * "Time tracked" row: total time logged to solidtime (the Time app) for this work item.
 * Renders nothing unless the integration is configured and the user may use it.
 */
export const IssueSolidtimeProperty = observer(function IssueSolidtimeProperty(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled } = props;
  const { t } = useTranslation();
  const [isModalOpen, setIsModalOpen] = useState(false);

  const { data, mutate } = useSWR(
    workspaceSlug && projectId && issueId ? `ISSUE_SOLIDTIME_TIME_${issueId}` : null,
    () => issueSolidtimeService.getIssueTime(workspaceSlug, projectId, issueId),
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );

  if (!data?.configured) return null;

  return (
    <>
      <SidebarPropertyListItem icon={Timer} label={t("issue.solidtime.label")}>
        <button
          type="button"
          className="flex items-center gap-2 rounded-sm px-2 py-0.5 text-body-xs-medium text-primary outline-none hover:bg-layer-transparent-hover"
          onClick={() => setIsModalOpen(true)}
        >
          <span>{formatTrackedSeconds(data.total_seconds)}</span>
          {!disabled && <span className="text-tertiary">· {t("issue.solidtime.log_time")}</span>}
        </button>
      </SidebarPropertyListItem>
      <IssueSolidtimeLogTimeModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        issueId={issueId}
        data={data}
        disabled={disabled}
        onLogged={() => void mutate()}
      />
    </>
  );
});

/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TIssueSolidtimeTime, TSolidtimeTimeEntry, TSolidtimeTimeEntryCreate } from "@plane/types";
// services
import { APIService } from "@/services/api.service";

export class IssueSolidtimeService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private url(workspaceSlug: string, projectId: string, issueId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/solidtime-time-entries/`;
  }

  async getIssueTime(workspaceSlug: string, projectId: string, issueId: string): Promise<TIssueSolidtimeTime> {
    return this.get(this.url(workspaceSlug, projectId, issueId))
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async logTime(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    data: TSolidtimeTimeEntryCreate
  ): Promise<TSolidtimeTimeEntry> {
    return this.post(this.url(workspaceSlug, projectId, issueId), data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}

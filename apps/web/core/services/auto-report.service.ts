/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import { APIService } from "@/services/api.service";

export type TAutoReportGroup = "finished" | "in_progress" | "pipeline";

export type TAutoReportItem = {
  id: string;
  key: string;
  name: string;
  project_id: string;
  state_name: string;
  state_group: string;
  start_date: string | null;
  target_date: string | null;
  completed_at: string | null;
  groups: TAutoReportGroup[];
};

export type TAutoReport = {
  period: { start: string; end: string; pipeline_end: string };
  projects: { id: string; name: string; identifier: string }[];
  items: TAutoReportItem[];
};

export type TAutoReportParams = {
  project_ids: string;
  start_date: string;
  end_date: string;
};

export class AutoReportService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async getReport(workspaceSlug: string, params: TAutoReportParams): Promise<TAutoReport> {
    return this.get(`/api/workspaces/${workspaceSlug}/auto-report/`, { params })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}

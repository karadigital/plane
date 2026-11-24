# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import AutoReportEndpoint, ExportIssuesEndpoint


urlpatterns = [
    path(
        "workspaces/<str:slug>/export-issues/",
        ExportIssuesEndpoint.as_view(),
        name="export-issues",
    ),
    path(
        "workspaces/<str:slug>/auto-report/",
        AutoReportEndpoint.as_view(http_method_names=["get"]),
        name="auto-report",
    ),
]

# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.solidtime import ProjectTimeSummaryAPIEndpoint

urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/time-summary/",
        ProjectTimeSummaryAPIEndpoint.as_view(http_method_names=["get"]),
        name="project-time-summary",
    ),
]

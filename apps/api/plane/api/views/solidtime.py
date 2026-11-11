# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Time logged in solidtime (Kara's "Time" app) per work item, for API-key clients (KARA-219)."""

# Django imports
from django.core.cache import cache

# Third party imports
from drf_spectacular.utils import OpenApiResponse
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions.project import ProjectEntityPermission
from plane.db.models import Issue, Project
from plane.utils.openapi.decorators import work_item_docs
from plane.utils.solidtime import SolidtimeClient, SolidtimeError, project_time_by_sequence

# solidtime allows 200 requests/min for the one admin token every Plane user shares.
TIME_SUMMARY_CACHE_SECONDS = 60


def _cache_key(project) -> str:
    # The identifier is part of the key: after a rename, tasks are matched by the new prefix.
    return f"solidtime:time-summary:{project.id}:{project.identifier}"


class ProjectTimeSummaryAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectEntityPermission]

    @work_item_docs(
        operation_id="get_project_time_summary",
        summary="Time logged per work item",
        description=(
            "Seconds of finished time entries logged in Time (solidtime) per work item of the project. "
            "Only work items with time are listed. Results can be up to 60 seconds old."
        ),
        responses={200: OpenApiResponse(description="Time per work item")},
    )
    def get(self, request, slug, project_id):
        project = Project.objects.filter(workspace__slug=slug, pk=project_id).first()
        if project is None:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        client = SolidtimeClient.from_settings()
        if client is None:
            return Response({"configured": False, "total_seconds": 0, "work_items": []}, status=status.HTTP_200_OK)

        key = _cache_key(project)
        seconds_by_sequence = cache.get(key)
        if seconds_by_sequence is None:
            try:
                seconds_by_sequence = project_time_by_sequence(client, project)
            except SolidtimeError as e:
                return Response(
                    {"error": e.message, "code": "solidtime_unavailable"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            cache.set(key, seconds_by_sequence, TIME_SUMMARY_CACHE_SECONDS)

        rows = (
            Issue.objects.filter(project=project, is_draft=False, sequence_id__in=list(seconds_by_sequence))
            .order_by("sequence_id")
            .values_list("id", "sequence_id")
        )
        work_items = [
            {"id": str(issue_id), "sequence_id": sequence_id, "seconds": seconds_by_sequence[sequence_id]}
            for issue_id, sequence_id in rows
        ]
        return Response(
            {
                "configured": True,
                "total_seconds": sum(item["seconds"] for item in work_items),
                "work_items": work_items,
            },
            status=status.HTTP_200_OK,
        )

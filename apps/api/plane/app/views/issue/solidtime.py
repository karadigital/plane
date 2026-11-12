# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Log time to solidtime (Kara's "Time" app) from a work item."""

# Django imports
from django.utils import timezone

# Third party imports
from rest_framework import serializers, status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.db.models import Issue
from plane.utils.solidtime import SolidtimeClient, SolidtimeError, get_issue_time, log_issue_time

from .. import BaseAPIView

MAX_DURATION_MINUTES = 24 * 60

ERROR_STATUS = {
    "member_not_found": (status.HTTP_400_BAD_REQUEST, "member_not_found"),
    "project_not_found": (status.HTTP_400_BAD_REQUEST, "project_not_found"),
    "invalid_request": (status.HTTP_400_BAD_REQUEST, "invalid_request"),
    "unavailable": (status.HTTP_502_BAD_GATEWAY, "solidtime_unavailable"),
}


class SolidtimeTimeEntryCreateSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    duration_minutes = serializers.IntegerField(min_value=1, max_value=MAX_DURATION_MINUTES)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=5000)

    def validate_start(self, value):
        if value > timezone.now():
            raise serializers.ValidationError("Start time can't be in the future.")
        return value


def _error_response(error: SolidtimeError) -> Response:
    http_status, code = ERROR_STATUS.get(error.code, (status.HTTP_400_BAD_REQUEST, error.code))
    return Response({"error": error.message, "code": code}, status=http_status)


class IssueSolidtimeTimeEntryEndpoint(BaseAPIView):
    def _get_issue(self, slug, project_id, issue_id):
        return Issue.objects.select_related("project").get(workspace__slug=slug, project_id=project_id, pk=issue_id)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id, issue_id):
        issue = self._get_issue(slug, project_id, issue_id)
        client = SolidtimeClient.from_settings()
        if client is None:
            return Response({"configured": False}, status=status.HTTP_200_OK)
        try:
            summary = get_issue_time(client, issue)
        except SolidtimeError as e:
            return _error_response(e)
        return Response({"configured": True, **summary}, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, issue_id):
        issue = self._get_issue(slug, project_id, issue_id)
        client = SolidtimeClient.from_settings()
        if client is None:
            return Response(
                {"error": "Time tracking is not configured.", "code": "solidtime_not_configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = SolidtimeTimeEntryCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        try:
            entry = log_issue_time(
                client,
                issue,
                request.user,
                data["start"],
                data["duration_minutes"],
                data.get("description") or None,
            )
        except SolidtimeError as e:
            return _error_response(e)
        return Response(entry, status=status.HTTP_201_CREATED)

# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Grouped work items for the project report PDF (KARA-107)."""

# Python imports
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

# Django imports
from django.db.models import Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import allow_permission, ROLE
from plane.db.models import Issue, Project, Workspace

from .. import BaseAPIView

MAX_PERIOD_DAYS = 366
MAX_PROJECTS = 50
MAX_ITEMS = 2000
PIPELINE_DAYS = 14
IN_PROGRESS_STATE_NAMES = ("Todo", "In Progress")


def _bad_request(message):
    return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)


def _parse_dates(request):
    try:
        start = date.fromisoformat(request.query_params["start_date"])
        end = date.fromisoformat(request.query_params["end_date"])
    except (KeyError, ValueError):
        return None
    if end > date.max - timedelta(days=PIPELINE_DAYS):
        return None
    return start, end


def _parse_project_ids(raw):
    try:
        return {UUID(value) for value in raw.split(",")}
    except ValueError:
        return None


class AutoReportEndpoint(BaseAPIView):
    @allow_permission(allowed_roles=[ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request, slug):
        dates = _parse_dates(request)
        if dates is None:
            return _bad_request("start_date and end_date must be valid dates (YYYY-MM-DD)")
        start, end = dates
        if start > end:
            return _bad_request("start_date must not be after end_date")
        if (end - start).days + 1 > MAX_PERIOD_DAYS:
            return _bad_request(f"The period must not be longer than {MAX_PERIOD_DAYS} days")

        project_ids = _parse_project_ids(request.query_params.get("project_ids", ""))
        if not project_ids:
            return _bad_request("project_ids must be a list of project ids")
        if len(project_ids) > MAX_PROJECTS:
            return _bad_request(f"Select at most {MAX_PROJECTS} projects")

        # Same answer for "does not exist" and "no access", so project existence does not leak.
        projects = list(
            Project.objects.filter(
                id__in=project_ids,
                workspace__slug=slug,
                archived_at__isnull=True,
                project_projectmember__member=request.user,
                project_projectmember__is_active=True,
                project_projectmember__role__gte=ROLE.MEMBER.value,
            )
            .distinct()
            .order_by("name")
        )
        if len(projects) != len(project_ids):
            return Response(
                {"error": "You don't have the required permissions."},
                status=status.HTTP_403_FORBIDDEN,
            )

        tz = ZoneInfo(Workspace.objects.get(slug=slug).timezone)
        completed_from = datetime.combine(start, time.min, tzinfo=tz)
        completed_to = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)
        pipeline_end = end + timedelta(days=PIPELINE_DAYS)

        finished_q = Q(state__group="completed", completed_at__gte=completed_from, completed_at__lt=completed_to)
        in_progress_q = Q()
        for name in IN_PROGRESS_STATE_NAMES:
            in_progress_q |= Q(state__name__iexact=name)
        pipeline_q = Q(start_date__gt=end, start_date__lte=pipeline_end)

        issues = (
            Issue.issue_objects.filter(project_id__in=project_ids)
            .exclude(state__group="cancelled")
            .filter(finished_q | in_progress_q | pipeline_q)
            .select_related("project", "state")
            .order_by("project__name", "sequence_id")
        )
        if issues.count() > MAX_ITEMS:
            return _bad_request("Too many items, select fewer projects or a shorter period")

        items = []
        for issue in issues:
            state = issue.state
            groups = []
            if (
                state.group == "completed"
                and issue.completed_at is not None
                and completed_from <= issue.completed_at < completed_to
            ):
                groups.append("finished")
            if state.name.lower() in {name.lower() for name in IN_PROGRESS_STATE_NAMES}:
                groups.append("in_progress")
            if issue.start_date is not None and end < issue.start_date <= pipeline_end:
                groups.append("pipeline")
            items.append(
                {
                    "id": str(issue.id),
                    "key": f"{issue.project.identifier}-{issue.sequence_id}",
                    "name": issue.name,
                    "project_id": str(issue.project_id),
                    "state_name": state.name,
                    "state_group": state.group,
                    "start_date": issue.start_date,
                    "target_date": issue.target_date,
                    "completed_at": issue.completed_at,
                    "groups": groups,
                }
            )

        return Response(
            {
                "period": {"start": start, "end": end, "pipeline_end": pipeline_end},
                "projects": [{"id": str(p.id), "name": p.name, "identifier": p.identifier} for p in projects],
                "items": items,
            },
            status=status.HTTP_200_OK,
        )

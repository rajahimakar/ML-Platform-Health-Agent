"""
collectors/jira_collector.py
Pulls open platform tickets from Jira — P1/P2/High priority issues,
recent ticket velocity, and SLA breaches.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from jira import JIRA, JIRAError

from config import settings

logger = logging.getLogger(__name__)


def get_jira_client() -> JIRA:
    return JIRA(
        server=settings.jira_url,
        basic_auth=(settings.jira_email, settings.jira_api_token),
    )


def collect() -> dict[str, Any]:
    """
    Returns open high-priority tickets, recently resolved tickets,
    and ticket velocity metrics for the ML platform project.
    """
    logger.info("Collecting Jira ticket data...")
    try:
        client = get_jira_client()
        project = settings.jira_project_key
        priorities = '", "'.join(settings.jira_priorities)

        # ── Open high priority tickets ──────────────────────────
        open_jql = (
            f'project = "{project}" '
            f'AND status != Done '
            f'AND priority in ("{priorities}") '
            f'ORDER BY priority ASC, created DESC'
        )
        open_issues = client.search_issues(open_jql, maxResults=50, fields=[
            "summary", "status", "priority", "assignee",
            "created", "updated", "description", "comment"
        ])

        # ── Tickets resolved in last 24h ────────────────────────
        resolved_jql = (
            f'project = "{project}" '
            f'AND status = Done '
            f'AND resolved >= -24h '
            f'ORDER BY resolved DESC'
        )
        resolved_issues = client.search_issues(resolved_jql, maxResults=20, fields=[
            "summary", "priority", "resolutiondate"
        ])

        # ── All tickets created in last 7 days (velocity) ───────
        velocity_jql = (
            f'project = "{project}" '
            f'AND created >= -7d '
            f'ORDER BY created DESC'
        )
        velocity_issues = client.search_issues(velocity_jql, maxResults=200, fields=["created", "status"])

        open_formatted = [_format_issue(i) for i in open_issues]
        resolved_formatted = [_format_resolved(i) for i in resolved_issues]

        # Count by priority
        priority_counts: dict[str, int] = {}
        for issue in open_formatted:
            p = issue["priority"]
            priority_counts[p] = priority_counts.get(p, 0) + 1

        status = "healthy"
        p1_count = priority_counts.get("P1", 0) + priority_counts.get("Critical", 0)
        p2_count = priority_counts.get("P2", 0) + priority_counts.get("High", 0)
        if p1_count > 0:
            status = "critical"
        elif p2_count > 2:
            status = "warning"

        result = {
            "source": "jira",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "open_high_priority": len(open_formatted),
                "resolved_last_24h": len(resolved_formatted),
                "created_last_7d": len(velocity_issues),
                "by_priority": priority_counts,
            },
            "open_tickets": open_formatted,
            "resolved_last_24h": resolved_formatted,
            "status": status,
        }

        logger.info(f"Jira: {result['summary']}")
        return result

    except JIRAError as e:
        logger.error(f"Jira collector failed: {e}")
        return {
            "source": "jira",
            "status": "error",
            "error": str(e),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }


def _format_issue(issue) -> dict:
    fields = issue.fields
    return {
        "key": issue.key,
        "summary": fields.summary,
        "priority": fields.priority.name if fields.priority else "Unknown",
        "status": fields.status.name if fields.status else "Unknown",
        "assignee": fields.assignee.displayName if fields.assignee else "Unassigned",
        "created": str(fields.created),
        "updated": str(fields.updated),
        "url": f"{settings.jira_url}/browse/{issue.key}",
    }


def _format_resolved(issue) -> dict:
    fields = issue.fields
    return {
        "key": issue.key,
        "summary": fields.summary,
        "priority": fields.priority.name if fields.priority else "Unknown",
        "resolved_at": str(fields.resolutiondate),
        "url": f"{settings.jira_url}/browse/{issue.key}",
    }

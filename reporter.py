"""
reporter.py
Renders the HTML report and delivers it via Email and Microsoft Teams.
"""
import json
import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import requests
from jinja2 import Environment, FileSystemLoader

from config import settings

logger = logging.getLogger(__name__)

STATUS_COLOR = {
    "healthy":  "#1a7a3a",
    "warning":  "#b45309",
    "critical": "#991b1b",
    "error":    "#6b21a8",
}

STATUS_EMOJI = {
    "healthy":  "✅",
    "warning":  "⚠️",
    "critical": "🔴",
    "error":    "❌",
}


def render_and_deliver(report: dict[str, Any], snapshot: dict[str, Any]) -> Path:
    """
    Main entry point:
    1. Render HTML report
    2. Save to disk
    3. Send email
    4. Post Teams card
    Returns the path to the saved HTML report.
    """
    html = _render_html(report)
    report_path = _save_report(html, report)

    _send_email(html, report)
    _send_teams(report, snapshot, report_path)

    return report_path


def _render_html(report: dict) -> str:
    """Render the Jinja2 HTML template with report data."""
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
        autoescape=True,
    )
    template = env.get_template("report.html")

    overall = report.get("overall_status", "error")
    narrative = report.get("narrative", "")
    # Split narrative into paragraphs
    narrative_paragraphs = [p.strip() for p in narrative.split("\n\n") if p.strip()]
    if not narrative_paragraphs:
        narrative_paragraphs = [narrative]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return template.render(
        overall_status=overall.upper(),
        status_color=STATUS_COLOR.get(overall, "#6b7280"),
        headline=report.get("headline", ""),
        narrative_paragraphs=narrative_paragraphs,
        anomalies=report.get("anomalies", []),
        recommended_actions=report.get("recommended_actions", []),
        source_statuses=report.get("source_statuses", {}),
        generated_at=now,
        collected_at=report.get("snapshot_collected_at", now),
        generated_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )


def _save_report(html: str, report: dict) -> Path:
    """Save HTML report to disk with timestamp filename."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"platform_health_{ts}.html"
    path = settings.report_dir / filename

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    # Also save raw JSON for audit trail
    json_path = settings.report_dir / f"platform_health_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"Report saved: {path}")
    return path


def _send_email(html: str, report: dict) -> None:
    """Send the HTML report as an email."""
    if not settings.email_recipients:
        logger.warning("No email recipients configured — skipping email.")
        return

    overall = report.get("overall_status", "error").upper()
    emoji = STATUS_EMOJI.get(report.get("overall_status", "error"), "📋")
    subject = f"{emoji} ML Platform Health — {overall} — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = settings.email_from
    msg["To"]      = ", ".join(settings.email_recipients)

    # Plain text fallback
    plain = (
        f"ML Platform Health Report\n"
        f"Status: {overall}\n"
        f"{report.get('headline', '')}\n\n"
        f"{report.get('narrative', '')}\n\n"
        f"View full report in the HTML attachment."
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(
                settings.email_from,
                settings.email_recipients,
                msg.as_string(),
            )
        logger.info(f"Email sent to {settings.email_recipients}")
    except Exception as e:
        logger.error(f"Email delivery failed: {e}")


def _send_teams(report: dict, snapshot: dict, report_path: Path) -> None:
    """Post an Adaptive Card summary to Microsoft Teams via webhook."""
    if not settings.teams_webhook_url:
        logger.warning("No Teams webhook configured — skipping Teams notification.")
        return

    overall = report.get("overall_status", "error")
    emoji = STATUS_EMOJI.get(overall, "📋")
    color = STATUS_COLOR.get(overall, "#6b7280").lstrip("#")

    facts = snapshot.get("quick_facts", {})
    source_statuses = report.get("source_statuses", {})

    # Build facts table for Teams card
    fact_pairs = [
        {"title": "🤖 ML Jobs Failed",       "value": str(facts.get("ml_jobs_failed", "—"))},
        {"title": "🤖 ML Jobs Running",       "value": str(facts.get("ml_jobs_running", "—"))},
        {"title": "🔔 Critical Alerts",       "value": str(facts.get("monitor_critical_alerts", "—"))},
        {"title": "🎫 Open P1/P2 Tickets",    "value": str(facts.get("jira_open_high_priority", "—"))},
        {"title": "✅ Tickets Resolved (24h)", "value": str(facts.get("jira_resolved_24h", "—"))},
        {"title": "🖥️ Shell Check Failures",  "value": str(facts.get("shell_checks_critical", "—"))},
    ]

    # Top anomaly for Teams preview
    anomalies = report.get("anomalies", [])
    top_anomaly = anomalies[0]["title"] if anomalies else "No anomalies detected"

    # Top action
    actions = report.get("recommended_actions", [])
    top_action = actions[0]["action"] if actions else "No actions required"

    # Source status summary line
    src_summary = " | ".join(
        f"{STATUS_EMOJI.get(v, '❓')} {k.replace('_', ' ').title()}: {v.upper()}"
        for k, v in source_statuses.items()
    )

    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": color,
        "summary": f"ML Platform Health — {overall.upper()}",
        "sections": [
            {
                "activityTitle": f"{emoji} ML Platform Health Report",
                "activitySubtitle": f"**{overall.upper()}** — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
                "activityText": report.get("headline", ""),
            },
            {
                "title": "Platform Metrics",
                "facts": fact_pairs,
            },
            {
                "title": "Source Statuses",
                "text": src_summary,
            },
            {
                "title": "Top Anomaly",
                "text": f"⚠️ {top_anomaly}",
            },
            {
                "title": "Recommended Action #1",
                "text": f"🎯 {top_action}",
            },
        ],
        "potentialAction": [
            {
                "@type": "OpenUri",
                "name": "View Full Report",
                "targets": [{"os": "default", "uri": f"file://{report_path}"}],
            }
        ],
    }

    try:
        response = requests.post(
            settings.teams_webhook_url,
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        logger.info("Teams notification sent successfully.")
    except Exception as e:
        logger.error(f"Teams delivery failed: {e}")

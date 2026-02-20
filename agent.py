"""
agent.py
The Claude LLM reasoning layer.
Takes the aggregated platform snapshot and produces a structured
health report with narrative, anomaly flags, and prioritised actions.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any

import anthropic

from config import settings

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

SYSTEM_PROMPT = """
You are an expert ML Platform Health Agent for an enterprise retail organisation.
You have deep knowledge of MLOps, Azure ML, Azure Monitor, and platform reliability engineering.

Your job is to analyse the platform health snapshot and produce a clear, actionable report.

You must respond ONLY with a valid JSON object — no preamble, no markdown, no explanation outside the JSON.

The JSON must follow this exact schema:
{
  "overall_status": "healthy|warning|critical",
  "headline": "One sentence platform status summary",
  "narrative": "2-4 paragraph plain English summary of what is happening across the platform",
  "anomalies": [
    {
      "severity": "critical|warning|info",
      "source": "azure_ml|azure_monitor|jira|shell",
      "title": "Short anomaly title",
      "detail": "What is wrong and why it matters"
    }
  ],
  "recommended_actions": [
    {
      "priority": 1,
      "action": "What to do",
      "rationale": "Why this should be done first",
      "owner": "Platform Engineer|Data Science Team|Management"
    }
  ],
  "source_statuses": {
    "azure_ml": "healthy|warning|critical|error",
    "azure_monitor": "healthy|warning|critical|error",
    "jira": "healthy|warning|critical|error",
    "shell": "healthy|warning|critical|error"
  },
  "generated_at": "ISO timestamp"
}

Rules:
- Be specific — use actual job names, ticket keys, alert names from the data
- Prioritise actions by business impact, not just severity
- Keep the narrative readable by both engineers AND managers
- If a collector returned an error, note it but do not let it block the report
- Never hallucinate data — only reference what is in the snapshot
""".strip()


def analyse(snapshot: dict[str, Any]) -> dict[str, Any]:
    """
    Send the platform snapshot to Claude and get back a structured health report.
    """
    logger.info("Sending snapshot to Claude for analysis...")

    prompt = _build_prompt(snapshot)

    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()

        # Strip accidental markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        report = json.loads(raw)
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        report["snapshot_collected_at"] = snapshot.get("collected_at")

        logger.info(f"Agent analysis complete. Status: {report.get('overall_status', 'unknown').upper()}")
        return report

    except json.JSONDecodeError as e:
        logger.error(f"Claude returned invalid JSON: {e}")
        return _fallback_report(snapshot, f"JSON parse error: {e}")
    except Exception as e:
        logger.error(f"Agent analysis failed: {e}")
        return _fallback_report(snapshot, str(e))


def _build_prompt(snapshot: dict) -> str:
    """Build the user prompt from the snapshot."""
    facts = snapshot.get("quick_facts", {})
    collected_at = snapshot.get("collected_at", "unknown")
    overall = snapshot.get("overall_status", "unknown")

    # Quick facts header for fast LLM orientation
    header = f"""
PLATFORM HEALTH SNAPSHOT
Collected: {collected_at}
Overall Status: {overall.upper()}

QUICK FACTS:
- Azure ML: {facts.get('ml_jobs_failed', '?')} failed jobs, {facts.get('ml_jobs_running', '?')} running, {facts.get('ml_jobs_completed', '?')} completed
- Azure Monitor: {facts.get('monitor_critical_alerts', '?')} critical alerts, {facts.get('monitor_warnings', '?')} warnings
- Jira: {facts.get('jira_open_high_priority', '?')} open high-priority tickets, {facts.get('jira_resolved_24h', '?')} resolved last 24h
- Shell Checks: {facts.get('shell_checks_critical', '?')} critical, {facts.get('shell_checks_warnings', '?')} warnings

FULL DATA:
""".strip()

    # Serialize full snapshot — keep it lean by truncating large lists
    lean_snapshot = _trim_snapshot(snapshot)
    data = json.dumps(lean_snapshot, indent=2, default=str)

    return f"{header}\n\n{data}"


def _trim_snapshot(snapshot: dict) -> dict:
    """Trim large lists to keep the prompt within token limits."""
    import copy
    s = copy.deepcopy(snapshot)

    ml = s.get("sources", {}).get("azure_ml", {})
    # Keep full failed jobs, trim completed
    ml["completed_jobs"] = ml.get("completed_jobs", [])[:5]

    return s


def _fallback_report(snapshot: dict, error: str) -> dict:
    """Return a minimal report when the LLM call fails."""
    return {
        "overall_status": snapshot.get("overall_status", "error"),
        "headline": "Health report generation failed — manual review required",
        "narrative": f"The agent encountered an error during analysis: {error}. Raw data has been collected and is available in the JSON log.",
        "anomalies": [],
        "recommended_actions": [
            {
                "priority": 1,
                "action": "Review raw collected data in the JSON log file",
                "rationale": "LLM analysis failed — raw data still available",
                "owner": "Platform Engineer",
            }
        ],
        "source_statuses": {
            src: snapshot.get("sources", {}).get(src, {}).get("status", "unknown")
            for src in ["azure_ml", "azure_monitor", "jira", "shell"]
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }

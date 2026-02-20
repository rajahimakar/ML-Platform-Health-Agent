"""
aggregator.py
Runs all collectors in parallel, normalises the results into a single
structured context object ready for the LLM agent.
"""
import logging
import concurrent.futures
from datetime import datetime, timezone
from typing import Any

from collectors import azure_ml, azure_monitor, jira_collector, shell_collector

logger = logging.getLogger(__name__)

# RAG status priority — higher index wins
STATUS_RANK = {"healthy": 0, "warning": 1, "critical": 2, "error": 2}


def collect_all() -> dict[str, Any]:
    """
    Run all collectors concurrently and return a unified platform snapshot.
    """
    logger.info("Starting parallel data collection from all sources...")

    collectors = {
        "azure_ml":      azure_ml.collect,
        "azure_monitor": azure_monitor.collect,
        "jira":          jira_collector.collect,
        "shell":         shell_collector.collect,
    }

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fn): name for name, fn in collectors.items()}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
                logger.info(f"✓ {name} collected — status: {results[name].get('status', 'unknown')}")
            except Exception as e:
                logger.error(f"✗ {name} collector raised exception: {e}")
                results[name] = {
                    "source": name,
                    "status": "error",
                    "error": str(e),
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                }

    # ── Derive overall platform status ──────────────────────────
    overall_status = "healthy"
    for r in results.values():
        s = r.get("status", "healthy")
        if STATUS_RANK.get(s, 0) > STATUS_RANK.get(overall_status, 0):
            overall_status = s

    # ── Build unified snapshot ───────────────────────────────────
    snapshot = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall_status,
        "sources": results,
        # Flattened key facts for quick LLM consumption
        "quick_facts": _extract_quick_facts(results),
    }

    logger.info(f"Collection complete. Overall platform status: {overall_status.upper()}")
    return snapshot


def _extract_quick_facts(results: dict) -> dict:
    """Extract the most important numbers for the LLM prompt header."""
    facts = {}

    ml = results.get("azure_ml", {})
    if ml.get("status") != "error":
        s = ml.get("summary", {})
        facts["ml_jobs_failed"]    = s.get("failed", 0)
        facts["ml_jobs_running"]   = s.get("running", 0)
        facts["ml_jobs_completed"] = s.get("completed", 0)

    mon = results.get("azure_monitor", {})
    if mon.get("status") != "error":
        s = mon.get("summary", {})
        facts["monitor_critical_alerts"] = s.get("critical", 0)
        facts["monitor_warnings"]        = s.get("warnings", 0)

    jira = results.get("jira", {})
    if jira.get("status") != "error":
        s = jira.get("summary", {})
        facts["jira_open_high_priority"] = s.get("open_high_priority", 0)
        facts["jira_resolved_24h"]       = s.get("resolved_last_24h", 0)
        facts["jira_created_7d"]         = s.get("created_last_7d", 0)

    shell = results.get("shell", {})
    if shell.get("status") != "error":
        s = shell.get("summary", {})
        facts["shell_checks_critical"] = s.get("critical", 0)
        facts["shell_checks_warnings"] = s.get("warnings", 0)

    return facts

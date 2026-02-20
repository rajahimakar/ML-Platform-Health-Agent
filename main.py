"""
main.py
Entry point for the ML Platform Health Agent.

Usage:
  python main.py              # run once immediately
  python main.py --schedule   # run on schedule (config: SCHEDULE_TIME)
  python main.py --dry-run    # run with mock data (no real Azure/Jira needed)
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import schedule

from aggregator import collect_all
from agent import analyse
from reporter import render_and_deliver

# ── Logging setup ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def run_health_check(dry_run: bool = False) -> None:
    """
    Full pipeline:
    collect → aggregate → analyse → report → deliver
    """
    logger.info("=" * 60)
    logger.info("ML Platform Health Agent — Starting run")
    logger.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 60)

    try:
        # 1. Collect from all sources
        if dry_run:
            logger.info("DRY RUN: Loading mock data...")
            snapshot = _load_mock_data()
        else:
            snapshot = collect_all()

        # 2. Analyse with Claude
        report = analyse(snapshot)

        # 3. Render + deliver (email + Teams + save HTML)
        report_path = render_and_deliver(report, snapshot)

        logger.info("=" * 60)
        logger.info(f"Run complete. Status: {report.get('overall_status','?').upper()}")
        logger.info(f"Report saved: {report_path}")
        logger.info("=" * 60)

    except Exception as e:
        logger.critical(f"Health agent run failed catastrophically: {e}", exc_info=True)


def _load_mock_data() -> dict:
    """
    Load mock platform data for dry-run / portfolio demo mode.
    Simulates a platform with some warnings to make the report interesting.
    """
    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": "warning",
        "quick_facts": {
            "ml_jobs_failed": 2,
            "ml_jobs_running": 5,
            "ml_jobs_completed": 18,
            "monitor_critical_alerts": 0,
            "monitor_warnings": 3,
            "jira_open_high_priority": 4,
            "jira_resolved_24h": 2,
            "jira_created_7d": 11,
            "shell_checks_critical": 0,
            "shell_checks_warnings": 1,
        },
        "sources": {
            "azure_ml": {
                "source": "azure_ml",
                "status": "warning",
                "lookback_hours": 24,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "summary": {"total": 25, "completed": 18, "failed": 2, "running": 5, "other": 0},
                "failed_jobs": [
                    {"name": "demand-forecast-prod-run-20241201", "display_name": "Demand Forecast Prod",
                     "status": "Failed", "type": "pipeline", "error": {"message": "OOMKilled on compute cluster"}},
                    {"name": "churn-model-retrain-weekly", "display_name": "Churn Model Weekly Retrain",
                     "status": "Failed", "type": "command", "error": {"message": "Data drift detected — input schema mismatch"}},
                ],
                "running_jobs": [
                    {"name": "pricing-model-inference-batch", "display_name": "Pricing Inference Batch", "status": "Running"},
                    {"name": "inventory-forecast-daily",     "display_name": "Inventory Forecast Daily", "status": "Running"},
                ],
                "compute": [
                    {"name": "cpu-cluster-prod",  "type": "AmlCompute", "state": "Succeeded"},
                    {"name": "gpu-cluster-train", "type": "AmlCompute", "state": "Succeeded"},
                ],
            },
            "azure_monitor": {
                "source": "azure_monitor",
                "status": "warning",
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "summary": {"total_alerts": 3, "critical": 0, "warnings": 3},
                "critical_alerts": [],
                "warning_alerts": [
                    {"alertName": "High CPU on cpu-cluster-prod",   "severity": "Sev2", "targetResource": "cpu-cluster-prod"},
                    {"alertName": "Storage account latency elevated", "severity": "Sev3", "targetResource": "mlstorageprod"},
                    {"alertName": "Endpoint response time > 2s",     "severity": "Sev3", "targetResource": "pricing-endpoint"},
                ],
                "resource_health": [],
            },
            "jira": {
                "source": "jira",
                "status": "warning",
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "summary": {
                    "open_high_priority": 4,
                    "resolved_last_24h": 2,
                    "created_last_7d": 11,
                    "by_priority": {"P1": 0, "P2": 2, "High": 2},
                },
                "open_tickets": [
                    {"key": "MLPLAT-412", "summary": "Demand forecast pipeline OOM failure in prod",
                     "priority": "P2", "status": "In Progress", "assignee": "Raja Himakar"},
                    {"key": "MLPLAT-408", "summary": "Churn model retrain failing due to schema drift",
                     "priority": "P2", "status": "Open", "assignee": "Unassigned"},
                    {"key": "MLPLAT-401", "summary": "Pricing endpoint p99 latency exceeding SLA",
                     "priority": "High", "status": "In Progress", "assignee": "Raja Himakar"},
                    {"key": "MLPLAT-399", "summary": "R Shiny dashboard not loading for AU-East users",
                     "priority": "High", "status": "Open", "assignee": "Unassigned"},
                ],
                "resolved_last_24h": [
                    {"key": "MLPLAT-405", "summary": "Compute quota increase approved and applied", "priority": "P2"},
                    {"key": "MLPLAT-397", "summary": "Azure ML SDK version pinned across all pipelines", "priority": "High"},
                ],
            },
            "shell": {
                "source": "shell_checks",
                "status": "warning",
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "summary": {"total_checks": 2, "healthy": 1, "warnings": 1, "critical": 0, "errors": 0},
                "checks": [
                    {"name": "disk_usage_check",    "status": "warning",
                     "output": "High disk usage detected: /mnt/mldata: 87%"},
                    {"name": "python_process_check", "status": "healthy",
                     "output": "12 Python process(es) running"},
                ],
            },
        },
    }


def main():
    parser = argparse.ArgumentParser(description="ML Platform Health Agent")
    parser.add_argument("--schedule", action="store_true", help="Run on schedule")
    parser.add_argument("--dry-run",  action="store_true", help="Use mock data (no Azure/Jira needed)")
    args = parser.parse_args()

    if args.schedule:
        from config import settings
        logger.info(f"Scheduled mode: running daily at {settings.schedule_time} ({settings.schedule_timezone})")
        schedule.every().day.at(settings.schedule_time).do(run_health_check, dry_run=args.dry_run)

        # Run immediately on start too
        run_health_check(dry_run=args.dry_run)

        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        run_health_check(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

"""
collectors/azure_ml.py
Collects Azure ML job run statuses, failure details, and compute health.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from azure.ai.ml import MLClient
from azure.identity import ClientSecretCredential

from config import settings

logger = logging.getLogger(__name__)


def get_ml_client() -> MLClient:
    credential = ClientSecretCredential(
        tenant_id=settings.azure_tenant_id,
        client_id=settings.azure_client_id,
        client_secret=settings.azure_client_secret,
    )
    return MLClient(
        credential=credential,
        subscription_id=settings.azure_subscription_id,
        resource_group_name=settings.azure_ml_resource_group,
        workspace_name=settings.azure_ml_workspace,
    )


def collect() -> dict[str, Any]:
    """
    Returns a structured summary of Azure ML job health
    for the configured lookback window.
    """
    logger.info("Collecting Azure ML job data...")
    try:
        client = get_ml_client()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.azure_ml_lookback_hours)

        jobs = list(client.jobs.list())

        completed, failed, running, other = [], [], [], []

        for job in jobs:
            # Filter to lookback window
            created = getattr(job, "creation_context", None)
            created_at = getattr(created, "created_at", None) if created else None
            if created_at and created_at < cutoff:
                continue

            status = getattr(job, "status", "Unknown")
            entry = {
                "name": job.name,
                "display_name": getattr(job, "display_name", job.name),
                "status": status,
                "type": getattr(job, "type", "Unknown"),
                "created_at": str(created_at) if created_at else "Unknown",
                "error": None,
            }

            if status == "Completed":
                completed.append(entry)
            elif status == "Failed":
                # Try to pull error message
                try:
                    entry["error"] = getattr(job, "error", {})
                except Exception:
                    pass
                failed.append(entry)
            elif status in ("Running", "Starting", "Queued"):
                running.append(entry)
            else:
                other.append(entry)

        # Compute cluster health
        compute_summary = []
        try:
            for compute in client.compute.list():
                compute_summary.append({
                    "name": compute.name,
                    "type": getattr(compute, "type", "Unknown"),
                    "state": getattr(compute, "provisioning_state", "Unknown"),
                })
        except Exception as e:
            logger.warning(f"Could not fetch compute list: {e}")

        result = {
            "source": "azure_ml",
            "lookback_hours": settings.azure_ml_lookback_hours,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total": len(completed) + len(failed) + len(running) + len(other),
                "completed": len(completed),
                "failed": len(failed),
                "running": len(running),
                "other": len(other),
            },
            "failed_jobs": failed,
            "running_jobs": running,
            "completed_jobs": completed[:10],  # last 10 only to keep context lean
            "compute": compute_summary,
            "status": "healthy" if len(failed) == 0 else ("critical" if len(failed) > 3 else "warning"),
        }

        logger.info(f"Azure ML: {result['summary']}")
        return result

    except Exception as e:
        logger.error(f"Azure ML collector failed: {e}")
        return {
            "source": "azure_ml",
            "status": "error",
            "error": str(e),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

"""
collectors/azure_monitor.py
Pulls active alerts and key metrics from Azure Monitor / Log Analytics.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from azure.identity import ClientSecretCredential
from azure.monitor.query import LogsQueryClient, MetricsQueryClient, LogsQueryStatus
from azure.core.exceptions import HttpResponseError

from config import settings

logger = logging.getLogger(__name__)


def get_credentials():
    return ClientSecretCredential(
        tenant_id=settings.azure_tenant_id,
        client_id=settings.azure_client_id,
        client_secret=settings.azure_client_secret,
    )


def collect() -> dict[str, Any]:
    """
    Returns active alerts and platform metric anomalies
    from Azure Monitor Log Analytics.
    """
    logger.info("Collecting Azure Monitor data...")
    try:
        credential = get_credentials()
        logs_client = LogsQueryClient(credential)

        lookback = timedelta(hours=settings.azure_ml_lookback_hours)
        end_time = datetime.now(timezone.utc)
        start_time = end_time - lookback

        alerts = _get_active_alerts(logs_client, start_time, end_time)
        resource_health = _get_resource_health(logs_client, start_time, end_time)

        critical = [a for a in alerts if a.get("severity") in ("Sev0", "Sev1", "Critical")]
        warnings  = [a for a in alerts if a.get("severity") in ("Sev2", "Sev3", "Warning")]

        status = "healthy"
        if critical:
            status = "critical"
        elif warnings:
            status = "warning"

        result = {
            "source": "azure_monitor",
            "collected_at": end_time.isoformat(),
            "lookback_hours": settings.azure_ml_lookback_hours,
            "summary": {
                "total_alerts": len(alerts),
                "critical": len(critical),
                "warnings": len(warnings),
            },
            "critical_alerts": critical,
            "warning_alerts": warnings,
            "resource_health": resource_health,
            "status": status,
        }

        logger.info(f"Azure Monitor: {result['summary']}")
        return result

    except Exception as e:
        logger.error(f"Azure Monitor collector failed: {e}")
        return {
            "source": "azure_monitor",
            "status": "error",
            "error": str(e),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }


def _get_active_alerts(client: LogsQueryClient, start: datetime, end: datetime) -> list:
    """Query Log Analytics for fired alerts."""
    query = """
    AlertsManagementResources
    | where type == 'microsoft.alertsmanagement/alerts'
    | where properties.essentials.startDateTime >= ago(24h)
    | project
        alertName = properties.essentials.alertRule,
        severity  = properties.essentials.severity,
        state     = properties.essentials.alertState,
        monitorCondition = properties.essentials.monitorCondition,
        targetResource   = properties.essentials.targetResourceName,
        firedAt   = properties.essentials.startDateTime
    | order by firedAt desc
    | limit 50
    """
    try:
        response = client.query_workspace(
            workspace_id=settings.azure_monitor_workspace_id,
            query=query,
            timespan=(start, end),
        )
        if response.status == LogsQueryStatus.SUCCESS:
            alerts = []
            for row in response.tables[0].rows:
                cols = response.tables[0].columns
                alerts.append(dict(zip(cols, row)))
            return alerts
        return []
    except HttpResponseError as e:
        logger.warning(f"Alert query failed: {e}")
        return []


def _get_resource_health(client: LogsQueryClient, start: datetime, end: datetime) -> list:
    """Query resource health events from the last window."""
    query = """
    AzureActivity
    | where TimeGenerated >= ago(24h)
    | where Level in ("Critical", "Error", "Warning")
    | summarize EventCount=count() by ResourceGroup, ResourceId, OperationName, Level
    | order by EventCount desc
    | limit 20
    """
    try:
        response = client.query_workspace(
            workspace_id=settings.azure_monitor_workspace_id,
            query=query,
            timespan=(start, end),
        )
        if response.status == LogsQueryStatus.SUCCESS:
            health = []
            for row in response.tables[0].rows:
                cols = response.tables[0].columns
                health.append(dict(zip(cols, row)))
            return health
        return []
    except HttpResponseError as e:
        logger.warning(f"Resource health query failed: {e}")
        return []

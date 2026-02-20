"""
config.py — Centralised settings loaded from environment / .env file.
All other modules import from here — no scattered os.getenv() calls.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
from pathlib import Path


class Settings(BaseSettings):
    # ── Azure Core ──────────────────────────────────────────────
    azure_tenant_id: str
    azure_client_id: str
    azure_client_secret: str
    azure_subscription_id: str

    # ── Azure ML ────────────────────────────────────────────────
    azure_ml_workspace: str
    azure_ml_resource_group: str
    azure_ml_lookback_hours: int = 24

    # ── Azure Monitor ───────────────────────────────────────────
    azure_monitor_workspace_id: str
    azure_monitor_resource_ids: str = ""

    @property
    def monitor_resource_id_list(self) -> List[str]:
        return [r.strip() for r in self.azure_monitor_resource_ids.split(",") if r.strip()]

    # ── Jira ────────────────────────────────────────────────────
    jira_url: str
    jira_email: str
    jira_api_token: str
    jira_project_key: str = "MLPLAT"
    jira_priority_filter: str = "P1,P2,High,Critical"

    @property
    def jira_priorities(self) -> List[str]:
        return [p.strip() for p in self.jira_priority_filter.split(",")]

    # ── Shell Checks ────────────────────────────────────────────
    shell_check_scripts: str = ""

    @property
    def shell_scripts(self) -> List[str]:
        return [s.strip() for s in self.shell_check_scripts.split(",") if s.strip()]

    # ── Claude ──────────────────────────────────────────────────
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-6"

    # ── Email ───────────────────────────────────────────────────
    smtp_host: str = "smtp.office365.com"
    smtp_port: int = 587
    smtp_user: str
    smtp_password: str
    email_from: str
    email_to: str  # comma-separated

    @property
    def email_recipients(self) -> List[str]:
        return [e.strip() for e in self.email_to.split(",") if e.strip()]

    # ── Teams ───────────────────────────────────────────────────
    teams_webhook_url: str

    # ── Scheduler ───────────────────────────────────────────────
    schedule_time: str = "08:00"
    schedule_timezone: str = "Australia/Melbourne"

    # ── Output ──────────────────────────────────────────────────
    report_output_dir: str = "./reports"

    @property
    def report_dir(self) -> Path:
        p = Path(self.report_output_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Singleton — import this everywhere
settings = Settings()

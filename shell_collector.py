"""
collectors/shell_collector.py
Runs custom shell health-check scripts and captures their output.
Scripts should exit 0 for healthy, 1 for warning, 2 for critical.
Output is captured as plain text and passed to the LLM.
"""
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

# Exit code → status mapping
EXIT_STATUS = {0: "healthy", 1: "warning", 2: "critical"}

# Built-in lightweight checks (no external script needed)
BUILTIN_CHECKS = [
    _disk_usage_check,
    _python_process_check,
]


def collect() -> dict[str, Any]:
    """
    Runs all configured shell scripts plus built-in checks.
    Returns structured results for each check.
    """
    logger.info("Running shell health checks...")
    results = []

    # ── Built-in checks ─────────────────────────────────────────
    for check_fn in BUILTIN_CHECKS:
        try:
            results.append(check_fn())
        except Exception as e:
            results.append({
                "name": check_fn.__name__,
                "status": "error",
                "output": str(e),
                "exit_code": -1,
            })

    # ── External scripts from config ────────────────────────────
    for script_path in settings.shell_scripts:
        results.append(_run_script(script_path))

    overall = "healthy"
    for r in results:
        if r["status"] == "critical":
            overall = "critical"
            break
        elif r["status"] in ("warning", "error") and overall == "healthy":
            overall = "warning"

    result = {
        "source": "shell_checks",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_checks": len(results),
            "healthy": sum(1 for r in results if r["status"] == "healthy"),
            "warnings": sum(1 for r in results if r["status"] == "warning"),
            "critical": sum(1 for r in results if r["status"] == "critical"),
            "errors": sum(1 for r in results if r["status"] == "error"),
        },
        "checks": results,
        "status": overall,
    }

    logger.info(f"Shell checks: {result['summary']}")
    return result


def _run_script(script_path: str) -> dict:
    """Execute a shell script and capture output + exit code."""
    path = Path(script_path)
    name = path.name

    if not path.exists():
        return {
            "name": name,
            "script": script_path,
            "status": "error",
            "output": f"Script not found: {script_path}",
            "exit_code": -1,
        }

    try:
        proc = subprocess.run(
            [str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
        status = EXIT_STATUS.get(proc.returncode, "critical")
        output = (proc.stdout + proc.stderr).strip()

        return {
            "name": name,
            "script": script_path,
            "status": status,
            "output": output[:2000],  # cap output length
            "exit_code": proc.returncode,
        }

    except subprocess.TimeoutExpired:
        return {"name": name, "script": script_path, "status": "critical",
                "output": "Script timed out after 30s", "exit_code": -1}
    except Exception as e:
        return {"name": name, "script": script_path, "status": "error",
                "output": str(e), "exit_code": -1}


def _disk_usage_check() -> dict:
    """Built-in: check disk usage on key mount points."""
    try:
        proc = subprocess.run(
            ["df", "-h", "--output=target,pcent"],
            capture_output=True, text=True, timeout=10,
        )
        lines = proc.stdout.strip().split("\n")[1:]  # skip header
        high_usage = []
        for line in lines:
            parts = line.split()
            if len(parts) == 2:
                mount, pct = parts
                try:
                    usage = int(pct.replace("%", ""))
                    if usage >= 90:
                        high_usage.append(f"{mount}: {pct}")
                except ValueError:
                    pass

        status = "critical" if high_usage else "healthy"
        output = (
            f"High disk usage detected: {', '.join(high_usage)}"
            if high_usage else "All mount points under 90% usage"
        )
        return {"name": "disk_usage_check", "status": status, "output": output, "exit_code": 0}
    except Exception as e:
        return {"name": "disk_usage_check", "status": "error", "output": str(e), "exit_code": -1}


def _python_process_check() -> dict:
    """Built-in: verify key Python processes are running."""
    try:
        proc = subprocess.run(
            ["pgrep", "-a", "-f", "python"],
            capture_output=True, text=True, timeout=10,
        )
        running = proc.stdout.strip().split("\n") if proc.stdout.strip() else []
        output = f"{len(running)} Python process(es) running"
        return {"name": "python_process_check", "status": "healthy", "output": output, "exit_code": 0}
    except Exception as e:
        return {"name": "python_process_check", "status": "error", "output": str(e), "exit_code": -1}

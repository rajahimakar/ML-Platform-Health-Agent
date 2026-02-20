# ML Platform Health Agent

An automated agent that monitors your ML platform across **Azure ML**, **Azure Monitor**, **Jira**, and custom shell checks — then uses **Claude AI** to synthesise everything into a plain-English health report delivered via **Email** and **Microsoft Teams** on a daily schedule.

---

## Architecture

```
Scheduler (cron)
     │
     ▼
Collectors (parallel)
├── Azure ML        → job statuses, failures, compute health
├── Azure Monitor   → active alerts, resource health events
├── Jira            → open P1/P2 tickets, velocity metrics
└── Shell Scripts   → custom infra health checks
     │
     ▼
Aggregator          → normalise + structure all data
     │
     ▼
Claude Agent        → analyse, flag anomalies, recommend actions
     │
     ▼
Reporter
├── HTML Report     → saved to disk
├── Email           → full HTML report via SMTP
└── Teams           → Adaptive Card summary via webhook
```

---

## Quick Start

### 1. Clone and install
```bash
git clone https://github.com/rajahimakar/ml-health-agent
cd ml-health-agent
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Run (dry-run with mock data — no Azure needed)
```bash
python main.py --dry-run
```

### 4. Run once against real data
```bash
python main.py
```

### 5. Run on schedule (daily at configured time)
```bash
python main.py --schedule
```

---

## Configuration

All configuration is via environment variables in `.env`:

| Variable | Description |
|---|---|
| `AZURE_TENANT_ID` | Azure AD tenant ID |
| `AZURE_CLIENT_ID` | Service principal client ID |
| `AZURE_CLIENT_SECRET` | Service principal secret |
| `AZURE_ML_WORKSPACE` | Azure ML workspace name |
| `AZURE_MONITOR_WORKSPACE_ID` | Log Analytics workspace ID |
| `JIRA_URL` | Your Jira instance URL |
| `JIRA_API_TOKEN` | Jira API token |
| `ANTHROPIC_API_KEY` | Claude API key |
| `SMTP_HOST` | SMTP server (e.g. smtp.office365.com) |
| `TEAMS_WEBHOOK_URL` | Incoming webhook URL for Teams channel |
| `SCHEDULE_TIME` | Daily run time e.g. `08:00` |

See `.env.example` for the full list.

---

## Project Structure

```
ml-health-agent/
├── main.py                  # Entry point + scheduler
├── config.py                # Settings (pydantic)
├── aggregator.py            # Parallel collector orchestration
├── agent.py                 # Claude LLM analysis layer
├── reporter.py              # HTML render + Email + Teams delivery
├── collectors/
│   ├── azure_ml.py          # Azure ML SDK collector
│   ├── azure_monitor.py     # Azure Monitor / Log Analytics
│   ├── jira_collector.py    # Jira REST API collector
│   └── shell_collector.py   # Shell script runner + built-in checks
├── templates/
│   └── report.html          # Jinja2 HTML report template
├── .env.example
├── requirements.txt
└── README.md
```

---

## Output

Each run produces:
- **`reports/platform_health_YYYYMMDD_HHMMSS.html`** — full visual report
- **`reports/platform_health_YYYYMMDD_HHMMSS.json`** — raw JSON audit log
- **Email** — HTML report to configured recipients
- **Teams message** — summary card with key metrics and top action

---

## Deploying as a Scheduled Job

### Linux cron
```bash
# Run at 8am Melbourne time daily
0 8 * * * cd /opt/ml-health-agent && python main.py >> /var/log/ml-health-agent.log 2>&1
```

### Azure Container Instance (recommended for production)
```bash
# Build
docker build -t ml-health-agent .

# Push to ACR and deploy as ACI with a schedule trigger
az container create \
  --resource-group your-rg \
  --name ml-health-agent \
  --image yourregistry.azurecr.io/ml-health-agent:latest \
  --environment-variables-file .env
```

---

## Adding Custom Shell Checks

Create a script that exits `0` (healthy), `1` (warning), or `2` (critical):

```bash
#!/bin/bash
# checks/my_service_check.sh

STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://my-ml-service/health)
if [ "$STATUS" == "200" ]; then
  echo "Service healthy"
  exit 0
else
  echo "Service returned HTTP $STATUS"
  exit 2
fi
```

Then add it to `.env`:
```
SHELL_CHECK_SCRIPTS=./checks/my_service_check.sh,./checks/another_check.sh
```

---

## Built With

- [Anthropic Claude](https://anthropic.com) — LLM analysis
- [Azure AI ML SDK](https://learn.microsoft.com/azure/machine-learning/) — Azure ML data
- [Azure Monitor Query](https://learn.microsoft.com/azure/azure-monitor/) — Alerts & metrics
- [Jira Python](https://jira.readthedocs.io/) — Jira integration
- [Jinja2](https://jinja.palletsprojects.com/) — HTML templating
- [schedule](https://schedule.readthedocs.io/) — Python job scheduler

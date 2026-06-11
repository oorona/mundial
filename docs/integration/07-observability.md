# Observability: Prometheus, Grafana & Loki

This guide shows how to connect the Baseline Framework to a Prometheus + Grafana + Loki stack for metrics, dashboards, and log aggregation.

> **What's already built in** — you do not need to add instrumentation code.
> The backend already:
> - emits **JSON-structured logs** on stdout (Loki-ready, via `structlog`)
> - exposes a **Prometheus `/metrics` endpoint** at `GET /api/v1/metrics`
> - records **bot command metrics**, **HTTP request metrics**, **guild events**, and **card usage** to Postgres

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│  Docker Compose Stack                                │
│                                                      │
│  backend  ──stdout──►  Promtail ──►  Loki            │
│  bot      ──stdout──►  Promtail                      │
│  frontend ──stdout──►  Promtail                      │
│                                                      │
│  backend  ──/metrics──►  Prometheus                  │
│                                                      │
│  Prometheus ──►  Grafana  (dashboards)               │
│  Loki       ──►  Grafana  (log explorer)             │
└──────────────────────────────────────────────────────┘
```

- **Promtail** reads container stdout and ships logs to Loki
- **Prometheus** scrapes `/api/v1/metrics` on a 15-second interval
- **Grafana** visualises both data sources

---

## 2. Quick Start — Docker Compose

Add the observability services to a `docker-compose.observability.yml` file alongside your existing `docker-compose.yml`. Keep them in a separate file so they can be omitted in environments where monitoring is handled at the host/cloud level.

```yaml
# docker-compose.observability.yml
services:

  # ── Prometheus ────────────────────────────────────────────────────────────
  prometheus:
    image: prom/prometheus:v2.51.0
    container_name: bot-prometheus
    volumes:
      - ./observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --storage.tsdb.retention.time=30d
      - --web.enable-lifecycle          # allows config reload via POST /-/reload
    networks:
      - intranet
    ports:
      - "9090:9090"
    restart: unless-stopped

  # ── Loki ──────────────────────────────────────────────────────────────────
  loki:
    image: grafana/loki:2.9.5
    container_name: bot-loki
    volumes:
      - ./observability/loki.yml:/etc/loki/local-config.yaml:ro
      - loki_data:/loki
    command: -config.file=/etc/loki/local-config.yaml
    networks:
      - intranet
    ports:
      - "3100:3100"
    restart: unless-stopped

  # ── Promtail ──────────────────────────────────────────────────────────────
  promtail:
    image: grafana/promtail:2.9.5
    container_name: bot-promtail
    volumes:
      - ./observability/promtail.yml:/etc/promtail/config.yml:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command: -config.file=/etc/promtail/config.yml
    networks:
      - intranet
    depends_on:
      - loki
    restart: unless-stopped

  # ── Grafana ───────────────────────────────────────────────────────────────
  grafana:
    image: grafana/grafana:10.4.0
    container_name: bot-grafana
    volumes:
      - grafana_data:/var/lib/grafana
      - ./observability/grafana/provisioning:/etc/grafana/provisioning:ro
    environment:
      GF_SECURITY_ADMIN_PASSWORD: "${GRAFANA_ADMIN_PASSWORD:-changeme}"
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_SERVER_ROOT_URL: "https://grafana.yourdomain.com"  # update or leave blank
    networks:
      - intranet
    ports:
      - "3030:3000"      # host:container (avoid clashing with Next.js on 3000)
    depends_on:
      - prometheus
      - loki
    restart: unless-stopped

volumes:
  prometheus_data:
  loki_data:
  grafana_data:
```

Start everything:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
```

---

## 3. Configuration Files

Create an `observability/` directory at the project root.

### 3.1 Prometheus — `observability/prometheus.yml`

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: baseline_backend
    # The metrics endpoint is internal-only; Prometheus reaches the backend
    # directly on the intranet Docker network — no public exposure needed.
    static_configs:
      - targets: ["backend:8000"]
    metrics_path: /api/v1/metrics
    # The endpoint returns 403 for non-internal IPs.
    # Prometheus containers are on the intranet network so they pass the check.
```

> The `/api/v1/metrics` endpoint checks the source IP and rejects anything outside
> `127.0.0.1`, `::1`, and RFC-1918 ranges (`10.*`, `172.*`, `192.168.*`).
> Because Prometheus runs on the same `intranet` Docker network, its container IP
> falls into the `172.*` range and is always accepted without any auth header.

### 3.2 Loki — `observability/loki.yml`

```yaml
auth_enabled: false

server:
  http_listen_port: 3100

ingester:
  lifecycler:
    ring:
      kvstore:
        store: inmemory
      replication_factor: 1
    final_sleep: 0s
  chunk_idle_period: 1h
  chunk_retain_period: 30s

schema_config:
  configs:
    - from: 2024-01-01
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

storage_config:
  boltdb_shipper:
    active_index_directory: /loki/index
    cache_location: /loki/cache
    shared_store: filesystem
  filesystem:
    directory: /loki/chunks

limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  retention_period: 720h   # 30 days

compactor:
  working_directory: /loki/compactor
  shared_store: filesystem
```

### 3.3 Promtail — `observability/promtail.yml`

```yaml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: docker_containers
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 5s
    relabel_configs:
      # Use the Docker container name as the Loki "container" label
      - source_labels: [__meta_docker_container_name]
        target_label: container
        regex: "/(.*)"
        replacement: "$1"

      # Map each service to a Loki "service" label for easy filtering
      - source_labels: [__meta_docker_container_name]
        target_label: service
        regex: "bot-(backend|bot|frontend|discord)"
        replacement: "$1"

    pipeline_stages:
      # All three services emit JSON logs via structlog.
      # Parse the JSON so Loki can index the fields as labels.
      - json:
          expressions:
            level: level
            service: service
            env: env
            event: event
      - labels:
          level:
          service:
          env:
```

> **Why JSON parsing matters**: `structlog` is already configured in `backend/main.py`
> (and the bot) to emit JSON with `service`, `env`, and `level` fields on every line.
> Promtail's `json` stage extracts those as Loki labels, making log queries like
> `{service="backend", level="error"}` instant.

### 3.4 Grafana Provisioning

Auto-provision the data sources so Grafana is ready on first boot without manual UI steps.

**`observability/grafana/provisioning/datasources/datasources.yml`**

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false

  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    editable: false
```

---

## 4. Available Metrics

The backend registers the following Prometheus metrics in `backend/app/api/prom_metrics.py`:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_requests_total` | Counter | `method`, `path`, `status` | All HTTP requests handled |
| `http_request_duration_seconds` | Histogram | `method`, `path` | Request latency (10 buckets, 10ms–10s) |
| `bot_commands_total` | Counter | `command`, `cog`, `success` | Discord slash command invocations |
| `bot_command_duration_seconds` | Histogram | `command`, `cog` | Command execution latency |
| `card_views_total` | Counter | `card_id`, `permission_level` | Dashboard card clicks |
| `guild_count_total` | Gauge | — | Current guild count (updated on join/leave) |
| `guild_joins_total` | Counter | — | Total guild join events |
| `guild_leaves_total` | Counter | — | Total guild leave events |

---

## 5. Grafana Dashboards

### 5.1 Suggested Panels — HTTP Performance

```
# Panel: Request rate (req/s)
rate(http_requests_total[5m])

# Panel: Error rate (5xx)
sum(rate(http_requests_total{status=~"5.."}[5m]))
/ sum(rate(http_requests_total[5m])) * 100

# Panel: p95 latency by endpoint
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le, path)
)

# Panel: p99 latency overall
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
)
```

### 5.2 Suggested Panels — Bot Commands

```
# Panel: Commands per minute
sum(rate(bot_commands_total[5m])) * 60

# Panel: Top commands (table)
topk(10, sum(rate(bot_commands_total[1h])) by (command, cog))

# Panel: Command error rate by cog
sum(rate(bot_commands_total{success="False"}[5m])) by (cog)

# Panel: p95 command latency
histogram_quantile(0.95,
  sum(rate(bot_command_duration_seconds_bucket[5m])) by (le, command)
)
```

### 5.3 Suggested Panels — Guild Growth

```
# Panel: Current guilds (stat)
guild_count_total

# Panel: Guild joins vs leaves (time series)
rate(guild_joins_total[1h])
rate(guild_leaves_total[1h])
```

### 5.4 Suggested Log Queries (Loki / Explore)

```logql
# All backend errors in the last hour
{service="backend", level="error"} | json

# Command failures from the bot
{service="bot"} | json | event="command_failed"

# Slow HTTP requests (> 1s) — requires duration field in log
{service="backend"} | json | duration > 1000

# All logs for a specific guild
{service="backend"} | json | guild_id="123456789"

# Auth failures
{service="backend"} | json | event="session_expired" or event="platform_admin_check_failed"
```

---

## 6. Adding Custom Metrics to a Cog

To track cog-specific metrics, import the registry and add your own counters alongside the existing ones.

```python
# The bot and backend are separate services — the bot cannot import from backend directly.
# The correct pattern is to POST to the instrumentation endpoint from your cog:
#
# POST /api/v1/instrumentation/bot-command  (already done by the framework for every command)
#
# For entirely new event types:
# 1. Add a new Counter/Histogram to backend/app/api/prom_metrics.py
# 2. Add a new POST endpoint in backend/app/api/instrumentation.py following the existing pattern
# 3. Call that endpoint from your cog using self.bot.session.post(...)
```

For **bot-side custom events**, post to the instrumentation endpoint from your cog — the pattern is already established in the framework:

```python
# bot/cogs/my_cog.py
import time

async def _record_my_event(self, event_name: str, duration_ms: float):
    payload = {
        "command": event_name,
        "cog": "MyCog",
        "guild_id": ...,
        "user_id": ...,
        "duration_ms": duration_ms,
        "success": True,
    }
    # Use self.bot.session — never create a new aiohttp.ClientSession per call
    await self.bot.session.post(
        "http://backend:8000/api/v1/instrumentation/bot-command",
        json=payload,
    )
```

---

## 7. Adding Custom Log Fields for Loki

Every `structlog` call already emits `service`, `env`, and `level`. Add domain-specific fields to make log queries faster:

```python
# bot/cogs/my_cog.py
import structlog
logger = structlog.get_logger()

# Bad — Loki cannot filter on embedded text
logger.info(f"User {user_id} used command {cmd} in guild {guild_id}")

# Good — Loki indexes these as labels / parsed fields
logger.info("command_used",
    command=cmd,
    user_id=user_id,
    guild_id=guild_id,
    duration_ms=elapsed,
)
```

Useful standard fields (use these names consistently so Loki queries work across services):

| Field | Type | Example |
|-------|------|---------|
| `command` | str | `"gemini-demo thinking"` |
| `user_id` | int | `123456789` |
| `guild_id` | int | `987654321` |
| `cog` | str | `"GeminiCapabilitiesDemo"` |
| `error` | str | `"HTTPException: 503"` |
| `duration_ms` | float | `142.7` |
| `event` | str | `"command_failed"` |

---

## 8. Security Notes

- **`/api/v1/metrics`** — returns 403 to any IP outside RFC-1918 ranges. Never expose this port publicly; keep Prometheus on the `intranet` Docker network.
- **Grafana** — run behind your reverse proxy (nginx / Caddy) with TLS. Set `GF_SECURITY_ADMIN_PASSWORD` via an environment variable or Docker secret, never hardcoded.
- **Loki** — likewise internal-only. Loki has no authentication in the default config above; add `auth_enabled: true` and a reverse proxy with basic auth if Loki is exposed beyond localhost.
- **Prometheus** — internal only. Do not expose port 9090 publicly.

Production compose override example for keeping all observability ports off the public interface:

```yaml
# docker-compose.prod.yml  (add to existing file)
services:
  prometheus:
    ports: []          # remove 9090 — Grafana reaches it via intranet network
  loki:
    ports: []          # remove 3100
  grafana:
    ports:
      - "127.0.0.1:3030:3000"   # only localhost — put nginx in front
```

---

## 9. Alerting (Prometheus Alertmanager)

Add Alertmanager for on-call alerts (PagerDuty, Slack, email).

**`observability/alerts.yml`** (mount into Prometheus):

```yaml
groups:
  - name: baseline_alerts
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
          / sum(rate(http_requests_total[5m])) > 0.05
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Backend error rate > 5%"

      - alert: BotCommandsDown
        expr: sum(rate(bot_commands_total[5m])) == 0
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "No bot commands recorded for 10 minutes — bot may be down"

      - alert: HighP99Latency
        expr: |
          histogram_quantile(0.99,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
          ) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "p99 API latency above 2 seconds"
```

Reference `alerts.yml` from `prometheus.yml`:

```yaml
# observability/prometheus.yml
rule_files:
  - /etc/prometheus/alerts.yml
```

And mount it in the Prometheus service:

```yaml
# docker-compose.observability.yml
prometheus:
  volumes:
    - ./observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    - ./observability/alerts.yml:/etc/prometheus/alerts.yml:ro
    - prometheus_data:/prometheus
```

---

## 10. File Structure Summary

```
observability/
├── prometheus.yml                          # Scrape config
├── alerts.yml                              # Alert rules (optional)
├── loki.yml                                # Loki storage config
├── promtail.yml                            # Log shipping config
└── grafana/
    └── provisioning/
        └── datasources/
            └── datasources.yml             # Auto-provision Prometheus + Loki
```

```
docker-compose.yml                          # Core services (no changes needed)
docker-compose.observability.yml           # Add this file
docker-compose.prod.yml                     # Production overrides (ports, resources)
```

---

## Data Retention and Purge

Instrumentation data accumulates in Postgres over time. Use the purge endpoint to clean up old records without a full table truncation.

**Endpoint:** `DELETE /api/v1/instrumentation/data` — L6 Developer access required.

### Examples

```bash
# Purge all data older than 90 days across all tables
curl -X DELETE "https://your-api/api/v1/instrumentation/data?older_than_days=90&tables=all" \
     -H "Authorization: Bearer <token>"

# Purge only request_metrics before a specific date
curl -X DELETE "https://your-api/api/v1/instrumentation/data?before=2025-01-01&tables=request_metrics" \
     -H "Authorization: Bearer <token>"

# Purge guild_events and card_usage for a date range
curl -X DELETE "https://your-api/api/v1/instrumentation/data?after=2024-01-01&before=2025-01-01&tables=guild_events,card_usage" \
     -H "Authorization: Bearer <token>"
```

The response lists deleted row counts per table:
```json
{"deleted": {"guild_events": 120, "card_usage": 340, "bot_commands": 0, "request_metrics": 0}}
```

Valid table keys: `guild_events`, `card_usage`, `bot_commands`, `request_metrics`.

The dashboard Instrumentation page also exposes a **Purge Data** button (visible to L6 developers) with a modal for mode selection (all / older than N days / date range) and table checkboxes.

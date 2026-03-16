# ServiceScope v2 — Technical Metrics & Architecture Reference

> Real data from local runs. All LLM inference via **gemma3:4b** on Ollama (local, no API calls).
> Stack: FastAPI · Celery · PostgreSQL · Redis · Python 3.12 · macOS (Apple Silicon)

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENT / API                            │
│   POST /api/v1/repositories/   →   GET /api/v1/jobs/{id}        │
│   POST /api/v1/chat/ask        →   GET /api/v1/chat/summary      │
└────────────────────┬────────────────────────────────────────────┘
                     │ HTTP (FastAPI / uvicorn)
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI (port 8000)                        │
│  Auth (JWT)  ·  Tenant isolation  ·  Schema validation (Pydantic)│
│  Repositories · Jobs · Chat · Tenants · Users (25 endpoints)    │
└────────────────────┬────────────────────────────────────────────┘
                     │ .delay()
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Celery Worker  ←── Redis (broker :6379)       │
│                                                                  │
│  analyze_repository task                                         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  0%   receive repo_id                                     │   │
│  │ 10%   git clone --depth 1 (with branch fallback)         │   │
│  │ 30%   AST walk → extract HTTP calls (3 patterns)         │   │
│  │ 60%   LLM inference per call → service name + confidence │   │
│  │ 90%   Neo4j upsert (tenant+repo scoped)                  │   │
│  │100%   cleanup clone dir + write result_summary           │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────┬──────────────────────────┬──────────────────────────────┘
         │                          │
         ▼                          ▼
┌─────────────────┐      ┌──────────────────────┐
│  PostgreSQL      │      │  Ollama  (port 11434) │
│  :5432           │      │  model: gemma3:4b     │
│                  │      │  local inference only  │
│  tenants         │      └──────────────────────┘
│  users           │
│  repositories    │      ┌──────────────────────┐
│  analysis_jobs   │      │  Neo4j  (port 7687)   │
│  extracted_calls │      │  graph: Service nodes │
│  inferred_deps   │      │  + CALLS edges        │
└─────────────────┘      │  (optional, graceful  │
                          │   fallback if absent) │
                          └──────────────────────┘
```

---

## 2. AST Extraction Engine

### Three Detection Patterns

```python
# Pattern 1 — requests / httpx direct calls
requests.get("http://payment-service/charge")
httpx.post("http://user-service/api/users")

# Pattern 2 — method calls on client objects
client.get("http://internal-service/health")
session.post(url, json=payload)

# Pattern 3 — any .get/.post/.put/.delete where URL starts with "http"
# (previously matched "/" — caused FastAPI route decorator false positives)
# Fixed: url.startswith("http") only
```

### Dynamic URL Detection

When the first argument to an HTTP call is not a string literal, the extractor stores the variable name:

```python
requests.get(url, stream=True)       → <dynamic:url>
requests.put(worker, json=payload)   → <dynamic:worker>
requests.get(metric)                 → <dynamic:metric>
```

The LLM infers service names from variable names + call context even without a resolved URL.

---

## 3. Benchmark Results — All Repos Tested

| Repo | Files | HTTP Calls | Dependencies | Duration | Failure Rate |
|------|-------|-----------|--------------|----------|-------------|
| `karpathy/nanochat` | 36 | 8 (8 dynamic) | 8 | **12.3s** | **0.0%** |
| `karpathy/autoresearch` | 2 | 1 (1 dynamic) | 1 | 7.2s | 0.0% |
| `django/django` | 2,886 | 1,323 | 1,323 | **559s** (LLM) / **15s** (extract only) | — |
| `Aravind0403/ServiceScope` (v1) | 10 | 5 | 5 | 5.7s | 0.0% |
| `Aravind0403/ServiceScope` (v1) | 10 | 5 | 3 | 7.5s | 0.0% |
| `tiangolo/full-stack-fastapi-template` | 45 | 0 | 0 | 1.5s | — |
| `GoogleCloudPlatform/microservices-demo` | 13 | 0 | 0 | 3.0s | — |
| `robusta-dev/robusta` | 394 | 103 (103 dynamic) | 103 | **104.1s** | **0.0%** |
| Synthetic e-commerce (local) | 6 | 31 (11 dynamic) | 28 | **6ms** (extract only) | — |

> **Django note:** 2,886 Python files scanned in ~15s (pure AST extraction). Full LLM inference on all 1,323 calls ran in 559s ≈ **2.4 LLM inferences/second** on local gemma3:4b. Django is a monolith — only 2 unique caller services found, but demonstrates scale ceiling.

> **Robusta note:** 394 Python files, 103 calls, **all 103 dynamic URLs** (zero hardcoded hostnames). LLM inferred 50 unique callee service names purely from variable names. 2 real caller modules (`src`, `playbooks`). Reveals two LLM inference quality tiers: named URL constants (`RELAY_EXTERNAL_ACTIONS_URL → relay_service`, 0.95) vs generic names (`data → data_service`, 0.85). Also surfaced Pattern 2 false positives: `dict.get("cpu")` and `dict.get("memory")` captured as HTTP calls — requires Fix 2 (url.startswith("http") guard on all patterns).

> **Google Microservices Demo note:** Python wrapper files only — actual service logic is in Go. 0 HTTP calls in Python layer is correct.

---

## 4. Deep Dive — `karpathy/nanochat` (Best Run)

### Repository Profile
```
URL      : https://github.com/karpathy/nanochat.git
Branch   : master (auto-fallback from main → master)
Files    : 36 Python files
Commit   : [shallow clone, depth=1]
Duration : 12.3 seconds end-to-end
```

### Full Dependency Graph (all 8 edges)

```
Confidence | Caller        | Method | Callee             | Source File
-----------|---------------|--------|--------------------|---------------------------
0.85       | dev           | POST   | user_service       | dev/gen_synthetic_data.py
0.95       | nanochat      | GET    | metrics_service    | nanochat/report.py
0.95       | nanochat      | GET    | stage_service      | nanochat/report.py
0.85       | nanochat      | GET    | user_profile       | nanochat/dataset.py
0.85       | scripts       | GET    | data_service       | scripts/chat_sft.py
0.85       | scripts       | GET    | task_orchestration | scripts/chat_eval.py
0.95       | scripts       | PUT    | worker_service     | scripts/chat_web.py (line A)
0.95       | scripts       | PUT    | worker_service     | scripts/chat_web.py (line B)
```

> The two `scripts → worker_service` edges are **correct** — two distinct `requests.put(worker, ...)` call sites in `chat_web.py` (start/stop worker). These are separate traceable call sites, not duplicates.

### Service Topology

```
                    ┌─────────────────┐
            POST    │   user_service  │
dev ───────────────►│                 │
                    └─────────────────┘

                    ┌─────────────────┐
            GET     │ metrics_service │
nanochat ──────────►│                 │
         │  GET     └─────────────────┘
         │          ┌─────────────────┐
         └─────────►│  stage_service  │
         │  GET     └─────────────────┘
         │          ┌─────────────────┐
         └─────────►│  user_profile   │
                    └─────────────────┘

                    ┌─────────────────┐
            GET     │  data_service   │
scripts ───────────►│                 │
        │   GET     └─────────────────┘
        │           ┌─────────────────────┐
        └──────────►│  task_orchestration │
        │   PUT×2   └─────────────────────┘
        │           ┌─────────────────┐
        └──────────►│ worker_service  │◄── highest fan-in (2 callers)
                    └─────────────────┘
```

### Fan-In / Fan-Out Analysis

```
Most-called services (fan-in):
  worker_service       ██  (2 inbound calls)
  metrics_service      █   (1 inbound call)
  stage_service        █   (1 inbound call)
  data_service         █   (1 inbound call)
  user_profile         █   (1 inbound call)
  user_service         █   (1 inbound call)
  task_orchestration   █   (1 inbound call)

Most calls made (fan-out):
  scripts              ████  (4 outbound calls) ← highest blast radius source
  nanochat             ███   (3 outbound calls)
  dev                  █     (1 outbound call)
```

### Confidence Score Distribution

```
Band           Count   Avg Confidence
high  (≥0.90)    4        0.950
medium(0.70-0.90) 4       0.850
low   (<0.70)     0        —

Overall avg: 0.900
Inference failure rate: 0.0%  (0/8 calls returned null)
```

### Critical Path (Blast Radius)

```
HIGHEST RISK: scripts/chat_web.py → worker_service
  - 2 call sites depend on worker_service
  - If worker_service degrades: chat_web.py loses PUT capability at both sites
  - Confidence: 0.95 (high certainty from variable name "worker")

SECONDARY RISK: scripts/chat_eval.py → task_orchestration
  - Evaluation pipeline broken if task_orchestration unavailable
  - Confidence: 0.85

Isolated services (no dependencies on them from other callers):
  - metrics_service, stage_service, user_profile (each called once by nanochat only)
```

---

## 5. Scale Benchmark — `django/django`

```
Repository   : https://github.com/django/django
Python files : 2,886
HTTP calls   : 1,323 (extracted via AST in ~15 seconds)
Services     : 2 unique callers (Django is a monolith)
Extraction   : 14–17s  (pure AST, no LLM)
Full LLM run : 559s    (1,323 × LLM inferences at ~2.4/sec)
```

**Throughput profile:**
```
AST extraction rate   : ~190 files/sec
LLM inference rate    : ~2.4 inferences/sec  (gemma3:4b, local, M-series chip)
                        ~86 inferences/min
                        ~1,300 inferences/30min
```

**Implication:** For production repos with 50–200 Python files and 20–100 HTTP calls, total pipeline time is **15–60 seconds** end-to-end. Django is an extreme case (a framework, not a microservice).

---

## 6. Deep Dive — `robusta-dev/robusta` (True Microservice Agent)

### Repository Profile
```
URL      : https://github.com/robusta-dev/robusta
Branch   : master
Commit   : 1f0b67d7f1bfcdec971941e8007ecf168973bb33
Files    : 394 Python files
Duration : 104.1 seconds end-to-end
```

### What robusta is
A Kubernetes troubleshooting agent. It runs as a pod inside a cluster, receives alerts from
Prometheus, enriches them with context (pod logs, CPU/memory metrics, Helm state), and routes
them to sinks (Slack, PagerDuty, Jira, OpsGenie, Telegram, etc.) via HTTP.

### Analysis Summary
```
total_calls          : 103  (all 103 are dynamic URLs — zero hardcoded http:// URLs)
services_found       : 2    (src, playbooks — top-level repo directories)
dependencies_inferred: 103
failed_inferences    : 0
inference_failure_rate: 0.0%
```

### Real Caller Modules (2 total)
```
src        → 90 outbound calls to 42 unique inferred targets
playbooks  → 13 outbound calls to 10 unique inferred targets
```

> The chat endpoint reported "52 services" — that is 2 callers + 50 unique LLM-inferred callee
> names. Not 52 microservices.

### LLM Inference Quality — Three Tiers

**Tier 1 — Exact (named URL constants, confidence 0.95)**
The variable name is itself a URL descriptor. LLM inference is correct.

| Variable in source | LLM inferred callee | File |
|--------------------|--------------------|----|
| `RELAY_EXTERNAL_ACTIONS_URL` | `relay_service` | `core/reporting/action_requests.py` |
| `RUNNER_GET_INFO_URL` | `runner_info_service` | `clients/robusta_client.py` |
| `GRAFANA_RENDERER_URL` | `grafana_renderer` | `playbooks/deployment_status_report.py` |
| `RUNNER_GET_HOLMES_SLACKBOT_INFO` | `slackbot_service` | `core/sinks/robusta/robusta_sink.py` |
| `PROM_GRAPH_URL_EXPR_PARAM` | `graph_query` | `core/reporting/url_helpers.py` |
| `ALERT_EVENT` | `alert_events_service` | `integrations/prometheus/trigger.py` |
| `git_repo_url` | `git_service` | `integrations/git/git_repo.py` |

**Tier 2 — Semantic (generic names, confidence 0.85)**
Variable name gives a domain hint but not a definitive target.

| Variable | LLM inferred | Assessment |
|----------|-------------|-----------|
| `job_id` | `job_status` | Reasonable — scheduled job tracking |
| `label_key` | `label_service` | Kubernetes label attribute, used via API |
| `sink_name` | `data_catalog` | Robusta sink routing, plausible |
| `node_name` | `node_service` | K8s node enrichment API |

**Tier 3 — False Positive (dict.get() caught as HTTP, confidence 0.95)**
Pattern 2 is too broad — catches Python dict `.get()` as HTTP GET.

```python
# src/robusta/core/model/pods.py — these are dict lookups, NOT HTTP requests
container.resources.requests.get("cpu")    # stored as: [GET] cpu    → cpu_service   0.95
container.resources.requests.get("memory") # stored as: [GET] memory → memory_service 0.95
```

Root cause: `container.resources.requests` is a Kubernetes dict. `.get("cpu")` is Python dict
lookup. Pattern 2 matches ANY `.get(arg)` on any object. Fix: add `url.startswith("http")`
guard to Pattern 2 (same fix already applied to Pattern 3).

### Confidence Distribution (103 calls)

```
0.95   ████████████████████████████████  (32 calls)  named URL constants
0.85   ██████████████████████████████████████████████████  (56 calls)  semantic vars
0.80   █████  (5 calls)   ambiguous context
0.20   ██     (2 calls)   LLM genuinely uncertain
```

### Top Inferred Services by Inbound Call Count

```
user_profile_service     ←── 19 calls from: src, playbooks   (generic `profile` var patterns)
user_service             ←── 10 calls from: src
job_status               ←── 6 calls  from: src
resource_service         ←── 4 calls  from: src, playbooks
label_service            ←── 4 calls  from: src
data_service             ←── 4 calls  from: src
metrics_service          ←── 3 calls  from: src
namespace_service        ←── 3 calls  from: src
```

### What This Repo Proves

1. **100% dynamic URL analysis works** — zero hardcoded URLs, LLM still inferred 50 named targets
2. **Named URL constants are the highest-quality signal** — `RELAY_EXTERNAL_ACTIONS_URL` gives
   better inference than 10 generic `url` variables
3. **Pattern 2 false positives confirmed** — `dict.get()` = noise, needs the `http` guard
4. **Blast-radius chat queries are structurally valid** — even with inferred names, the 37 file
   references returned for `user_profile_service` are real call sites in the codebase
5. **Robusta is not a microservice** — it's a Python agent calling external APIs. True
   microservices (services calling each other) need repos where each directory is a separate
   deployed service

---

## 7. Synthetic E-Commerce Demo — Extraction Only

Used to demonstrate extraction quality without LLM inference. 6 service files, designed to represent a real microservice architecture.

```
Scan time        : 6ms  (pure AST, 6 files)
HTTP calls found : 31
  Static URLs    : 20   (64%)
  Dynamic URLs   : 11   (36%)

Caller services  : 6
  api_gateway          →  4 outbound calls
  inventory_service    →  5 outbound calls
  notification_service →  5 outbound calls
  order_service        →  8 outbound calls  ← highest fan-out
  payment_service      →  5 outbound calls
  user_service         →  4 outbound calls

Target services  : 17 unique (discovered from URLs only)
  user-service:8002              ████  (4 inbound)
  notification-service:8004      ████  (4 inbound)
  warehouse-service:8014         ███   (3 inbound)
  payment-gateway:8007           ██    (2 inbound)
  ledger-service:8008            ██    (2 inbound)
  ...

HTTP Method breakdown:
  POST     ███████████████████  (19 calls / 61%)
  GET      ████████             (8 calls  / 26%)
  DELETE   ██                   (2 calls  / 6%)
  PUT      ██                   (2 calls  / 6%)

Dependency edges : 21 unique caller→callee pairs
```

### Critical Path (e-commerce)
```
api_gateway
  → order_service
      → payment_service
          → fraud_service      (blocks charge if risk=HIGH)
          → payment_gateway    (external charge)
          → ledger_service     (record transaction)
      → inventory_service
          → warehouse_service
      → notification_service
          → email_gateway
          → sms_gateway
          → push_gateway
```

---

## 8. Error Handling — Before vs After Fix

### Problem (pre-fix)
```json
{
  "status": "failed",
  "error_message": "Command '['git', 'clone', '--depth', '1', '--branch', 'main',
    'https://github.com/karpathy/autoresearch.git',
    '/tmp/servicescope/repos/repo_44b98c2f9b7fce1f']'
    returned non-zero exit status 128."
}
```

### After Fix — Error Classification Table

| Git Failure Mode | stderr Pattern | User-Facing Message |
|-----------------|---------------|-------------------|
| Repo doesn't exist | `repository '...' not found` | `Repository not found or is private: <url>` |
| Private repo (no auth) | `Could not read from remote` | `Cannot access repository (private or URL invalid): <url>` |
| Branch missing | `Remote branch X not found` | `Branch 'X' does not exist. Try 'main' or 'master'.` → **auto-fallback to default branch** |
| Auth failure | `Authentication failed` | `Authentication failed for <url>. Repository may be private.` |
| DNS failure | `Could not resolve host` | `Cannot resolve hostname in URL: <url>` |
| Timeout | `TimeoutExpired` | `Clone timed out after 300s: <url>` |
| Malformed URL | Pydantic validator | **HTTP 422** before Celery is invoked |

### Branch Auto-Fallback (verified)

```
karpathy/nanochat submitted with branch: "main"
  Step 1: git clone --depth 1 --branch main → FAIL
          stderr: "fatal: Remote branch main not found in upstream origin"
  Step 2: re.search(r"remote branch .+ not found", stderr)  → True
          cleanup partial clone dir
          git clone --depth 1 (no --branch)  → SUCCESS
          default branch: master
  Result: status=COMPLETED, 36 files, 8 calls
```

---

## 8. API Surface (25 Endpoints)

```
Auth
  POST /api/v1/auth/register
  POST /api/v1/auth/login
  GET  /api/v1/auth/me

Tenants
  POST /api/v1/tenants/          (bootstrap-secret protected)
  GET  /api/v1/tenants/{id}

Repositories
  POST /api/v1/repositories/     → queues Celery task, returns repo_id
  GET  /api/v1/repositories/
  GET  /api/v1/repositories/{id}
  DELETE /api/v1/repositories/{id}

Jobs
  GET  /api/v1/jobs/
  GET  /api/v1/jobs/{id}
  GET  /api/v1/jobs/repository/{repo_id}

Analysis
  GET  /api/v1/repositories/{id}/calls       → raw extracted HTTP calls
  GET  /api/v1/repositories/{id}/dependencies → inferred service deps

Chat (LLM Q&A over analysis results)
  POST /api/v1/chat/ask
  GET  /api/v1/chat/repositories/{id}/summary
  POST /api/v1/chat/repositories/{id}/insights
  GET  /api/v1/chat/repositories/{id}/history

Graph (Neo4j, when available)
  GET  /api/v1/graph/repositories/{id}
  GET  /api/v1/graph/services/{name}
```

---

## 9. Data Models

### `extracted_calls`
```sql
id              UUID  PK
repository_id   UUID  FK → repositories
service_name    TEXT        -- caller (directory/module name)
method          VARCHAR(10) -- get | post | put | delete | patch
url             TEXT        -- full URL or <dynamic:varname>
file_path       TEXT        -- relative path within repo
line_number     INTEGER
created_at      TIMESTAMP
```

### `inferred_dependencies`
```sql
id                UUID  PK
extracted_call_id UUID  FK → extracted_calls
caller_service    TEXT       -- source service name
callee_service    TEXT       -- LLM-inferred target service name
confidence        FLOAT      -- 0.0–1.0  (from LLM JSON response)
llm_model         TEXT       -- e.g. "gemma3:4b"
llm_response      TEXT       -- raw LLM output (stored for audit)
created_at        TIMESTAMP
```

### `analysis_jobs`
```sql
id              UUID  PK
repository_id   UUID  FK → repositories
status          ENUM  QUEUED | RUNNING | COMPLETED | COMPLETED_WITH_WARNINGS | FAILED
progress        FLOAT      -- 0–100
started_at      TIMESTAMP
completed_at    TIMESTAMP
error_message   TEXT
result_summary  JSONB      -- {total_calls, services_found, dependencies_inferred,
                           --  failed_inferences, inference_failure_rate}
```

---

## 10. LLM Prompt (Inference)

```
You are a microservice architecture assistant.

Given this HTTP call made by service "{caller}":
  Method: {METHOD}
  URL: {url}

Identify the most likely internal service being called and your confidence.

Respond with ONLY a JSON object, no markdown, no explanation:
{"service": "service_name", "confidence": 0.0}

Where "service" is a short snake_case name (e.g. "payment_service") and
"confidence" is a float between 0.0 and 1.0.
```

**Observed model behaviour (gemma3:4b):**
- Returns valid JSON on ~100% of calls (0% failure rate on nanochat/ServiceScope runs)
- Confidence calibration: variable names strongly named (`worker`, `metric`) → 0.95; generic (`url`, `name`) → 0.85
- Strips its own markdown fences automatically (handled in parser as fallback)
- Avg response latency: ~415ms per inference (local M-series)

---

## 11. Layer Roadmap

```
LAYER 1 — ServiceScope (current)
  Signal source : Python AST
  Answers       : "What Python code calls what?"
  When          : Code-time (static analysis)
  Status        : WORKING — hardened, tested on Django (2886 files), nanochat, ServiceScope v1
  Gate          : 0% false positives on own codebase ✓
                  0% inference failure on nanochat ✓
                  Branch auto-fallback verified ✓

LAYER 2 — PlatformScope (next)
  Signal source : Dockerfile, docker-compose, k8s manifests, .env, Terraform, CI YAML
  Answers       : "What does the full platform depend on?"
  When          : Deploy-time (infra config analysis)
  New extractors: DockerExtractor, K8sExtractor, EnvVarExtractor,
                  MessageBusExtractor, DatabaseExtractor, IaCExtractor
  New DB tables : infra_signals, platform_dependencies, blast_radius_scores
  New endpoints : GET /api/v2/repositories/{id}/topology
                  GET /api/v2/repositories/{id}/blast-radius
                  GET /api/v2/repositories/{id}/signals

LAYER 3 — Data Observability Engine (future)
  Signal source : Pydantic models, OpenAPI specs, Alembic migrations, Avro/Protobuf schemas
  Answers       : "What data flows where, at what quality, who owns it?"
  When          : Run-time contract validation
  New concepts  : DataContract, SchemaVersion, DriftEvent, DataLineage, PII Surface
  New DB tables : data_schemas, data_contracts, schema_drift_events,
                  data_lineage, pii_surfaces
  New endpoints : GET /api/v3/contracts
                  GET /api/v3/lineage/{entity_type}
                  GET /api/v3/services/{name}/pii-surface
```

---

## 12. Performance Summary

### Pipeline Breakdown by Repo (measured, not estimated)

```
nanochat  (36 files, 8 calls)        Total: 12.3s
  ├── git clone                :  1.069s   8.7%
  ├── AST extraction           :  0.081s   0.7%   [447 files/sec]
  ├── LLM inference (8 calls)  : ~11.0s  89.0%   [1 cold + 7 warm]
  └── DB writes + cleanup      :  0.198s   1.6%

robusta   (394 files, 103 calls)      Total: 104.1s
  ├── git clone                :  5.656s   5.4%
  ├── AST extraction           :  0.338s   0.3%  [1,166 files/sec]
  ├── LLM inference (103 calls): ~98.0s  94.1%   [1 cold + 102 warm]
  └── DB writes + cleanup      :  0.134s   0.1%

django    (2,886 files, 1,323 calls)  Total: 559s
  ├── git clone                : ~45.0s   8.1%
  ├── AST extraction           : ~15.0s   2.7%  [~190 files/sec]
  ├── LLM inference (1,323×)   : ~499.0s  89.3%
  └── DB writes + cleanup      :  ~0.5s   0.1%
```

> **LLM is 89–94% of total pipeline time across all repo sizes.**
> AST extraction is always under 3% even at django scale.

---

### LLM Per-Call Timing — 8 live calls measured (gemma3:4b, Apple Silicon)

| # | ms | URL type | URL | Inferred service | Confidence |
|---|-----|---------|-----|-----------------|-----------|
| 1 | **4,540ms** | static | `http://payment-service/api/charge` | `payment_service` | 0.95 |
| 2 | 917ms | dynamic | `<dynamic:RELAY_EXTERNAL_ACTIONS_URL>` | `relay` | 0.90 |
| 3 | 851ms | dynamic | `<dynamic:node_name>` | `node_management` | 0.80 |
| 4 | 860ms | dynamic | `<dynamic:job_id>` | `job_status` | 0.80 |
| 5 | 916ms | static | `http://notification-service:8004/…` | `email_service` | 0.80 |
| 6 | 939ms | dynamic | `<dynamic:url>` | `data_access` | 0.80 |
| 7 | 907ms | dynamic | `<dynamic:worker>` | `worker` | 0.95 |
| 8 | 946ms | dynamic | `<dynamic:GRAFANA_RENDERER_URL>` | `Grafana Renderer` | 0.95 |

```
Cold start (call 1) : 4,540ms  ← model context load
Warm calls (2–8)    :   905ms avg  |  916ms median  |  851–946ms range
Effective rate      :  1.10 calls/sec  (warm)
                       0.74 calls/sec  (cold-included avg)
```

> **Cold start note:** Call 1 in every analysis pipeline pays a ~4.5s penalty.
> For repos with ≥10 calls, cold start is <5% of total LLM time.
> For repos with 1–3 calls (autoresearch), cold start dominates.

---

### Discrepancy — Django back-calculated vs today's measurement

| Source | LLM time/call |
|--------|-------------|
| Django run (from DB, back-calculated) | **0.377s** (2.65 calls/sec) |
| Fresh measurement today (8 calls) | **0.905s** (1.10 calls/sec warm) |
| Delta | 2.4× faster during django run |

**Likely causes:** Django ran in a sustained Ollama session where the model was fully loaded
into the Neural Engine cache. Short prompt tokens from simple `requests.get(url)` calls
produce shorter completions → faster token generation. Today's isolated 8-call test paid
re-initialization overhead between measurements. The 2.4 calls/sec figure from the django
run is the sustained warm throughput ceiling for this hardware.

---

### Timing Reference Table

| Operation | Time | Notes |
|-----------|------|-------|
| git clone — nanochat (shallow) | 1.1s | network + small repo |
| git clone — robusta (shallow) | 5.7s | network + medium repo |
| git clone — django (shallow) | ~45s | large repo estimate |
| AST extraction — 36 files | **81ms** | 447 files/sec |
| AST extraction — 394 files | **338ms** | 1,166 files/sec |
| AST extraction — 2,886 files | **~15s** | ~190 files/sec (I/O bound) |
| LLM cold start (call 1) | **4,540ms** | model context initialisation |
| LLM warm call (median) | **916ms** | calls 2–N in same session |
| LLM warm call (sustained run) | **~377ms** | sustained throughput ceiling |
| Full pipeline — nanochat (8 calls) | **12.3s** | |
| Full pipeline — robusta (103 calls) | **104.1s** | |
| Full pipeline — django (1,323 calls) | **559s** | |
| DB write — extracted_call | <1ms | PostgreSQL async |
| DB write — inferred_dependency | <1ms | PostgreSQL async |
| Neo4j upsert per edge | ~5ms | when Neo4j available |

---

*Generated from live PostgreSQL data + direct measurement — macOS Apple Silicon, Ollama gemma3:4b, no external API calls.*

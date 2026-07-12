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
│  │ 30%   AST walk → extract HTTP/gRPC calls                  │   │
│  │         (Python AST + Polyglot Tree-sitter)              │   │
│  │ 60%   Dependency inference:                              │   │
│  │         1. Try Cross-Layer Linker (Deterministic           │   │
│  │            manifest env/URL mapping → 1.0 confidence)     │   │
│  │         2. Fall back to local Ollama LLM if unresolved   │   │
│  │ 90%   Neo4j upsert (tenant+repo scoped)                  │   │
│  │100%   cleanup clone dir + write result_summary           │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────┬──────────────────────────┬──────────────────────────────┘
         │                          │
         ▼                          ▼
┌─────────────────┐      ┌──────────────────────┐
│  PostgreSQL      │      │  Ollama  (port 11434) │
│  :5432           │      │  model: gemma3:4b     │
│  tenants         │      │  local inference only  │
│  users           │      └──────────────────────┘
│  repositories    │
│  analysis_jobs   │      ┌──────────────────────┐
│  extracted_calls │      │  Neo4j  (port 7687)   │
│  inferred_deps   │      │  graph: Service nodes │
└─────────────────┘      │  + CALLS edges        │
                          │  (optional, graceful  │
                          │   fallback if absent) │
                          └──────────────────────┘
```

---

## 2. AST Extraction Engine

### Three Python Detection Patterns

```python
# Pattern 1 — requests / httpx direct calls
requests.get("http://payment-service/charge")
httpx.post("http://user-service/api/users")

# Pattern 2 — method calls on client objects
client.get("http://internal-service/health")
session.post(url, json=payload)

# Pattern 3 — any .get/.post/.put/.delete where URL starts with "http"
# Fixed: url.startswith("http") only to prevent dict lookup false positives
```

### Tree-Sitter Polyglot AST Extractors
ServiceScope v2 scans Java, JavaScript/TypeScript, and C# source files using Tree-sitter parsers:

* **Java (`.java`)**: 
  - RestTemplate methods: `getForObject`, `getForEntity`, `postForObject`, `postForEntity`, and `exchange`.
  - WebClient/HttpClient `uri(...)` arguments.
  - gRPC stub initialization: `newBlockingStub`, `newStub`, and `newFutureStub`.
* **JavaScript/TypeScript (`.js`, `.ts`)**:
  - `fetch(...)` calls.
  - Axios methods: `axios.get`, `axios.post`, `axios.put`, `axios.delete`, and `axios.patch`.
  - gRPC client instantiations (`new Client(...)`).
* **C# (`.cs`)**:
  - HttpClient calls: `GetAsync`, `PostAsync`, `PutAsync`, `DeleteAsync`, and `SendAsync`.
  - GrpcChannel initializations: `GrpcChannel.ForAddress(...)`.
  - gRPC client creation: `new XYZServiceClient(channel)`.

### Go AST Extractor & Bindings Tracking
In addition to native Go gRPC and HTTP patterns, the Go extractor tracks:
* Go environment mappings: `mustMapEnv(var, envName)` configuration bindings.
* Go gRPC connection mappings: `mustConnGRPC(client, conn, varName)`.

---

## 2b. Kubernetes & Helm Manifest Parser

Scans the repository for deployment configurations:
* **Helm Templates**: Renders templates using values declared in `values.yaml` and chart metadata, evaluating simple control flows (e.g. `{{- if eq .Values.database.type "postgres" }}`).
* **ConfigMaps & Secrets**: Aggregates properties, automatically base64-decoding Kubernetes Secret payloads.
* **Service Environment Variables**: Parses `env` and `envFrom` blocks (including `configMapKeyRef` and `secretKeyRef` resolvers) to compile a complete runtime environment dictionary for each microservice.

---

## 3. Benchmark Results — All Repos Tested

All runs on local Apple Silicon, Ollama `gemma3:4b`, no external API calls.

| Repo | Languages | Files | HTTP/gRPC Calls | GT Deps | Linker-only F1 | Linker + LLM F1 | Duration |
|------|-----------|-------|-----------------|---------|----------------|-----------------|----------|
| `karpathy/nanochat` | Python | 36 | 8 (all dynamic) | 8 | 0.000 | **1.000** | 12.3s |
| `karpathy/autoresearch` | Python | 2 | 1 (dynamic) | 1 | 0.000 | **1.000** | 7.2s |
| `Aravind0403/ServiceScope` v1 | Python | 10 | 5 | 5 | 0.200 | **1.000** | 5.7s |
| `robusta-dev/robusta` | Python | 394 | 103 (all dynamic) | 103 | 0.000 | **0.880** | 104.1s |
| `GoogleCloudPlatform/microservices-demo` | Go, Python | 13 | 7 (all dynamic) | 15 | **0.966** | **1.000** | 3.0s |
| `open-telemetry/opentelemetry-demo` (otel-demo) | Py, Go, TS, C# | 39 | 18 (all dynamic) | 17 | **0.970** | **1.000** | 6.0s |
| `django/django` | Python | 2,886 | 1,323 | — | — | — | 559s |

---

## 4. Deep Dive — `open-telemetry/opentelemetry-demo` (Polyglot Linker Verification)

### Repository Profile
```
URL      : https://github.com/open-telemetry/opentelemetry-demo.git
Files    : 39 microservice source files scanned
GT calls : 18 HTTP/gRPC calls
GT deps  : 17 inter-service dependencies
```

### Manifest Linker Performance
* **Linker-Only F1 Score**: **0.970** (Precision: 1.000, Recall: 0.941, 16 True Positive edges resolved, 0 False Positives, 1 Missed).
* **Speed**: **0.455s** end-to-end (entirely deterministic; 0 LLM calls made).
* **Missed Dependency**: `chatbot → agent` (chatbot service makes a dynamic post request to `http://chatbot-agent-addr` which is not registered in the Kubernetes manifest `env:` block).

### LLM Fallback Performance
* Triggering a single LLM query for the missed `chatbot → agent` site achieves a perfect **F1 = 1.000**.
* Total duration with LLM fallback: **6.0s** (compared to ~40s if querying the LLM for all 18 call sites).

---

## 5. Deep Dive — `GoogleCloudPlatform/microservices-demo`

### Repository Profile
```
URL      : https://github.com/GoogleCloudPlatform/microservices-demo.git
Files    : 13 source files scanned (Go, Python)
GT calls : 7 HTTP/gRPC calls
GT deps  : 15 inter-service dependencies
```

### Manifest Linker Performance
* **Linker-Only F1 Score**: **0.966** (Precision: 1.000, Recall: 0.933, 14 True Positive edges resolved, 0 False Positives, 1 Missed).
* **Speed**: **0.102s** end-to-end.
* **Missed Dependency**: `frontend → shoppingassistant` (frontend maps HTTP posts dynamically to a URL not fully declared in environment variable manifests).
* **With LLM Fallback**: **F1 = 1.000** (resolved the final edge in 3.0s total).

---

## 6. Deep Dive — `robusta-dev/robusta` (True Microservice Agent)

### Repository Profile
```
URL      : https://github.com/robusta-dev/robusta
Files    : 394 Python files
Duration : 104.1 seconds end-to-end
```

### Analysis Summary
```
total_calls          : 103  (all 103 are dynamic URLs — zero hardcoded http:// URLs)
services_found       : 2    (src, playbooks — top-level repo directories)
dependencies_inferred: 103
failed_inferences    : 0
inference_failure_rate: 0.0%
```

### LLM Inference Quality Tiers (Ollama Fallback)

* **Tier 1 — Exact (named URL constants, confidence 0.95)**:
  `RELAY_EXTERNAL_ACTIONS_URL` → `relay_service`
  `RUNNER_GET_INFO_URL` → `runner_info_service`
  `GRAFANA_RENDERER_URL` → `grafana_renderer`
* **Tier 2 — Semantic (generic names, confidence 0.85)**:
  `job_id` → `job_status`
  `label_key` → `label_service`
* **Tier 3 — False Positive Guards**:
  Python dict `.get("cpu")` matched as HTTP GET in robusta v1. ServiceScope v2 fixes this by enforcing that all loose method-based extraction matches must check `url.startswith("http")`.

---

## 7. Scale Benchmark — `django/django`

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
```

---

## 8. Error Handling — Before vs After Fix

| Git Failure Mode | stderr Pattern | User-Facing Message |
|-----------------|---------------|-------------------|
| Repo doesn't exist | `repository '...' not found` | `Repository not found or is private: <url>` |
| Private repo (no auth) | `Could not read from remote` | `Cannot access repository (private or URL invalid): <url>` |
| Branch missing | `Remote branch X not found` | `Branch 'X' does not exist. Try 'main' or 'master'.` → **auto-fallback to default branch** |
| Auth failure | `Authentication failed` | `Authentication failed for <url>. Repository may be private.` |
| DNS failure | `Could not resolve host` | `Cannot resolve hostname in URL: <url>` |
| Timeout | `TimeoutExpired` | `Clone timed out after 300s: <url>` |
| Malformed URL | Pydantic validator | **HTTP 422** before Celery is invoked |

---

## 9. API Surface (25 Endpoints)

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

## 10. Data Models

### `extracted_calls`
```sql
id              UUID  PK
repository_id   UUID  FK → repositories
service_name    TEXT        -- caller (directory/module name)
method          VARCHAR(10) -- get | post | put | delete | patch | grpc
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
callee_service    TEXT       -- target service name
confidence        FLOAT      -- 0.0–1.0 (deterministic manifest link gets 1.0)
llm_model         TEXT       -- e.g. "gemma3:4b" or "linker"
llm_response      TEXT       -- raw completion or link trace
created_at        TIMESTAMP
```

---

## 11. LLM Prompt (Inference)

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

---

## 12. Layer Roadmap

```
LAYER 1 — Polyglot AST Call Extraction                 ✅ working
  Signal source : Python AST + Tree-sitter (Go, Java, TS, C#)
  Answers       : "What calls exist in source code?"
  Status        : Hardened, zero-config parsing at ~190 files/second.

LAYER 2 — Cross-Layer Linker                           ✅ working (this branch)
  Signal source : Kubernetes deployment manifests, Helm charts/values, Docker Compose
  Answers       : "What infrastructure configuration variables bind dynamic calls?"
  Benefit       : Turns dynamic variable arguments into 1.0 confidence links in sub-50ms.

LAYER 3 — Local LLM Inference Fallback                 ✅ working
  Signal source : Ollama local LLM + service-aware prompt templates
  Answers       : "Where do remaining unresolved calls go?"
```

---

## 13. Performance Summary

### Pipeline Breakdown by Repo (measured)

```
nanochat  (36 files, 8 calls)        Total: 12.3s
  ├── git clone                :  1.069s   8.7%
  ├── AST extraction           :  0.081s   0.7%
  ├── LLM inference (8 calls)  : ~11.0s  89.0%
  └── DB writes + cleanup      :  0.198s   1.6%

otel-demo (39 files, 18 calls)       Total: 0.455s (Baseline/Linker Only)
  ├── git clone                :  0.312s  68.6%
  ├── AST extraction           :  0.118s  25.9%
  ├── Manifest Linker (18×)    :  0.021s   4.6%
  └── DB writes + cleanup      :  0.004s   0.9%
```

> **Performance Advantage**: When the Cross-Layer Linker resolves dependencies, the pipeline runs **25x faster** by bypassing Ollama inference entirely.

---

*Generated from live PostgreSQL data + direct measurement — macOS Apple Silicon, Ollama gemma3:4b, no external API calls.*

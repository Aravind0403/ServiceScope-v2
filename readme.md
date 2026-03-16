# ServiceScope v2

> **Static dependency mapping for Python microservices — powered by AST parsing and local LLM inference.**

Point it at any Python GitHub repo. It clones it, walks every `.py` file with the AST, finds every outbound HTTP call, asks a local LLM what service is being called, and stores the resulting dependency graph in PostgreSQL and Neo4j.

No agents running in production. No service mesh required. No code changes needed.

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-green.svg)](https://fastapi.tiangolo.com/)
[![Celery](https://img.shields.io/badge/Celery-5.3-orange.svg)](https://docs.celeryq.dev/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What it does

```
GitHub repo URL
      ↓
  git clone --depth 1
      ↓
  AST walk every .py file
  → find requests.get/post, httpx.post, session.get …
  → capture URL (static) or variable name (dynamic)
      ↓
  LLM inference  (local Ollama — gemma3:4b, no API calls)
  → "what service is this HTTP call talking to?"
  → confidence score 0.0–1.0
      ↓
  PostgreSQL  ← structured records (calls, dependencies, jobs)
  Neo4j       ← graph  (Service nodes + CALLS edges)
      ↓
  Chat interface
  → "which service has the most dependencies?"
  → "I'm changing user_service — what breaks?"
  → "explain the critical path"
```

---

## Benchmarks

All runs on local Apple Silicon, Ollama gemma3:4b, no external API calls.

| Repo | Files | HTTP calls | Dependencies | Duration | Failure rate |
|------|-------|-----------|--------------|----------|-------------|
| `karpathy/nanochat` | 36 | 8 (all dynamic) | 8 | **12.3s** | **0%** |
| `karpathy/autoresearch` | 2 | 1 (dynamic) | 1 | 7.2s | 0% |
| `robusta-dev/robusta` | 394 | 103 (all dynamic) | 103 | **104.1s** | **0%** |
| `Aravind0403/ServiceScope` v1 | 10 | 5 | 5 | 5.7s | 0% |
| `django/django` | 2,886 | 1,323 | 1,323 | 559s | — |
| `tiangolo/full-stack-fastapi-template` | 45 | 0 | 0 | 1.5s | — |
| Synthetic 6-service demo (local) | 6 | 31 (11 dynamic) | 28 | **6ms** extract only | — |

**AST extraction rate:** ~190 files/second (pure parsing, no LLM)
**LLM inference rate:** ~2.4 calls/second (gemma3:4b local)
**Typical repo (50–200 files):** 15–60 seconds end-to-end

---

## LLM inference quality

The LLM receives the HTTP method, the URL or its variable name if dynamic, and the calling file path. Quality splits into three tiers:

**Tier 1 — Named URL constants → 0.95 confidence**
```python
requests.get(RELAY_EXTERNAL_ACTIONS_URL)  →  relay_service       ✅
requests.post(GRAFANA_RENDERER_URL)        →  grafana_renderer    ✅
requests.get(RUNNER_GET_INFO_URL)          →  runner_info_service ✅
```

**Tier 2 — Semantic variable names → 0.85 confidence**
```python
requests.get(node_name)   →  node_service   ✅ reasonable
requests.get(job_id)      →  job_status     ✅ reasonable
requests.get(label_key)   →  label_service  ⚠️ could be a k8s label, not a service
```

**Tier 3 — False positive (dict.get() caught as HTTP)**
```python
# Pattern 2 is broad — catches any .get() call on any object
container.resources.requests.get("cpu")
# stored as: [GET] cpu → cpu_service  ← incorrect (dict lookup, not HTTP)
```

Known issue — fix is `url.startswith("http")` guard on Pattern 2 (Pattern 3 already has this).

---

## Stack

| Component | Technology |
|-----------|-----------|
| API server | FastAPI 0.104, uvicorn, Pydantic v2 |
| Auth | JWT (python-jose), bcrypt (passlib) |
| Task queue | Celery 5.3 + Redis 7 |
| LLM | Ollama local — gemma3:4b |
| Primary DB | PostgreSQL 15, SQLAlchemy 2.0 async, Alembic |
| Graph DB | Neo4j 5 community (optional — graceful fallback if absent) |

---

## Quick start

### Prerequisites

```
Python 3.12+
Docker + Docker Compose
Ollama  →  https://ollama.com
Git
```

### 1. Infrastructure

```bash
docker-compose up -d        # PostgreSQL :5432  Redis :6379  Neo4j :7687
alembic upgrade head        # apply migrations
```

### 2. LLM

```bash
ollama pull gemma3:4b       # ~1.6 GB, one-time download
```

### 3. App

```bash
pip install -r requirements.txt

# Terminal 1 — API
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Worker
celery -A app.celery_app worker --loglevel=info --concurrency=2
```

Expected output:
```
🚀 Starting ServiceScope API...
⚠️  Neo4j unavailable at startup (graph features disabled)   ← expected if not running
✅ Database connections initialized
INFO: Uvicorn running on http://0.0.0.0:8000
```

### 4. Bootstrap (one time)

```bash
# Create tenant
curl -X POST http://localhost:8000/api/v1/tenants/ \
  -H "Content-Type: application/json" \
  -H "X-Bootstrap-Secret: dev-bootstrap-secret-2024" \
  -d '{"name":"my-org"}'

# Register user
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"yourpass","full_name":"You","tenant_id":"<TENANT_ID>"}'

# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"yourpass"}'
# → save access_token
```

### 5. Analyse a repo

```bash
TOKEN="<your_jwt>"
TENANT_ID="<your_tenant_id>"

# Submit
curl -X POST http://localhost:8000/api/v1/repositories/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"url\": \"https://github.com/robusta-dev/robusta\",
    \"name\": \"robusta-demo\",
    \"branch\": \"master\",
    \"tenant_id\": \"$TENANT_ID\"
  }"

# Poll progress  (0 → 10 → 30 → 60 → 90 → 100)
curl http://localhost:8000/api/v1/jobs/repository/<REPO_ID> \
  -H "Authorization: Bearer $TOKEN"

# Chat
curl -X POST http://localhost:8000/api/v1/chat/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"repository_id\":\"<REPO_ID>\",\"question\":\"Which service has the most dependencies?\"}"
```

Swagger UI: **http://localhost:8000/docs**

---

## Architecture

```
Client
  │  REST
  ▼
FastAPI  :8000
  • JWT auth + multi-tenant isolation
  • Pydantic URL validation — HTTP 422 before queuing for bad URLs
  │
  │  .delay()
  ▼
Celery Worker  ←── Redis :6379
  │
  ├── 0%    receive repo_id
  ├── 10%   git clone --depth 1
  │           branch not found → auto-fallback to repo default
  ├── 30%   AST walk → extract HTTP calls
  │           Pattern 1: requests.get / post / put / delete / patch
  │           Pattern 2: session.get, client.post (any object)
  │           Pattern 3: httpx.get / post / put / delete / patch
  │           Dynamic: variable name stored as <dynamic:varname>
  ├── 60%   LLM inference  (Ollama local, gemma3:4b)
  │           → {"service": "...", "confidence": 0.85}
  ├── 90%   Neo4j upsert  (tenant + repo scoped)
  └── 100%  cleanup + write result_summary
        │
        ├── PostgreSQL :5432
        │     tenants · users · repositories
        │     analysis_jobs · extracted_calls · inferred_dependencies
        │
        └── Neo4j :7687  (optional)
              (:Service)-[:CALLS {method, url, confidence}]->(:Service)
```

---

## API reference

```
Auth
  POST  /api/v1/auth/register
  POST  /api/v1/auth/login
  GET   /api/v1/auth/me

Tenants
  POST  /api/v1/tenants/            X-Bootstrap-Secret header required
  GET   /api/v1/tenants/{id}

Repositories
  POST   /api/v1/repositories/      queues Celery task, returns immediately
  GET    /api/v1/repositories/
  GET    /api/v1/repositories/{id}
  DELETE /api/v1/repositories/{id}

Jobs
  GET  /api/v1/jobs/
  GET  /api/v1/jobs/{id}
  GET  /api/v1/jobs/repository/{repo_id}

Analysis results
  GET  /api/v1/repositories/{id}/calls          raw extracted HTTP calls
  GET  /api/v1/repositories/{id}/dependencies   inferred service dependencies

Chat
  POST /api/v1/chat/ask
  GET  /api/v1/chat/repositories/{id}/summary
  POST /api/v1/chat/repositories/{id}/insights
  GET  /api/v1/chat/repositories/{id}/history

Graph  (requires Neo4j)
  GET  /api/v1/graph/repositories/{id}
  GET  /api/v1/graph/services/{name}
```

---

## Git error handling

Raw exit-128 errors are translated into human-readable messages.

| Condition | Message |
|-----------|---------|
| Repo doesn't exist | `Repository not found or is private: <url>` |
| Private / no credentials | `Cannot access repository (private or URL invalid): <url>` |
| Wrong branch specified | Silent auto-fallback to repo default branch |
| Auth failure | `Authentication failed for <url>` |
| DNS failure | `Cannot resolve hostname in URL: <url>` |
| Clone timeout (>300s) | `Clone timed out after 300s: <url>` |
| Malformed URL | HTTP 422 — rejected before Celery is invoked |

---

## Project structure

```
app/
├── main.py                     FastAPI app + lifespan
├── config.py                   Settings (pydantic-settings + .env)
├── celery_app.py               Celery configuration
├── models/
│   ├── tenant.py               Tenant, User
│   ├── repository.py           Repository
│   ├── job.py                  AnalysisJob
│   ├── api_call.py             ExtractedCall
│   └── dependency.py           InferredDependency
├── schemas/                    Pydantic request/response models
├── routers/                    auth, repositories, jobs, chat, graph, tenants
├── tasks/
│   └── analyzer.py             Main Celery pipeline (clone → extract → infer → store)
├── extraction/
│   └── extract_http_calls.py   AST walker — 3 detection patterns
└── db/
    ├── session.py              PostgreSQL async session
    └── Neo4j_session.py        Neo4j driver wrapper

migrations/                     Alembic versions
scripts/                        Utility scripts
tests/                          Test suite (pytest)
docker-compose.yml              PostgreSQL + Redis + Neo4j
TECHNICAL_METRICS.md            Full benchmark data from real runs
```

---

## Configuration

Copy `env.local` → `.env`:

```bash
# PostgreSQL
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=servicescope
DATABASE_USER=servicescope
DATABASE_PASSWORD=changeme

# Neo4j (optional)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=changeme

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:4b
OLLAMA_TIMEOUT=60

# Auth
SECRET_KEY=change-this-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Bootstrap
BOOTSTRAP_SECRET=dev-bootstrap-secret-2024
```

---

## Testing

```bash
pytest tests/ -v
pytest tests/ --cov=app --cov-report=term-missing
```

---

## Roadmap

ServiceScope is Layer 1 of a three-layer static analysis platform:

```
Layer 1 — ServiceScope  (this repo)                    ✅ working
  Signal : Python AST
  Answers: "What Python code calls what?"
  Proven : 0% inference failure on nanochat, robusta, ServiceScope v1
           Branch auto-fallback verified
           Tested to 2,886 files (django)

Layer 2 — PlatformScope                                 next
  Signal : Dockerfile, docker-compose, k8s manifests,
           .env files, Terraform, CI YAML
  Answers: "What does the full platform depend on?"
  Adds   : DockerExtractor, K8sExtractor, EnvVarExtractor,
           MessageBusExtractor (Kafka/RabbitMQ),
           blast-radius scoring, GET /topology
  Why    : .env resolution turns dynamic URL variable names into
           real hostnames — inference quality 0.85 → 1.0

Layer 3 — Data Observability Engine                     future
  Signal : Pydantic models, OpenAPI specs, Alembic migrations,
           Avro/Protobuf schema files
  Answers: "What data flows where, at what quality, who owns it?"
  Adds   : DataContract, SchemaVersion, DriftEvent, DataLineage,
           PII surface map, contract validation pipeline
```

---

## Author

**Aravind Sundaresan**
- GitHub: [@Aravind0403](https://github.com/Aravind0403)
- LinkedIn: [Aravind Sundaresan](https://linkedin.com/in/aravind-sundaresan)

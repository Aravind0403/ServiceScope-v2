# ServiceScope v2

> **Know your blast radius before you deploy — not after.**

Built after 4 years of shipping distributed infrastructure at Microsoft across 17,000+ microservices.  
The hardest part wasn't the code. It was answering: *"If I change this service, what breaks?"*  
ServiceScope is the tool I wished existed.

---

## At a Glance

| | |
|---|---|
| **Supported Languages** | Python · Go · Java · JavaScript/TypeScript · C# (.NET) |
| **Manifest Parsers** | Kubernetes Manifests · Helm Charts (`values.yaml` + templates) · Docker Compose |
| **AST Extraction Speed**| ~190 files/second (Tree-sitter & Python AST) |
| **Manifest Linking Speed** | Sub-50ms (Deterministic resolution with 1.0 confidence) |
| **Inference Accuracy** | **F1 = 1.000** on `microservices-demo` and `opentelemetry-demo` (Linker + LLM fallback) |
| **LLM Inference Rate** | ~2.4 calls/second (gemma3:4b, local) |
| **External API Calls** | Zero — fully local Ollama + deterministic linker |

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-green.svg)](https://fastapi.tiangolo.com/)
[![Celery](https://img.shields.io/badge/Celery-5.3-orange.svg)](https://docs.celeryq.dev/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## The Problem

In large microservice ecosystems, dependencies are **implicit, undocumented, and tribal**.

Dynamic HTTP calls, shared configs, and environment-variable-resolved hostnames mean no static tool can tell you what's actually connected. Engineers cannot answer the fundamental question before a deploy:

> *"If I change this component, what breaks?"*

ServiceScope solves this by scanning codebases to extract call sites, parsing Kubernetes/Helm deployment files to resolve dynamic configuration bindings, and falling back to a local LLM only when static relationships are opaque.

---

## What it does

```
                     GitHub Repo URL
                            ↓
                       git clone
                            ↓
      Polyglot AST Call Extractor (Tree-sitter)
      → Scan: Python, Go, Java, JS/TS, C# (.NET)
      → Find: HTTP calls (requests, axios, fetch, HttpClient) 
              & gRPC stubs/channels
      → Output: Static URLs or dynamic configuration bindings (<dynamic:VAR_NAME>)
                            ↓
               Cross-Layer Manifest Linker
      → Parse: K8s templates, values.yaml, envVars, Docker Compose
      → Map: Resolve <dynamic:VAR_NAME> using container env settings
      → Confidence: 1.0 (Deterministic resolution in <50ms)
                            ↓
            Ollama Local LLM Fallback (gemma3:4b)
      → Prompt: "Where does this unresolved call go?"
      → Context: Service-aware prompt using discovered repository services
                            ↓
                PostgreSQL & Neo4j Storage
      → Graph: (:Service)-[:CALLS {method, url, confidence}]->(:Service)
                            ↓
               Blast Radius & Chat Interface
      → Query: "I'm changing payment_service — what breaks?"
```

---

## Benchmarks

All runs on local Apple Silicon, Ollama `gemma3:4b`, no external API calls.

| Repo | Languages | Files | HTTP/gRPC Calls | GT Deps | Linker-only F1 | Linker + LLM F1 | E2E Duration |
|------|-----------|-------|-----------------|---------|----------------|-----------------|--------------|
| `karpathy/nanochat` | Python | 36 | 8 (all dynamic) | 8 | 0.000 | **1.000** | 12.3s |
| `robusta-dev/robusta` | Python | 394 | 103 (all dynamic) | 103 | 0.000 | **0.880** | 104.1s |
| `Aravind0403/ServiceScope` v1 | Python | 10 | 5 | 5 | 0.200 | **1.000** | 5.7s |
| `GoogleCloudPlatform/microservices-demo` | Go, Python | 13 | 7 (all dynamic) | 15 | **0.966** | **1.000** (1 LLM call) | 0.1s (baseline) / 3.0s |
| `open-telemetry/opentelemetry-demo` (otel-demo) | Py, Go, TS, C# | 39 | 18 (all dynamic) | 17 | **0.970** | **1.000** (1 LLM call) | 0.4s (baseline) / 6.0s |
| `django/django` | Python | 2,886 | 1,323 | — | — | — | 559s |

* **Deterministic Speed**: The Cross-Layer Manifest Linker resolves >95% of dynamic dependencies in under 50ms without hitting the LLM.
* **LLM Fallback**: Only unresolved call sites (e.g. dynamic endpoints like `chatbot -> agent` not declared in manifest environment mappings) trigger an LLM inference call, minimizing CPU/GPU load.

---

## Deep-Dive: Cross-Layer Linking & Polyglot Parsing

ServiceScope v2 introduces **Layer 2 (Cross-Layer Manifest Linking)**, bridging the gap between application-level code (AST) and platform-level infrastructure (Kubernetes/Helm).

### 1. Polyglot AST Call Extraction
We support Tree-sitter parsers across multiple languages:
* **Java**: Detects Spring Boot `RestTemplate` (e.g., `getForObject`), `WebClient` (`uri()`), and gRPC blocking stubs.
* **JavaScript/TypeScript**: Parses `fetch`, `axios` method calls (`axios.post`), and Node.js gRPC `new Client()` initializations.
* **C# (.NET)**: Tracks `HttpClient` (`GetAsync`, `PostAsync`) and `.NET` `GrpcChannel.ForAddress` configurations.
* **Go**: Scans Go files using custom Go AST patterns and tracks bindings mapped via helper frameworks (e.g., `mustMapEnv` and `mustConnGRPC`).

### 2. Kubernetes & Helm Manifest Parser
ServiceScope crawls the repository to find deployment manifests, `values.yaml` files, and Helm templates.
* Evaluates simple Helm conditions (e.g., `{{- if eq .Values.database.type "postgres" }}`).
* Extracts container-level `env` variables, resolving dependencies mapped via `configMapKeyRef` and `secretKeyRef` fields.
* Base64 decodes Secret blocks automatically to resolve credentials and configuration values.

### 3. Linker Resolution Example
If the C# AST parser extracts a call:
```csharp
var dbUrl = Environment.GetEnvironmentVariable("DB_CONNECTION_URL");
await client.GetAsync(dbUrl); // Stored as <dynamic:DB_CONNECTION_URL>
```
The **Cross-Layer Linker** checks the Kubernetes deployment manifest environment for the caller service:
```yaml
spec:
  containers:
  - name: cartservice
    env:
    - name: DB_CONNECTION_URL
      value: "http://redis-cart:6379"
```
It immediately resolves `<dynamic:DB_CONNECTION_URL>` to `redis-cart` and returns a **1.0 confidence score** without running LLM inference.

---

## Stack

| Component | Technology |
|-----------|-----------|
| **API server** | FastAPI 0.104, uvicorn, Pydantic v2 |
| **Auth** | JWT (python-jose), bcrypt (passlib) |
| **Task queue** | Celery 5.3 + Redis 7 |
| **AST Parser** | Tree-sitter + Python `ast` module |
| **LLM** | Ollama local — `gemma3:4b` |
| **Primary DB** | PostgreSQL 15, SQLAlchemy 2.0 async, Alembic |
| **Graph DB** | Neo4j 5 community (optional — graceful fallback) |

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

### 4. Run Benchmark Harness
You can run the evaluation harness locally to verify extraction and inference metrics on our benchmark repositories without starting the API or database:

```bash
# Evaluate otel-demo using the manifest linker baseline
python benchmark/harness.py \
    --repo benchmark/repos/otel-demo \
    --ground-truth benchmark/ground_truth/otel-demo.json \
    --baseline

# Evaluate microservices-demo using the manifest linker baseline
python benchmark/harness.py \
    --repo benchmark/repos/microservices-demo \
    --ground-truth benchmark/ground_truth/microservices-demo.json \
    --baseline
```

---

## Architecture

```
Client
  │  REST
  ▼
FastAPI  :8000
  • JWT auth + multi-tenant isolation
  • Pydantic URL validation
  │
  │  .delay()
  ▼
Celery Worker  ←── Redis :6379
  │
  ├── 0%    receive repo_id
  ├── 10%   git clone --depth 1
  ├── 30%   AST walk → extract HTTP/gRPC calls (Python AST + Polyglot Tree-sitter)
  ├── 60%   Dependency inference:
  │           1. Try Cross-Layer Linker (deterministic K8s/Helm mapping → 1.0 confidence)
  │           2. Fall back to Ollama local LLM only for unresolved call sites
  ├── 90%   Neo4j upsert (tenant + repo scoped)
  └── 100%  cleanup + write result_summary
```

---

## Roadmap

ServiceScope is now a fully realized pre-deployment analysis engine:

```
Layer 1 — AST Call Extraction                          ✅ working
  Signal : Python AST + Polyglot Tree-sitter (Go, Java, TS, C#)
  Answers: "What source code call patterns exist?"

Layer 2 — Cross-Layer Linker                           ✅ working (this branch)
  Signal : Kubernetes manifests, Docker Compose, Helm values, envVars
  Answers: "What target services are bound to runtime environment variables?"
  Benefit: Turns dynamic variables into 1.0 confidence linkages in <50ms.

Layer 3 — LLM Fallback & Chat Interface                 ✅ working
  Signal : Ollama local LLM + service-aware prompt template
  Answers: "For unresolved variables, what service does the LLM predict?"
```

---

## Author

**Aravind Sundaresan** — Infrastructure & Distributed Systems Engineer  
Microsoft (distributed validation platform, 17K+ microservices) · Ex-Amazon (Alexa device infrastructure)

- 🌐 [aravindsundaresan.netlify.app](https://aravindsundaresan.netlify.app)
- 💼 [LinkedIn](https://linkedin.com/in/aravind-sundaresan)
- ✍️ [Substack](https://aravindsundaresan.substack.com)

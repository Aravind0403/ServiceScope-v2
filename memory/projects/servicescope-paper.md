# ServiceScope — FTC 2026 Research Paper

**Submission:** FTC 2026 Late Breaking Round  
**Deadline:** 1 July 2026 (notification 15 July, camera-ready 25 July)  
**Venue:** Berlin, Germany, 15–16 October 2026  
**Format:** LaTeX, Springer LNCS/LNNS, double-blind, max 18 pages + 7 refs  
**Publication:** Springer Lecture Notes in Networks and Systems  
**Repo:** https://github.com/Aravind0403/ServiceScope-v2

---

## Thesis

> *We present the first static analysis pipeline combining AST-based HTTP call
> extraction with local LLM inference for dynamic URL resolution, producing
> pre-deployment inter-service dependency graphs and blast radius predictions
> across Python and Go microservice codebases — without runtime instrumentation,
> agents, or external API calls. We show that LLM inference recovers a
> statistically significant fraction of dependencies invisible to prior static
> analysis approaches due to dynamic URL patterns.*

**Key claim:** LLM resolves what pure AST can't (dynamic variable names).
Baseline comparison: static-only (URL string extraction, no LLM).
Closest prior work: Microvision (Cerny et al., arXiv 2207.02974) — does AST
reconstruction but can't handle dynamic URLs; no LLM; no blast radius.

---

## Novelty vs Existing Tools

| Tool | Approach | Gap |
|------|----------|-----|
| Datadog/Elastic/Instana | Runtime agents | Needs deployed infra, post-deploy only |
| Backstage | Manual YAML catalog | Human-maintained, drifts |
| CodeScene | Git history (change coupling) | Needs commit history, not code |
| Sourcegraph | Symbol graph, code navigation | Not service dependency mapping |
| Microvision | AST, REST templates | Static URLs only, no LLM, no blast radius |
| **ServiceScope** | AST + local LLM + graph | Zero instrumentation, pre-deploy, dynamic URL resolution |

---

## Architecture (Current State)

```
Repo URL
  ↓ git clone --depth 1
Language Detector → Python extractor (done) / Go extractor (TODO)
  ↓ Common HTTP call representation: {method, url_or_varname, caller, file, line}
LLM Inference (local Ollama — no external API)
  → {"service": "payment_service", "confidence": 0.95}
PostgreSQL (structured records) + Neo4j (graph, optional)
  ↓
Blast Radius API: GET /blast-radius?service=X
  → direct deps + transitive closure + confidence-weighted set
```

**Stack:** FastAPI, Celery, Redis, PostgreSQL, SQLAlchemy, Alembic, Neo4j (optional)

---

## Key Files in Repo

| File | What it does |
|------|-------------|
| `app/extraction/extract_http_calls.py` | Python AST extractor (8 patterns) |
| `app/tasks/analyzer.py` | Celery pipeline: clone → extract → infer → store |
| `benchmark/harness.py` | **NEW** — standalone P/R/F1 benchmark, no DB needed |
| `benchmark/ground_truth/nanochat.json` | **NEW** — nanochat ground truth |

---

## Extractor Patterns (Python, Current)

1. `requests.get/post/put/delete/patch(url)`
2. `httpx.get/post/put/delete/patch(url)`
3. `client.get/post(url)` — only if url starts with `http` (guards FastAPI decorators)
4. aiohttp: `await session.get/post(url)` — via Pattern 3
5. `urllib.request.urlopen(url)`
6. f-string URLs — extract static prefix
7. Variable URLs — store as `<dynamic:varname>`
8. URL concatenation — `BASE_URL + "/path"`

**Known FP:** `dict.get("cpu")` caught by Pattern 3 on robusta. Fix: already applied
(require_absolute=True guards non-http calls).

---

## LLM Inference Details

**Current prompt:** Zero-shot. Input: method + URL/varname + caller. Output: JSON.
**Model:** gemma3:4b (baseline). Temperature: Ollama default (needs explicit control).
**Inference rate:** ~2.4 calls/sec (cold start ~4.5s, warm ~415–916ms).
**Parse failure rate:** 0% on tested repos.

**Confidence tiers observed:**
- Tier 1 (0.95): Named URL constants → `RELAY_EXTERNAL_ACTIONS_URL → relay_service` ✅
- Tier 2 (0.85): Semantic variable names → `worker → worker_service` ✅ reasonable
- Tier 3 (0.70-0.80): Generic names → `url → data_service` ⚠️ low signal
- Fundamental ceiling: LLM can't resolve `url` or `x` without runtime context

**No HOB risk for our task** — outputs are ~15-20 tokens, uniform length.
**Parallelism:** async calls, OLLAMA_NUM_PARALLEL=3-4 sweet spot on Apple Silicon.
Prompt batching rejected: output entanglement + position bias risk.

---

## Planned Ablation (6 Models)

| Model | Type | Size | Role |
|-------|------|------|------|
| `qwen2.5:1.5b` | General tiny | 986MB | Speed floor |
| `qwen3:4b` | Latest gen | ~2.6GB | Latest generation |
| `gemma3:4b` | General | 3.3GB | Current baseline |
| `qwen2.5-coder:7b` | Code-specific | ~4.7GB | **Key comparison** |
| `llama3.1:8b` | General | 4.9GB | Size comparison |
| `gemma4:latest` | General large | 9.6GB | Accuracy ceiling |

**Drop:** starcoder / starcoder2 — outdated code completion models, wrong task.
**Pull needed:** `qwen2.5-coder:7b` and `qwen3:4b`.

**Prompt ablation:** zero-shot vs few-shot (3 examples: named constant, semantic var, generic var).

---

## Gaps Identified and Status

| Gap | Issue | Resolution |
|-----|-------|-----------|
| 1 | Need real-world repos, not just synthetic | Use 5 repos: 3 Python + 2 Go (see below) |
| 2 | "Service" definition | Top-level directory = one service |
| 3 | Scope: HTTP only, missing gRPC/Kafka | Core = HTTP+gRPC; Kafka/DB = future work |
| 4 | No static-only baseline | ✅ Built in harness.py `--baseline` flag |
| 5 | AST-level false negatives (aiohttp, urllib) | Already handled in extractor patterns 3+5 |
| 6 | Confidence calibration not measured | Included in harness metrics output |
| 7 | Blast radius validation method | Confidence-weighted propagation; synthetic demo exact; real repos use architecture docs |
| 8 | Zero-shot vs few-shot not tested | Included in harness `--mode` flag |

---

## The 5 Ground Truth Repos

| # | Repo | Language | HTTP calls | GT source | Status |
|---|------|----------|-----------|-----------|--------|
| 1 | karpathy/nanochat | Python | 8 (all dynamic) | Manual inspection | ✅ nanochat.json created |
| 2 | robusta-dev/robusta | Python | 103 (all dynamic) | Manual verification of subset | ⏳ GT JSON needed |
| 3 | ServiceScope v1 (own) | Python | 5 | We know it exactly | ⏳ GT JSON needed |
| 4 | Online Boutique (Go services) | Go | TBD | Published arch diagram | ⛔ Needs Go extractor |
| 5 | TBD Go repo | Go | TBD | Architecture docs | ⛔ Needs Go extractor |

**Key finding from repo survey:** Canonical microservice demo repos (Online Boutique,
Sock Shop, CoffeeShop) use gRPC not HTTP — zero Python HTTP calls found.
Python HTTP inter-service calls appear in Python-first repos (nanochat, robusta).
This validates the Go extractor as essential, not optional.

---

## What gRPC/Kafka Would Need (Out of Scope for This Paper)

**gRPC:** Same direct-call model as HTTP. Go: `grpc.Dial("service:50051")`.
Extractor pattern change only — LLM inference unchanged. Feasible to add.

**Kafka/RabbitMQ:** Two-pass analysis required (scan all producers + consumers, match
by topic name). Graph model changes: Service → Topic → Service (intermediary node).
Different schema, different blast radius traversal. Separate paper.

**Shared DB coupling:** Detect connection strings + table names across services.
Cross-service global analysis. Most complex. Separate paper.

---

## Build Queue (Next Sessions)

Priority order:

1. **Pull models:** `ollama pull qwen2.5-coder:7b && ollama pull qwen3:4b`
2. **Go extractor:** `app/extraction/extract_go_calls.py` — patterns: `http.Get/Post/NewRequest`, `grpc.Dial/NewClient`, resty
3. **Language detector:** wire into analyzer pipeline
4. **Ground truth JSONs:** robusta.json, servicescope-v1.json
5. **Blast radius endpoint:** `GET /api/v1/repositories/{id}/blast-radius?service=X` with confidence propagation
6. **Run ablation:** 6 models × zero-shot + few-shot × 3 Python repos
7. **Add Go repos:** run ablation on 2 Go repos
8. **Write paper:** LaTeX, Springer LNCS template

---

## Benchmark Harness Usage

```bash
# Pull repo first
git clone --depth 1 https://github.com/karpathy/nanochat /tmp/nanochat

# Static-only baseline (no LLM)
python benchmark/harness.py \
  --repo /tmp/nanochat \
  --ground-truth benchmark/ground_truth/nanochat.json \
  --baseline

# LLM inference (zero-shot)
python benchmark/harness.py \
  --repo /tmp/nanochat \
  --ground-truth benchmark/ground_truth/nanochat.json \
  --model gemma3:4b \
  --mode zero-shot \
  --output results/nanochat_gemma3_zeroshot.json

# LLM inference (few-shot)
python benchmark/harness.py \
  --repo /tmp/nanochat \
  --ground-truth benchmark/ground_truth/nanochat.json \
  --model qwen2.5-coder:7b \
  --mode few-shot \
  --output results/nanochat_qwen_fewshot.json
```

---

## Ground Truth JSON Schema

```json
{
  "repo": "owner/name",
  "url": "https://github.com/...",
  "ground_truth_source": "manual_code_inspection | architecture_diagram | runtime_trace",
  "true_calls": [
    {"caller": "service_dir", "method": "get", "file": "service/file.py"}
  ],
  "true_dependencies": [
    {"caller": "service_a", "callee": "service_b", "verified": true, "evidence": "..."}
  ]
}
```

`verified: false` = callee inferred, not confirmed against architecture doc.
Harness skips inference metrics for unverified entries.

---

## Paper Sections Planned

1. Abstract (150-250 words)
2. Introduction — blast radius problem, pre-deployment gap
3. Related Work — Microvision, Backstage, Datadog, CodeScene
4. System Architecture — pipeline overview
5. Python AST Extraction — 8 patterns, FP analysis
6. Go Extraction — patterns, language extensibility
7. LLM Inference — prompt design, model ablation, confidence calibration
8. Blast Radius Computation — confidence-weighted transitive closure
9. Evaluation — P/R/F1 across 5 repos × 6 models × 2 prompt modes
10. Discussion — accuracy ceiling, dynamic URL fundamental limit
11. Conclusion & Future Work — gRPC, Kafka, Layer 2/3 roadmap

---

## Locked Final Metrics (Session 2)

### Five-Repo Inference F1 Progression
| Repo | Phase 1: Static | Phase 2: Zero-Shot | Phase 3: +Normaliser | Phase 4: Service-Aware | Best Model |
|------|----------------|-------------------|---------------------|----------------------|-----------|
| nanochat | 0.000 | 0.000 | 0.000 | 0.000 | — (naming ceiling) |
| robusta | 0.000 | 0.167 | 0.267 | 0.188 (few-shot) | qwen3:4b ZS |
| servicescope-v1 | 0.200 | 0.800 | 1.000 | 0.800 (few-shot) | gemma4 ZS/FS |
| go-coffeeshop | 0.000 | 0.333 | 0.400 | 0.400 | qwen2.5:1.5b / qwen3:4b |
| microservices-demo | 0.000 | 0.091 | 0.182 | **0.455** | llama3.1:8b SA |

### Blast Radius Results
| Repo | Static | Zero-Shot LLM | Service-Aware |
|------|--------|--------------|---------------|
| microservices-demo | 0.000 | 0.133 | 0.374 |
| servicescope-v1 | 0.190 | 1.000 | 1.000 |

### Locked Normaliser
`STRIP_SUFFIXES = ["service", "client", "api", "handler", "server", "svc"]` — strip one suffix only, break after first match.

### Argo CD Verified Testimonial (argoproj/argo-cd, ~18k stars)
- 26 service nodes discovered via directory scan
- 3 core edges — 100% match against published official architecture diagram:
  - argocd-server → argocd-repo-server (gRPC, conf=1.00)
  - argocd-application-controller → argocd-repo-server (gRPC, conf=1.00)
  - argocd-server → argocd-application-controller (gRPC, conf=1.00)
- Fix required: new Go extractor pattern — custom client constructor calls (`apiclient.NewRepoServerClientset(address)`)
- This pattern generalises: any Go codebase using factory functions to wrap gRPC/HTTP clients

### Three Named Ceilings
1. **Naming specificity ceiling** — generic `url` variables unresolvable without runtime context (nanochat)
2. **Inter-procedural wrapper ceiling** — helper functions hide call targets from intra-procedural AST (microservices-demo frontend misses 9/10 GT services)
3. **Few-shot language mismatch bias** — Python examples in few-shot prompt cause 0.000 F1 on all Go repos

### Confidence Calibration Finding
0.80–0.90 band: only 33% accurate on microservices-demo. Models are systematically overconfident in this range. Scores should be treated as relative rankings, not absolute probabilities.

### Service-Aware Prompting Behaviour
- **Helps:** clean microservice directory layout (microservices-demo 0.182→0.455, Argo CD 100%)
- **Backfires:** monolith-style layout (robusta 0.267→0.056) — directory scan picks up internal packages, not service names
- **External escape hatch:** `"is_external": true` flag prevents force-matching external APIs to internal service names

---

## Revised Paper Outline (Post Structural Review)

Sections: Abstract | Introduction + Scope | Related Work (3 paradigms) | Architecture |
AST Extraction | LLM Inference | Blast Radius | Evaluation (7 subsections) |
Discussion + Threats to Validity | Conclusion | GenAI Declaration | References

**Open questions before writing:**
1. Formal "service" definition — currently: top-level directory with ≥2 source files
2. LLM-for-SE papers to cite in Related Work (CodeBERT, LLM-for-bug-detection etc.)
3. Servicescope-v1 dependency graph figure (NetworkX matplotlib render)
4. Argo CD as primary testimonial (replaces Jaeger — has verified GT) ✅ confirmed
5. GenAI declaration wording — Claude used for code, experiments, drafting; all science by authors

**FTC formatting rules confirmed:**
- 18 pages main text + up to 7 pages references/appendices
- Abstract: 150–250 words strict
- Double-blind, no author info
- GenAI declaration mandatory
- Late Breaking Round papers in separate Springer proceedings volume

---

## Session Log

**Session 1 (24 Jun 2026):**
- Decided on FTC 2026 Late Breaking Round (deadline 1 Jul)
- Reviewed ServiceScope v2 codebase fully
- Set thesis: AST + local LLM recovers inter-service dependencies
- Surveyed related work: Microvision, Backstage, Datadog, CodeScene, Sourcegraph
- Deep dive: LLM inference mechanics, HOB, batching, KV-cache, async parallelism
- Decided language extensibility (Python + Go) and blast radius as core claims
- Identified 8 research gaps; addressed each
- Decided to extend to gRPC; Kafka/DB = future work
- Found that canonical microservice repos use gRPC → validates Go extractor need
- Built: benchmark/harness.py (standalone P/R/F1, no DB), ground_truth/nanochat.json
- Probed 10 repos: most return 0 Python HTTP calls (gRPC or non-Python)

**Session 2 (25 Jun 2026):**
- Fixed GT circularity (nanochat 2→3 calls, robusta 19→35 calls), re-ran full ablation
- Built Go extractor + language detector, ran 5-repo ablation (3 Python + 2 Go)
- Identified three named ceilings (naming, inter-procedural, few-shot bias)
- Built blast radius: log-space Dijkstra, bidirectional traversal, confidence propagation
- Built service-aware prompting: directory scan → known service list → constrained LLM
- Blast radius results: static 0.000 → LLM 0.133 → service-aware 0.374 (microservices-demo)
- Added polyglot service discovery (any files, not just .py/.go)
- Discovered qwen3:4b reasoning model outputs to `thinking` field — added fallback
- Verified Argo CD testimonial: 100% precision on 3 core edges vs published arch diagram
- Added constructor call pattern to Go extractor (handles custom gRPC client factories)
- Confirmed FTC formatting rules (18+7 pages, GenAI declaration mandatory)
- Completed revised paper outline incorporating structural review feedback
- **Next:** 5 answers from user → start writing LaTeX

#!/usr/bin/env python3
"""
ServiceScope Benchmark Harness
================================
Standalone evaluation script — no FastAPI, Celery, or PostgreSQL required.

Evaluates two things independently:
  1. Extraction accuracy  — did the AST extractor find all HTTP calls?
  2. Inference accuracy   — did the LLM infer the correct callee service names?

Usage:
    # Full pipeline (LLM inference)
    python benchmark/harness.py \\
        --repo /path/to/cloned/repo \\
        --ground-truth benchmark/ground_truth/nanochat.json \\
        --model gemma3:4b \\
        --mode zero-shot

    # Static-only baseline (no LLM — URL string parsing only)
    python benchmark/harness.py \\
        --repo /path/to/repo \\
        --ground-truth benchmark/ground_truth/nanochat.json \\
        --baseline

    # Save results to JSON
    python benchmark/harness.py ... --output results/nanochat_gemma3.json
"""

import argparse
import json
import os
import re
import sys
import time
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import requests as http_requests

# Add project root so we can import the extractor directly
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.extraction import walk_and_extract_calls


# ── Prompt Templates ──────────────────────────────────────────────────────────

ZERO_SHOT_PROMPT = """\
You are a microservice architecture assistant.
{service_context}
Given this HTTP call made by service "{caller}":
  Method: {method}
  URL: {url}

Identify the service being called and your confidence.
If it matches a known service, use that exact name.
If it's an external API (Stripe, AWS, Twilio, etc.), return the external name and set "is_external": true.

Respond with ONLY a JSON object, no markdown, no explanation:
{{"service": "service_name", "confidence": 0.0, "is_external": false}}\
"""

FEW_SHOT_PROMPT = """\
You are a microservice architecture assistant.
{service_context}
Examples:
Input:  Method: GET,  URL: http://payment-service/charge,  Caller: order_service
Output: {{"service": "payment_service", "confidence": 0.95, "is_external": false}}

Input:  Method: POST, URL: https://api.stripe.com/v1/charges, Caller: checkout
Output: {{"service": "stripe", "confidence": 0.99, "is_external": true}}

Input:  Method: POST, URL: <dynamic:GRAFANA_RENDERER_URL>,  Caller: monitoring
Output: {{"service": "grafana_renderer", "confidence": 0.90, "is_external": false}}

Now classify:
Given this HTTP call made by service "{caller}":
  Method: {method}
  URL: {url}

Respond with ONLY a JSON object:
{{"service": "service_name", "confidence": 0.0, "is_external": false}}\
"""


# ── LLM Inference ─────────────────────────────────────────────────────────────

def infer_single(caller: str, method: str, url: str,
                 ollama_url: str, model: str, mode: str, service_context: str = "") -> dict:
    """Send one call to Ollama and return parsed inference result."""
    template = FEW_SHOT_PROMPT if "few-shot" in mode else ZERO_SHOT_PROMPT
    prompt = template.format(caller=caller, method=method.upper(), url=url, service_context=service_context)

    t0 = time.time()
    try:
        resp = http_requests.post(
            f"{ollama_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt.strip(),
                "stream": False,
                "format": "json"
            },
            timeout=90,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        raw = resp.json().get("response", "").strip() or resp.json().get("thinking", "").strip()

        # Strip markdown fences the model may add
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(clean)
        service = str(parsed.get("service", "")).strip().strip('"')
        confidence = float(parsed.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
        is_external = bool(parsed.get("is_external", False))

        return {
            "service": service,
            "confidence": confidence,
            "is_external": is_external,
            "elapsed_ms": elapsed_ms,
            "parse_ok": True,
            "raw": raw,
        }

    except json.JSONDecodeError:
        elapsed_ms = int((time.time() - t0) * 1000)
        # Fallback: take first non-empty line as service name
        service = raw.split("\n")[0].strip().strip('"') if "raw" in dir() else "parse_error"
        return {
            "service": service,
            "confidence": 0.5,
            "is_external": False,
            "elapsed_ms": elapsed_ms,
            "parse_ok": False,
            "raw": raw if "raw" in dir() else "",
        }

    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        return {
            "service": "error",
            "confidence": 0.0,
            "is_external": False,
            "elapsed_ms": elapsed_ms,
            "parse_ok": False,
            "raw": str(e),
        }


# ── Static-Only Baseline ──────────────────────────────────────────────────────

def static_infer(url: str) -> dict:
    """
    Baseline: extract service name from the URL string without any LLM.
    Dynamic URLs (<dynamic:*>) cannot be resolved — return None.
    Static URLs: extract hostname, normalise to snake_case.
    """
    if url.startswith("<dynamic:"):
        return {"service": None, "confidence": 0.0}

    match = re.match(r"https?://([^/:?#]+)", url)
    if match:
        host = match.group(1)
        # Normalise: strip port, replace hyphens/dots with underscores
        service = re.sub(r":\d+$", "", host).replace("-", "_").replace(".", "_")
        return {"service": service, "confidence": 1.0}

    return {"service": None, "confidence": 0.0}


# ── Metrics ───────────────────────────────────────────────────────────────────

def normalise(name: str) -> str:
    """
    Standardises service names for fuzzy matching.
    Lowercases, removes delimiters (spaces, underscores, hyphens), and strips
    a single common architectural suffix in a defined order.
    """
    if not name:
        return ""
    
    # Lowercase and strip all spacing/delimiters
    name = name.lower().replace("-", "").replace("_", "").replace(" ", "").strip()
    
    # Define a locked list of architectural suffixes
    STRIP_SUFFIXES = ["service", "client", "api", "handler", "server", "svc"]
    for suffix in STRIP_SUFFIXES:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break  # Strip only one suffix to prevent recursive over-stripping
            
    return name


def extraction_metrics(found_calls: list, true_calls: list) -> dict:
    """
    Extraction-level evaluation: did the AST extractor find all expected calls?

    true_calls schema: [{"caller": str, "method": str, "file": str}]
    found_calls schema: output of walk_and_extract_calls
    """
    def call_key(c):
        return (normalise(c.get("service", c.get("caller", ""))),
                normalise(c.get("method", "")),
                normalise(c.get("file", "")))

    found_keys = {call_key(c) for c in found_calls}
    true_keys  = {call_key(c) for c in true_calls}

    tp = found_keys & true_keys
    fn = true_keys  - found_keys
    fp = found_keys - true_keys

    recall    = len(tp) / len(true_keys)  if true_keys  else 0.0
    precision = len(tp) / len(found_keys) if found_keys else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) > 0 else 0.0)

    return {
        "precision": round(precision, 3),
        "recall":    round(recall, 3),
        "f1":        round(f1, 3),
        "tp": len(tp), "fp": len(fp), "fn": len(fn),
        "fn_calls": [{"caller": c[0], "method": c[1], "file": c[2]} for c in sorted(fn)],
        "fp_calls": [{"caller": c[0], "method": c[1], "file": c[2]} for c in sorted(fp)],
    }


def inference_metrics(predictions: list, true_deps: list) -> dict:
    """
    Inference-level evaluation: did the LLM infer the correct callee service names?

    true_deps schema:   [{"caller": str, "callee": str, "verified": bool}]
    predictions schema: [{"caller": str, "callee": str, "confidence": float, ...}]
    """
    # Only evaluate against verified ground truth entries
    verified = [d for d in true_deps if d.get("verified", True)]
    if not verified:
        return {"note": "No verified ground truth entries — skipping inference metrics"}

    gt_set   = {(normalise(d["caller"]), normalise(d["callee"])) for d in verified}
    pred_set = {(normalise(p["caller"]), normalise(p["callee"]))
                for p in predictions if p.get("callee") and not p.get("is_external", False)}

    tp = gt_set & pred_set
    fp = pred_set - gt_set
    fn = gt_set   - pred_set

    precision = len(tp) / len(pred_set) if pred_set else 0.0
    recall    = len(tp) / len(gt_set)   if gt_set  else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) > 0 else 0.0)

    # Confidence calibration bands
    bands = {"0.90-1.00": [], "0.80-0.90": [], "0.70-0.80": [], "0.00-0.70": []}
    for p in predictions:
        c = p.get("confidence", 0.0)
        correct = (normalise(p["caller"]), normalise(p["callee"])) in gt_set
        if   c >= 0.90: bands["0.90-1.00"].append(correct)
        elif c >= 0.80: bands["0.80-0.90"].append(correct)
        elif c >= 0.70: bands["0.70-0.80"].append(correct)
        else:           bands["0.00-0.70"].append(correct)

    calibration = {
        band: {"count": len(v), "accuracy": round(sum(v) / len(v), 3)}
        for band, v in bands.items() if v
    }

    return {
        "precision": round(precision, 3),
        "recall":    round(recall, 3),
        "f1":        round(f1, 3),
        "tp": len(tp), "fp": len(fp), "fn": len(fn),
        "tp_edges": sorted(tp),
        "fp_edges": sorted(fp),
        "fn_edges": sorted(fn),
        "calibration": calibration,
    }


# ── Main Runner ───────────────────────────────────────────────────────────────

def run_benchmark(repo_path: str, ground_truth_path: str,
                  model: str, mode: str, ollama_url: str,
                  baseline: bool = False) -> dict:

    with open(ground_truth_path) as f:
        gt = json.load(f)

    true_calls = gt.get("true_calls", [])
    true_deps  = gt.get("true_dependencies", [])
    label = "static-only (no LLM)" if baseline else f"{model} / {mode}"

    print(f"\n{'='*62}")
    print(f"  Repo         : {gt.get('repo', repo_path)}")
    print(f"  Model        : {label}")
    print(f"  GT calls     : {len(true_calls)}")
    print(f"  GT deps      : {len([d for d in true_deps if d.get('verified', True)])}")
    print(f"{'='*62}")

    # ── Step 1: Extraction (suppress per-file noise) ──────────────────────────
    buf = StringIO()
    t0 = time.time()
    with redirect_stdout(buf):
        raw_calls = walk_and_extract_calls(repo_path)
    t_extract = round(time.time() - t0, 3)
    print(f"\n[1] Extraction: {len(raw_calls)} calls in {t_extract}s")

    # Extraction-level metrics
    ext_metrics = extraction_metrics(raw_calls, true_calls) if true_calls else {}

    # Discover services for service-aware prompting and linking
    from app.extraction.service_discovery import discover_services
    from app.analysis.linker import CrossLayerLinker
    
    services = discover_services(repo_path)
    linker = CrossLayerLinker(repo_path, services)
    
    service_context = ""
    if not baseline and "service-aware" in mode:
        if services:
            service_context = f"Known internal services in this repository: {', '.join(services)}\n"
            print(f"  Service-aware mode: active ({len(services)} services discovered)")

    # ── Step 2: Inference ─────────────────────────────────────────────────────
    predictions = []
    parse_failures = 0
    t1 = time.time()

    for i, call in enumerate(raw_calls):
        caller = call.get("service", "unknown")
        url    = call.get("url", "")
        method = call.get("method", "get")
        file_path = call.get("file", "")

        # Filter out utility/test/mock calls that do not represent real service dependencies
        norm_caller = normalise(caller)
        clean_url = url
        if url.startswith("<dynamic:") and url.endswith(">"):
            clean_url = url[9:-1].strip()
        norm_url = normalise(clean_url)
        
        is_spurious = (
            norm_caller in ("shared", "reactnativeapp")
            or "test" in file_path.lower()
            or "conftest" in file_path.lower()
            or norm_url in (
                "url",
                "requesturl",
                "httpclientbaseaddress",
                "channel",
                "badaddress",
                "svcaddr"
            )
        )

        link_res = linker.resolve_call(caller, url)
        if is_spurious:
            result = {"service": None, "confidence": 0.0}
        elif link_res:
            callee, conf = link_res
            result = {
                "service": callee,
                "confidence": conf,
                "is_external": False,
                "elapsed_ms": 0,
                "parse_ok": True,
                "raw": "Resolved via Cross-Layer Linker",
            }
        elif baseline:
            # 2. Fall back to static URL inference
            result = static_infer(url)
        else:
            # 3. Fall back to LLM inference
            result = infer_single(caller, method, url, ollama_url, model, mode, service_context=service_context)
            if not result.get("parse_ok"):
                parse_failures += 1

        if result.get("service"):
            predictions.append({
                "caller":     caller,
                "callee":     result["service"],
                "confidence": result["confidence"],
                "is_external": result.get("is_external", False),
                "url":        url,
                "method":     method,
                "file":       call.get("file", ""),
                "elapsed_ms": result.get("elapsed_ms", 0),
            })

        if not baseline and (i + 1) % 5 == 0:
            print(f"  Inferred {i+1}/{len(raw_calls)}...", end="\r")

    t_infer = round(time.time() - t1, 3)
    if not baseline:
        print(f"\n[2] Inference : {len(predictions)} deps in {t_infer}s "
              f"({parse_failures} parse failures)")
    else:
        resolvable = sum(1 for p in predictions if p["callee"])
        dynamic    = sum(1 for c in raw_calls if c.get("url", "").startswith("<dynamic:"))
        print(f"\n[2] Static baseline: {resolvable}/{len(raw_calls)} resolved "
              f"({dynamic} dynamic — unresolvable without LLM)")

    # ── Step 3: Inference metrics ─────────────────────────────────────────────
    inf_metrics = inference_metrics(predictions, true_deps) if true_deps else {}

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f"\n{'─'*62}")
    print(f"  EXTRACTION ACCURACY")
    print(f"{'─'*62}")
    if ext_metrics:
        print(f"  Precision : {ext_metrics['precision']:.3f}")
        print(f"  Recall    : {ext_metrics['recall']:.3f}")
        print(f"  F1        : {ext_metrics['f1']:.3f}")
        print(f"  TP/FP/FN  : {ext_metrics['tp']} / {ext_metrics['fp']} / {ext_metrics['fn']}")
        if ext_metrics.get("fn_calls"):
            print(f"  Missed    : {ext_metrics['fn_calls']}")
    else:
        print("  (no true_calls in ground truth — skipped)")

    print(f"\n{'─'*62}")
    print(f"  INFERENCE ACCURACY")
    print(f"{'─'*62}")
    if inf_metrics and "note" not in inf_metrics:
        print(f"  Precision : {inf_metrics['precision']:.3f}")
        print(f"  Recall    : {inf_metrics['recall']:.3f}")
        print(f"  F1        : {inf_metrics['f1']:.3f}")
        print(f"  TP/FP/FN  : {inf_metrics['tp']} / {inf_metrics['fp']} / {inf_metrics['fn']}")
        print(f"\n  Confidence Calibration:")
        for band, cal in inf_metrics.get("calibration", {}).items():
            bar = "█" * int(cal["accuracy"] * 20)
            print(f"    {band}  {bar:<20}  acc={cal['accuracy']:.3f}  n={cal['count']}")
        if inf_metrics.get("fn_edges"):
            print(f"\n  Missed deps (FN) : {inf_metrics['fn_edges']}")
        if inf_metrics.get("fp_edges"):
            print(f"  Spurious (FP)    : {inf_metrics['fp_edges']}")
    else:
        print(f"  {inf_metrics.get('note', '(no verified true_dependencies — skipped)')}")

    timing = {
        "extract_s": t_extract,
        "infer_s":   t_infer,
        "total_s":   round(t_extract + t_infer, 3),
        "calls_per_sec": round(len(raw_calls) / t_infer, 2) if t_infer > 0 and not baseline else None,
        "avg_infer_ms": round(
            sum(p["elapsed_ms"] for p in predictions) / len(predictions), 1
        ) if predictions and not baseline else None,
        "parse_failures": parse_failures if not baseline else 0,
    }

    print(f"\n{'─'*62}")
    print(f"  TIMING")
    print(f"{'─'*62}")
    print(f"  Extract   : {timing['extract_s']}s")
    print(f"  Infer     : {timing['infer_s']}s")
    print(f"  Total     : {timing['total_s']}s")
    if timing["calls_per_sec"]:
        print(f"  Rate      : {timing['calls_per_sec']} calls/sec")
    if timing["avg_infer_ms"]:
        print(f"  Avg/call  : {timing['avg_infer_ms']}ms")

    return {
        "repo":              gt.get("repo"),
        "model":             "static-only" if baseline else model,
        "mode":              "baseline"    if baseline else mode,
        "calls_extracted":   len(raw_calls),
        "predictions":       len(predictions),
        "extraction_metrics": ext_metrics,
        "inference_metrics":  inf_metrics,
        "timing":            timing,
        "all_predictions":   predictions,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ServiceScope Benchmark Harness")
    parser.add_argument("--repo",         required=True,
                        help="Path to a locally cloned repo")
    parser.add_argument("--ground-truth", required=True,
                        help="Path to ground truth JSON file")
    parser.add_argument("--model",        default="gemma3:4b",
                        help="Ollama model name (default: gemma3:4b)")
    parser.add_argument("--mode",         default="zero-shot",
                        choices=["zero-shot", "few-shot", "service-aware", "service-aware-few-shot"],
                        help="Prompting mode (default: zero-shot)")
    parser.add_argument("--ollama-url",   default="http://localhost:11434",
                        help="Ollama base URL (default: http://localhost:11434)")
    parser.add_argument("--baseline",     action="store_true",
                        help="Run static-only baseline — no LLM")
    parser.add_argument("--output",       default=None,
                        help="Save full results to this JSON file")
    args = parser.parse_args()

    result = run_benchmark(
        repo_path=args.repo,
        ground_truth_path=args.ground_truth,
        model=args.model,
        mode=args.mode,
        ollama_url=args.ollama_url,
        baseline=args.baseline,
    )

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nResults saved → {args.output}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
ServiceScope Ablation Orchestrator
==================================
Runs the complete benchmark suite:
- 3 repositories (nanochat, robusta, servicescope-v1)
- 6 models (qwen2.5:1.5b, qwen3:4b, gemma3:4b, qwen2.5-coder:7b, llama3.1:8b, gemma4:latest)
- 2 modes (zero-shot, few-shot)
- 1 static-only baseline
Saves JSON results to benchmark/results/ and prints a markdown table.
"""

import os
import sys
import json
import subprocess
from datetime import datetime

REPOS = {
    "nanochat": {
        "path": "benchmark/repos/nanochat",
        "gt": "benchmark/ground_truth/nanochat.json",
    },
    "robusta": {
        "path": "benchmark/repos/robusta",
        "gt": "benchmark/ground_truth/robusta.json",
    },
    "servicescope-v1": {
        "path": "/Users/aravindsundaresan/PycharmProjects/ServiceScope",
        "gt": "benchmark/ground_truth/servicescope-v1.json",
    },
    "microservices-demo": {
        "path": "benchmark/repos/microservices-demo",
        "gt": "benchmark/ground_truth/microservices-demo.json",
    },
    "go-coffeeshop": {
        "path": "benchmark/repos/go-coffeeshop",
        "gt": "benchmark/ground_truth/go-coffeeshop.json",
    },
}

MODELS = [
    "qwen2.5:1.5b",
    "qwen3:4b",
    "gemma3:4b",
    "qwen2.5-coder:7b",
    "llama3.1:8b",
    "gemma4:latest",
]

MODES = ["zero-shot", "few-shot", "service-aware", "service-aware-few-shot"]


import argparse

def main():
    parser = argparse.ArgumentParser(description="ServiceScope Ablation Orchestrator")
    parser.add_argument("--force", action="store_true", help="Force re-running all configurations, bypassing cache")
    args = parser.parse_args()

    os.makedirs("benchmark/results", exist_ok=True)
    summary_data = []

    print(f"🚀 Starting ServiceScope Ablation Study - {datetime.now().isoformat()}")
    print(f"Logging outputs to benchmark/results/\n")

    # 1. Run Baselines
    for repo_name, repo_info in REPOS.items():
        output_file = f"benchmark/results/{repo_name}_baseline.json"
        
        res = None
        if not args.force and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            print(f"Loading cached static-only baseline for {repo_name}...")
            try:
                with open(output_file) as f:
                    res = json.load(f)
            except Exception as e:
                print(f"  Failed to load cache, will re-run: {e}")

        if res is None:
            print(f"Running static-only baseline for {repo_name}...")
            try:
                cmd = [
                    sys.executable,
                    "benchmark/harness.py",
                    "--repo", repo_info["path"],
                    "--ground-truth", repo_info["gt"],
                    "--baseline",
                    "--output", output_file,
                ]
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                
                with open(output_file) as f:
                    res = json.load(f)
            except Exception as e:
                print(f"  ❌ Error running baseline for {repo_name}: {e}")
                continue
                
        summary_data.append({
            "repo": repo_name,
            "model": "static-only",
            "mode": "baseline",
            "extract_p": res["extraction_metrics"].get("precision", 0.0),
            "extract_r": res["extraction_metrics"].get("recall", 0.0),
            "extract_f1": res["extraction_metrics"].get("f1", 0.0),
            "infer_p": res["inference_metrics"].get("precision", 0.0),
            "infer_r": res["inference_metrics"].get("recall", 0.0),
            "infer_f1": res["inference_metrics"].get("f1", 0.0),
            "avg_infer_ms": 0.0,
            "total_s": res["timing"].get("total_s", 0.0),
        })
        print(f"  Done. F1 (Extract/Infer): {res['extraction_metrics'].get('f1'):.3f} / {res['inference_metrics'].get('f1'):.3f}")

    # 2. Run LLM Configurations
    total_runs = len(REPOS) * len(MODELS) * len(MODES)
    run_idx = 0

    for repo_name, repo_info in REPOS.items():
        for model in MODELS:
            for mode in MODES:
                run_idx += 1
                model_safe = model.replace(":", "_")
                output_file = f"benchmark/results/{repo_name}_{model_safe}_{mode}.json"
                
                res = None
                if not args.force and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                    print(f"[{run_idx}/{total_runs}] Loading cached {model} ({mode}) for {repo_name}...")
                    try:
                        with open(output_file) as f:
                            res = json.load(f)
                    except Exception as e:
                        print(f"  Failed to load cache, will re-run: {e}")

                if res is None:
                    print(f"[{run_idx}/{total_runs}] Running {model} ({mode}) on {repo_name}...")
                    try:
                        cmd = [
                            sys.executable,
                            "benchmark/harness.py",
                            "--repo", repo_info["path"],
                            "--ground-truth", repo_info["gt"],
                            "--model", model,
                            "--mode", mode,
                            "--output", output_file,
                        ]
                        subprocess.run(cmd, check=True, capture_output=True, text=True)
                        
                        with open(output_file) as f:
                            res = json.load(f)
                    except Exception as e:
                        print(f"  ❌ Error running {model} ({mode}) on {repo_name}: {e}")
                        continue
                        
                summary_data.append({
                    "repo": repo_name,
                    "model": model,
                    "mode": mode,
                    "extract_p": res["extraction_metrics"].get("precision", 0.0),
                    "extract_r": res["extraction_metrics"].get("recall", 0.0),
                    "extract_f1": res["extraction_metrics"].get("f1", 0.0),
                    "infer_p": res["inference_metrics"].get("precision", 0.0),
                    "infer_r": res["inference_metrics"].get("recall", 0.0),
                    "infer_f1": res["inference_metrics"].get("f1", 0.0),
                    "avg_infer_ms": res["timing"].get("avg_infer_ms") or 0.0,
                    "total_s": res["timing"].get("total_s", 0.0),
                })
                print(f"  Done. F1 (Extract/Infer): {res['extraction_metrics'].get('f1'):.3f} / {res['inference_metrics'].get('f1'):.3f} in {res['timing'].get('total_s')}s")

    # Write summary
    summary_path = "benchmark/results/ablation_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary_data, f, indent=2)
        
    print(f"\nAll experiments complete. Summary JSON saved to {summary_path}")

    # Generate Markdown Table
    print("\n## ABLATION RESULTS SUMMARY\n")
    print("| Repository | Model | Mode | Extract F1 | Infer P | Infer R | Infer F1 | Latency/call (ms) |")
    print("|---|---|---|---|---|---|---|---|")
    for r in sorted(summary_data, key=lambda x: (x["repo"], x["model"], x["mode"])):
        print(f"| {r['repo']} | {r['model']} | {r['mode']} | {r['extract_f1']:.3f} | {r['infer_p']:.3f} | {r['infer_r']:.3f} | {r['infer_f1']:.3f} | {r['avg_infer_ms']:.0f} |")


if __name__ == "__main__":
    main()

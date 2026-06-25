#!/usr/bin/env python3
"""
ServiceScope Blast Radius Evaluation Harness
============================================
Evaluates:
  Claim 1: Blast radius accuracy (Precision, Recall, F1) vs. Ground Truth graph.
  Claim 2: Calibration of path confidence scores (exploratory/qualitative).
  Baseline: Compares LLM-inferred blast radius vs. static-only baseline.

Prints a worked example comparing predicted vs. true blast radius for a service.
"""

import json
import os
import sys
import math
from pathlib import Path
import networkx as nx

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.analysis.graph_builder import build_graph
from app.analysis.blast_radius import compute_blast_radius, normalise

# We target two main repositories for evaluation
EVAL_CONFIG = {
    "microservices-demo": {
        "gt_file": "benchmark/ground_truth/microservices-demo.json",
        "best_result_file": "benchmark/results/microservices-demo_llama3.1_8b_service-aware.json",
        "baseline_result_file": "benchmark/results/microservices-demo_baseline.json",
        "example_service": "frontend"
    },
    "servicescope-v1": {
        "gt_file": "benchmark/ground_truth/servicescope-v1.json",
        "best_result_file": "benchmark/results/servicescope-v1_gemma4_latest_zero-shot.json",
        "baseline_result_file": "benchmark/results/servicescope-v1_baseline.json",
        "example_service": "samples"
    }
}


def build_gt_graph(gt_deps: list) -> nx.DiGraph:
    """
    Builds a NetworkX DiGraph from ground truth dependencies.
    Since this is the ground truth, all edges have confidence 1.0 (weight = 0.0).
    """
    g = nx.DiGraph()
    for dep in gt_deps:
        caller = normalise(dep["caller"])
        callee = normalise(dep["callee"])
        if caller and callee:
            # Multi-edges collapse under GT (weight = -log(1.0) = 0.0)
            g.add_edge(caller, callee, confidence=1.0, weight=0.0, method="grpc", url="")
    return g


def evaluate_blast_radius(gt_graph: nx.DiGraph, pred_graph: nx.DiGraph, confidence_threshold: float = 0.5) -> dict:
    """
    Computes Precision, Recall, and F1 of predicted blast radius vs. GT blast radius
    for all services present in the ground truth graph.
    """
    gt_services = list(gt_graph.nodes)
    
    per_service_metrics = {}
    calibration_data = []
    
    for svc in gt_services:
        # 1. Compute Ground Truth Blast Radius (threshold = 0.0)
        gt_res = compute_blast_radius(gt_graph, svc, confidence_threshold=0.0)
        gt_affected = {item["service"] for item in gt_res["affected_services"]}
        
        # 2. Compute Predicted Blast Radius (using log-space Dijkstra & threshold)
        try:
            pred_res = compute_blast_radius(pred_graph, svc, confidence_threshold=confidence_threshold)
            pred_affected = {item["service"]: item for item in pred_res["affected_services"]}
        except ValueError:
            # Service not present in predicted graph
            pred_affected = {}
            
        pred_set = set(pred_affected.keys())
        
        # 3. Calculate metrics
        tp = gt_affected & pred_set
        fp = pred_set - gt_affected
        fn = gt_affected - pred_set
        
        precision = len(tp) / len(pred_set) if pred_set else 0.0
        recall = len(tp) / len(gt_affected) if gt_affected else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0.0 else 0.0
        
        per_service_metrics[svc] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "tp": sorted(list(tp)),
            "fp": sorted(list(fp)),
            "fn": sorted(list(fn))
        }
        
        # 4. Collect calibration data (Claim 2)
        # For each predicted affected service, we record path confidence and correctness
        for target, data in pred_affected.items():
            is_correct = target in gt_affected
            calibration_data.append((data["confidence"], is_correct))
            
    # Compute averages across services
    if per_service_metrics:
        avg_precision = sum(m["precision"] for m in per_service_metrics.values()) / len(per_service_metrics)
        avg_recall = sum(m["recall"] for m in per_service_metrics.values()) / len(per_service_metrics)
        avg_f1 = sum(m["f1"] for m in per_service_metrics.values()) / len(per_service_metrics)
    else:
        avg_precision, avg_recall, avg_f1 = 0.0, 0.0, 0.0
        
    return {
        "averages": {
            "precision": round(avg_precision, 3),
            "recall": round(avg_recall, 3),
            "f1": round(avg_f1, 3)
        },
        "per_service": per_service_metrics,
        "calibration": calibration_data
    }


def analyze_calibration(calibration_data: list) -> dict:
    """Group path predictions into standard confidence bands and compute accuracy."""
    bands = {"0.90-1.00": [], "0.80-0.90": [], "0.70-0.80": [], "0.00-0.70": []}
    for confidence, correct in calibration_data:
        if confidence >= 0.90:
            bands["0.90-1.00"].append(correct)
        elif confidence >= 0.80:
            bands["0.80-0.90"].append(correct)
        elif confidence >= 0.70:
            bands["0.70-0.80"].append(correct)
        else:
            bands["0.00-0.70"].append(correct)
            
    summary = {}
    for band, results in bands.items():
        if results:
            summary[band] = {
                "count": len(results),
                "accuracy": round(sum(results) / len(results), 3)
            }
        else:
            summary[band] = {"count": 0, "accuracy": 0.0}
    return summary


def run_evaluation():
    print(f"\n============================================================")
    print(f"       ServiceScope Blast Radius Benchmarks                ")
    print(f"============================================================\n")
    
    for repo_name, config in EVAL_CONFIG.items():
        print(f"### Repository: {repo_name}")
        
        # Load ground truth
        with open(config["gt_file"]) as f:
            gt = json.load(f)
            
        gt_graph = build_gt_graph(gt.get("true_dependencies", []))
        
        # 1. Best LLM model
        best_file = config["best_result_file"]
        if not os.path.exists(best_file):
            print(f"  [Error] Best result file missing: {best_file}")
            continue
            
        with open(best_file) as f:
            best_res = json.load(f)
        
        pred_graph_llm = build_graph(best_res.get("all_predictions", []))
        llm_eval = evaluate_blast_radius(gt_graph, pred_graph_llm, confidence_threshold=0.5)
        
        # 2. Baseline
        base_file = config["baseline_result_file"]
        if not os.path.exists(base_file):
            print(f"  [Error] Baseline file missing: {base_file}")
            continue
            
        with open(base_file) as f:
            base_res = json.load(f)
            
        pred_graph_base = build_graph(base_res.get("all_predictions", []))
        base_eval = evaluate_blast_radius(gt_graph, pred_graph_base, confidence_threshold=0.5)
        
        # ── Output Results table ──
        print(f"  {'─'*52}")
        print(f"  {'Metric':<15} | {'Static Baseline':<17} | {'ServiceScope (LLM)':<16}")
        print(f"  {'─'*52}")
        print(f"  {'Precision':<15} | {base_eval['averages']['precision']:<17.3f} | {llm_eval['averages']['precision']:<16.3f}")
        print(f"  {'Recall':<15} | {base_eval['averages']['recall']:<17.3f} | {llm_eval['averages']['recall']:<16.3f}")
        print(f"  {'F1-score':<15} | {base_eval['averages']['f1']:<17.3f} | {llm_eval['averages']['f1']:<16.3f}")
        print(f"  {'─'*52}")
        
        # Calibration (Claim 2)
        cal_summary = analyze_calibration(llm_eval["calibration"])
        print("\n  Exploratory Calibration (LLM Path Confidence):")
        for band, metrics in cal_summary.items():
            if metrics["count"] > 0:
                bar = "█" * int(metrics["accuracy"] * 10)
                print(f"    {band}: {bar:<10} acc={metrics['accuracy']:.3f} (n={metrics['count']})")
            else:
                print(f"    {band}: (no predictions)")
        print()
        
        # ── Worked Example (Paper Illustrative Figure Context) ──
        example_svc = config["example_service"]
        print(f"  Worked Example: Service '{example_svc}' Blast Radius comparison")
        print(f"  {'─'*70}")
        
        # True blast radius
        gt_res = compute_blast_radius(gt_graph, example_svc, confidence_threshold=0.0)
        gt_list = {item["service"]: item for item in gt_res["affected_services"]}
        
        # Predicted blast radius
        try:
            pred_res = compute_blast_radius(pred_graph_llm, example_svc, confidence_threshold=0.5)
            pred_list = {item["service"]: item for item in pred_res["affected_services"]}
        except ValueError:
            pred_res = {"affected_services": []}
            pred_list = {}
            
        print(f"  {'Service':<18} | {'GT Direction':<13} | {'Pred Direction':<14} | {'Path Confidence':<15}")
        print(f"  {'─'*70}")
        
        all_example_services = sorted(list(set(gt_list.keys()) | set(pred_list.keys())))
        for s in all_example_services:
            gt_dir = gt_list[s]["direction"] if s in gt_list else "None"
            pred_dir = pred_list[s]["direction"] if s in pred_list else "None"
            conf_str = f"{pred_list[s]['confidence']:.4f}" if s in pred_list else "N/A"
            
            # Highlight correctness
            marker = "✓" if (s in gt_list and s in pred_list) else "✗"
            print(f"  {marker} {s:<15} | {gt_dir:<13} | {pred_dir:<14} | {conf_str:<15}")
            
        print(f"  {'─'*70}")
        print(f"  (✓ = True Positive, ✗ = Misprediction or Miss)\n\n")


if __name__ == "__main__":
    run_evaluation()

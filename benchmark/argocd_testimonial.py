#!/usr/bin/env python3
"""
ServiceScope Testimonial Checker: Argo CD GitOps System
======================================================
Clones, extracts, and infers service dependencies on the real-world
18k-star 'argoproj/argo-cd' Go codebase.
"""

import os
import sys
import time
import networkx as nx

# Add project root to path
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.extraction import walk_and_extract_calls
from app.extraction.service_discovery import discover_services
from app.analysis.graph_builder import build_graph
from app.analysis.blast_radius import compute_blast_radius
from benchmark.harness import infer_single

def main():
    repo_path = "benchmark/repos/argo-cd"
    model = "llama3.1:8b"
    ollama_url = "http://localhost:11434"
    
    print("======================================================================")
    if not os.path.exists(repo_path):
        print("❌ Argo CD repository not found! Please clone it first.")
        return
        
    print(f"🚀 Running ServiceScope Argo CD Testimonial Evaluation")
    print("======================================================================\n")

    # 1. Run Service Discovery
    print("[1] Running Service Discovery...")
    services = discover_services(repo_path)
    print(f"  Discovered services: {services}\n")
    
    service_context = ""
    if services:
        service_context = f"Known internal services in this repository: {', '.join(services)}\n"

    # 2. Run AST Call Site Extraction
    print("[2] Running AST Call Site Extraction...")
    all_calls = walk_and_extract_calls(repo_path)
    print(f"  Total raw calls found: {len(all_calls)}")
    
    # Filter network-only production calls
    network_keys = ['addr', 'host', 'port', 'url', 'http', 'client', 'conn', 'dial', 'endpoint', 'server', 'controller']
    prod_calls = [
        c for c in all_calls
        if '_test' not in c['file'] 
        and 'test' not in c['file'] 
        and 'example' not in c['file'] 
        and 'scripts' not in c['file']
        and 'hack/' not in c['file']
        and 'mock' not in c['file']
    ]
    network_calls = [
        c for c in prod_calls
        if any(k in c['url_raw_expr'].lower() for k in network_keys) 
        or c['method'] == 'grpc'
    ]
    
    # Focus only on target cmd-level controller and server callers to keep run focused and fast
    filtered_calls = []
    target_callers = {'argocd-server', 'argocd-application-controller'}
    for c in network_calls:
        if c.get("service") in target_callers:
            # Avoid generic/redundant duplicate entries
            if not any(fc['service'] == c['service'] and fc['url_raw_expr'] == c['url_raw_expr'] for fc in filtered_calls):
                filtered_calls.append(c)
                
    print(f"  Filtered network-only production calls for core components: {len(filtered_calls)}\n")

    if not filtered_calls:
        print("❌ No matching network calls found for evaluation!")
        return

    # 3. Run LLM Inference (Service-Aware)
    print(f"[3] Running Service-Aware LLM Inference ({model})...")
    predictions = []
    
    for i, call in enumerate(filtered_calls):
        caller = call.get("service", "unknown")
        url = call.get("url", "")
        method = call.get("method", "get")
        raw_expr = call.get("url_raw_expr", "")
        
        print(f"  Inferring {i+1}/{len(filtered_calls)}: {caller} calls {raw_expr} ({method.upper()})...")
        
        result = infer_single(
            caller=caller,
            method=method,
            url=url if url != "<dynamic:>" else f"<dynamic:{raw_expr}>",
            ollama_url=ollama_url,
            model=model,
            mode="service-aware",
            service_context=service_context
        )
        
        if result.get("service") and result["service"] != "error":
            predictions.append({
                "caller": caller,
                "callee": result["service"],
                "confidence": result["confidence"],
                "is_external": result.get("is_external", False),
                "url": url,
                "method": method,
                "file": call.get("file", ""),
                "elapsed_ms": result.get("elapsed_ms", 0),
            })
            print(f"    -> Inferred: {result['service']} (conf={result['confidence']}, external={result.get('is_external')})")

    print(f"\n[4] Building Dependency Graph & Analyzing Blast Radius...")
    
    # Build predicted graph
    graph = build_graph(predictions)
    
    print("\n==============================================================")
    print("      ServiceScope Mapped Argo CD Service Dependencies         ")
    print("==============================================================")
    for u, v, d in graph.edges(data=True):
        ext_str = " (EXTERNAL)" if d.get("is_external") else ""
        print(f"  {u} ──({d['method'].upper()})──> {v} [conf={d['confidence']:.2f}]{ext_str}")
        
    # Standardize ground truth validation targets
    print("\n==============================================================")
    print("      Computed Blast Radius from 'argocd-server'              ")
    print("==============================================================")
    try:
        blast = compute_blast_radius(graph, "argocd-server", confidence_threshold=0.5)
        print(f"Service: {blast['service']}")
        print(f"Affected set:")
        for item in blast["affected_services"]:
            ext_flag = " [EXTERNAL]" if item.get("is_external") else ""
            print(f"  - {item['service']} ({item['direction']}, hops={item['hops']}, conf={item['confidence']:.2f}){ext_flag}")
            print(f"    Path: {' -> '.join(item['path'])}")
    except ValueError as e:
        print(f"  Could not compute blast radius for 'argocd-server': {e}")
        
    print("\n==============================================================")
    print("Testimonial check concluded successfully.")

if __name__ == "__main__":
    main()

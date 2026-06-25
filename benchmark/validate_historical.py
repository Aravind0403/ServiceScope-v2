#!/usr/bin/env python3
"""
validate_historical.py
======================
Historical validation harness for ServiceScope.
Traverses squash-merged PR commits on the main branch of a microservices repository,
checks out the pre-merge commit, runs the baseline linker, computes blast radius,
and compares against the actual changes in the PR.
"""

import os
import re
import sys
import argparse
import subprocess
import json
import traceback
from pathlib import Path
import networkx as nx

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.extraction import walk_and_extract_calls
from app.extraction.service_discovery import discover_services
from app.analysis.linker import CrossLayerLinker
from app.analysis.graph_builder import build_graph
from app.analysis.blast_radius import compute_blast_radius, normalise


def run_git(cmd: str, cwd: str) -> str:
    """Helper to run a git command and return stdout."""
    res = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def get_pr_commits(repo_dir: str, limit: int = 20) -> list:
    """Finds squash-merge PR commits on main branch using linear history."""
    log_output = run_git("git log --first-parent --oneline -n 150", repo_dir)
    commits = []
    
    # Match lines like: 5096a85b fix(deps): update dependency uuid to v14 [security] (#3332)
    # or general merge/squash syntax containing (#PR_NUMBER)
    pattern = re.compile(r"^([a-f0-9]+)\s+(.*?)\s+\(#(\d+)\)$")
    
    for line in log_output.splitlines():
        m = pattern.match(line)
        if m:
            commits.append({
                "hash": m.group(1),
                "title": m.group(2),
                "pr_number": int(m.group(3))
            })
            if len(commits) >= limit:
                break
                
    return commits


def get_modified_services(commit_hash: str, repo_dir: str) -> list:
    """Finds all service directories in src/ modified by a commit."""
    files_output = run_git(f"git diff-tree --no-commit-id --name-only -r {commit_hash}", repo_dir)
    services = set()
    
    for f in files_output.splitlines():
        f = f.strip()
        if not f:
            continue
        parts = f.split("/")
        if len(parts) > 1:
            # Check for microservices-demo structure: src/paymentservice/
            if parts[0] in ("src", "services", "apps", "cmd", "internal") and len(parts) > 2:
                # Exclude common config folders inside src if any
                svc_name = parts[1]
                if svc_name not in ("shared", "tools", "tests", "test"):
                    services.add(normalise(svc_name))
            else:
                services.add(normalise(parts[0]))
                
    return sorted(list(services))


def main():
    parser = argparse.ArgumentParser(description="ServiceScope Historical Validation on microservices-demo")
    parser.add_argument("--repo", type=str, required=True, help="Path to microservices-demo repository")
    parser.add_argument("--prs", type=int, default=20, help="Number of squash PR commits to validate")
    args = parser.parse_args()

    repo_dir = os.path.abspath(args.repo)
    if not os.path.exists(repo_dir) or not os.path.isdir(repo_dir):
        print(f"Error: Repository directory not found at {repo_dir}")
        sys.exit(1)

    # 1. Store original git state to restore at the end
    try:
        original_commit = run_git("git rev-parse HEAD", repo_dir)
        original_branch = run_git("git rev-parse --abbrev-ref HEAD", repo_dir)
        is_dirty = bool(run_git("git status --porcelain", repo_dir))
        if is_dirty:
            print("Warning: Repository is dirty. Stashing changes...")
            run_git("git stash", repo_dir)
    except Exception as e:
        print(f"Failed to inspect git repository state: {e}")
        sys.exit(1)

    print(f"============================================================")
    print(f"  ServiceScope Historical Validation Harness")
    print(f"  Target Repository : {repo_dir}")
    print(f"  PRs limit         : {args.prs}")
    print(f"============================================================\n")

    # 2. Get list of squash-merged PRs
    try:
        pr_commits = get_pr_commits(repo_dir, limit=args.prs)
    except Exception as e:
        print(f"Error retrieving PR commits: {e}")
        sys.exit(1)

    print(f"Found {len(pr_commits)} PR commits to process.\n")

    results = []
    
    # Stats trackers
    processed_count = 0
    predictions_made = 0
    co_change_hits = 0
    co_change_misses = 0

    try:
        for idx, pr in enumerate(pr_commits):
            pr_hash = pr["hash"]
            pr_num = pr["pr_number"]
            pr_title = pr["title"]
            
            # Identify services modified in this PR
            modified_services = get_modified_services(pr_hash, repo_dir)
            if len(modified_services) != 1:
                # PR must touch exactly one service directory to be processed
                continue
                
            processed_count += 1
            print(f"[{processed_count}] PR #{pr_num}: {pr_title}")
            print(f"    Modified services: {', '.join(modified_services)}")
            
            # Select primary service
            primary_svc = modified_services[0]
            co_changed = [s for s in modified_services[1:]]
            
            # 3. Checkout pre-merge commit (parent of squash-merge commit)
            pre_merge_commit = f"{pr_hash}^"
            print(f"    Checking out pre-merge commit: {pre_merge_commit}...")
            run_git(f"git checkout --quiet {pre_merge_commit}", repo_dir)
            
            try:
                # 4. Run call extraction & discover services
                discovered_svcs = discover_services(repo_dir)
                raw_calls = walk_and_extract_calls(repo_dir)
                
                # 5. Link calling dependencies
                linker = CrossLayerLinker(repo_dir, discovered_svcs)
                predictions = []
                
                for call in raw_calls:
                    caller = call.get("service", "unknown")
                    url = call.get("url", "")
                    file_path = call.get("file", "")
                    
                    # Filter spurious calls (same as harness.py)
                    norm_caller = normalise(caller)
                    clean_url = url
                    if url.startswith("<dynamic:") and url.endswith(">"):
                        clean_url = url[9:-1].strip()
                    norm_url = normalise(clean_url)
                    
                    is_spurious = (
                        norm_caller in ("shared", "reactnativeapp")
                        or "test" in file_path.lower()
                        or "conftest" in file_path.lower()
                        or norm_url in ("url", "requesturl", "httpclientbaseaddress", "channel", "badaddress", "svcaddr")
                    )
                    if is_spurious:
                        continue
                        
                    link_res = linker.resolve_call(caller, url)
                    if link_res:
                        callee, conf = link_res
                        predictions.append({
                            "caller": caller,
                            "callee": callee,
                            "confidence": conf
                        })
                        
                # 6. Build Graph and compute blast radius
                graph = build_graph(predictions)
                
                # Try to compute blast radius for primary service
                affected_set = []
                error_msg = None
                try:
                    radius_res = compute_blast_radius(graph, primary_svc, confidence_threshold=0.5)
                    affected_set = [item["service"] for item in radius_res["affected_services"]]
                except ValueError as ve:
                    error_msg = str(ve)
                except Exception as ex:
                    error_msg = f"Blast radius error: {ex}"
                    
                # Validate co-changing services
                hits = []
                misses = []
                for s in co_changed:
                    if normalise(s) in affected_set:
                        hits.append(s)
                        co_change_hits += 1
                    else:
                        misses.append(s)
                        co_change_misses += 1
                        
                results.append({
                    "pr_number": pr_num,
                    "title": pr_title,
                    "hash": pr_hash,
                    "primary_service": primary_svc,
                    "co_changed": co_changed,
                    "predicted_blast_radius": affected_set,
                    "hits": hits,
                    "misses": misses,
                    "error": error_msg
                })
                
                predictions_made += 1
                print(f"    Radius size: {len(affected_set)} services")
                if co_changed:
                    print(f"    Co-changes: hits={hits}, misses={misses}")
                if error_msg:
                    print(f"    Status    : {error_msg}")
                    
            except Exception as e:
                print(f"    Failed during analysis at commit: {e}")
                traceback.print_exc()
                
            print()
            
    finally:
        # 7. Restore repository to original branch/commit
        print("Restoring repository to original state...")
        try:
            run_git(f"git checkout --quiet {original_branch if original_branch != 'HEAD' else original_commit}", repo_dir)
            run_git("git checkout --quiet .", repo_dir) # Discard modifications if any
            if is_dirty:
                run_git("git stash pop --quiet", repo_dir)
            print("Repository restored successfully.")
        except Exception as e:
            print(f"Error restoring repository: {e}")

    # 8. Print Summary Table
    print(f"\n{'='*72}")
    print(f"  HISTORICAL VALIDATION SUMMARY")
    print(f"{'='*72}")
    print(f"  PR #  | Primary Service    | Co-changed   | Predicted Radius (Size)")
    print(f"  ------|--------------------|--------------|-------------------------")
    
    for r in results:
        co_str = ",".join(r["co_changed"]) if r["co_changed"] else "-"
        radius_str = f"{len(r['predicted_blast_radius'])} services"
        if r["error"]:
            radius_str = "Isolated/No calls"
        print(f"  {r['pr_number']:<5} | {r['primary_service']:<18} | {co_str:<12} | {radius_str}")
        
    print(f"{'='*72}")
    print(f"  Processed PR commits    : {processed_count}")
    print(f"  Analysis runs completed : {predictions_made}")
    if co_change_hits + co_change_misses > 0:
        precision = co_change_hits / (co_change_hits + co_change_misses)
        print(f"  Co-change prediction hits: {co_change_hits}")
        print(f"  Co-change prediction miss: {co_change_misses}")
        print(f"  Co-change Recall        : {precision:.3f}")
    else:
        print("  Co-change validation: N/A (all processed PRs touched single services)")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()

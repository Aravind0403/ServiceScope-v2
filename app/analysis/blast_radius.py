"""
Blast Radius Traversal
======================
Computes bidirectional transitive closure of service impact paths
propagating confidence scores using log-space Dijkstra.
"""

import math
import networkx as nx

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
            if name != suffix:
                name = name[:-len(suffix)]
            break  # Strip only one suffix to prevent recursive over-stripping
            
    return name


def compute_blast_radius(graph: nx.DiGraph, service_name: str, confidence_threshold: float = 0.5) -> dict:
    """
    Computes the bidirectional blast radius for a given service in a NetworkX dependency graph.
    
    Using log-space Dijkstra to find the path that maximizes the product of edge confidences.
    For each edge, the weight is -log(confidence).
    
    Returns:
        dict: {
            "service": str,
            "affected_services": [
                {
                    "service": str,
                    "confidence": float,
                    "hops": int,
                    "direction": str, ("outbound" | "inbound" | "both")
                    "path": list
                },
                ...
            ]
        }
    
    Raises:
        ValueError: If service_name is not found in the graph.
    """
    norm_start = normalise(service_name)
    if norm_start not in graph:
        available_services = sorted(list(graph.nodes))
        raise ValueError(
            f"Service '{service_name}' (normalized: '{norm_start}') not found in dependency graph. "
            f"Available services: {available_services}"
        )

    def run_dijkstra(g: nx.DiGraph, start_node: str, direction: str) -> dict:
        # direction: "outbound" means follow directed edges forward
        # direction: "inbound" means follow directed edges backward (reverse graph)
        target_graph = g if direction == "outbound" else g.reverse(copy=False)
        
        try:
            lengths, paths = nx.single_source_dijkstra(
                target_graph,
                source=start_node,
                weight="weight"
            )
        except (nx.NodeNotFound, KeyError):
            lengths, paths = {}, {}
            
        results = {}
        for target, dist in lengths.items():
            if target == start_node:
                continue
                
            confidence = math.exp(-dist)
            if confidence >= confidence_threshold:
                path_list = paths[target]
                if direction == "inbound":
                    display_path = path_list[::-1]
                else:
                    display_path = path_list
                    
                results[target] = {
                    "service": target,
                    "confidence": round(confidence, 4),
                    "hops": len(path_list) - 1,
                    "direction": direction,
                    "path": display_path
                }
        return results

    # Run in both directions
    outbound_results = run_dijkstra(graph, norm_start, "outbound")
    inbound_results = run_dijkstra(graph, norm_start, "inbound")
    
    # Merge and deduplicate
    merged = {}
    all_targets = set(outbound_results.keys()) | set(inbound_results.keys())
    for target in all_targets:
        out_item = outbound_results.get(target)
        in_item = inbound_results.get(target)
        
        if out_item and in_item:
            # Present in both directions
            # Choose the one with the higher confidence
            if out_item["confidence"] >= in_item["confidence"]:
                chosen = out_item.copy()
            else:
                chosen = in_item.copy()
            chosen["direction"] = "both"
            merged[target] = chosen
        elif out_item:
            merged[target] = out_item
        else:
            merged[target] = in_item
            
    # Sort results: confidence descending, then hops ascending, then name alphabetically
    sorted_affected = sorted(
        merged.values(),
        key=lambda x: (-x["confidence"], x["hops"], x["service"])
    )
    
    return {
        "service": norm_start,
        "affected_services": sorted_affected
    }

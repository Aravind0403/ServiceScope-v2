"""
Graph Builder Utility
=====================
Builds NetworkX DiGraph from database records or raw prediction dictionaries,
normalizing service names and collapsing duplicate edges with max confidence.
"""

import math
import networkx as nx
from app.analysis.blast_radius import normalise

def build_graph(dependencies: list) -> nx.DiGraph:
    """
    Builds a NetworkX DiGraph from a list of dependency dicts or DB model objects.
    
    Each dependency in the list must yield:
        - caller: str (or caller_service)
        - callee: str (or callee_service)
        - confidence: float
        - method: str (optional)
        - url: str (optional)
    
    Nodes are normalized. Multiple edges between the same node pair are collapsed,
    retaining the edge with the maximum confidence.
    For log-space Dijkstra, we assign the edge 'weight' = -log(confidence).
    """
    g = nx.DiGraph()
    
    # Track unique caller -> callee edges to select the highest confidence one
    raw_edges = {}
    
    for dep in dependencies:
        # Determine format (SQLAlchemy model, dict, or standard object)
        if hasattr(dep, "caller_service"):
            # SQLAlchemy InferredDependency model
            caller = dep.caller_service
            callee = dep.callee_service
            confidence = dep.confidence
            method = getattr(dep.extracted_call, "method", "get") if getattr(dep, "extracted_call", None) else "get"
            url = getattr(dep.extracted_call, "url", "") if getattr(dep, "extracted_call", None) else ""
        elif isinstance(dep, dict):
            caller = dep.get("caller") or dep.get("caller_service")
            callee = dep.get("callee") or dep.get("callee_service")
            confidence = dep.get("confidence")
            method = dep.get("method", "get")
            url = dep.get("url", "")
        else:
            # Fallback reflection
            caller = getattr(dep, "caller", None) or getattr(dep, "caller_service", None)
            callee = getattr(dep, "callee", None) or getattr(dep, "callee_service", None)
            confidence = getattr(dep, "confidence", 1.0)
            method = getattr(dep, "method", "get")
            url = getattr(dep, "url", "")
            
        if not caller or not callee:
            continue
            
        caller_norm = normalise(caller)
        callee_norm = normalise(callee)
        
        # Prevent self-loop dependencies from causing traversal issues, or normalize them
        if not caller_norm or not callee_norm:
            continue
            
        if confidence is None:
            confidence = 1.0
            
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (ValueError, TypeError):
            confidence = 0.5
            
        key = (caller_norm, callee_norm)
        if key not in raw_edges or confidence > raw_edges[key]["confidence"]:
            raw_edges[key] = {
                "confidence": confidence,
                "method": method,
                "url": url
            }
            
    # Add unique edges to NetworkX
    for (u, v), data in raw_edges.items():
        conf = data["confidence"]
        
        # Use log-space weight with epsilon clamping for numerical stability (avoids log(0.0))
        eps = 1e-6
        conf_clamped = max(eps, conf)
        weight = -math.log(conf_clamped)
        
        g.add_edge(
            u, v,
            confidence=conf,
            weight=weight,
            method=data["method"],
            url=data["url"]
        )
        
    return g

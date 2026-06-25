#!/usr/bin/env python3
"""
Cross-Layer Linker
==================
Matches dynamic call arguments (environment variables) and static URLs
to Kubernetes/Helm manifest environment values and known service targets.
Supports Go variable and connection bindings tracking.
"""

import os
from typing import Dict, List, Optional, Tuple
from app.analysis.blast_radius import normalise
from app.extraction.manifest_parser import extract_env_from_manifests

def extract_host(address: str) -> str:
    """Extracts the host component of an address or URL."""
    # Strip quotes and spacing
    address = address.strip(' "\'')
    # Remove protocol prefix if present
    if "://" in address:
        address = address.split("://", 1)[1]
    # Remove path, query, fragment
    if "/" in address:
        address = address.split("/", 1)[0]
    # Remove port
    if ":" in address:
        address = address.split(":", 1)[0]
    # Remove common Kubernetes service suffixes
    suffixes = [".svc.cluster.local", ".svc", ".cluster.local"]
    for suffix in suffixes:
        if address.endswith(suffix):
            address = address[:-len(suffix)]
            break
    # Split by namespace or dot qualifiers (e.g. paymentservice.default -> paymentservice)
    address = address.split(".")[0]
    return address.strip()

class CrossLayerLinker:
    def __init__(self, repo_dir: str, known_services: List[str]):
        self.repo_dir = repo_dir
        self.known_services = known_services
        # Build normalized lookup table for known services
        self.norm_to_service = {normalise(s): s for s in known_services if s}
        # Parse environments from manifests
        self.service_envs = extract_env_from_manifests(repo_dir)
        
        # Maps to resolve Go connection struct fields to their env var names
        self.go_env_map = {}
        self.go_conn_map = {}
        self._parse_go_variable_mappings()

    def _parse_go_variable_mappings(self):
        """Uses tree-sitter to parse Go files for mustMapEnv and mustConnGRPC bindings."""
        from tree_sitter_languages import get_parser
        try:
            parser = get_parser("go")
        except Exception as e:
            # Fallback if go parser not available
            print(f"Go parser not available: {e}")
            return

        def clean_go_identifier(text: str) -> str:
            text = text.strip()
            if text.startswith("&") or text.startswith("*"):
                text = text[1:]
            if "." in text:
                text = text.split(".")[-1]
            return text.strip()

        def get_node_text(node, code_bytes) -> str:
            return node.text.decode("utf-8", errors="ignore")

        def walk_node(node, code_bytes):
            if node.type == "call_expression":
                func_node = node.child_by_field_name("function")
                args_node = node.child_by_field_name("arguments")
                if func_node and args_node:
                    func_text = get_node_text(func_node, code_bytes)
                    args = [c for c in args_node.children if c.type not in ("(", ")", ",")]
                    
                    if func_text == "mustMapEnv" and len(args) >= 2:
                        var_name = clean_go_identifier(get_node_text(args[0], code_bytes))
                        env_name = get_node_text(args[1], code_bytes).strip("\"'`")
                        self.go_env_map[var_name] = env_name
                    elif func_text == "mustConnGRPC" and len(args) >= 3:
                        conn_name = clean_go_identifier(get_node_text(args[1], code_bytes))
                        addr_name = clean_go_identifier(get_node_text(args[2], code_bytes))
                        self.go_conn_map[conn_name] = addr_name

            for child in node.children:
                walk_node(child, code_bytes)

        for root, dirs, files in os.walk(self.repo_dir):
            dirs[:] = [d for d in dirs if d not in [
                '.git', 'vendor', 'node_modules', 'venv', '.venv'
            ]]
            for file in files:
                if file.endswith(".go"):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, "rb") as f:
                            code_bytes = f.read()
                        tree = parser.parse(code_bytes)
                        walk_node(tree.root_node, code_bytes)
                    except Exception as e:
                        print(f"Error parsing Go file {filepath} for bindings: {e}")

    def resolve_call(self, caller: str, url: str) -> Optional[Tuple[str, float]]:
        """
        Attempts to deterministically resolve a call URL (static or dynamic) to a callee service.
        Returns:
            Tuple[callee_service, confidence] if resolved, else None.
        """
        url = url.strip()
        address = None
        
        # Normalize caller name to match service_envs keys
        caller_key = caller
        for k in self.service_envs.keys():
            if normalise(k) == normalise(caller):
                caller_key = k
                break
        
        # 1. Check if it is a dynamic env var call: <dynamic:VAR_NAME>
        if url.startswith("<dynamic:") and url.endswith(">"):
            var_name = url[9:-1].strip()
            
            # Clean identifier to support field/receiver selectors (e.g. cs.shippingSvcConn -> shippingSvcConn)
            clean_name = var_name
            if "." in clean_name or clean_name.startswith(("&", "*")):
                if clean_name.startswith(("&", "*")):
                    clean_name = clean_name[1:]
                if "." in clean_name:
                    clean_name = clean_name.split(".")[-1]
            
            # Resolve Go connection variables
            if clean_name in self.go_conn_map:
                clean_name = self.go_conn_map[clean_name]
            if clean_name in self.go_env_map:
                var_name = self.go_env_map[clean_name]
            
            # Lookup env block for caller service
            caller_env = self.service_envs.get(caller_key, {})
            # Try case-insensitive env key lookup
            val = None
            if var_name in caller_env:
                val = caller_env[var_name]
            else:
                for k, v in caller_env.items():
                    if k.lower() == var_name.lower():
                        val = v
                        break
            
            if val:
                address = val
        else:
            # 2. Treat as static URL address
            address = url
            
        if not address:
            return None
            
        # Extract host and check against known services
        host = extract_host(address)
        if not host:
            return None
            
        norm_host = normalise(host)
        if norm_host in self.norm_to_service:
            callee = self.norm_to_service[norm_host]
            # Deterministic manifest-based mapping gets 1.0 confidence
            return callee, 1.0
            
        return None

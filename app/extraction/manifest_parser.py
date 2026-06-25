#!/usr/bin/env python3
"""
Kubernetes & Helm Manifest Parser
=================================
Scans the repository for K8s manifests and Helm templates, resolves variable bindings
using values.yaml, and extracts environment variables for each service container.
"""

import os
import re
import yaml
import base64
from typing import Dict, List, Any

# Helper to decode base64 Secret data
def decode_base64(s: str) -> str:
    try:
        # Standard base64 decoding
        if not s:
            return ""
        # Remove any padding issues
        s = s.strip()
        missing_padding = len(s) % 4
        if missing_padding:
            s += '=' * (4 - missing_padding)
        return base64.b64decode(s).decode("utf-8", errors="ignore")
    except Exception:
        return s

def get_nested_value(d: Dict[str, Any], path_parts: List[str]) -> Any:
    """Helper to traverse a nested dictionary case-insensitively."""
    curr = d
    for part in path_parts:
        if not isinstance(curr, dict):
            return None
        # Exact match first
        if part in curr:
            curr = curr[part]
        else:
            # Case-insensitive lookup
            found = False
            for k, v in curr.items():
                if k.lower() == part.lower():
                    curr = v
                    found = True
                    break
            if not found:
                return None
    return curr

def resolve_val_str(expr: str, context: Dict[str, Any]) -> Any:
    expr = expr.strip()
    if (expr.startswith('"') and expr.endswith('"')) or (expr.startswith("'") and expr.endswith("'")):
        return expr[1:-1]
    if expr.isdigit():
        return int(expr)
    if expr.lower() == "true":
        return True
    if expr.lower() == "false":
        return False
    if expr.startswith("."):
        parts = expr[1:].split(".")
        return get_nested_value(context, parts)
    return expr

def eval_condition(expr: str, context: Dict[str, Any]) -> bool:
    expr = expr.strip()
    # Handle "not <expr>"
    if expr.startswith("not "):
        return not eval_condition(expr[4:].strip(), context)
    # Handle "eq A B"
    if expr.startswith("eq "):
        parts = re.findall(r'"[^"]*"|\'[^\']*\'|\S+', expr)
        if len(parts) >= 3:
            val1 = resolve_val_str(parts[1], context)
            val2 = resolve_val_str(parts[2], context)
            return val1 == val2
    # Default: truthiness of the resolved expression
    resolved = resolve_val_str(expr, context)
    return bool(resolved)

def resolve_expression(expr: str, context: Dict[str, Any]) -> str:
    expr = expr.strip()
    if "|" in expr:
        parts = [p.strip() for p in expr.split("|")]
        val = resolve_expression_v(parts[0], context)
        for filter_part in parts[1:]:
            filter_parts = filter_part.split()
            filter_name = filter_parts[0]
            if filter_name == "default":
                default_expr = " ".join(filter_parts[1:])
                if not val:
                    val = resolve_expression_v(default_expr, context)
            elif filter_name == "quote":
                val = f'"{val}"'
        return val
    else:
        return resolve_expression_v(expr, context)

def resolve_expression_v(expr: str, context: Dict[str, Any]) -> str:
    expr = expr.strip()
    if expr.startswith("."):
        parts = expr[1:].split(".")
        val = get_nested_value(context, parts)
        if val is None:
            return ""
        return str(val)
    if (expr.startswith('"') and expr.endswith('"')) or (expr.startswith("'") and expr.endswith("'")):
        return expr[1:-1]
    return expr

def render_helm_template(content: str, context: Dict[str, Any]) -> str:
    """Pre-processes Helm templates line-by-line, handling simple if/else/end blocks."""
    lines = content.splitlines()
    output_lines = []
    
    # Active stack stores: (parent_active, condition_evaluated_to_true, outputting_now)
    # Initially outputting is enabled
    active_stack = []
    
    control_pattern = re.compile(r'\{\{-?\s*(if|else\s+if|else|end|with|define|block)\s*(.*?)\s*-?\}\}')
    tag_pattern = re.compile(r'\{\{-?\s*(.*?)\s*-?\}\}')
    
    for line in lines:
        # Check if line contains a control structure
        m_control = control_pattern.search(line)
        if m_control:
            keyword = m_control.group(1).strip()
            args = m_control.group(2).strip()
            
            parent_active = active_stack[-1][2] if active_stack else True
            
            if keyword == "if" or keyword == "with":
                val = eval_condition(args, context)
                outputting_now = parent_active and val
                active_stack.append((parent_active, val, outputting_now))
                output_lines.append(f"# {line}  # antg-ctrl-start")
                continue
                
            elif keyword.startswith("else"):
                if not active_stack:
                    output_lines.append(f"# {line}  # antg-ctrl-else-unmatched")
                    continue
                p_act, prev_val, _ = active_stack.pop()
                if prev_val:
                    # Previous branch in this if chain was executed, so don't execute this one
                    active_stack.append((p_act, True, False))
                else:
                    if "if" in keyword: # else if
                        val = eval_condition(args, context)
                        outputting_now = p_act and val
                        active_stack.append((p_act, val, outputting_now))
                    else: # else
                        outputting_now = p_act
                        active_stack.append((p_act, True, outputting_now))
                output_lines.append(f"# {line}  # antg-ctrl-else")
                continue
                
            elif keyword == "end":
                if active_stack:
                    active_stack.pop()
                output_lines.append(f"# {line}  # antg-ctrl-end")
                continue
                
            elif keyword in ("define", "block"):
                # Always skip definitions
                active_stack.append((parent_active, False, False))
                output_lines.append(f"# {line}  # antg-ctrl-def-start")
                continue
        
        # Check outputting state
        is_outputting = active_stack[-1][2] if active_stack else True
        if not is_outputting:
            # We are in an inactive block, skip output or comment it out
            output_lines.append(f"# {line}  # antg-skipped")
            continue
            
        # Ignore lines containing toYaml or include/template/nindent on their own
        if "toYaml" in line or "include" in line or "nindent" in line or "tpl" in line:
            output_lines.append(f"# {line}  # antg-skipped-complex")
            continue
            
        # Substitute non-control tag variables
        new_line = line
        matches = list(tag_pattern.finditer(line))
        # Iterate backwards to replace safely without shifting offsets
        for m in reversed(matches):
            expr = m.group(1).strip()
            # If it looks like a variable reference or expression, resolve it
            if not expr.startswith(("if", "else", "end", "with", "define", "block", "range")):
                resolved = resolve_expression(expr, context)
                start, end = m.span()
                new_line = new_line[:start] + resolved + new_line[end:]
                
        output_lines.append(new_line)
        
    return "\n".join(output_lines)

def parse_yaml_file(filepath: str, is_helm_template: bool, context: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        if is_helm_template:
            content = render_helm_template(content, context or {})
            
        # Parse all documents in the YAML stream
        docs = list(yaml.safe_load_all(content))
        return [doc for doc in docs if doc and isinstance(doc, dict)]
    except Exception as e:
        print(f"Error parsing K8s manifest {filepath}: {e}")
        return []

def extract_env_from_manifests(repo_dir: str) -> Dict[str, Dict[str, str]]:
    """
    Scans the repository for K8s manifests and Helm charts,
    resolving variable mappings, and extracts environment variables
    for each microservice.
    """
    config_maps = {}
    secrets = {}
    resources = []
    
    # 1. Locate all Chart directories and files
    chart_dirs = {} # path -> (values, chart_meta)
    
    for root, dirs, files in os.walk(repo_dir):
        # Skip common non-source/non-manifest directories
        dirs[:] = [d for d in dirs if d not in [
            '.git', '.github', 'node_modules', 'venv', '.venv', 'tests', 'bin', 'obj', 'pkg'
        ]]
        
        if "Chart.yaml" in files:
            chart_path = os.path.join(root, "Chart.yaml")
            values_path = os.path.join(root, "values.yaml")
            
            # Load metadata and default values
            chart_meta = {}
            values_dict = {}
            
            try:
                with open(chart_path, "r", encoding="utf-8") as f:
                    chart_meta = yaml.safe_load(f) or {}
            except Exception:
                pass
                
            try:
                if os.path.exists(values_path):
                    with open(values_path, "r", encoding="utf-8") as f:
                        values_dict = yaml.safe_load(f) or {}
            except Exception:
                pass
                
            chart_dirs[root] = {
                "values": values_dict,
                "chart": chart_meta
            }

    # 2. Parse all K8s manifests
    processed_files = set()
    
    # Process Helm templates first
    for chart_dir, data in chart_dirs.items():
        templates_dir = os.path.join(chart_dir, "templates")
        if not os.path.exists(templates_dir):
            continue
            
        context = {
            "Values": data["values"],
            "Chart": data["chart"],
            "Release": {
                "Name": data["chart"].get("name", "release-name"),
                "Namespace": "default"
            }
        }
        
        for root, _, files in os.walk(templates_dir):
            for file in files:
                if file.endswith((".yaml", ".yml")):
                    filepath = os.path.join(root, file)
                    processed_files.add(filepath)
                    docs = parse_yaml_file(filepath, is_helm_template=True, context=context)
                    resources.extend(docs)
                    
    # Process raw K8s manifests (any YAML file not inside templates or charts)
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in [
            '.git', '.github', 'node_modules', 'venv', '.venv', 'tests', 'bin', 'obj', 'pkg'
        ]]
        
        # Don't process templates again
        if any(root.startswith(os.path.join(cd, "templates")) for cd in chart_dirs):
            continue
        if any(root.startswith(os.path.join(cd, "charts")) for cd in chart_dirs):
            continue
            
        for file in files:
            if file.endswith((".yaml", ".yml")):
                filepath = os.path.join(root, file)
                if filepath in processed_files:
                    continue
                # Skip files like skaffold.yaml, cloudbuild.yaml, etc. unless they look like manifests
                if file in ("skaffold.yaml", "cloudbuild.yaml", "values.yaml", "Chart.yaml"):
                    continue
                docs = parse_yaml_file(filepath, is_helm_template=False)
                resources.extend(docs)

    # 3. First pass: Collect ConfigMaps and Secrets
    for doc in resources:
        if not doc or not isinstance(doc, dict):
            continue
        kind = doc.get("kind")
        metadata = doc.get("metadata", {})
        name = metadata.get("name")
        if not name or not kind:
            continue
            
        if kind == "ConfigMap":
            data = doc.get("data", {})
            config_maps[name] = data
        elif kind == "Secret":
            sec_data = {}
            # Base64 data
            for k, v in doc.get("data", {}).items():
                if v:
                    sec_data[k] = decode_base64(str(v))
            # String data (direct raw text)
            for k, v in doc.get("stringData", {}).items():
                if v:
                    sec_data[k] = str(v)
            secrets[name] = sec_data

    # 4. Second pass: Extract environments from Deployments/StatefulSets/DaemonSets/Jobs/Pods
    service_environments = {}
    
    for doc in resources:
        if not doc or not isinstance(doc, dict):
            continue
        kind = doc.get("kind")
        metadata = doc.get("metadata", {})
        name = metadata.get("name")
        if not name or not kind:
            continue
            
        # Target controllers that contain pod templates or container lists
        containers = []
        if kind in ("Deployment", "StatefulSet", "DaemonSet", "Job"):
            spec = doc.get("spec", {})
            template = spec.get("template", {})
            pod_spec = template.get("spec", {})
            containers = pod_spec.get("containers", [])
        elif kind == "CronJob":
            spec = doc.get("spec", {})
            job_template = spec.get("jobTemplate", {})
            job_spec = job_template.get("spec", {})
            template = job_spec.get("template", {})
            pod_spec = template.get("spec", {})
            containers = pod_spec.get("containers", [])
        elif kind == "Pod":
            spec = doc.get("spec", {})
            containers = spec.get("containers", [])
            
        if not containers:
            continue
            
        env_dict = {}
        for container in containers:
            # 4a. Process envFrom
            env_from = container.get("envFrom", [])
            for ef in env_from:
                if "configMapRef" in ef:
                    ref_name = ef["configMapRef"].get("name")
                    if ref_name in config_maps:
                        env_dict.update(config_maps[ref_name])
                elif "secretRef" in ef:
                    ref_name = ef["secretRef"].get("name")
                    if ref_name in secrets:
                        env_dict.update(secrets[ref_name])
                        
            # 4b. Process env list
            env_list = container.get("env", [])
            if not isinstance(env_list, list):
                continue
            for item in env_list:
                if not isinstance(item, dict) or "name" not in item:
                    continue
                var_name = item["name"]
                
                if "value" in item:
                    env_dict[var_name] = str(item["value"])
                elif "valueFrom" in item:
                    vf = item["valueFrom"]
                    if "configMapKeyRef" in vf:
                        ref = vf["configMapKeyRef"]
                        cm_name = ref.get("name")
                        cm_key = ref.get("key")
                        env_dict[var_name] = config_maps.get(cm_name, {}).get(cm_key, f"<configmap:{cm_name}:{cm_key}>")
                    elif "secretKeyRef" in vf:
                        ref = vf["secretKeyRef"]
                        sec_name = ref.get("name")
                        sec_key = ref.get("key")
                        env_dict[var_name] = secrets.get(sec_name, {}).get(sec_key, f"<secret:{sec_name}:{sec_key}>")
                    else:
                        env_dict[var_name] = "<dynamic:valueFrom>"
                        
        if env_dict:
            # Merge if the service environment already exists (e.g. multi-container or multiple files)
            if name in service_environments:
                service_environments[name].update(env_dict)
            else:
                service_environments[name] = env_dict

    return service_environments

#!/usr/bin/env python3
"""
Polyglot AST Call Extractor using Tree-sitter
=============================================
Walks the codebase and extracts API / gRPC connection call sites
for Java, Node.js/TypeScript, and C# (.NET).
"""

import os
import re
from typing import List, Dict
from tree_sitter_languages import get_parser

def extract_calls_from_source(code: str, filepath: str, lang: str, service: str) -> List[Dict]:
    calls = []
    try:
        parser = get_parser(lang)
        tree = parser.parse(bytes(code, "utf-8"))
    except Exception as e:
        print(f"Error parsing {filepath} with tree-sitter-{lang}: {e}")
        return []

    def get_node_text(node) -> str:
        return node.text.decode("utf-8", errors="ignore")

    var_assignments = {}

    # Pre-pass to find variable declarations and assignments
    def find_assignments(node):
        if node.type == "variable_declarator":
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            # C# uses identifier and equals_value_clause
            if not name_node or not value_node:
                c_ident = None
                c_val = None
                for c in node.children:
                    if c.type == "identifier":
                        c_ident = c
                    elif c.type == "equals_value_clause":
                        for cc in c.children:
                            if cc.type not in ("=", "value"):
                                c_val = cc
                if c_ident and c_val:
                    var_assignments[get_node_text(c_ident)] = c_val
            else:
                var_assignments[get_node_text(name_node)] = value_node
                
        for child in node.children:
            find_assignments(child)

    find_assignments(tree.root_node)

    def resolve_node(arg_node):
        if arg_node.type == "identifier":
            name = get_node_text(arg_node)
            if name in var_assignments:
                val_node = var_assignments[name]
                val_text = get_node_text(val_node)
                is_env = any(k in val_text for k in ("getenv", "process.env", "GetEnvironmentVariable"))
                is_lit = val_node.type in ("string_literal", "string", "basic_string_literal")
                if is_env or is_lit:
                    return val_node
        return arg_node

    def parse_url_argument(arg_node):
        arg_node = resolve_node(arg_node)
        arg_text = get_node_text(arg_node)
        
        # Check Java env: System.getenv("ENV_VAR")
        if "System.getenv" in arg_text:
            m = re.search(r'System\.getenv\(\s*["\']([^"\']+)["\']\s*\)', arg_text)
            if m:
                return f"<dynamic:{m.group(1)}>", True, arg_text
                
        # Check JS/TS env: process.env.ENV_VAR or process.env['ENV_VAR']
        if "process.env" in arg_text:
            m = re.search(r'process\.env(?:(?:\.([A-Za-z0-9_]+))|\[\s*["\']([^"\']+)["\']\s*\])', arg_text)
            if m:
                var_name = m.group(1) or m.group(2)
                return f"<dynamic:{var_name}>", True, arg_text
                
        # Check C# env: Environment.GetEnvironmentVariable("ENV_VAR")
        if "GetEnvironmentVariable" in arg_text:
            m = re.search(r'GetEnvironmentVariable\(\s*["\']([^"\']+)["\']\s*\)', arg_text)
            if m:
                return f"<dynamic:{m.group(1)}>", True, arg_text

        # Check template string or general interpolation: `${SHIPPING_ADDR}/get-quote`
        m = re.search(r'\$\{(\w+)\}', arg_text)
        if m:
            var_name = m.group(1)
            return f"<dynamic:{var_name}>", True, arg_text

        # Basic string check
        if arg_node.type in ("string_literal", "string", "basic_string_literal"):
            val = arg_text.strip("\"'")
            return val, False, ""
            
        # Default to dynamic
        return f"<dynamic:{arg_text}>", True, arg_text

    def visitor(node):
        node_type = node.type
        
        # Helper to find children by type
        def find_child_by_type(n, t):
            for c in n.children:
                if c.type == t:
                    return c
            return None

        # -------------------------------------------------------------------
        # JAVA PARSING
        # -------------------------------------------------------------------
        if lang == "java":
            if node_type == "method_invocation":
                name_node = node.child_by_field_name("name")
                arguments_node = node.child_by_field_name("arguments")
                
                if name_node and arguments_node:
                    method_name = get_node_text(name_node)
                    args = [c for c in arguments_node.children if c.type not in ("(", ")", ",")]
                    
                    # RestTemplate: getForObject, postForEntity, etc.
                    if method_name in ("getForObject", "getForEntity", "postForObject", "postForEntity", "exchange"):
                        if len(args) >= 1:
                            url, is_dyn, raw_expr = parse_url_argument(args[0])
                            line = node.start_point[0] + 1
                            calls.append({
                                "method": method_name.lower().replace("forobject", "").replace("forentity", ""),
                                "url": url,
                                "line": line,
                                "url_is_dynamic": is_dyn,
                                "url_raw_expr": raw_expr if is_dyn else "",
                                "file": filepath,
                                "service": service
                            })
                            
                    # WebClient / HttpClient: uri()
                    elif method_name == "uri":
                        if len(args) >= 1:
                            url, is_dyn, raw_expr = parse_url_argument(args[0])
                            if is_dyn or url.startswith("http") or ":" in url:
                                line = node.start_point[0] + 1
                                calls.append({
                                    "method": "get",
                                    "url": url,
                                    "line": line,
                                    "url_is_dynamic": is_dyn,
                                    "url_raw_expr": raw_expr if is_dyn else "",
                                    "file": filepath,
                                    "service": service
                                })
                                
                    # gRPC newBlockingStub, newStub
                    elif method_name in ("newBlockingStub", "newStub", "newFutureStub"):
                        if len(args) >= 1:
                            url, is_dyn, raw_expr = parse_url_argument(args[0])
                            line = node.start_point[0] + 1
                            calls.append({
                                "method": "grpc",
                                "url": url,
                                "line": line,
                                "url_is_dynamic": is_dyn,
                                "url_raw_expr": raw_expr if is_dyn else "",
                                "file": filepath,
                                "service": service
                            })

        # -------------------------------------------------------------------
        # JAVASCRIPT / TYPESCRIPT PARSING
        # -------------------------------------------------------------------
        elif lang in ("javascript", "typescript"):
            # axios.get, fetch(url)
            if node_type == "call_expression":
                func_node = node.child_by_field_name("function")
                arguments_node = node.child_by_field_name("arguments")
                
                if func_node and arguments_node:
                    func_text = get_node_text(func_node)
                    args = [c for c in arguments_node.children if c.type not in ("(", ")", ",")]
                    
                    # fetch(url)
                    if func_text == "fetch":
                        if len(args) >= 1:
                            url, is_dyn, raw_expr = parse_url_argument(args[0])
                            line = node.start_point[0] + 1
                            calls.append({
                                "method": "get",
                                "url": url,
                                "line": line,
                                "url_is_dynamic": is_dyn,
                                "url_raw_expr": raw_expr if is_dyn else "",
                                "file": filepath,
                                "service": service
                            })
                            
                    # axios.get, axios.post
                    elif func_text.startswith("axios."):
                        method_name = func_text.split(".")[-1].lower()
                        if method_name in ("get", "post", "put", "delete", "patch") and len(args) >= 1:
                            url, is_dyn, raw_expr = parse_url_argument(args[0])
                            line = node.start_point[0] + 1
                            calls.append({
                                "method": method_name,
                                "url": url,
                                "line": line,
                                "url_is_dynamic": is_dyn,
                                "url_raw_expr": raw_expr if is_dyn else "",
                                "file": filepath,
                                "service": service
                            })

            # gRPC clients: new Client(addr)
            elif node_type == "new_expression":
                constructor_node = node.child_by_field_name("constructor")
                arguments_node = node.child_by_field_name("arguments")
                
                if constructor_node and arguments_node:
                    func_text = get_node_text(constructor_node)
                    args = [c for c in arguments_node.children if c.type not in ("(", ")", ",")]
                    if "Client" in func_text:
                        if len(args) >= 1:
                            url, is_dyn, raw_expr = parse_url_argument(args[0])
                            if is_dyn or ":" in url or url.startswith("localhost") or url.endswith("50051"):
                                line = node.start_point[0] + 1
                                calls.append({
                                    "method": "grpc",
                                    "url": url,
                                    "line": line,
                                    "url_is_dynamic": is_dyn,
                                    "url_raw_expr": raw_expr if is_dyn else "",
                                    "file": filepath,
                                    "service": service
                                })

        # -------------------------------------------------------------------
        # C# PARSING
        # -------------------------------------------------------------------
        elif lang == "c_sharp":
            # In invocation_expression, find expression and argument_list (which is of type argument_list)
            if node_type == "invocation_expression":
                expr_node = node.child_by_field_name("expression")
                if not expr_node and node.children:
                    expr_node = node.children[0]
                argument_list = find_child_by_type(node, "argument_list")
                
                if expr_node and argument_list:
                    expr_text = get_node_text(expr_node)
                    c_args = []
                    for c in argument_list.children:
                        if c.type == "argument":
                            val_node = c.children[0] if c.children else c
                            c_args.append(val_node)
                    if not c_args:
                        c_args = [c for c in argument_list.children if c.type not in ("(", ")", ",")]
                        
                    # HttpClient: GetAsync, PostAsync
                    if any(m in expr_text for m in (".GetAsync", ".PostAsync", ".PutAsync", ".DeleteAsync", ".SendAsync")):
                        method = "get"
                        for m in ["Get", "Post", "Put", "Delete", "Send"]:
                            if m in expr_text:
                                method = m.lower()
                                break
                        if len(c_args) >= 1:
                            url, is_dyn, raw_expr = parse_url_argument(c_args[0])
                            line = node.start_point[0] + 1
                            calls.append({
                                "method": method,
                                "url": url,
                                "line": line,
                                "url_is_dynamic": is_dyn,
                                "url_raw_expr": raw_expr if is_dyn else "",
                                "file": filepath,
                                "service": service
                            })
                            
                    # GrpcChannel.ForAddress(url)
                    elif "GrpcChannel.ForAddress" in expr_text:
                        if len(c_args) >= 1:
                            url, is_dyn, raw_expr = parse_url_argument(c_args[0])
                            line = node.start_point[0] + 1
                            calls.append({
                                "method": "grpc",
                                "url": url,
                                "line": line,
                                "url_is_dynamic": is_dyn,
                                "url_raw_expr": raw_expr if is_dyn else "",
                                "file": filepath,
                                "service": service
                            })

            # Handle C# object creation (new HelloServiceClient(channel))
            elif node_type == "object_creation_expression":
                type_node = node.child_by_field_name("type")
                if not type_node:
                    for c in node.children:
                        if c.type in ("identifier", "generic_name", "qualified_name", "type"):
                            type_node = c
                            break
                argument_list = find_child_by_type(node, "argument_list")
                if type_node and argument_list:
                    type_text = get_node_text(type_node)
                    if "Client" in type_text:
                        c_args = []
                        for c in argument_list.children:
                            if c.type == "argument":
                                val_node = c.children[0] if c.children else c
                                c_args.append(val_node)
                        if not c_args:
                            c_args = [c for c in argument_list.children if c.type not in ("(", ")", ",")]
                        if len(c_args) >= 1:
                            url, is_dyn, raw_expr = parse_url_argument(c_args[0])
                            line = node.start_point[0] + 1
                            calls.append({
                                "method": "grpc",
                                "url": url,
                                "line": line,
                                "url_is_dynamic": is_dyn,
                                "url_raw_expr": raw_expr if is_dyn else "",
                                "file": filepath,
                                "service": service
                            })

        for child in node.children:
            visitor(child)

    visitor(tree.root_node)
    return calls

def walk_and_extract_polyglot_calls(base_dir: str) -> List[Dict]:
    all_calls = []
    
    # Map extensions to tree-sitter language names
    extension_map = {
        ".java": "java",
        ".js": "javascript",
        ".ts": "typescript",
        ".cs": "c_sharp"
    }

    for root, dirs, files in os.walk(base_dir):
        # Skip common non-source directories
        dirs[:] = [d for d in dirs if d not in [
            '.git', '__pycache__', '.venv', 'venv', 'node_modules', 'migrations', 'bin', 'obj'
        ]]

        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in extension_map:
                lang = extension_map[ext]
                full_path = os.path.join(root, file)
                
                # Service name logic
                rel_path = os.path.relpath(full_path, base_dir)
                parts = rel_path.split(os.sep)
                service = "unknown"
                if parts:
                    if parts[0] in ["src", "services", "apps", "cmd", "internal"] and len(parts) > 1:
                        service = parts[1]
                    else:
                        service = parts[0]
                
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        code = f.read()
                    file_calls = extract_calls_from_source(code, rel_path, lang, service)
                    all_calls.extend(file_calls)
                except Exception as e:
                    print(f"Error reading file {full_path}: {e}")

    return all_calls

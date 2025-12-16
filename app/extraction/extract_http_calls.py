"""
HTTP Call Extractor

Extract HTTP API calls from Python source code using AST analysis.
"""

import os
import ast
from typing import List, Dict


def extract_http_calls_from_file(file_path: str) -> List[Dict]:
    """
    Extract HTTP calls from a single Python file.

    Args:
        file_path: Path to Python file

    Returns:
        List of HTTP call dictionaries
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            tree = ast.parse(content, filename=file_path)
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
        return []

    calls = []

    class APICallVisitor(ast.NodeVisitor):
        def visit_Call(self, node):
            try:
                # Pattern 1: requests.get/post/etc
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "requests":
                        if node.func.attr in ["get", "post", "put", "delete", "patch"]:
                            if node.args and isinstance(node.args[0], ast.Constant):
                                calls.append({
                                    "method": node.func.attr,
                                    "url": node.args[0].value,
                                    "line": node.lineno
                                })

                    # Pattern 2: httpx.get/post/etc
                    elif isinstance(node.func.value, ast.Name) and node.func.value.id == "httpx":
                        if node.func.attr in ["get", "post", "put", "delete", "patch"]:
                            if node.args and isinstance(node.args[0], ast.Constant):
                                calls.append({
                                    "method": node.func.attr,
                                    "url": node.args[0].value,
                                    "line": node.lineno
                                })

                    # Pattern 3: client.get/post (for requests.Session or httpx.Client)
                    elif node.func.attr in ["get", "post", "put", "delete", "patch"]:
                        if node.args and isinstance(node.args[0], ast.Constant):
                            url = node.args[0].value
                            if isinstance(url, str) and (url.startswith("http") or "/" in url):
                                calls.append({
                                    "method": node.func.attr,
                                    "url": url,
                                    "line": node.lineno
                                })
            except Exception as e:
                print(f"Error visiting node: {e}")
            self.generic_visit(node)

    visitor = APICallVisitor()
    visitor.visit(tree)

    print(f"Found {len(calls)} calls in {file_path}")
    return calls


def walk_and_extract_calls(base_dir: str) -> List[Dict]:
    """
    Walk directory tree and extract HTTP calls from all Python files.

    Args:
        base_dir: Root directory to scan

    Returns:
        List of HTTP call dictionaries with metadata
    """
    all_calls = []

    for root, dirs, files in os.walk(base_dir):
        # Skip common non-source directories
        dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', '.venv', 'venv', 'node_modules']]

        for file in files:
            if file.endswith(".py"):
                full_path = os.path.join(root, file)
                file_calls = extract_http_calls_from_file(full_path)

                for call in file_calls:
                    rel_path = os.path.relpath(full_path, base_dir)
                    parts = rel_path.split(os.sep)

                    call["file"] = rel_path
                    call["service"] = parts[0] if parts else "unknown"
                    all_calls.append(call)

    return all_calls
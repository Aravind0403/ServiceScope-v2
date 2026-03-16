"""
HTTP Call Extractor

Extract HTTP API calls from Python source code using AST analysis.

Patterns detected:
  1. requests.get/post/put/delete/patch(url)
  2. httpx.get/post/put/delete/patch(url)
  3. client.get/post/...(url)  — only when url starts with "http" (prevents
     FastAPI decorator false positives like @router.get("/path"))
  4. aiohttp: await session.get/post/...(url)
  5. urllib.request.urlopen(url)
  6. f-string URLs  — captured as dynamic, static prefix extracted
  7. Variable URLs  — captured as dynamic, variable name stored
  8. URL concatenation  — captured as dynamic, left-hand constant stored
"""

import os
import ast
from typing import List, Dict

HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


def _extract_fstring_prefix(node: ast.JoinedStr) -> str:
    """Return the leading constant portion of an f-string, e.g. 'http://api/' from f'http://api/{id}'."""
    parts = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            break
    return "".join(parts)


def extract_http_calls_from_file(file_path: str) -> List[Dict]:
    """
    Extract HTTP calls from a single Python file.

    Args:
        file_path: Path to Python file

    Returns:
        List of HTTP call dictionaries with keys:
          method, url, line, url_is_dynamic (bool), url_raw_expr (str, optional)
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
                if isinstance(node.func, ast.Attribute):
                    obj = node.func.value
                    method = node.func.attr

                    if method not in HTTP_METHODS:
                        self.generic_visit(node)
                        return

                    # Pattern 1: requests.get/post/etc
                    if isinstance(obj, ast.Name) and obj.id == "requests":
                        self._capture(node, method)

                    # Pattern 2: httpx.get/post/etc
                    elif isinstance(obj, ast.Name) and obj.id == "httpx":
                        self._capture(node, method)

                    # Pattern 5: urllib.request.urlopen  (handled separately below)

                    # Pattern 3: client.get/post (requests.Session, httpx.Client, aiohttp)
                    # Guard: only match absolute URLs (http/https) to avoid catching
                    # FastAPI route decorators like @router.get("/path").
                    else:
                        self._capture(node, method, require_absolute=True)

                # Pattern 5: urllib.request.urlopen(url)
                elif isinstance(node.func, ast.Attribute):
                    pass  # handled above

                # urllib.request.urlopen as a dotted call
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "urlopen"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "request"
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id == "urllib"
                ):
                    self._capture(node, "get")  # urlopen is always GET-like

            except Exception as e:
                print(f"Error visiting node: {e}")
            self.generic_visit(node)

        def _capture(self, node: ast.Call, method: str, require_absolute: bool = False):
            """Extract a call record from a Call AST node."""
            if not node.args:
                return
            arg = node.args[0]

            # Constant string URL
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                url = arg.value
                if require_absolute and not url.startswith("http"):
                    return
                calls.append({
                    "method": method,
                    "url": url,
                    "line": node.lineno,
                    "url_is_dynamic": False,
                })

            # Pattern 6: f-string URL — extract static prefix
            elif isinstance(arg, ast.JoinedStr):
                prefix = _extract_fstring_prefix(arg)
                if not prefix.startswith("http"):
                    return
                calls.append({
                    "method": method,
                    "url": prefix,
                    "line": node.lineno,
                    "url_is_dynamic": True,
                    "url_raw_expr": ast.unparse(arg),
                })

            # Pattern 7: Variable URL — store variable name
            elif isinstance(arg, ast.Name):
                calls.append({
                    "method": method,
                    "url": f"<dynamic:{arg.id}>",
                    "line": node.lineno,
                    "url_is_dynamic": True,
                    "url_raw_expr": arg.id,
                })

            # Pattern 8: URL concatenation — BASE_URL + "/path"
            elif isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
                if isinstance(arg.left, ast.Constant) and isinstance(arg.left.value, str):
                    left = arg.left.value
                    if left.startswith("http"):
                        calls.append({
                            "method": method,
                            "url": left,
                            "line": node.lineno,
                            "url_is_dynamic": True,
                            "url_raw_expr": ast.unparse(arg),
                        })
                elif isinstance(arg.left, ast.Name):
                    calls.append({
                        "method": method,
                        "url": f"<dynamic:{arg.left.id}>",
                        "line": node.lineno,
                        "url_is_dynamic": True,
                        "url_raw_expr": ast.unparse(arg),
                    })

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
        dirs[:] = [d for d in dirs if d not in [
            '.git', '__pycache__', '.venv', 'venv', 'node_modules', 'migrations'
        ]]

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

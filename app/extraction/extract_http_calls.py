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


def is_http_client_name(name: str) -> bool:
    """Return True if the receiver variable name looks like an HTTP client or session."""
    name_lower = name.lower()
    return (
        name_lower in ("client", "session", "api", "conn", "request", "http")
        or name_lower.endswith(("_client", "_session", "_api", "_conn"))
        or "http" in name_lower
        or "client." in name_lower
        or "session." in name_lower
    )


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

    # Pre-pass to find local variable assignments to environment variables
    var_envs = {}
    
    class AssignmentVisitor(ast.NodeVisitor):
        def visit_Assign(self, node):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                var_name = node.targets[0].id
                env_var = self._get_env_var(node.value)
                if env_var:
                    var_envs[var_name] = env_var
            self.generic_visit(node)
            
        def visit_AnnAssign(self, node):
            if isinstance(node.target, ast.Name) and node.value:
                var_name = node.target.id
                env_var = self._get_env_var(node.value)
                if env_var:
                    var_envs[var_name] = env_var
            self.generic_visit(node)

        def _get_env_var(self, val):
            # 1. os.environ.get('VAR') or os.getenv('VAR')
            if isinstance(val, ast.Call):
                func = val.func
                if isinstance(func, ast.Attribute):
                    if (
                        func.attr == "get"
                        and isinstance(func.value, ast.Attribute)
                        and func.value.attr == "environ"
                        and isinstance(func.value.value, ast.Name)
                        and func.value.value.id == "os"
                    ):
                        if val.args and isinstance(val.args[0], ast.Constant) and isinstance(val.args[0].value, str):
                            return val.args[0].value
                elif isinstance(func, ast.Name) and func.id == "getenv":
                    if val.args and isinstance(val.args[0], ast.Constant) and isinstance(val.args[0].value, str):
                        return val.args[0].value
                elif isinstance(func, ast.Attribute) and func.attr == "getenv":
                    if (
                        isinstance(func.value, ast.Name)
                        and func.value.id == "os"
                    ):
                        if val.args and isinstance(val.args[0], ast.Constant) and isinstance(val.args[0].value, str):
                            return val.args[0].value
            # 2. os.environ['VAR']
            elif isinstance(val, ast.Subscript):
                if (
                    isinstance(val.value, ast.Attribute)
                    and val.value.attr == "environ"
                    and isinstance(val.value.value, ast.Name)
                    and val.value.value.id == "os"
                ):
                    if isinstance(val.slice, ast.Constant) and isinstance(val.slice.value, str):
                        return val.slice.value
            return None

    # Run the pre-pass
    assign_visitor = AssignmentVisitor()
    assign_visitor.visit(tree)

    class APICallVisitor(ast.NodeVisitor):
        def visit_Call(self, node):
            try:
                if isinstance(node.func, ast.Attribute):
                    # Pattern 5: urllib.request.urlopen as a dotted call
                    if (
                        node.func.attr == "urlopen"
                        and isinstance(node.func.value, ast.Attribute)
                        and node.func.value.attr == "request"
                        and isinstance(node.func.value.value, ast.Name)
                        and node.func.value.value.id == "urllib"
                    ):
                        self._capture(node, "get", require_absolute=True)  # urlopen is always GET-like
                    else:
                        obj = node.func.value
                        method = node.func.attr

                        if method in HTTP_METHODS:
                            # Pattern 1: requests.get/post/etc
                            if isinstance(obj, ast.Name) and obj.id == "requests":
                                self._capture(node, method, require_absolute=True)

                            # Pattern 2: httpx.get/post/etc
                            elif isinstance(obj, ast.Name) and obj.id == "httpx":
                                self._capture(node, method, require_absolute=True)

                            # Pattern 3: client.get/post (requests.Session, httpx.Client, aiohttp)
                            # Guard: only match absolute URLs (http/https) to avoid catching
                            # FastAPI route decorators like @router.get("/path").
                            else:
                                receiver_name = ast.unparse(obj)
                                if is_http_client_name(receiver_name):
                                    self._capture(node, method, require_absolute=True)
                        elif isinstance(obj, ast.Name) and obj.id == "grpc" and method in ("insecure_channel", "secure_channel"):
                            self._capture(node, "grpc", require_absolute=False)
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
                url_val = f"<dynamic:{arg.id}>"
                if arg.id in var_envs:
                    url_val = f"<dynamic:{var_envs[arg.id]}>"
                calls.append({
                    "method": method,
                    "url": url_val,
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
                    url_val = f"<dynamic:{arg.left.id}>"
                    if arg.left.id in var_envs:
                        url_val = f"<dynamic:{var_envs[arg.left.id]}>"
                    calls.append({
                        "method": method,
                        "url": url_val,
                        "line": node.lineno,
                        "url_is_dynamic": True,
                        "url_raw_expr": ast.unparse(arg),
                    })
            else:
                expr_str = ast.unparse(arg)
                calls.append({
                    "method": method,
                    "url": f"<dynamic:{expr_str}>",
                    "line": node.lineno,
                    "url_is_dynamic": True,
                    "url_raw_expr": expr_str,
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
                    service = "unknown"
                    if parts:
                        if parts[0] in ["src", "services", "apps", "cmd", "internal"] and len(parts) > 1:
                            service = parts[1]
                        else:
                            service = parts[0]
                    call["service"] = service
                    all_calls.append(call)

    return all_calls

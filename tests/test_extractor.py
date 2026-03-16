"""
Tests for the AST HTTP call extractor.

Covers:
- Pattern 1: requests.get/post/put/delete/patch
- Pattern 2: httpx.get/post/put/delete/patch
- Pattern 3: client.get/post/... (only absolute URLs)
- Pattern 6: f-string URLs (dynamic, prefix captured)
- Pattern 7: variable URLs (dynamic)
- Pattern 8: URL concatenation (dynamic)
- Regression: FastAPI decorators must NOT be detected as HTTP calls
"""

import textwrap
import tempfile
import os
import pytest

from app.extraction.extract_http_calls import (
    extract_http_calls_from_file,
    walk_and_extract_calls,
)


def _write_tmp(code: str) -> str:
    """Write code to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
    f.write(textwrap.dedent(code))
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# Pattern 1 — requests.*
# ---------------------------------------------------------------------------

class TestPattern1Requests:
    def test_get(self):
        path = _write_tmp("""
            import requests
            requests.get("http://api.example.com/users")
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 1
        assert calls[0]["method"] == "get"
        assert calls[0]["url"] == "http://api.example.com/users"
        assert calls[0]["url_is_dynamic"] is False

    def test_post(self):
        path = _write_tmp("""
            import requests
            requests.post("http://payment-service/charge", json={"amount": 100})
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 1
        assert calls[0]["method"] == "post"

    def test_put_delete_patch(self):
        path = _write_tmp("""
            import requests
            requests.put("http://api/resource/1", json={})
            requests.delete("http://api/resource/1")
            requests.patch("http://api/resource/1", json={})
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 3
        methods = {c["method"] for c in calls}
        assert methods == {"put", "delete", "patch"}

    def test_no_url_arg_ignored(self):
        path = _write_tmp("""
            import requests
            requests.get()
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 0

    def test_non_http_method_ignored(self):
        path = _write_tmp("""
            import requests
            requests.session()
            requests.Session()
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 0


# ---------------------------------------------------------------------------
# Pattern 2 — httpx.*
# ---------------------------------------------------------------------------

class TestPattern2Httpx:
    def test_httpx_get(self):
        path = _write_tmp("""
            import httpx
            httpx.get("https://inventory-service/stock")
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 1
        assert calls[0]["method"] == "get"
        assert "inventory-service" in calls[0]["url"]

    def test_httpx_post(self):
        path = _write_tmp("""
            import httpx
            httpx.post("https://order-service/orders", json={})
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 1
        assert calls[0]["method"] == "post"

    def test_httpx_multiple_methods(self):
        path = _write_tmp("""
            import httpx
            httpx.get("http://a/1")
            httpx.post("http://b/2")
            httpx.delete("http://c/3")
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 3


# ---------------------------------------------------------------------------
# Pattern 3 — client.get/post (absolute URLs only)
# ---------------------------------------------------------------------------

class TestPattern3Client:
    def test_session_get_absolute_url(self):
        path = _write_tmp("""
            import requests
            session = requests.Session()
            session.get("http://notification-service/notify")
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 1
        assert calls[0]["url"].startswith("http")

    def test_session_post_absolute_url(self):
        path = _write_tmp("""
            client = SomeClient()
            client.post("https://internal-api/webhook", json={})
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 1

    def test_relative_url_not_matched(self):
        """Relative-path strings must be ignored — this is the false-positive fix."""
        path = _write_tmp("""
            router = APIRouter()
            @router.get("/users")
            async def list_users(): pass

            @router.post("/items")
            async def create_item(): pass
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 0, (
            f"Expected 0 calls but got {len(calls)}: {calls}"
        )


# ---------------------------------------------------------------------------
# Regression: FastAPI decorators must produce zero results
# ---------------------------------------------------------------------------

class TestFastAPIDecoratorRegression:
    def test_fastapi_router_decorators(self):
        path = _write_tmp("""
            from fastapi import APIRouter
            router = APIRouter()

            @router.get("/")
            async def root(): return {}

            @router.post("/login")
            async def login(): return {}

            @router.get("/health")
            async def health(): return {"status": "ok"}

            @router.put("/{item_id}")
            async def update(item_id: int): return {}

            @router.delete("/{item_id}")
            async def delete(item_id: int): return {}
        """)
        calls = extract_http_calls_from_file(path)
        assert calls == [], (
            f"FastAPI decorators incorrectly detected as HTTP calls: {calls}"
        )

    def test_app_get_decorator(self):
        path = _write_tmp("""
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/")
            async def root(): return {}

            @app.post("/items")
            async def create(): return {}
        """)
        calls = extract_http_calls_from_file(path)
        assert calls == []


# ---------------------------------------------------------------------------
# Pattern 6 — f-string URLs
# ---------------------------------------------------------------------------

class TestPattern6FString:
    def test_fstring_url_captured_as_dynamic(self):
        path = _write_tmp("""
            import requests
            user_id = 42
            requests.get(f"http://user-service/users/{user_id}")
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 1
        assert calls[0]["url_is_dynamic"] is True
        assert calls[0]["url"].startswith("http://user-service")

    def test_fstring_prefix_extracted(self):
        path = _write_tmp("""
            import requests
            requests.post(f"http://order-service/orders/{order_id}/confirm")
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 1
        assert "order-service" in calls[0]["url"]
        assert "url_raw_expr" in calls[0]

    def test_fstring_no_http_prefix_ignored(self):
        path = _write_tmp("""
            import requests
            requests.get(f"/relative/{user_id}")
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 0


# ---------------------------------------------------------------------------
# Pattern 7 — variable URLs
# ---------------------------------------------------------------------------

class TestPattern7Variable:
    def test_variable_url_flagged_as_dynamic(self):
        path = _write_tmp("""
            import requests
            base_url = "http://payment-service"
            requests.post(base_url)
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 1
        assert calls[0]["url_is_dynamic"] is True
        assert calls[0]["url_raw_expr"] == "base_url"

    def test_variable_url_stores_name(self):
        path = _write_tmp("""
            import httpx
            api_endpoint = "http://catalog"
            httpx.get(api_endpoint)
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 1
        assert "api_endpoint" in calls[0]["url_raw_expr"]


# ---------------------------------------------------------------------------
# Pattern 8 — URL concatenation
# ---------------------------------------------------------------------------

class TestPattern8Concatenation:
    def test_constant_plus_path(self):
        path = _write_tmp("""
            import requests
            BASE = "http://catalog-service"
            requests.get(BASE + "/products")
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 1
        assert calls[0]["url_is_dynamic"] is True

    def test_var_plus_path(self):
        path = _write_tmp("""
            import requests
            base_url = get_base_url()
            requests.get(base_url + "/health")
        """)
        calls = extract_http_calls_from_file(path)
        assert len(calls) == 1
        assert calls[0]["url_is_dynamic"] is True


# ---------------------------------------------------------------------------
# walk_and_extract_calls — directory scan
# ---------------------------------------------------------------------------

class TestWalkAndExtract:
    def test_scans_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for service in ["order_service", "payment_service"]:
                os.makedirs(os.path.join(tmpdir, service))
                code = f"""
import requests
requests.get("http://inventory-service/stock")
requests.post("http://notification-service/notify", json={{}})
"""
                with open(os.path.join(tmpdir, service, "api.py"), "w") as f:
                    f.write(textwrap.dedent(code))

            calls = walk_and_extract_calls(tmpdir)

        assert len(calls) == 4
        services = {c["service"] for c in calls}
        assert "order_service" in services
        assert "payment_service" in services

    def test_service_name_from_top_level_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "auth_service"))
            code = 'import requests\nrequests.get("http://user-service/me")\n'
            with open(os.path.join(tmpdir, "auth_service", "app.py"), "w") as f:
                f.write(code)

            calls = walk_and_extract_calls(tmpdir)

        assert len(calls) == 1
        assert calls[0]["service"] == "auth_service"

    def test_skips_venv_and_pycache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for skip_dir in [".venv", "__pycache__", "venv"]:
                os.makedirs(os.path.join(tmpdir, skip_dir))
                code = 'import requests\nrequests.get("http://should-not-appear/api")\n'
                with open(os.path.join(tmpdir, skip_dir, "ignored.py"), "w") as f:
                    f.write(code)

            os.makedirs(os.path.join(tmpdir, "real_service"))
            code = 'import requests\nrequests.get("http://real-service/api")\n'
            with open(os.path.join(tmpdir, "real_service", "app.py"), "w") as f:
                f.write(code)

            calls = walk_and_extract_calls(tmpdir)

        assert len(calls) == 1
        assert "real-service" in calls[0]["url"]

    def test_own_codebase_zero_false_positives(self):
        """Scanning ServiceScope itself should return only absolute-URL calls."""
        project_root = os.path.join(os.path.dirname(__file__), "..")
        calls = walk_and_extract_calls(project_root)
        non_http = [c for c in calls if not c["url"].startswith("http") and not c["url_is_dynamic"]]
        assert non_http == [], (
            f"Non-absolute static URLs found (likely false positives): {non_http}"
        )

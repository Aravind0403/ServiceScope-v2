"""
Tests for the Go AST HTTP/gRPC call extractor.
"""

import os
import tempfile
import textwrap
import pytest

from app.extraction.extract_go_calls import (
    extract_go_calls_from_file,
    walk_and_extract_go_calls,
)


def _write_tmp_go(code: str) -> str:
    """Write code to a temp Go file and return its path."""
    f = tempfile.NamedTemporaryFile(suffix=".go", mode="w", delete=False)
    f.write(textwrap.dedent(code))
    f.close()
    return f.name


class TestGoExtractor:
    def test_std_http_methods(self):
        path = _write_tmp_go("""
            package main
            import "net/http"
            func main() {
                http.Get("http://api.example.com/users")
                http.Post("http://payment-service/charge", "application/json", nil)
                http.PostForm("http://auth/login", nil)
            }
        """)
        calls = extract_go_calls_from_file(path)
        os.unlink(path)

        assert len(calls) == 3
        assert calls[0]["method"] == "get"
        assert calls[0]["url"] == "http://api.example.com/users"
        assert calls[0]["url_is_dynamic"] is False

        assert calls[1]["method"] == "post"
        assert calls[1]["url"] == "http://payment-service/charge"

        assert calls[2]["method"] == "postform"
        assert calls[2]["url"] == "http://auth/login"

    def test_std_http_newrequest(self):
        path = _write_tmp_go("""
            package main
            import "net/http"
            func main() {
                req, _ := http.NewRequest("POST", "http://gateway/route", nil)
                req2, _ := http.NewRequestWithContext(ctx, "GET", "http://gateway/details", nil)
            }
        """)
        calls = extract_go_calls_from_file(path)
        os.unlink(path)

        assert len(calls) == 2
        assert calls[0]["method"] == "post"
        assert calls[0]["url"] == "http://gateway/route"
        assert calls[0]["url_is_dynamic"] is False

        assert calls[1]["method"] == "get"
        assert calls[1]["url"] == "http://gateway/details"
        assert calls[1]["url_is_dynamic"] is False

    def test_grpc_calls(self):
        path = _write_tmp_go("""
            package main
            import "google.golang.org/grpc"
            func main() {
                conn, _ := grpc.Dial("payment-service:50051", grpc.WithInsecure())
                conn2, _ := grpc.DialContext(ctx, "order-service:50051")
                client, _ := grpc.NewClient("user-service:50051")
            }
        """)
        calls = extract_go_calls_from_file(path)
        os.unlink(path)

        assert len(calls) == 3
        for c in calls:
            assert c["method"] == "grpc"
            assert c["url_is_dynamic"] is False
        assert calls[0]["url"] == "payment-service:50051"
        assert calls[1]["url"] == "order-service:50051"
        assert calls[2]["url"] == "user-service:50051"

    def test_generic_client_resty(self):
        path = _write_tmp_go("""
            package main
            func main() {
                // Should match because URL is absolute
                client.R().Get("http://reporting-service/metrics")
                // Should NOT match because URL is static and non-absolute
                client.Get("metrics")
                // Should match because URL is dynamic
                client.R().Post(urlVar)
            }
        """)
        calls = extract_go_calls_from_file(path)
        os.unlink(path)

        assert len(calls) == 2
        assert calls[0]["method"] == "get"
        assert calls[0]["url"] == "http://reporting-service/metrics"
        assert calls[0]["url_is_dynamic"] is False

        assert calls[1]["method"] == "post"
        assert calls[1]["url"] == "<dynamic:urlVar>"
        assert calls[1]["url_is_dynamic"] is True

    def test_dynamic_url_resolutions(self):
        path = _write_tmp_go("""
            package main
            import (
                "fmt"
                "os"
            )
            func main() {
                // os.Getenv
                http.Get(os.Getenv("TARGET_HOST"))
                // fmt.Sprintf
                http.Get(fmt.Sprintf("http://%s/api", host))
                // string concat
                http.Get(baseURL + "/charge")
                http.Get("http://host/" + path)
            }
        """)
        calls = extract_go_calls_from_file(path)
        os.unlink(path)

        assert len(calls) == 4
        assert calls[0]["url"] == "<dynamic:TARGET_HOST>"
        assert calls[0]["url_is_dynamic"] is True

        assert calls[1]["url"] == "http://"
        assert calls[1]["url_is_dynamic"] is True

        assert calls[2]["url"] == "<dynamic:baseURL>"
        assert calls[2]["url_is_dynamic"] is True

        assert calls[3]["url"] == "http://host/"
        assert calls[3]["url_is_dynamic"] is True

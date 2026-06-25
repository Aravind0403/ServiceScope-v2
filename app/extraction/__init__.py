# app/extraction/__init__.py
from app.extraction.extract_http_calls import (
    extract_http_calls_from_file,
    walk_and_extract_calls as walk_py_calls,
)
from app.extraction.extract_go_calls import (
    extract_go_calls_from_file,
    walk_and_extract_go_calls as walk_go_calls,
)


def walk_and_extract_calls(base_dir: str) -> list:
    """
    Walk directory tree and extract HTTP/gRPC calls from both Python and Go files.
    """
    py_calls = walk_py_calls(base_dir)
    go_calls = walk_go_calls(base_dir)
    return py_calls + go_calls


__all__ = [
    "extract_http_calls_from_file",
    "extract_go_calls_from_file",
    "walk_and_extract_calls",
]
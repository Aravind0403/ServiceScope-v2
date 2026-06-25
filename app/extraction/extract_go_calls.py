"""
Go AST Call Extractor

Uses a compiled Go helper (go_ast_parser) to extract HTTP and gRPC calls from Go files.
"""

import os
import sys
import json
import subprocess
from typing import List, Dict

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
GO_PARSER_SOURCE = os.path.join(CURRENT_DIR, "go_ast_parser.go")
GO_PARSER_BINARY = os.path.join(CURRENT_DIR, "go_ast_parser")


def _ensure_parser_compiled() -> bool:
    """Ensure the Go AST parser binary is compiled and available."""
    if os.path.exists(GO_PARSER_BINARY):
        return True

    if not os.path.exists(GO_PARSER_SOURCE):
        print(f"Error: Go AST parser source not found at {GO_PARSER_SOURCE}")
        return False

    print(f"Compiling Go AST parser: {GO_PARSER_SOURCE} -> {GO_PARSER_BINARY}")
    try:
        subprocess.run(
            ["go", "build", "-o", GO_PARSER_BINARY, GO_PARSER_SOURCE],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error compiling Go AST parser: {e.stderr}")
        return False
    except Exception as e:
        print(f"Failed to run compiler: {e}")
        return False


def extract_go_calls_from_file(file_path: str) -> List[Dict]:
    """
    Extract HTTP/gRPC calls from a single Go file.

    Args:
        file_path: Path to Go source file

    Returns:
        List of call dicts matching common schema.
    """
    if not _ensure_parser_compiled():
        return []

    try:
        result = subprocess.run(
            [GO_PARSER_BINARY, file_path],
            check=True,
            capture_output=True,
            text=True,
        )
        calls = json.loads(result.stdout)
        return calls if calls is not None else []
    except Exception as e:
        print(f"Error extracting Go calls from file {file_path}: {e}")
        return []


def walk_and_extract_go_calls(base_dir: str) -> List[Dict]:
    """
    Walk base_dir and extract HTTP/gRPC calls from all Go source files.

    Args:
        base_dir: Root directory of code

    Returns:
        List of call dicts.
    """
    if not _ensure_parser_compiled():
        return []

    try:
        result = subprocess.run(
            [GO_PARSER_BINARY, base_dir],
            check=True,
            capture_output=True,
            text=True,
        )
        calls = json.loads(result.stdout)
        return calls if calls is not None else []
    except Exception as e:
        print(f"Error walking and extracting Go calls from {base_dir}: {e}")
        return []

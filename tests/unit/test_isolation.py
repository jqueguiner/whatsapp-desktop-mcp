"""REL-05 enforcement test: Reader and Sender packages MUST NOT import each other.

CLAUDE.md §1 hard architectural rule: ``reader/`` and ``sender/`` isolate the
two highest-volatility surfaces (DB schema vs UI) and the tool layer is the
only integration point. A test that asserts this by structure (not by
convention) catches any drift the moment a future executor types
``from whatsapp_mcp.sender import ...`` inside the reader package.

In Phase 0 both packages are empty placeholder ``__init__.py`` files, so the
file-scan assertions are vacuously true — the test gains teeth in Phase 1
(when ``reader/`` fills) and Phase 2 (when ``sender/`` fills). The first
assertion (independent imports) is non-vacuous even today: it catches
collateral damage from any future shared-module refactor that accidentally
crosses the boundary at import time.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import whatsapp_mcp.reader
import whatsapp_mcp.sender


def _package_dir(module_name: str) -> Path:
    """Resolve a sub-package's source directory via importlib.

    Using ``importlib`` instead of a hard-coded relative path lets the test
    run correctly whether invoked from the repo root, a tmp checkout, or an
    installed wheel layout (where the source lives under ``site-packages``).
    """
    spec = importlib.util.find_spec(module_name)
    assert spec is not None, f"could not locate {module_name}"
    assert spec.origin is not None, f"{module_name} has no __init__.py origin"
    return Path(spec.origin).parent


def test_isolation_reader_imports_independently() -> None:
    """``import whatsapp_mcp.reader`` succeeds in isolation."""
    # The module-level ``import`` above already succeeded; the assertion
    # documents the invariant so a future executor reading this test sees
    # the intent.
    assert whatsapp_mcp.reader is not None


def test_isolation_sender_imports_independently() -> None:
    """``import whatsapp_mcp.sender`` succeeds in isolation."""
    assert whatsapp_mcp.sender is not None


def test_isolation_reader_does_not_import_sender() -> None:
    """No ``.py`` file under ``reader/`` references the Sender package."""
    reader_dir = _package_dir("whatsapp_mcp.reader")
    for py_file in reader_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "from whatsapp_mcp.sender" not in content, (
            f"REL-05 violation: {py_file} imports from whatsapp_mcp.sender"
        )
        assert "import whatsapp_mcp.sender" not in content, (
            f"REL-05 violation: {py_file} imports whatsapp_mcp.sender"
        )


def test_isolation_sender_does_not_import_reader() -> None:
    """No ``.py`` file under ``sender/`` references the Reader package."""
    sender_dir = _package_dir("whatsapp_mcp.sender")
    for py_file in sender_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "from whatsapp_mcp.reader" not in content, (
            f"REL-05 violation: {py_file} imports from whatsapp_mcp.reader"
        )
        assert "import whatsapp_mcp.reader" not in content, (
            f"REL-05 violation: {py_file} imports whatsapp_mcp.reader"
        )

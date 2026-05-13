"""REL-05 enforcement test: Reader and Sender packages MUST NOT import each other.

CLAUDE.md §1 hard architectural rule: ``reader/`` and ``sender/`` isolate the
two highest-volatility surfaces (DB schema vs UI) and the tool layer is the
only integration point. A test that asserts this by structure (not by
convention) catches any drift the moment a future executor types
``from whatsapp_mcp.sender import ...`` inside the reader package.

Phase 0 originally shipped both packages as empty placeholder ``__init__.py``
files, so the file-scan assertions were vacuously true. Phase 1 Plan 02
filled ``reader/`` with 10 modules — the AST walk in
:func:`test_isolation_reader_does_not_import_sender` is now LOAD-BEARING
(the walk has real source to inspect). The Phase 0 ``str-in-content``
assertions are preserved AND extended with a real :func:`ast.walk` over
every reader module's ``Import`` / ``ImportFrom`` nodes — the AST form
catches a ``from whatsapp_mcp.sender.foo import bar`` even if the literal
``"from whatsapp_mcp.sender"`` substring would not appear contiguously
(e.g. across line continuations).

A new positive-whitelist test enforces that ``reader/`` only imports from
a curated set of in-package modules — catching accidental drift into
``tools/``, ``permissions/``, or ``sender/`` (W4 import-edge invariant).
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import whatsapp_mcp.reader
import whatsapp_mcp.sender

# Allow-list for ``reader/*.py`` whatsapp_mcp.* imports. Drift outside this
# set is caught by :func:`test_reader_imports_models_paths_time_only`.
# ``reader`` itself is allowed for intra-package imports
# (e.g. ``from whatsapp_mcp.reader.connection import open_ro`` inside a
# sibling reader module).
_ALLOWED_READER_INTERNAL_IMPORTS: frozenset[str] = frozenset(
    {"models", "paths", "time", "exceptions", "reader"}
)


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


def _imported_dotted_names(py_file: Path) -> list[str]:
    """Return every dotted module name imported by ``py_file``.

    Handles both ``import x.y.z`` (yields ``"x.y.z"``) and
    ``from x.y import z`` (yields ``"x.y"``). Relative imports are
    converted to ``""`` (skipped — Plan 01 reader uses absolute imports
    only, so this defensive case never fires in practice).
    """
    out: list[str] = []
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Relative import — Plan 01-02 should not contain any.
                continue
            if node.module is not None:
                out.append(node.module)
    return out


def test_isolation_reader_imports_independently() -> None:
    """``import whatsapp_mcp.reader`` succeeds in isolation."""
    assert whatsapp_mcp.reader is not None


def test_isolation_sender_imports_independently() -> None:
    """``import whatsapp_mcp.sender`` succeeds in isolation."""
    assert whatsapp_mcp.sender is not None


def test_isolation_reader_does_not_import_sender() -> None:
    """No ``.py`` file under ``reader/`` references the Sender package.

    Two-layer check:
    1. String scan (Phase 0 — preserved verbatim) catches the obvious
       ``from whatsapp_mcp.sender`` and ``import whatsapp_mcp.sender``
       substrings.
    2. AST walk (Phase 1 — load-bearing now that ``reader/`` has 10
       modules) catches any module whose ``ast.Import`` / ``ast.ImportFrom``
       node references the sender package — including line-wrapped or
       aliased forms the substring scan would miss.
    """
    reader_dir = _package_dir("whatsapp_mcp.reader")
    py_files = list(reader_dir.rglob("*.py"))
    # Phase 1 Plan 02 ships 10 reader modules; the test would be vacuously
    # true if the walk found zero files (that would mean the package was
    # somehow emptied, which is itself a regression).
    assert len(py_files) >= 9, (
        f"expected reader/ to contain ≥9 modules; found {len(py_files)}: "
        f"{[p.name for p in py_files]}"
    )

    for py_file in py_files:
        # Layer 1: Phase 0 string scan (preserved).
        content = py_file.read_text(encoding="utf-8")
        assert "from whatsapp_mcp.sender" not in content, (
            f"REL-05 violation: {py_file} imports from whatsapp_mcp.sender"
        )
        assert "import whatsapp_mcp.sender" not in content, (
            f"REL-05 violation: {py_file} imports whatsapp_mcp.sender"
        )

        # Layer 2: Phase 1 load-bearing AST walk.
        for dotted in _imported_dotted_names(py_file):
            assert not dotted.startswith("whatsapp_mcp.sender"), (
                f"REL-05 violation (AST): {py_file} imports {dotted!r}"
            )


def test_isolation_sender_does_not_import_reader() -> None:
    """Sender package may import the read-side DB-connection helper ONLY.

    D-24 EVOLVED REL-05 (Plan 02-03): the original Phase 0/1 invariant
    ("sender MUST NOT import reader, period") is relaxed to permit a
    SINGLE narrow edge — :mod:`whatsapp_mcp.sender.verify` imports
    :func:`whatsapp_mcp.reader.connection.open_ro` for the post-hoc
    DB poll. EVERY OTHER read-side import path stays forbidden in
    ``sender/``.

    The AST walk enumerates every read-side import across the sender
    package; any dotted name starting with ``whatsapp_mcp.reader.``
    that is not exactly ``whatsapp_mcp.reader.connection`` fails the
    test. Importing the package-level ``whatsapp_mcp.reader`` (which
    would pull the 14-accessor data-tier surface) is also forbidden.

    Plan 02-04 may further tighten this test to assert the offending
    file is exactly ``sender/verify.py`` (no other sender file may
    take the connection edge). For now we enforce the type-of-import
    invariant: only the narrow connection module is reachable from
    ``sender/``.
    """
    sender_dir = _package_dir("whatsapp_mcp.sender")
    for py_file in sender_dir.rglob("*.py"):
        # Layer 1: substring scan — forbid the package-level form
        # ``from whatsapp_mcp.reader import ...`` (which would pull
        # the 14-accessor data-tier re-export surface). The narrow
        # ``from whatsapp_mcp.reader.connection import ...`` form is
        # the only sanctioned shape and is checked at Layer 2.
        content = py_file.read_text(encoding="utf-8")
        assert "from whatsapp_mcp.reader import" not in content, (
            f"REL-05 D-24 violation: {py_file} imports from the "
            "read-side package-level surface; only "
            "whatsapp_mcp.reader.connection is permitted"
        )
        assert "import whatsapp_mcp.reader\n" not in content + "\n", (
            f"REL-05 D-24 violation: {py_file} imports the read-side package as a whole"
        )

        # Layer 2: AST walk — the only permitted read-side dotted name
        # is exactly ``whatsapp_mcp.reader.connection``.
        for dotted in _imported_dotted_names(py_file):
            if dotted.startswith("whatsapp_mcp.reader"):
                assert dotted == "whatsapp_mcp.reader.connection", (
                    f"REL-05 D-24 violation (AST): {py_file} imports "
                    f"{dotted!r}; only whatsapp_mcp.reader.connection "
                    "is permitted under the evolved D-24 invariant"
                )


def test_reader_imports_models_paths_time_only() -> None:
    """``reader/*.py`` only imports from an allow-listed set of in-package modules.

    Catches accidental drift into ``tools/``, ``permissions/``, or
    ``sender/`` — any non-allow-listed sub-package import surfaces here as
    a structured failure message naming the offending file + dotted name.
    External imports (``sqlite3``, ``asyncio``, ``pydantic``, etc.) are
    untouched — only ``whatsapp_mcp.*`` imports are scrutinised.
    """
    reader_dir = _package_dir("whatsapp_mcp.reader")
    violations: list[str] = []
    for py_file in reader_dir.rglob("*.py"):
        for dotted in _imported_dotted_names(py_file):
            if not dotted.startswith("whatsapp_mcp"):
                continue
            # ``whatsapp_mcp`` itself is allowed (the package re-export
            # surface — e.g. ``from whatsapp_mcp.models import Chat``).
            parts = dotted.split(".")
            if len(parts) < 2:
                # Plain ``import whatsapp_mcp`` — fine, harmless.
                continue
            sub_pkg = parts[1]  # the second component, e.g. "models"
            if sub_pkg not in _ALLOWED_READER_INTERNAL_IMPORTS:
                violations.append(f"{py_file}: imports {dotted!r}")

    assert not violations, (
        "reader/ imports from non-allow-listed in-package modules:\n"
        + "\n".join(violations)
        + f"\nallow-list: {sorted(_ALLOWED_READER_INTERNAL_IMPORTS)}"
    )

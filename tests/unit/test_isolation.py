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

# D-24 REL-05 EVOLUTION (Plan 02-03 / 02-04): sender MAY import from reader
# but ONLY ``reader.connection`` — the post-hoc verify in ``sender/verify.py``
# needs the RO-WAL ``open_ro`` context manager. No other reader module is
# allowed; sender MUST NOT pull reader business logic.
_ALLOWED_SENDER_TO_READER_IMPORTS: frozenset[str] = frozenset({"connection"})

# Tools layer is the documented MCP integration point and MAY import from
# both reader and sender. This allow-list exists to prevent accidental
# REVERSE drift (e.g. tools/ importing from a yet-unminted ``whatsapp_mcp.foo``
# sub-package) without restricting the legitimate read+send composition pattern.
# ``server`` is here because tools/*.py import ``from whatsapp_mcp.server
# import mcp`` for @mcp.tool registration; ``tools`` is here for intra-package
# imports like ``from whatsapp_mcp.tools._decorators import timeout``;
# ``permissions`` is here because doctor.py composes the TCC probes.
_TOOLS_ALLOWED_INTERNAL_IMPORTS: frozenset[str] = frozenset(
    {
        "models",
        "paths",
        "time",
        "exceptions",
        "reader",
        "sender",
        "permissions",
        "server",
        "tools",
    }
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
    """REL-05 D-24 EVOLVED: sender MAY import ``reader.connection`` only.

    Phase 1 ran this assertion vacuously (``sender/`` was empty). Phase 2
    Plan 02-03 introduces ONE allowed edge — ``sender/verify.py`` imports
    ``from whatsapp_mcp.reader.connection import open_ro`` for the
    post-hoc DB verify poll. No other reader submodule is allowed; this
    test asserts that surgical narrowness via the
    :data:`_ALLOWED_SENDER_TO_READER_IMPORTS` allow-list (frozenset of
    permitted second-after-``reader`` submodule names) so future drift
    (e.g. a sender file pulling ``reader.messages`` or ``reader.chats``)
    is caught at test time.

    The reverse direction — ``reader → sender`` — remains strictly
    forbidden (see :func:`test_isolation_reader_does_not_import_sender`).

    Two-layer check (mirror of the reader-side test):

    1. Substring scan — forbids the package-level
       ``from whatsapp_mcp.reader import ...`` form (which would pull
       the data-tier re-export surface).
    2. AST walk — every ``whatsapp_mcp.reader.*`` dotted name found
       across ``sender/*.py`` must have its second-after-``reader``
       component in :data:`_ALLOWED_SENDER_TO_READER_IMPORTS`.
    """
    sender_dir = _package_dir("whatsapp_mcp.sender")
    violations: list[str] = []
    for py_file in sender_dir.rglob("*.py"):
        # Layer 1: substring scan — forbid the package-level form
        # ``from whatsapp_mcp.reader import ...`` (which would pull
        # the data-tier re-export surface). The narrow
        # ``from whatsapp_mcp.reader.connection import ...`` form is
        # the only sanctioned shape and is checked at Layer 2.
        content = py_file.read_text(encoding="utf-8")
        assert "from whatsapp_mcp.reader import" not in content, (
            f"REL-05 D-24 violation: {py_file} imports from the "
            "read-side package-level surface; only "
            f"submodules in {sorted(_ALLOWED_SENDER_TO_READER_IMPORTS)} are permitted"
        )
        assert "import whatsapp_mcp.reader\n" not in content + "\n", (
            f"REL-05 D-24 violation: {py_file} imports the read-side package as a whole"
        )

        # Layer 2: AST walk — the only permitted read-side dotted names
        # are those whose second-after-``reader`` component is in the
        # ``_ALLOWED_SENDER_TO_READER_IMPORTS`` allow-list.
        for dotted in _imported_dotted_names(py_file):
            if not dotted.startswith("whatsapp_mcp.reader"):
                continue
            parts = dotted.split(".")
            # parts = ["whatsapp_mcp", "reader", "<submodule>", ...]
            # parts[2] is the submodule name (e.g. "connection").
            if len(parts) < 3:
                # Bare ``whatsapp_mcp.reader`` — rejected (pulls package surface).
                violations.append(
                    f"{py_file}: imports {dotted!r} (package-level reader import forbidden)"
                )
                continue
            submodule = parts[2]
            if submodule not in _ALLOWED_SENDER_TO_READER_IMPORTS:
                violations.append(
                    f"{py_file}: imports {dotted!r} — only "
                    f"{sorted(_ALLOWED_SENDER_TO_READER_IMPORTS)} allowed under D-24"
                )

    assert not violations, (
        "REL-05 D-24 violation(s) — sender may import reader.connection only:\n"
        + "\n".join(violations)
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


def test_isolation_tools_may_import_both() -> None:
    """The tools/ package is the MCP integration point and MAY import from
    both reader/ and sender/.

    Positive allow-list test (mirror of
    :func:`test_reader_imports_models_paths_time_only`) so future drift
    into forbidden sub-packages — e.g. a stray
    ``from whatsapp_mcp.foo import bar`` snuck into a tool file —
    surfaces with a structured failure naming the offending file +
    dotted name. The allow-list deliberately includes BOTH ``reader``
    and ``sender`` (the documented integration pattern); the
    ``cross_chat_quote.record_bodies`` hook in 4 read tools and the
    full sender composition in ``send_message.py`` are the load-bearing
    use cases this test sanctions.
    """
    tools_dir = _package_dir("whatsapp_mcp.tools")
    violations: list[str] = []
    for py_file in tools_dir.rglob("*.py"):
        for dotted in _imported_dotted_names(py_file):
            if not dotted.startswith("whatsapp_mcp"):
                continue
            parts = dotted.split(".")
            if len(parts) < 2:
                # Plain ``import whatsapp_mcp`` — fine.
                continue
            sub_pkg = parts[1]
            if sub_pkg not in _TOOLS_ALLOWED_INTERNAL_IMPORTS:
                violations.append(f"{py_file}: imports {dotted!r}")

    assert not violations, (
        "tools/ imports from non-allow-listed in-package modules:\n"
        + "\n".join(violations)
        + f"\nallow-list: {sorted(_TOOLS_ALLOWED_INTERNAL_IMPORTS)}"
    )


def test_sender_to_reader_edge_is_exactly_one_file() -> None:
    """D-24 narrow edge: only ``sender/verify.py`` should import reader.connection.

    Defense-in-depth on top of
    :func:`test_isolation_sender_does_not_import_reader`. That test
    allows the edge from ANY sender file; this test asserts the edge
    actually only exists in the ONE file Plan 02-03 introduced it in.
    Drift here means a new sender file picked up the
    ``reader.connection`` edge — likely because the executor needed
    the DB and chose the expedient path instead of channeling via
    ``verify.py``. The remediation in that case is to refactor: the
    DB-read primitive lives in ``verify.py`` and any new sender code
    that needs read access composes through there.

    The plan-level intent is W-5 (Plan 02-04 must_have): "the
    sender→reader.connection edge MUST be exactly one file".
    """
    sender_dir = _package_dir("whatsapp_mcp.sender")
    files_with_edge: list[str] = []
    for py_file in sender_dir.rglob("*.py"):
        for dotted in _imported_dotted_names(py_file):
            if dotted.startswith("whatsapp_mcp.reader"):
                files_with_edge.append(py_file.name)
                break  # one edge per file is enough to surface this file
    # Dedup since a single file may import reader.connection multiple times.
    unique = sorted(set(files_with_edge))
    assert unique == ["verify.py"], (
        f"Expected sender→reader.connection edge ONLY in verify.py; "
        f"found in {unique!r}. If a new sender module needs DB read "
        f"access, channel it through sender/verify.py to keep the "
        f"edge surgical."
    )

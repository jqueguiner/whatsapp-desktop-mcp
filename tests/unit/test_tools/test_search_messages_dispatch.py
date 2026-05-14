"""Unit tests for ``tools/search_messages.py`` dispatcher (Phase 3 Plan 03-01 Task 2).

Coverage matrix mapped to the plan ``<behavior>`` block:

- Test 1 — ``server.fts5_mode`` defaults to ``"auto"`` at import time.
- Test 2 — CLI ``--fts5-mode force`` causes ``server.fts5_mode == "force"``
  BEFORE the lazy ``server.run`` import resolves.
- Test 3 — CLI rejects an unknown ``--fts5-mode`` value with SystemExit
  via argparse choices=...
- Test 4 — auto + sidecar absent → LIKE path runs (``reader.like_search``
  is called, ``search_fts5.fts5_search`` is NOT).
- Test 5 — auto + sidecar present → FTS5 path runs.
- Test 6 — force + sidecar absent → ``search_fts5.build_or_refresh`` is
  called, then ``search_fts5.fts5_search`` runs.
- Test 7 — disable → LIKE path always runs even if the sidecar exists.
- Test 8 — when ``search_fts5.fts5_search`` raises sqlite3.OperationalError
  under FTS5 dispatch, the dispatcher falls back to ``reader.like_search``.
- Test 9 — Phase 1 ``FullDiskAccessRequired`` mapping passes through both
  branches (regression guard for the existing error mapping).

The dispatcher is exercised by directly invoking the wrapped tool callable
(``search_messages.__wrapped__`` once @timeout / @mcp.tool finish), so the
input-validation / cursor / char-cap loop continues to run unchanged on
every dispatch path.
"""

from __future__ import annotations

import asyncio
import sqlite3
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from whatsapp_desktop_mcp import server
from whatsapp_desktop_mcp.exceptions import FullDiskAccessRequired
from whatsapp_desktop_mcp.models.contact import Jid
from whatsapp_desktop_mcp.models.message import Message
from whatsapp_desktop_mcp.tools import search_messages as search_messages_module


def _make_message(message_id: str, body: str, chat_id: int = 1) -> Message:
    """Build a minimal Message stand-in for dispatcher mock returns."""
    return Message(
        message_id=message_id,
        chat_id=chat_id,
        sender_jid=Jid(kind="phone", raw="33612345678@s.whatsapp.net", phone="33612345678"),
        timestamp=1_700_000_000,
        body=body,
        kind="text",
        is_outgoing=False,
        is_starred=False,
        quoted_message_id=None,
        media=None,
    )


def _async_return(value: Any) -> Callable[..., Awaitable[Any]]:
    """Return an async callable that resolves to ``value`` when awaited."""

    async def _coro(*_args: Any, **_kwargs: Any) -> Any:
        return value

    return _coro


def _async_raise(exc: BaseException) -> Callable[..., Awaitable[Any]]:
    """Return an async callable that raises ``exc`` when awaited."""

    async def _coro(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    return _coro


@pytest.fixture
def reset_fts5_mode() -> Any:
    """Restore ``server.fts5_mode`` to its module-import default after each test."""
    original = server.fts5_mode
    yield
    server.fts5_mode = original


# ---------------------------------------------------------------------------
# Test 1 — server.fts5_mode default.
# ---------------------------------------------------------------------------


def test_server_fts5_mode_defaults_to_auto() -> None:
    """``server.fts5_mode`` is ``"auto"`` at module import time (D-29)."""
    import whatsapp_desktop_mcp.server

    assert whatsapp_desktop_mcp.server.fts5_mode == "auto"


# ---------------------------------------------------------------------------
# Test 2 — CLI --fts5-mode sets server.fts5_mode BEFORE server.run import.
# ---------------------------------------------------------------------------


def test_cli_fts5_mode_force_sets_module_attr_before_run(reset_fts5_mode: Any) -> None:
    """``main(["--fts5-mode", "force"])`` mutates ``server.fts5_mode`` to "force"
    BEFORE the lazy ``server.run`` import resolves (mirrors D-19 / Plan 01-03).

    We mock ``mcp.run`` so the JSON-RPC loop never starts; the assertion
    checks the module attr observed AT the moment ``run`` would have fired.
    """
    from whatsapp_desktop_mcp import cli

    observed: dict[str, str] = {}

    def fake_run() -> None:
        # Observe the attr at the moment server.run() would fire.
        import whatsapp_desktop_mcp.server as srv

        observed["fts5_mode"] = srv.fts5_mode

    with mock.patch("whatsapp_desktop_mcp.server.mcp.run", side_effect=fake_run):
        rc = cli.main(["--fts5-mode", "force", "--read-only"])
    assert rc == 0
    assert observed["fts5_mode"] == "force"


def test_cli_fts5_mode_disable_sets_module_attr(reset_fts5_mode: Any) -> None:
    """``main(["--fts5-mode", "disable"])`` mutates ``server.fts5_mode`` to "disable"."""
    from whatsapp_desktop_mcp import cli

    observed: dict[str, str] = {}

    def fake_run() -> None:
        import whatsapp_desktop_mcp.server as srv

        observed["fts5_mode"] = srv.fts5_mode

    with mock.patch("whatsapp_desktop_mcp.server.mcp.run", side_effect=fake_run):
        rc = cli.main(["--fts5-mode", "disable", "--read-only"])
    assert rc == 0
    assert observed["fts5_mode"] == "disable"


# ---------------------------------------------------------------------------
# Test 3 — CLI rejects bad --fts5-mode value with argparse SystemExit.
# ---------------------------------------------------------------------------


def test_cli_rejects_unknown_fts5_mode_value() -> None:
    """``--fts5-mode bogus`` exits 2 (argparse choices error)."""
    from whatsapp_desktop_mcp import cli

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--fts5-mode", "bogus"])
    assert excinfo.value.code == 2


def test_cli_help_includes_fts5_mode_flag() -> None:
    """``--help`` exit-0 output includes the ``--fts5-mode`` flag (defense-in-depth)."""
    proc = subprocess.run(
        [sys.executable, "-m", "whatsapp_desktop_mcp", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, f"--help exit {proc.returncode}: {proc.stderr!r}"
    assert "--fts5-mode" in proc.stdout, f"--fts5-mode not in help: {proc.stdout!r}"
    # All three choices visible in the help output.
    for choice in ("auto", "force", "disable"):
        assert choice in proc.stdout, f"choice {choice!r} missing from help: {proc.stdout!r}"


# ---------------------------------------------------------------------------
# Test 4 — auto + sidecar absent → LIKE.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_auto_sidecar_absent_calls_like_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reset_fts5_mode: Any,
) -> None:
    """auto + missing sidecar → ``reader.like_search`` is called, FTS5 is NOT."""
    from whatsapp_desktop_mcp.reader import search_fts5

    server.fts5_mode = "auto"
    monkeypatch.setattr(search_fts5, "_DB_PATH", tmp_path / "missing-fts.sqlite")

    like_mock = mock.AsyncMock(return_value=[_make_message("S1", "hi from like")])
    fts_mock = mock.AsyncMock(return_value=[_make_message("S2", "hi from fts")])
    monkeypatch.setattr("whatsapp_desktop_mcp.reader.like_search", like_mock)
    monkeypatch.setattr(search_fts5, "fts5_search", fts_mock)

    result = await _call_search_messages(query="hi from")
    assert result["count"] == 1
    assert result["messages"][0]["message_id"] == "S1"
    assert like_mock.await_count == 1
    assert fts_mock.await_count == 0


# ---------------------------------------------------------------------------
# Test 5 — auto + sidecar present → FTS5.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_auto_sidecar_present_calls_fts5_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reset_fts5_mode: Any,
) -> None:
    """auto + existing sidecar → ``search_fts5.fts5_search`` is called, LIKE is NOT."""
    from whatsapp_desktop_mcp.reader import search_fts5

    server.fts5_mode = "auto"
    fts_path = tmp_path / "fts.sqlite"
    fts_path.touch()  # make the existence check return True
    monkeypatch.setattr(search_fts5, "_DB_PATH", fts_path)

    like_mock = mock.AsyncMock(return_value=[_make_message("S1", "hi from like")])
    fts_mock = mock.AsyncMock(return_value=[_make_message("S2", "hi from fts")])
    monkeypatch.setattr("whatsapp_desktop_mcp.reader.like_search", like_mock)
    monkeypatch.setattr(search_fts5, "fts5_search", fts_mock)

    result = await _call_search_messages(query="hi from")
    assert result["count"] == 1
    assert result["messages"][0]["message_id"] == "S2"
    assert fts_mock.await_count == 1
    assert like_mock.await_count == 0


# ---------------------------------------------------------------------------
# Test 6 — force + sidecar absent → lazy build then FTS5.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_force_sidecar_absent_lazy_builds_then_fts5(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reset_fts5_mode: Any,
) -> None:
    """force + missing sidecar → ``build_or_refresh`` runs, then FTS5 search."""
    from whatsapp_desktop_mcp.reader import search_fts5

    server.fts5_mode = "force"
    monkeypatch.setattr(search_fts5, "_DB_PATH", tmp_path / "missing-fts.sqlite")

    build_mock = mock.AsyncMock(return_value=None)
    fts_mock = mock.AsyncMock(return_value=[_make_message("S2", "hi from fts")])
    like_mock = mock.AsyncMock(return_value=[_make_message("S1", "hi from like")])
    monkeypatch.setattr(search_fts5, "build_or_refresh", build_mock)
    monkeypatch.setattr(search_fts5, "fts5_search", fts_mock)
    monkeypatch.setattr("whatsapp_desktop_mcp.reader.like_search", like_mock)

    result = await _call_search_messages(query="hi from")
    assert result["count"] == 1
    assert result["messages"][0]["message_id"] == "S2"
    assert build_mock.await_count == 1, "force-mode missing-sidecar should lazy-build"
    assert fts_mock.await_count == 1
    assert like_mock.await_count == 0


# ---------------------------------------------------------------------------
# Test 7 — disable → always LIKE.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_disable_always_uses_like(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reset_fts5_mode: Any,
) -> None:
    """disable + sidecar present → LIKE still runs, FTS5 untouched."""
    from whatsapp_desktop_mcp.reader import search_fts5

    server.fts5_mode = "disable"
    fts_path = tmp_path / "fts.sqlite"
    fts_path.touch()
    monkeypatch.setattr(search_fts5, "_DB_PATH", fts_path)

    like_mock = mock.AsyncMock(return_value=[_make_message("S1", "hi from like")])
    fts_mock = mock.AsyncMock(return_value=[_make_message("S2", "hi from fts")])
    monkeypatch.setattr("whatsapp_desktop_mcp.reader.like_search", like_mock)
    monkeypatch.setattr(search_fts5, "fts5_search", fts_mock)

    result = await _call_search_messages(query="hi from")
    assert result["count"] == 1
    assert result["messages"][0]["message_id"] == "S1"
    assert like_mock.await_count == 1
    assert fts_mock.await_count == 0


# ---------------------------------------------------------------------------
# Test 8 — FTS5 OperationalError → fallback to LIKE.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_fts5_operational_error_falls_back_to_like(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reset_fts5_mode: Any,
) -> None:
    """FTS5 dispatch + sqlite3.OperationalError → log warning, retry via LIKE."""
    from whatsapp_desktop_mcp.reader import search_fts5

    server.fts5_mode = "auto"
    fts_path = tmp_path / "fts.sqlite"
    fts_path.touch()
    monkeypatch.setattr(search_fts5, "_DB_PATH", fts_path)

    boom = sqlite3.OperationalError("fts5: boom")
    fts_mock = mock.AsyncMock(side_effect=boom)
    like_mock = mock.AsyncMock(return_value=[_make_message("S1", "fallback hit")])
    monkeypatch.setattr(search_fts5, "fts5_search", fts_mock)
    monkeypatch.setattr("whatsapp_desktop_mcp.reader.like_search", like_mock)

    result = await _call_search_messages(query="fallback hit")
    assert result["count"] == 1
    assert result["messages"][0]["body"] == "fallback hit"
    assert fts_mock.await_count == 1
    assert like_mock.await_count == 1, "LIKE fallback should run after FTS5 OperationalError"


# ---------------------------------------------------------------------------
# Test 9 — FullDiskAccessRequired pass-through (regression guard).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_disk_access_required_mapping_unchanged_under_like(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reset_fts5_mode: Any,
) -> None:
    """LIKE branch surfaces FullDiskAccessRequired as a structured ValueError."""
    from whatsapp_desktop_mcp.reader import search_fts5

    server.fts5_mode = "disable"  # ensure LIKE path
    monkeypatch.setattr(search_fts5, "_DB_PATH", tmp_path / "missing-fts.sqlite")

    fda = FullDiskAccessRequired(
        "FDA needed",
        binary_path="/usr/local/bin/whatsapp-desktop-mcp",
        db_path="/Users/x/Library/.../ChatStorage.sqlite",
        remediation="grant in System Settings",
    )
    like_mock = mock.AsyncMock(side_effect=fda)
    monkeypatch.setattr("whatsapp_desktop_mcp.reader.like_search", like_mock)

    with pytest.raises(ValueError) as excinfo:
        await _call_search_messages(query="anything")
    assert "Full Disk Access required" in str(excinfo.value)


@pytest.mark.asyncio
async def test_full_disk_access_required_mapping_unchanged_under_fts5(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reset_fts5_mode: Any,
) -> None:
    """FTS5 branch also surfaces FullDiskAccessRequired as a structured ValueError."""
    from whatsapp_desktop_mcp.reader import search_fts5

    server.fts5_mode = "auto"
    fts_path = tmp_path / "fts.sqlite"
    fts_path.touch()
    monkeypatch.setattr(search_fts5, "_DB_PATH", fts_path)

    fda = FullDiskAccessRequired(
        "FDA needed",
        binary_path="/usr/local/bin/whatsapp-desktop-mcp",
        db_path="/Users/x/Library/.../ChatStorage.sqlite",
        remediation="grant in System Settings",
    )
    fts_mock = mock.AsyncMock(side_effect=fda)
    monkeypatch.setattr(search_fts5, "fts5_search", fts_mock)
    # Belt-and-braces: ensure the LIKE fallback is NOT consulted on FDA.
    like_mock = mock.AsyncMock(return_value=[])
    monkeypatch.setattr("whatsapp_desktop_mcp.reader.like_search", like_mock)

    with pytest.raises(ValueError) as excinfo:
        await _call_search_messages(query="anything")
    assert "Full Disk Access required" in str(excinfo.value)
    assert like_mock.await_count == 0, (
        "FDA must not trigger the OperationalError → LIKE fallback path"
    )


# ---------------------------------------------------------------------------
# Internal helper — invoke the wrapped tool callable.
# ---------------------------------------------------------------------------


async def _call_search_messages(**kwargs: Any) -> dict[str, Any]:
    """Invoke ``search_messages`` through the @timeout/@mcp.tool wrappers.

    The decorated callable is the FastMCP tool; we invoke it with the
    same kwargs the MCP runtime would pass.
    """
    sm = search_messages_module.search_messages
    # The @timeout and @mcp.tool decorators preserve __call__; mypy sees
    # the FunctionTool surface, but at runtime FastMCP exposes ``fn``
    # for direct invocation in tests. Fall back to __wrapped__ if needed.
    if hasattr(sm, "fn"):
        return await sm.fn(**kwargs)  # type: ignore[no-any-return]
    if hasattr(sm, "__wrapped__"):
        result = await sm.__wrapped__(**kwargs)
        assert isinstance(result, dict)
        return result
    # Last resort — invoke directly (covers the bare-callable case).
    result = await sm(**kwargs)
    assert isinstance(result, dict)
    return result


# Silence asyncio "coroutine was never awaited" warnings on test teardown
# when AsyncMock side_effects raise before the awaitable is consumed.
_ = asyncio  # keep the import live for the @pytest.mark.asyncio runtime

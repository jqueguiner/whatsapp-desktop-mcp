"""Locale-blind ``osascript`` runner tests (P-PHASE0-02 regression guard).

The trailing ``(-NNNN)`` regex must extract the numeric error code regardless
of stderr language. Verified empirically on the user's Mac (fr_FR locale,
2026-05-13): the literal stderr is "Erreur dans WhatsApp ... (-1743)" — an
English-only prose regex would mis-classify the denied permission as granted.

These tests use the ``fp`` fixture from ``pytest-subprocess`` to register
fake ``osascript`` invocations; the production code's
``asyncio.create_subprocess_exec(...)`` call resolves to the registered
fake so we never actually spawn ``/usr/bin/osascript``.
"""

from __future__ import annotations

import pytest
from pytest_subprocess.fake_process import FakeProcess

from whatsapp_desktop_mcp.permissions.osascript import run_osascript


@pytest.mark.asyncio
async def test_run_osascript_parses_french_stderr_error_code(fp: FakeProcess) -> None:
    """P-PHASE0-02 regression: French stderr must yield error_code=-1743."""
    fp.register(
        ["/usr/bin/osascript", "-e", "foo"],
        # Verbatim shape of the user's machine output (fr_FR), including the
        # right-single-quotation-mark in "d'execution" that French macOS uses.
        stderr=(
            "0:30: erreur d’execution: Pas autorisé à envoyer "
            "des événements Apple à WhatsApp. (-1743)\n"
        ).encode(),
        returncode=1,
    )
    result = await run_osascript("foo", timeout=3.0)
    assert result.exit_code == 1
    assert result.error_code == -1743


@pytest.mark.asyncio
async def test_run_osascript_parses_english_stderr_error_code(fp: FakeProcess) -> None:
    """English stderr must yield the same error_code (locale-blind regex)."""
    fp.register(
        ["/usr/bin/osascript", "-e", "foo"],
        stderr=b"0:30: execution error: Not authorized to send Apple events to WhatsApp. (-1743)\n",
        returncode=1,
    )
    result = await run_osascript("foo", timeout=3.0)
    assert result.exit_code == 1
    assert result.error_code == -1743


@pytest.mark.asyncio
async def test_run_osascript_returns_none_error_code_on_clean_exit(fp: FakeProcess) -> None:
    """Clean exit -> error_code is None (no parenthesised code on stderr)."""
    fp.register(
        ["/usr/bin/osascript", "-e", "foo"],
        stdout=b"ok\n",
        returncode=0,
    )
    result = await run_osascript("foo", timeout=3.0)
    assert result.exit_code == 0
    assert result.stdout == "ok\n"
    assert result.error_code is None


@pytest.mark.asyncio
async def test_run_osascript_no_code_returns_none_error_code(fp: FakeProcess) -> None:
    """Non-zero exit with no trailing (-NNNN) -> error_code is None."""
    fp.register(
        ["/usr/bin/osascript", "-e", "foo"],
        stderr=b"some prose without a parenthesised code\n",
        returncode=1,
    )
    result = await run_osascript("foo", timeout=3.0)
    assert result.exit_code == 1
    assert result.error_code is None

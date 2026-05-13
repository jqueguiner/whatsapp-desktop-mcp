"""Accessibility probe tests — System Events + decision-matrix coverage.

The Accessibility probe runs
``osascript -e 'tell application "System Events" to count processes'``. When
Accessibility is granted, ``osascript`` exits 0 with a process count on
stdout. When it is not, ``-1719`` (errAEAccessibilityNotEnabled) or
``-25211`` (a wrapper variant seen on some Apple Communities reports) is
returned on stderr. Anything else falls through to the unexpected_result
branch (state=denied, safe default).

These tests use ``pytest-subprocess`` to register the exact probe command
``automation.py`` would invoke; the assertion grid mirrors the decision
matrix in ``00-RESEARCH.md`` §"AppleScript Probe Error Code Map".
"""

from __future__ import annotations

import pytest
from pytest_subprocess.fake_process import FakeProcess

from whatsapp_mcp.permissions.accessibility import check

_PROBE_CMD = [
    "/usr/bin/osascript",
    "-e",
    'tell application "System Events" to count processes',
]


@pytest.mark.asyncio
async def test_accessibility_granted(fp: FakeProcess) -> None:
    """Clean exit with stdout=process count -> state=granted."""
    fp.register(_PROBE_CMD, stdout=b"157\n", returncode=0)
    status = await check()
    assert status.bucket == "accessibility"
    assert status.state == "granted"
    assert "Privacy_Accessibility" in status.system_settings_url


@pytest.mark.asyncio
async def test_accessibility_denied_minus_1719(fp: FakeProcess) -> None:
    """error_code=-1719 (errAEAccessibilityNotEnabled) -> denied + Privacy_Accessibility URL."""
    fp.register(
        _PROBE_CMD,
        stderr=b"System Events got an error: not authorized. (-1719)\n",
        returncode=1,
    )
    status = await check()
    assert status.state == "denied"
    assert "Privacy_Accessibility" in status.system_settings_url
    assert "Accessibility" in status.remediation


@pytest.mark.asyncio
async def test_accessibility_denied_minus_25211(fp: FakeProcess) -> None:
    """error_code=-25211 (variant) -> state=denied (same branch as -1719)."""
    fp.register(
        _PROBE_CMD,
        stderr=b"System Events: accessibility framework deny. (-25211)\n",
        returncode=1,
    )
    status = await check()
    assert status.state == "denied"
    assert "Accessibility" in status.remediation


@pytest.mark.asyncio
async def test_accessibility_denied_on_unknown_code(fp: FakeProcess) -> None:
    """Unknown error_code -> state=denied via unexpected_result branch (safe default)."""
    fp.register(
        _PROBE_CMD,
        stderr=b"System Events got an error: something else. (-9999)\n",
        returncode=1,
    )
    status = await check()
    assert status.state == "denied"
    # The unexpected-result branch surfaces the diagnostic in the remediation hint.
    assert "unexpected" in status.remediation.lower()

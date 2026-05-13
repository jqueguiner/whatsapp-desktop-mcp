"""Automation probe tests — D-09 PATCHED probe + decision-matrix coverage.

The Automation probe queries WhatsApp's bundle id via
``osascript -e 'id of application "WhatsApp"'`` (the empirically corrected
form per CONTEXT.md D-09 PATCHED; the broken window-enumeration shape is
forbidden — see P-PHASE0-03). These tests mock that exact command via
``pytest-subprocess`` and assert every state in the decision matrix.

The most important assertion in this file is
``test_automation_handler_not_found_is_granted``: it codifies the empirical
finding that osascript exit 1 + stderr ``(-1708)`` means "the event reached
the app but the app doesn't implement that command" — which means the
Automation permission *is granted*. A future executor that "fixes"
``automation.py`` by removing the ``-1708 -> granted`` mapping will fail this
test loudly (P-PHASE0-03 regression guard).
"""

from __future__ import annotations

import pytest
from pytest_subprocess.fake_process import FakeProcess

from whatsapp_mcp.permissions.automation import check_whatsapp


@pytest.mark.asyncio
async def test_automation_granted(fp: FakeProcess) -> None:
    """Clean exit with stdout=net.whatsapp.WhatsApp -> state=granted."""
    fp.register(
        ["/usr/bin/osascript", "-e", 'id of application "WhatsApp"'],
        stdout=b"net.whatsapp.WhatsApp\n",
        returncode=0,
    )
    status = await check_whatsapp()
    assert status.bucket == "automation"
    assert status.state == "granted"
    assert "Privacy_Automation" in status.system_settings_url


@pytest.mark.asyncio
async def test_automation_denied_returns_minus_1743(fp: FakeProcess) -> None:
    """error_code=-1743 (errAEEventNotPermitted) -> state=denied with remediation."""
    fp.register(
        ["/usr/bin/osascript", "-e", 'id of application "WhatsApp"'],
        stderr=(
            b"0:30: execution error: Not authorized to send Apple events to WhatsApp. (-1743)\n"
        ),
        returncode=1,
    )
    status = await check_whatsapp()
    assert status.state == "denied"
    assert "Privacy_Automation" in status.system_settings_url
    assert "Automation" in status.remediation


@pytest.mark.asyncio
async def test_automation_whatsapp_not_installed(fp: FakeProcess) -> None:
    """error_code=-1728 (errAENoSuchObject) -> state=whatsapp_not_installed."""
    fp.register(
        ["/usr/bin/osascript", "-e", 'id of application "WhatsApp"'],
        stderr=b'0:0: execution error: Can\xe2\x80\x99t get application "WhatsApp". (-1728)\n',
        returncode=1,
    )
    status = await check_whatsapp()
    assert status.state == "whatsapp_not_installed"


@pytest.mark.asyncio
async def test_automation_handler_not_found_is_granted(fp: FakeProcess) -> None:
    """P-PHASE0-03 regression: error_code=-1708 (errAEEventNotHandled) -> state=granted.

    The event reached the app and Automation permission was honored — the app
    just doesn't implement the requested command. This is the empirically
    confirmed behavior of WhatsApp Catalyst when probed with shapes like
    ``tell ... to count windows`` (which is precisely why the corrected
    primary probe is ``id of application "WhatsApp"`` instead). If a future
    executor removes the -1708 -> granted mapping in automation.py, this test
    catches the regression.
    """
    fp.register(
        ["/usr/bin/osascript", "-e", 'id of application "WhatsApp"'],
        stderr=b"... (-1708)\n",
        returncode=1,
    )
    status = await check_whatsapp()
    assert status.state == "granted"


@pytest.mark.asyncio
async def test_automation_app_not_running_is_granted(fp: FakeProcess) -> None:
    """error_code=-600 (procNotFound, app not running) -> state=granted (permission is fine)."""
    fp.register(
        ["/usr/bin/osascript", "-e", 'id of application "WhatsApp"'],
        stderr=b"0:0: execution error: Application isn\xe2\x80\x99t running. (-600)\n",
        returncode=1,
    )
    status = await check_whatsapp()
    assert status.state == "granted"


@pytest.mark.asyncio
async def test_automation_unknown_error_is_denied(fp: FakeProcess) -> None:
    """Unknown error_code falls through to state=denied (safe default)."""
    fp.register(
        ["/usr/bin/osascript", "-e", 'id of application "WhatsApp"'],
        stderr=b"0:0: execution error: something unprecedented happened. (-9999)\n",
        returncode=1,
    )
    status = await check_whatsapp()
    assert status.state == "denied"
    assert "unexpected" in status.remediation.lower()

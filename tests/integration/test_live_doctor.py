"""Live end-to-end smoke test for the ``doctor`` MCP tool.

This test runs the real ``doctor`` tool against the live macOS environment
of the machine executing the test. It is decorated ``@pytest.mark.live`` and
is **skipped by default**: set ``RUN_LIVE=1`` in the environment to opt in.

CI (``pytest -m "not live"``) excludes it; release smoke runs
(``RUN_LIVE=1 pytest -m live``) include it. This is the P-PHASE0-07
mitigation from PLAN 00-04 — Plan 01 declared the ``live`` marker in
``[tool.pytest.ini_options].markers`` so ``--strict-markers`` does not
mis-fire here.

What the live test verifies that the mocked unit tests cannot:

- Real ``osascript`` invocation latency on the actual macOS Apple Events
  bus (the unit tests mock the boundary via ``pytest-subprocess``).
- Real ``os.stat`` against the real Group Container path resolved by
  ``whatsapp_desktop_mcp.paths.resolve_chatstorage_path()`` (the unit tests
  monkeypatch the resolver to a tmp file).
- Real Pydantic validation against the actual TCC states the user's
  machine reports (the unit tests construct ``PermissionStatus`` from
  registered fakes).

The test does **NOT** assert any particular state value — the maintainer's
machine state varies. The test only proves the report is well-formed
against a live system. (For reference, the maintainer's machine state on
2026-05-13 was all-``granted``; see ``00-03-SUMMARY.md`` "Live ``doctor()``
invocation transcript".)
"""

from __future__ import annotations

import os

import pytest

from whatsapp_desktop_mcp.tools.doctor import doctor


@pytest.mark.live
@pytest.mark.asyncio
async def test_doctor_returns_well_formed_report_on_live_system() -> None:
    """Live macOS smoke: doctor() returns a well-formed three-bucket DoctorReport."""
    # Belt-and-braces: the ``live`` marker alone suffices when the suite is
    # invoked as ``pytest -m "not live"`` (CI default), but a plain
    # ``pytest -m live`` invocation on an environment that did not opt in
    # would still attempt to run this test. The env-var skip protects
    # against that accidental invocation.
    if os.environ.get("RUN_LIVE") not in ("1", "true", "yes"):
        pytest.skip("set RUN_LIVE=1 to enable live macOS smoke tests")

    result = await doctor()

    # FDA bucket
    fda = result.full_disk_access
    assert fda.bucket == "fda"
    assert fda.state in {"granted", "denied", "whatsapp_not_installed"}
    assert fda.binary_path  # non-empty (sys.executable on the live runner)
    assert fda.system_settings_url.startswith("x-apple.systempreferences:")
    assert "Privacy_AllFiles" in fda.system_settings_url
    assert fda.db_path is not None
    assert fda.db_path.endswith("ChatStorage.sqlite")

    # Automation bucket
    automation = result.automation_whatsapp
    assert automation.bucket == "automation"
    assert automation.state in {"granted", "denied", "whatsapp_not_installed"}
    assert automation.binary_path
    assert automation.system_settings_url.startswith("x-apple.systempreferences:")
    assert "Privacy_Automation" in automation.system_settings_url

    # Accessibility bucket
    accessibility = result.accessibility
    assert accessibility.bucket == "accessibility"
    assert accessibility.state in {"granted", "denied", "whatsapp_not_installed"}
    assert accessibility.binary_path
    assert accessibility.system_settings_url.startswith("x-apple.systempreferences:")
    assert "Privacy_Accessibility" in accessibility.system_settings_url

    # The computed ``all_granted`` property must be a bool (not a Pydantic field).
    assert isinstance(result.all_granted, bool)

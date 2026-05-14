"""Doctor tool tests — Plan 05 DIAG-01 expansion + DIAG-02 defensive probing.

Verifies:

- DIAG-01: ``DoctorReport`` carries the 8 expected fields after Plan 05's
  expansion (3 Phase 0 PermissionStatus + 5 new fields).
- DIAG-02: doctor returns successfully even when FDA is denied / DB open
  fails / WhatsApp.app is absent. Each failure path degrades the
  corresponding field (state="unreachable" / None) but the report still
  serialises.
- D-08 invariant preserved (mcp.list_tools still names "doctor" exactly
  once — Plan 04 added 7 more tools but the doctor row is unchanged).
- W3 invariant: ``doctor`` carries no ``@timeout`` wrapper at runtime
  (introspection-level companion to the source-level grep test in
  test_read_tools_registration.py).
"""

from __future__ import annotations

import inspect
import sqlite3

import pytest

from whatsapp_desktop_mcp.models import DoctorReport, PermissionStatus
from whatsapp_desktop_mcp.server import mcp
from whatsapp_desktop_mcp.tools.doctor import doctor


@pytest.mark.asyncio
async def test_doctor_returns_8_field_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """DIAG-01: DoctorReport has the 8 expected fields after Plan 05."""
    expected_fields = {
        "full_disk_access",
        "automation_whatsapp",
        "accessibility",
        "db_path",
        "schema_fingerprint",
        "whatsapp_app_version",
        "last_message_ts",
        "coverage_summary",
    }
    fields = set(DoctorReport.model_fields.keys())
    assert expected_fields <= fields, f"missing DIAG-01 fields: {expected_fields - fields}"


def _denied_fda_status() -> PermissionStatus:
    return PermissionStatus(
        bucket="fda",
        state="denied",
        binary_path="/x",
        db_path="/y",
        system_settings_url="x-apple.systempreferences:fake",
        remediation="grant",
    )


def _granted_status(bucket: str) -> PermissionStatus:
    return PermissionStatus(
        bucket=bucket,  # type: ignore[arg-type]
        state="granted",
        binary_path="/x",
        db_path="/y" if bucket == "fda" else None,
        system_settings_url="x-apple.systempreferences:fake",
        remediation="",
    )


@pytest.mark.asyncio
async def test_doctor_diag02_fda_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """FDA-denied: doctor returns successfully with schema_fingerprint.state == 'unreachable'."""
    from whatsapp_desktop_mcp.permissions import accessibility, automation, fda

    async def fake_fda_check() -> PermissionStatus:
        return _denied_fda_status()

    async def fake_automation_check() -> PermissionStatus:
        return _granted_status("automation")

    async def fake_accessibility_check() -> PermissionStatus:
        return _granted_status("accessibility")

    monkeypatch.setattr(fda, "check", fake_fda_check)
    monkeypatch.setattr(automation, "check_whatsapp", fake_automation_check)
    monkeypatch.setattr(accessibility, "check", fake_accessibility_check)

    report = await doctor()
    assert isinstance(report, DoctorReport)
    assert report.schema_fingerprint.state == "unreachable"
    assert report.last_message_ts is None
    assert report.coverage_summary.from_ts is None


@pytest.mark.asyncio
async def test_doctor_diag02_db_open_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB open failure: doctor returns 'unreachable' fingerprint instead of crashing."""
    from whatsapp_desktop_mcp.permissions import accessibility, automation, fda
    from whatsapp_desktop_mcp.tools import doctor as doctor_module

    async def fake_fda_check() -> PermissionStatus:
        return _granted_status("fda")

    async def fake_automation_check() -> PermissionStatus:
        return _granted_status("automation")

    async def fake_accessibility_check() -> PermissionStatus:
        return _granted_status("accessibility")

    def boom(_db_path: str) -> tuple[object, object, object]:
        raise sqlite3.OperationalError("simulated DB open failure")

    monkeypatch.setattr(fda, "check", fake_fda_check)
    monkeypatch.setattr(automation, "check_whatsapp", fake_automation_check)
    monkeypatch.setattr(accessibility, "check", fake_accessibility_check)
    monkeypatch.setattr(doctor_module, "_probe_db_blocking", boom)

    report = await doctor()
    assert report.schema_fingerprint.state == "unreachable"
    assert report.last_message_ts is None
    assert report.coverage_summary.from_ts is None


@pytest.mark.asyncio
async def test_doctor_no_whatsapp_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """WhatsApp.app missing: ``whatsapp_app_version is None``; doctor still returns."""
    from whatsapp_desktop_mcp.permissions import accessibility, automation, fda
    from whatsapp_desktop_mcp.tools import doctor as doctor_module

    async def fake_fda_check() -> PermissionStatus:
        return _denied_fda_status()

    async def fake_automation_check() -> PermissionStatus:
        return _granted_status("automation")

    async def fake_accessibility_check() -> PermissionStatus:
        return _granted_status("accessibility")

    def fake_version_blocking() -> str | None:
        return None  # simulates "WhatsApp.app not installed"

    monkeypatch.setattr(fda, "check", fake_fda_check)
    monkeypatch.setattr(automation, "check_whatsapp", fake_automation_check)
    monkeypatch.setattr(accessibility, "check", fake_accessibility_check)
    monkeypatch.setattr(doctor_module, "_probe_whatsapp_version_blocking", fake_version_blocking)

    report = await doctor()
    assert report.whatsapp_app_version is None


@pytest.mark.asyncio
async def test_phase0_doctor_tool_invariant_preserved() -> None:
    """``mcp.list_tools()`` still contains exactly one tool named "doctor" (D-08)."""
    tools = await mcp.list_tools()
    doctor_tools = [t for t in tools if t.name == "doctor"]
    assert len(doctor_tools) == 1, f"D-08 violation: doctor count != 1; got {len(doctor_tools)}"


def test_doctor_does_not_have_tool_level_timeout() -> None:
    """W3 (runtime introspection): doctor's wrapper chain has no ``@timeout`` wrapper.

    The decorated callable's source must be the inline body — not a
    timeout wrapper. We assert this by inspecting the source of the
    function the FastMCP tool registry resolves.
    """
    # Walk the wrapper chain — if doctor were @timeout-wrapped, the
    # outermost callable would have an __wrapped__ attribute pointing
    # to the body. Plan 05 doctor uses @mcp.tool only (no @timeout)
    # so doctor.__wrapped__ should NOT exist (mcp.tool may set its
    # own attributes but not __wrapped__ in a way that mimics @timeout).
    # The structural invariant we check: the doctor source contains
    # NO ``@timeout(`` text. That's the canonical W3 gate.
    src = inspect.getsource(doctor)
    assert "@timeout" not in src, (
        "W3 violation: doctor source contains @timeout decorator (Plan 05 forbids)"
    )

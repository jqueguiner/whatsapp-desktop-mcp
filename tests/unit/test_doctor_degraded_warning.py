"""Plan 03-03 Task 1 — Doctor degraded-mode warning tests (RED → GREEN).

Verifies six behaviors:

5. ``SchemaFingerprint(...)`` constructed with the Phase 1 minimum kwargs has
   ``supported_version_range == (1, 1)`` and ``degraded_mode_warning is None``
   (CONTEXT.md D-20 default).
6. ``SchemaFingerprint(...)`` accepts non-default values for the two new
   fields (Pydantic field acceptance check).
7. doctor populates ``schema_fingerprint.supported_version_range`` from
   ``SUPPORTED_VERSION_RANGE`` regardless of WA version.
8. doctor sets ``schema_fingerprint.degraded_mode_warning`` to the structured
   string when ``wa_version`` is outside the tested matrix.
9. doctor leaves ``degraded_mode_warning is None`` when ``wa_version`` is
   inside the tested matrix.
10. ``DoctorReport.model_fields`` order: the 3 Phase 0 PermissionStatus fields
    come BEFORE the Phase 1 additions; the new SchemaFingerprint fields are
    appended INSIDE SchemaFingerprint, NOT at DoctorReport top level (Phase 0
    D-07 byte-stability invariant).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whatsapp_desktop_mcp.models import PermissionStatus
from whatsapp_desktop_mcp.models.doctor import DoctorReport, SchemaFingerprint


def _granted_status(bucket: str) -> PermissionStatus:
    return PermissionStatus(
        bucket=bucket,  # type: ignore[arg-type]
        state="granted",
        binary_path="/x",
        db_path="/y" if bucket == "fda" else None,
        system_settings_url="x-apple.systempreferences:fake",
        remediation="",
    )


def test_schema_fingerprint_default_supported_version_range_and_no_warning() -> None:
    """Test 5: defaults are ``(1, 1)`` and ``None`` (Phase 1 baseline)."""
    fp = SchemaFingerprint(
        state="supported",
        observed_version=1,
        supported_versions=[1],
    )
    assert fp.supported_version_range == (1, 1)
    assert fp.degraded_mode_warning is None


def test_schema_fingerprint_accepts_non_default_values() -> None:
    """Test 6: the two new fields accept user-supplied values."""
    warning = (
        "WhatsApp.app v26.99.0 not in tested-versions.md "
        "(last tested: 26.16.74); reads may degrade silently."
    )
    fp = SchemaFingerprint(
        state="supported",
        observed_version=1,
        supported_versions=[1],
        supported_version_range=(1, 3),
        degraded_mode_warning=warning,
    )
    assert fp.supported_version_range == (1, 3)
    assert fp.degraded_mode_warning == warning


def test_doctor_report_field_order_phase0_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 10: Phase 0 fields precede the Phase 1 additions; new fields live
    INSIDE SchemaFingerprint, NOT at DoctorReport top level (D-07 byte-stability).
    """
    fields = list(DoctorReport.model_fields.keys())
    # Phase 0 byte-stable order:
    assert fields[:3] == ["full_disk_access", "automation_whatsapp", "accessibility"]
    # The new SchemaFingerprint fields must NOT appear at DoctorReport top level.
    assert "supported_version_range" not in fields
    assert "degraded_mode_warning" not in fields
    # ...but they MUST appear on SchemaFingerprint.
    sf_fields = set(SchemaFingerprint.model_fields.keys())
    assert "supported_version_range" in sf_fields
    assert "degraded_mode_warning" in sf_fields


@pytest.mark.asyncio
async def test_doctor_populates_supported_version_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 7: doctor copies ``SUPPORTED_VERSION_RANGE`` onto the fingerprint.

    Mocks the live tested_versions path to (1, 2); after doctor() runs, the
    fingerprint's supported_version_range matches.
    """
    from whatsapp_desktop_mcp.permissions import accessibility, automation, fda
    from whatsapp_desktop_mcp.reader import tested_versions
    from whatsapp_desktop_mcp.tools import doctor as doctor_module

    table = tmp_path / "tv.md"
    table.write_text(
        "| WA | macOS | Z_VERSION |\n"
        "|----|-------|-----------|\n"
        "| 26.16.74 | 26.4 | 1 |\n"
        "| 27.0.0   | 26.5 | 2 |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tested_versions, "_TESTED_VERSIONS_PATH", table)
    # Force re-resolution: doctor reads SUPPORTED_VERSION_RANGE at call time.
    monkeypatch.setattr(
        tested_versions, "SUPPORTED_VERSION_RANGE", tested_versions.load_tested_z_versions()
    )

    async def fake_fda_check() -> PermissionStatus:
        return _granted_status("fda")

    async def fake_automation_check() -> PermissionStatus:
        return _granted_status("automation")

    async def fake_accessibility_check() -> PermissionStatus:
        return _granted_status("accessibility")

    async def fake_probe_db_safely(_db_path: str):  # type: ignore[no-untyped-def]
        from whatsapp_desktop_mcp.models.coverage import Coverage

        fp = SchemaFingerprint(
            state="supported",
            observed_version=1,
            supported_versions=[1],
            remediation="",
        )
        coverage = Coverage(
            from_ts=None,
            to_ts=None,
            asked_window_seconds=None,
            have_window_seconds=None,
            is_full=False,
        )
        return fp, None, coverage

    async def fake_probe_wa_version() -> str | None:
        return "26.16.74"

    monkeypatch.setattr(fda, "check", fake_fda_check)
    monkeypatch.setattr(automation, "check_whatsapp", fake_automation_check)
    monkeypatch.setattr(accessibility, "check", fake_accessibility_check)
    monkeypatch.setattr(doctor_module, "_probe_db_safely", fake_probe_db_safely)
    monkeypatch.setattr(doctor_module, "_probe_whatsapp_version", fake_probe_wa_version)

    report = await doctor_module.doctor()
    assert report.schema_fingerprint.supported_version_range == (1, 2)


@pytest.mark.asyncio
async def test_doctor_sets_degraded_warning_when_wa_version_oor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 8: WA version outside tested matrix → structured warning is set."""
    from whatsapp_desktop_mcp.models.coverage import Coverage
    from whatsapp_desktop_mcp.permissions import accessibility, automation, fda
    from whatsapp_desktop_mcp.reader import tested_versions
    from whatsapp_desktop_mcp.tools import doctor as doctor_module

    table = tmp_path / "tv.md"
    table.write_text(
        "| WA | macOS | Z_VERSION |\n"
        "|----|-------|-----------|\n"
        "| 26.16.74 | 26.4 | 1 |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tested_versions, "_TESTED_VERSIONS_PATH", table)
    monkeypatch.setattr(
        tested_versions, "SUPPORTED_VERSION_RANGE", tested_versions.load_tested_z_versions()
    )

    async def fake_fda_check() -> PermissionStatus:
        return _granted_status("fda")

    async def fake_automation_check() -> PermissionStatus:
        return _granted_status("automation")

    async def fake_accessibility_check() -> PermissionStatus:
        return _granted_status("accessibility")

    async def fake_probe_db_safely(_db_path: str):  # type: ignore[no-untyped-def]
        fp = SchemaFingerprint(
            state="supported",
            observed_version=1,
            supported_versions=[1],
            remediation="",
        )
        coverage = Coverage(
            from_ts=None,
            to_ts=None,
            asked_window_seconds=None,
            have_window_seconds=None,
            is_full=False,
        )
        return fp, None, coverage

    async def fake_probe_wa_version() -> str | None:
        return "26.99.0"  # NOT in the matrix

    monkeypatch.setattr(fda, "check", fake_fda_check)
    monkeypatch.setattr(automation, "check_whatsapp", fake_automation_check)
    monkeypatch.setattr(accessibility, "check", fake_accessibility_check)
    monkeypatch.setattr(doctor_module, "_probe_db_safely", fake_probe_db_safely)
    monkeypatch.setattr(doctor_module, "_probe_whatsapp_version", fake_probe_wa_version)

    report = await doctor_module.doctor()
    assert report.schema_fingerprint.degraded_mode_warning is not None
    assert "26.99.0" in report.schema_fingerprint.degraded_mode_warning
    assert "26.16.74" in report.schema_fingerprint.degraded_mode_warning
    assert "not in tested-versions.md" in report.schema_fingerprint.degraded_mode_warning


@pytest.mark.asyncio
async def test_doctor_leaves_degraded_warning_none_when_wa_version_in_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 9: WA version IN matrix → ``degraded_mode_warning is None``."""
    from whatsapp_desktop_mcp.models.coverage import Coverage
    from whatsapp_desktop_mcp.permissions import accessibility, automation, fda
    from whatsapp_desktop_mcp.reader import tested_versions
    from whatsapp_desktop_mcp.tools import doctor as doctor_module

    table = tmp_path / "tv.md"
    table.write_text(
        "| WA | macOS | Z_VERSION |\n"
        "|----|-------|-----------|\n"
        "| 26.16.74 | 26.4 | 1 |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tested_versions, "_TESTED_VERSIONS_PATH", table)
    monkeypatch.setattr(
        tested_versions, "SUPPORTED_VERSION_RANGE", tested_versions.load_tested_z_versions()
    )

    async def fake_fda_check() -> PermissionStatus:
        return _granted_status("fda")

    async def fake_automation_check() -> PermissionStatus:
        return _granted_status("automation")

    async def fake_accessibility_check() -> PermissionStatus:
        return _granted_status("accessibility")

    async def fake_probe_db_safely(_db_path: str):  # type: ignore[no-untyped-def]
        fp = SchemaFingerprint(
            state="supported",
            observed_version=1,
            supported_versions=[1],
            remediation="",
        )
        coverage = Coverage(
            from_ts=None,
            to_ts=None,
            asked_window_seconds=None,
            have_window_seconds=None,
            is_full=False,
        )
        return fp, None, coverage

    async def fake_probe_wa_version() -> str | None:
        return "26.16.74"  # IN matrix

    monkeypatch.setattr(fda, "check", fake_fda_check)
    monkeypatch.setattr(automation, "check_whatsapp", fake_automation_check)
    monkeypatch.setattr(accessibility, "check", fake_accessibility_check)
    monkeypatch.setattr(doctor_module, "_probe_db_safely", fake_probe_db_safely)
    monkeypatch.setattr(doctor_module, "_probe_whatsapp_version", fake_probe_wa_version)

    report = await doctor_module.doctor()
    assert report.schema_fingerprint.degraded_mode_warning is None

"""Exception hierarchy for the WhatsApp MCP.

Frozen public surface — Phase 1 tools import ``FullDiskAccessRequired``,
``AutomationPermissionRequired``, and ``AccessibilityPermissionRequired`` by
name. Renaming any of these classes, changing the ``bucket`` class attribute
literal values, or changing the ``system_settings_url`` strings is a breaking
change for downstream tools (CONTEXT.md D-12, PLAN 00-02 §"Interfaces this
plan publishes").

Phase 0 ships these classes but does NOT raise them — the ``doctor`` tool
returns a structured ``DoctorReport`` instead. Phase 1's read tools will be
the first to raise them when a probe fails for a real call (e.g. an
``os.stat`` against ``ChatStorage.sqlite`` returning ``EACCES`` becomes
``raise FullDiskAccessRequired(...)``).
"""

from __future__ import annotations


class WhatsAppMCPError(Exception):
    """Base class for all whatsapp-mcp errors. Never raise directly."""


class PermissionRequired(WhatsAppMCPError):
    """A required macOS TCC permission is not granted to the current process."""

    bucket: str = "unknown"  # subclasses override; one of: fda | automation | accessibility
    system_settings_url: str = ""

    def __init__(
        self,
        message: str,
        *,
        binary_path: str,
        db_path: str | None = None,
        remediation: str = "",
    ) -> None:
        super().__init__(message)
        self.binary_path = binary_path
        self.db_path = db_path
        self.remediation = remediation


class FullDiskAccessRequired(PermissionRequired):
    bucket = "fda"
    system_settings_url = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"


class AutomationPermissionRequired(PermissionRequired):
    bucket = "automation"
    system_settings_url = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"
    )


class AccessibilityPermissionRequired(PermissionRequired):
    bucket = "accessibility"
    system_settings_url = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    )

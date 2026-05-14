"""Frozen exception surface assertions for Phase 1.

Phase 1's read tools will ``from whatsapp_desktop_mcp.exceptions import
FullDiskAccessRequired, AutomationPermissionRequired,
AccessibilityPermissionRequired`` by name. Renaming any of these classes,
changing the ``bucket`` literal values, or changing the ``Privacy_*`` URL
substrings is a breaking change — these tests are the import-by-name guard.

D-12 (CONTEXT.md): the hierarchy is frozen public surface. Phase 0 ships the
classes but does NOT raise them; Phase 1 will. The constructor's
keyword-only ``binary_path`` / ``db_path`` / ``remediation`` payload
(verified by ``test_carries_remediation_payload``) is part of the frozen
surface — Phase 1 calls it as ``raise FullDiskAccessRequired(msg,
binary_path=sys.executable, db_path=resolve_chatstorage_path(),
remediation=...)``.
"""

from __future__ import annotations

from whatsapp_desktop_mcp.exceptions import (
    AccessibilityPermissionRequired,
    AutomationPermissionRequired,
    FullDiskAccessRequired,
    PermissionRequired,
    WhatsAppMCPError,
)


def test_permission_hierarchy_is_stable() -> None:
    """Phase 1 imports these by name; renaming any breaks Phase 1."""
    assert issubclass(FullDiskAccessRequired, PermissionRequired)
    assert issubclass(AutomationPermissionRequired, PermissionRequired)
    assert issubclass(AccessibilityPermissionRequired, PermissionRequired)
    assert issubclass(PermissionRequired, WhatsAppMCPError)


def test_subclass_buckets_and_urls() -> None:
    """``bucket`` literals and ``Privacy_*`` URL fragments are the frozen surface."""
    assert FullDiskAccessRequired.bucket == "fda"
    assert "Privacy_AllFiles" in FullDiskAccessRequired.system_settings_url
    assert AutomationPermissionRequired.bucket == "automation"
    assert "Privacy_Automation" in AutomationPermissionRequired.system_settings_url
    assert AccessibilityPermissionRequired.bucket == "accessibility"
    assert "Privacy_Accessibility" in AccessibilityPermissionRequired.system_settings_url


def test_carries_remediation_payload() -> None:
    """Constructor accepts the four keyword args that survive on the instance."""
    err = FullDiskAccessRequired(
        "no FDA",
        binary_path="/usr/bin/python3",
        db_path="/path/to/ChatStorage.sqlite",
        remediation="add it",
    )
    assert err.binary_path == "/usr/bin/python3"
    assert err.db_path == "/path/to/ChatStorage.sqlite"
    assert err.remediation == "add it"

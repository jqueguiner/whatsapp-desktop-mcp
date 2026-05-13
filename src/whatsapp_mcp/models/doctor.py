"""Public Pydantic v2 models for the ``doctor`` MCP tool.

Frozen public surface — Phase 1 reads ``DoctorReport`` and ``PermissionStatus``
by name and uses the ``PermissionState`` / ``PermissionBucket`` Literal aliases
in its own tool signatures. ``Literal`` is preferred over ``enum.Enum`` because
FastMCP's JSON-schema introspection (``mcp[cli]==1.27.1``) flows ``Literal``
through cleanly into the ``inputSchema`` / ``outputSchema`` it advertises to
clients (CONTEXT.md D-03).

The ``DoctorReport.all_granted`` accessor is a Python ``@property``, NOT a
Pydantic field — it is computed from the three ``PermissionStatus`` instances
and therefore must not appear in ``DoctorReport.model_fields`` / serialized
output (PLAN 00-02 Task 1 acceptance criterion).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PermissionState = Literal["granted", "denied", "whatsapp_not_installed"]
PermissionBucket = Literal["fda", "automation", "accessibility"]


class PermissionStatus(BaseModel):
    bucket: PermissionBucket
    state: PermissionState
    binary_path: str = Field(
        description=(
            "The exact filesystem path of the binary that needs the permission. "
            "User must add this path to the matching System Settings panel."
        ),
    )
    db_path: str | None = Field(
        default=None,
        description="Resolved path to ChatStorage.sqlite (only set for FDA bucket).",
    )
    system_settings_url: str = Field(
        description="x-apple.systempreferences: URL that opens the right TCC panel.",
    )
    remediation: str = Field(
        default="",
        description="One-line human instruction for fixing a denied state.",
    )


class DoctorReport(BaseModel):
    """Phase 0 doctor report. Phase 1 will extend this with schema_fingerprint, etc."""

    full_disk_access: PermissionStatus
    automation_whatsapp: PermissionStatus
    accessibility: PermissionStatus

    @property
    def all_granted(self) -> bool:
        return all(
            s.state == "granted"
            for s in (self.full_disk_access, self.automation_whatsapp, self.accessibility)
        )

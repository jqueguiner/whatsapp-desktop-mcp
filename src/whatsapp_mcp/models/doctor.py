"""Public Pydantic v2 models for the ``doctor`` MCP tool.

Frozen public surface — Phase 1 (Plan 01-05) extends ``DoctorReport`` with
five DIAG-01 fields and introduces the :class:`SchemaFingerprint` companion
model, **without** mutating the three Phase 0 ``PermissionStatus`` fields or
the ``all_granted`` accessor (D-07 byte-stability invariant).

``Literal`` is preferred over ``enum.Enum`` because FastMCP's JSON-schema
introspection (``mcp[cli]==1.27.1``) flows ``Literal`` through cleanly into
the ``inputSchema`` / ``outputSchema`` it advertises to clients
(CONTEXT.md D-03).

The ``DoctorReport.all_granted`` accessor is a Python ``@property``, NOT a
Pydantic field — it is computed from the three ``PermissionStatus`` instances
and therefore must not appear in ``DoctorReport.model_fields`` / serialized
output (PLAN 00-02 Task 1 acceptance criterion). DIAG-02 mandates
``all_granted`` reflect only the TCC permission probes, NOT schema /
WhatsApp-version reachability — a user with FDA granted but WhatsApp.app
uninstalled still has ``all_granted == True``.

Phase 1 surface additions (Plan 01-05, DIAG-01) — also frozen going
forward for downstream callers:

- :data:`SchemaState` — ``"supported" | "unsupported" | "unreachable"``.
- :class:`SchemaFingerprint` — ``Z_VERSION`` probe result with a sorted
  snapshot of the supported-versions set and a remediation message for the
  ``unsupported`` / ``unreachable`` states.
- 5 new ``DoctorReport`` fields: ``db_path``, ``schema_fingerprint``,
  ``whatsapp_app_version``, ``last_message_ts``, ``coverage_summary``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from whatsapp_mcp.models.coverage import Coverage

PermissionState = Literal["granted", "denied", "whatsapp_not_installed"]
PermissionBucket = Literal["fda", "automation", "accessibility"]

SchemaState = Literal["supported", "unsupported", "unreachable"]


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


class SchemaFingerprint(BaseModel):
    """Schema-version probe result (REL-04 + DIAG-01).

    Three possible states:

    - ``state="supported"`` — ``observed_version`` is in
      :data:`whatsapp_mcp.reader.SUPPORTED_VERSIONS`; read tools will work.
    - ``state="unsupported"`` — ``observed_version`` is set but outside
      the supported range; ``remediation`` carries the upgrade runbook hint
      (open an issue with the doctor JSON + ``CFBundleShortVersionString``
      + ``.schema ZWAMESSAGE``).
    - ``state="unreachable"`` — the DB could not be opened (FDA denied,
      file missing, or schema query failed); ``observed_version`` is
      ``None`` and ``remediation`` directs the user to grant FDA.
    """

    state: SchemaState = Field(
        description="Reachability + support classification of the live Z_VERSION.",
    )
    observed_version: int | None = Field(
        description=(
            "The ``Z_VERSION`` value read from ``Z_METADATA``; ``None`` when the "
            "DB couldn't be opened or the probe raised."
        ),
    )
    supported_versions: list[int] = Field(
        description=(
            "Sorted snapshot of ``reader.SUPPORTED_VERSIONS`` (frozenset is not "
            "JSON-serializable; convert to sorted list)."
        ),
    )
    remediation: str = Field(
        default="",
        description=(
            "Human-readable next step for the ``unsupported`` / ``unreachable`` "
            "states; empty string when ``state=='supported'``."
        ),
    )


class DoctorReport(BaseModel):
    """Phase 1 doctor report (DIAG-01 expansion of the Phase 0 3-field shape).

    The 3 Phase 0 ``PermissionStatus`` fields (``full_disk_access``,
    ``automation_whatsapp``, ``accessibility``) and the ``all_granted``
    accessor are byte-stable with Phase 0. Plan 01-05 appends 5 new fields
    AFTER them. ``all_granted`` deliberately considers only the 3 TCC
    permission states — a user with FDA granted but WhatsApp.app
    uninstalled still has ``all_granted == True`` (DIAG-02: doctor stays
    callable when other surfaces fail).
    """

    full_disk_access: PermissionStatus
    automation_whatsapp: PermissionStatus
    accessibility: PermissionStatus

    # Phase 1 ADDITIONS (DIAG-01) — see module docstring.
    db_path: str = Field(
        description=(
            "Resolved absolute path to ``ChatStorage.sqlite``. May not exist on "
            "disk if FDA is denied; doctor still returns it so the user knows "
            "what to grant access to."
        ),
    )
    schema_fingerprint: SchemaFingerprint = Field(
        description=(
            "``Z_VERSION`` probe result + supported-versions snapshot + "
            "degraded-mode remediation (REL-04)."
        ),
    )
    whatsapp_app_version: str | None = Field(
        default=None,
        description=(
            "``CFBundleShortVersionString`` from "
            "``/Applications/WhatsApp.app/Contents/Info.plist``; ``None`` when "
            "WhatsApp.app is not installed."
        ),
    )
    last_message_ts: int | None = Field(
        default=None,
        description=(
            "Unix timestamp (seconds) of the latest message across all chats. "
            "``None`` when DB unreadable or empty."
        ),
    )
    coverage_summary: Coverage = Field(
        description=(
            "Global cache coverage across all chats (P1 cache-vs-truth "
            "disclosure at the doctor level)."
        ),
    )

    @property
    def all_granted(self) -> bool:
        return all(
            s.state == "granted"
            for s in (self.full_disk_access, self.automation_whatsapp, self.accessibility)
        )

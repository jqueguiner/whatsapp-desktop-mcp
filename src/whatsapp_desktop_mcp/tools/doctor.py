"""The ``doctor`` MCP tool — preflight permission + DB-fingerprint report.

Phase 1 expansion (Plan 01-05): the body that shipped in Phase 0 with three
``PermissionStatus`` fields (FDA / Automation / Accessibility) now returns
five additional DIAG-01 fields — ``db_path``, ``schema_fingerprint``,
``whatsapp_app_version``, ``last_message_ts``, and ``coverage_summary``.
The Phase 0 three probes are preserved verbatim AND the ``@mcp.tool(...)``
registration block is the same one Phase 0 / Plan 01-04 shipped (D-08
invariant: exactly one tool named ``doctor`` exists in this module).

Annotation choices (all on the ``ToolAnnotations`` payload that FastMCP
advertises in ``tools/list``):

- read-only hint — the tool performs zero writes. ``os.stat`` /
  osascript / plistlib / ``?mode=ro`` SQLite are observably read-only.
- destructive hint set to false — no chat is ever sent, no DB row is
  touched.
- idempotent hint — running ``doctor`` twice yields identical payloads
  (modulo any TCC grant the user just changed in another window / a
  fresh message arriving in WhatsApp).
- closed-world hint — all I/O is against the local machine; no external
  services contacted.
- 60k-char response-budget meta annotation per W1 (Plan 01-04 lock):
  every tool, including ``doctor``, advertises the same response
  budget. ``DoctorReport`` is small (~1 KB), so the budget is never
  close to being hit; the annotation is structural so clients have a
  uniform contract across the entire tool surface.

**DIAG-02 (the diagnostic-path invariant).** ``doctor`` MUST remain
callable when other tools would fail. Each new probe lives in its own
private helper wrapped in a try/except block; failures degrade their
field to ``None`` / ``state="unreachable"`` annotations rather than
raising up to FastMCP. The Phase 0 probes already enforce this at the
osascript layer (D-10: 3 s subprocess timeout + structured
``PermissionStatus`` on every error path); Plan 01-05's helpers extend
the same discipline to plistlib and SQLite.

**W3 lock (no outer per-tool timeout).** The original Plan 01-04
framing applied the per-tool timeout decorator to every tool.
RESEARCH §"Per-Tool Timeouts (REL-03)" was revised post-W3 to remove
the doctor row entirely: a tool-level timeout fires mid-probe and
returns a partial ``DoctorReport`` that violates DIAG-02. The existing
Phase 0 probes carry their own 3 s osascript timeouts, and the new
``_probe_db_safely`` / ``_probe_whatsapp_version`` helpers own their
defensive exception handling + bounded I/O. Adding a per-tool timeout
decorator here would be a regression — do NOT add it.

**Import-order invariant (P-PHASE0-06).** This module imports
``from whatsapp_desktop_mcp.server import mcp``, and ``server`` imports
``from whatsapp_desktop_mcp.tools import doctor as _doctor`` AFTER its
``mcp = FastMCP(...)`` line. The ordering is documented in ``server.py``;
breaking it would cause a circular ``ImportError`` on first ``import``.

The three Phase 0 probes still run **sequentially** with ``await``; the
Phase 1 additions follow them (FDA-gated for the SQLite probe — reading
the WA app's Info.plist does NOT need FDA). Switching to
``asyncio.gather`` for the permission triplet is a Phase 3 optimisation
if ever needed.
"""

from __future__ import annotations

import asyncio
import plistlib
import sqlite3

from mcp.types import ToolAnnotations

from whatsapp_desktop_mcp.models.coverage import Coverage
from whatsapp_desktop_mcp.models.doctor import DoctorReport, SchemaFingerprint
from whatsapp_desktop_mcp.paths import resolve_chatstorage_path
from whatsapp_desktop_mcp.permissions import accessibility, automation, fda
from whatsapp_desktop_mcp.reader.connection import open_ro
from whatsapp_desktop_mcp.reader.schema_v1 import (
    SUPPORTED_VERSIONS,
    is_supported,
    probe_z_version,
)
from whatsapp_desktop_mcp.server import mcp
from whatsapp_desktop_mcp.time import cocoa_to_unix

# Canonical macOS WhatsApp.app Info.plist path. The directory is
# system-protected (admin to write to ``/Applications``); reading does
# NOT require Full Disk Access (it's a public app-bundle resource).
_WHATSAPP_INFO_PLIST_PATH = "/Applications/WhatsApp.app/Contents/Info.plist"


def _probe_whatsapp_version_blocking() -> str | None:
    """Read ``CFBundleShortVersionString`` from WhatsApp.app's Info.plist.

    Returns ``None`` when WhatsApp.app is not installed, the plist is
    malformed, or the version key is absent. Never raises — DIAG-02.
    """
    try:
        with open(_WHATSAPP_INFO_PLIST_PATH, "rb") as fp:  # noqa: PTH123 — stdlib open is fine here
            data = plistlib.load(fp)
    except (FileNotFoundError, PermissionError, plistlib.InvalidFileException, OSError):
        return None
    version = data.get("CFBundleShortVersionString")
    if isinstance(version, str):
        return version
    return None


async def _probe_whatsapp_version() -> str | None:
    """Dispatch :func:`_probe_whatsapp_version_blocking` via ``asyncio.to_thread``.

    Reading the Info.plist is bounded I/O (the file is ~13 KB) but stays
    off the event loop per REL-02. Returns ``None`` on any failure.
    """
    return await asyncio.to_thread(_probe_whatsapp_version_blocking)


def _probe_db_blocking(db_path: str) -> tuple[SchemaFingerprint, int | None, Coverage]:
    """Run schema + last-message-ts + global-coverage probes in one RO connection.

    Caller (:func:`_probe_db_safely`) wraps this in try/except to enforce
    DIAG-02. This blocking helper assumes the connection can be opened;
    if it can't (FDA denied, file missing, schema query failed) the
    exception propagates to the caller's fallback branch.
    """
    with open_ro(db_path) as conn:
        version = probe_z_version(conn)
        row = conn.execute("SELECT MIN(ZMESSAGEDATE), MAX(ZMESSAGEDATE) FROM ZWAMESSAGE").fetchone()

    if is_supported(version):
        fingerprint = SchemaFingerprint(
            state="supported",
            observed_version=version,
            supported_versions=sorted(SUPPORTED_VERSIONS),
            remediation="",
        )
    else:
        fingerprint = SchemaFingerprint(
            state="unsupported",
            observed_version=version,
            supported_versions=sorted(SUPPORTED_VERSIONS),
            remediation=(
                f"Schema version {version} not in supported set "
                f"{sorted(SUPPORTED_VERSIONS)}. Open a bug report with the doctor "
                "output, the CFBundleShortVersionString of /Applications/WhatsApp.app, "
                "and the output of `sqlite3 ChatStorage.sqlite '.schema ZWAMESSAGE'`."
            ),
        )

    min_cocoa = row[0] if row is not None else None
    max_cocoa = row[1] if row is not None else None
    from_ts = cocoa_to_unix(float(min_cocoa)) if min_cocoa is not None else None
    to_ts = cocoa_to_unix(float(max_cocoa)) if max_cocoa is not None else None
    have_window_seconds = (to_ts - from_ts) if (from_ts is not None and to_ts is not None) else None
    coverage = Coverage(
        from_ts=from_ts,
        to_ts=to_ts,
        asked_window_seconds=None,
        have_window_seconds=have_window_seconds,
        is_full=False,
    )
    last_ts = to_ts
    return fingerprint, last_ts, coverage


async def _probe_db_safely(db_path: str) -> tuple[SchemaFingerprint, int | None, Coverage]:
    """Defensive wrapper around :func:`_probe_db_blocking` (DIAG-02).

    On any SQLite / filesystem failure, returns an "unreachable"
    ``SchemaFingerprint`` + ``None`` last-ts + empty ``Coverage`` instead
    of raising. The doctor tool MUST stay callable; a hard failure here
    would blind the user's diagnostic path.
    """
    try:
        return await asyncio.to_thread(_probe_db_blocking, db_path)
    except (
        sqlite3.OperationalError,
        sqlite3.DatabaseError,
        FileNotFoundError,
        PermissionError,
        RuntimeError,
        OSError,
    ):
        fingerprint = SchemaFingerprint(
            state="unreachable",
            observed_version=None,
            supported_versions=sorted(SUPPORTED_VERSIONS),
            remediation=(
                "Cannot read DB until Full Disk Access is granted to the running "
                "binary (or ChatStorage.sqlite is otherwise unreadable). Run "
                "doctor again after granting FDA in System Settings → Privacy & "
                "Security → Full Disk Access."
            ),
        )
        coverage = Coverage(
            from_ts=None,
            to_ts=None,
            asked_window_seconds=None,
            have_window_seconds=None,
            is_full=False,
        )
        return fingerprint, None, coverage


@mcp.tool(
    name="doctor",
    title="Doctor — preflight permission check",
    description=(
        "Reports whether the three macOS permissions the WhatsApp MCP needs "
        "(Full Disk Access, Apple Events / Automation for WhatsApp, Accessibility) "
        "are granted to the current process; additionally reports the resolved "
        "ChatStorage.sqlite path, the live schema fingerprint, the installed "
        "WhatsApp.app version, the latest-message Unix timestamp, and the global "
        "cache coverage window. Safe to call any time; performs no I/O against "
        "WhatsApp's data beyond a single short-lived read-only SQLite probe and "
        "does not require WhatsApp to be running."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    meta={"anthropic/maxResultSizeChars": 60_000},
)
async def doctor() -> DoctorReport:
    """Run the three permission probes + four DB / WhatsApp.app probes."""
    # Phase 0 probes (PRESERVED EXACTLY — order + sequential await unchanged)
    fda_status = await fda.check()
    automation_status = await automation.check_whatsapp()
    accessibility_status = await accessibility.check()

    # Phase 1 additions (DIAG-01 + DIAG-02 defensive probing)
    db_path = resolve_chatstorage_path()
    if fda_status.state == "granted":
        schema_fp, last_ts, coverage = await _probe_db_safely(db_path)
    else:
        schema_fp = SchemaFingerprint(
            state="unreachable",
            observed_version=None,
            supported_versions=sorted(SUPPORTED_VERSIONS),
            remediation=(
                "Grant Full Disk Access to read the WhatsApp DB; until then "
                "schema/coverage cannot be probed."
            ),
        )
        last_ts = None
        coverage = Coverage(
            from_ts=None,
            to_ts=None,
            asked_window_seconds=None,
            have_window_seconds=None,
            is_full=False,
        )

    # WhatsApp.app version probe is independent of FDA — Info.plist is a
    # public app-bundle resource (not in a TCC-protected container).
    wa_version = await _probe_whatsapp_version()

    return DoctorReport(
        full_disk_access=fda_status,
        automation_whatsapp=automation_status,
        accessibility=accessibility_status,
        db_path=db_path,
        schema_fingerprint=schema_fp,
        whatsapp_app_version=wa_version,
        last_message_ts=last_ts,
        coverage_summary=coverage,
    )

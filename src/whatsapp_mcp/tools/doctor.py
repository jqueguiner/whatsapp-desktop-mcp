"""The ``doctor`` MCP tool — preflight permission report.

This is the **only** ``tools/list`` entry shipped in Phase 0 (D-08). It runs
the three permission probes (FDA / Automation / Accessibility) and returns a
``DoctorReport`` with one ``PermissionStatus`` per bucket. No SQLite read, no
schema fingerprinting, no WhatsApp version detection — those land in Phase 1
(D-07).

Annotation choices (all on the ``ToolAnnotations`` payload that FastMCP
advertises in ``tools/list``):

- ``readOnlyHint=True`` — the tool performs zero writes. ``os.stat`` and
  ``osascript -e 'id of application "WhatsApp"'`` are observably read-only.
- ``destructiveHint=False`` — no chat is ever sent, no DB row is touched.
- ``idempotentHint=True`` — running ``doctor`` twice yields identical
  payloads (modulo any TCC grant the user just changed in another window).
- ``openWorldHint=False`` — all I/O is against the local machine; no
  external services contacted.
- ``meta={"anthropic/maxResultSizeChars": 60000}`` — Plan 01-04 W1 lock:
  every tool, including ``doctor``, advertises the 60k-char response
  budget. ``DoctorReport`` is small (3 ``PermissionStatus`` rows), so the
  budget is never close to being hit; the annotation is structural so
  clients have a uniform contract across the entire tool surface.

**Import-order invariant (P-PHASE0-06).** This module imports
``from whatsapp_mcp.server import mcp``, and ``server`` imports
``from whatsapp_mcp.tools import doctor as _doctor`` AFTER its
``mcp = FastMCP(...)`` line. The ordering is documented in ``server.py``;
breaking it would cause a circular ``ImportError`` on first ``import``.

The three probes run **sequentially** with ``await``; the verbatim source
shape is correct for Phase 0 and well within any reasonable tool timeout
(worst case ≈ 3 × 3s probe timeouts = 9s wall-clock if every probe maxes
out, which only happens if WhatsApp is hung). Switching to
``asyncio.gather`` is a Phase 1 optimisation if ever needed.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from whatsapp_mcp.models.doctor import DoctorReport
from whatsapp_mcp.permissions import accessibility, automation, fda
from whatsapp_mcp.server import mcp


@mcp.tool(
    name="doctor",
    title="Doctor — preflight permission check",
    description=(
        "Reports whether the three macOS permissions the WhatsApp MCP needs "
        "(Full Disk Access, Apple Events / Automation for WhatsApp, Accessibility) "
        "are granted to the current process. Safe to call any time; performs no I/O "
        "against WhatsApp's data and does not require WhatsApp to be running."
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
    """Run the three permission probes and assemble the report."""
    return DoctorReport(
        full_disk_access=await fda.check(),
        automation_whatsapp=await automation.check_whatsapp(),
        accessibility=await accessibility.check(),
    )

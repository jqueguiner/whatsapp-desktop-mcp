"""JSONL audit log for WhatsApp send attempts (D-12 / D-13 / D-14, SEND-06).

Backing store: ``~/Library/Logs/whatsapp-desktop-mcp/audit.log`` (mode ``0o600``).
One :class:`AuditEntry` JSON object per send attempt — successful sends,
cancellations, rate-limit hits, and errors all produce exactly one
line. The :class:`AuditEntry` Pydantic schema is the frozen v0.1 audit
contract; downstream tooling (ban-recovery investigation, rate-limit
tuning, compromise detection) reads the file line-by-line and parses
each line as a self-contained JSON object.

D-13: body is NEVER plaintext-logged
====================================
Only ``body_sha256`` (64-char lowercase hex) appears in each row. The
audit log's three use cases (ban-recovery investigation, rate-limit
tuning, detecting compromise) need NONE of plaintext bodies; ALL of
them leak privately if the log file is exfiltrated. An investigator
who *needs* to confirm a specific body matches a logged row can
re-hash the candidate body and compare hex — the SHA-256 fingerprint
preserves auditability without preserving content.

This invariant is enforced STRUCTURALLY by :class:`AuditEntry`'s
schema: there is no ``body`` field, no ``body_text`` field, no
``body_preview`` field. Pydantic cannot serialize what it isn't
declared to hold. The regression test
``test_send_message_appends_audit_log_with_body_sha256_not_body``
(Plan 02-05) asserts via reflection that ``AuditEntry.model_fields``
contains no body-shaped keys.

D-12 / D-14: append-only, line-buffered, no rotation in v0.1
============================================================
The file is opened in line-buffered mode (Python's standard
file-buffer policy where each newline flushes the buffer to disk):
each :class:`AuditEntry` hits disk on its trailing ``\\n``. This
matters for audit integrity if the server crashes mid-send — a
partially written line is the worst the user can lose, never a
half-written row.

No log rotation. The file grows unbounded; users who care can
``truncate -s 0 audit.log`` manually or wait for Phase 3 to add
rotation. v0.1 doesn't ship a daemon, so there's no rotation cron.

Multi-instance race (Pitfall 9) — deferred to Phase 3
======================================================
Two MCP server instances appending to the same file under concurrent
writes CAN interleave lines (no ``fcntl.flock`` in v0.1). The
supported v0.1 config is a single MCP server instance per user
machine; README documents this. Phase 3 candidate: wrap
:func:`_blocking_append` in ``flock(LOCK_EX)`` to serialize
cross-process appends.

REL-05 D-24 invariant
=====================
This module imports from ``whatsapp_desktop_mcp.*`` only via standard
Pydantic — no reader, no exceptions, no models. The Pydantic class
defined here (:class:`AuditEntry`) is re-exported through
``whatsapp_desktop_mcp.models.__init__`` so the public tool tier imports it
through the ``models`` package uniformly (the Pydantic class
physically lives here; ``models/`` is the public re-export point —
matches the source-of-truth pattern used by Phase 1's reader-side
models).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

_LOG_DIR = Path.home() / "Library" / "Logs" / "whatsapp-desktop-mcp"
_LOG_PATH = _LOG_DIR / "audit.log"

# Phase 3 Plan 03-03 (D-25 / D-26 / D-28) — size-based rotation.
# 10 MB ≈ 50k JSONL entries ≈ several years of personal use; 5 archives
# = ~50 MB worst-case disk. Threshold is overridable via env var
# (set by cli.main from the --audit-log-max-bytes arg) so the rotation
# can be exercised in tests with a small ceiling.
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_ENV_MAX_BYTES = "WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES"
_ARCHIVE_COUNT = 5

Outcome = Literal[
    "sent",
    "sent_unverified",
    "cancelled",
    "rate_limited",
    "error",
]


# ---------------------------------------------------------------------------
# Pydantic schema — FROZEN v0.1
# ---------------------------------------------------------------------------


class AuditEntry(BaseModel):
    """One line of ``audit.log``. Frozen v0.1 schema (D-12).

    D-13 STRUCTURAL invariant: NO ``body`` / ``body_text`` /
    ``body_preview`` field. Only ``body_sha256`` (64-char lowercase hex).
    The Pydantic schema cannot serialize what isn't declared; the
    Plan 02-05 regression test reflects on ``model_fields`` to
    assert no body-shaped key sneaks in via a future refactor.
    """

    ts: int = Field(default_factory=lambda: int(time.time()))
    chat_id: int
    chat_name: str
    body_sha256: str
    outcome: Outcome
    message_id: str | None = None
    error: str | None = None
    confirm_skipped: bool = False
    elapsed_ms: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def body_sha256(body: str) -> str:
    """Return the SHA-256 fingerprint of ``body`` as 64-char lowercase hex.

    The single source of truth for the audit log's body-hash convention.
    Plan 02-03's send tool uses this for both the audit ``body_sha256``
    field and the rate-limit ``body_sha256`` argument so the two
    persisted artifacts share an identical fingerprint for any given
    send.
    """
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _resolve_max_bytes() -> int:
    """Resolve the rotation threshold from env, falling back to the default.

    Phase 3 Plan 03-03 (D-25 / D-28). Reads
    ``WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES`` at call time so a test or
    a runtime ``--audit-log-max-bytes`` change is observed on the next
    append. ``ValueError``-safe: garbage input falls back to the default
    rather than crashing the audit path (DIAG-02 spirit — the log must
    keep accepting writes).
    """
    val = os.environ.get(_ENV_MAX_BYTES)
    if not val:
        return _DEFAULT_MAX_BYTES
    try:
        return max(1, int(val))
    except ValueError:
        return _DEFAULT_MAX_BYTES


def _rotate_in_place(path: Path, archive_count: int) -> None:
    """Rotate ``path`` to ``path.1``, shifting existing ``path.N`` upward.

    Walks from the OLDEST archive downward to the NEWEST so no archive is
    overwritten before its content is moved (the inversion guard from
    Pitfall 5). The eldest archive (``path.{archive_count}``) is deleted
    before its slot is reused — the 5-archive cap evicts the oldest
    rotation when a 6th would land.

    D-13 STRUCTURAL invariant preserved by construction: rotation moves
    ENTIRE JSONL lines via :meth:`Path.rename`; the AuditEntry schema has
    ``body_sha256: str`` only (no raw ``body`` field), so rotated archives
    are byte-identical to the live log up to the rotation point and
    cannot leak any content the live log didn't already carry.
    """
    eldest = path.with_suffix(path.suffix + f".{archive_count}")
    if eldest.exists():
        eldest.unlink()
    for i in range(archive_count - 1, 0, -1):
        src = path.with_suffix(path.suffix + f".{i}")
        dst = path.with_suffix(path.suffix + f".{i + 1}")
        if src.exists():
            src.rename(dst)
    if path.exists():
        path.rename(path.with_suffix(path.suffix + ".1"))


def _blocking_append(entry_json: str) -> None:
    """Append one JSONL line to :data:`_LOG_PATH`, line-buffered, mode 0600.

    Creates the parent directory on first call. Sets the file mode to
    ``0o600`` once, after the create — the file does not exist when
    ``chmod`` would otherwise target it; the create-then-chmod ordering
    is the standard pattern.

    The file is opened in line-buffered mode (Python flushes the
    buffer on every newline), so the trailing ``\\n`` flushes the
    line to disk. This is important for audit integrity if the server
    crashes mid-send (D-14).

    Phase 3 Plan 03-03 (D-25 / D-26): if the live log is at or over the
    rotation threshold, rotate BEFORE the write. Rotation makes the live
    path non-existent so the subsequent ``is_new = not _LOG_PATH.exists()``
    branch fires and the fresh file gets ``mode 0600`` reapplied — the
    Phase 2 mode invariant carries through rotation automatically.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    if _LOG_PATH.exists() and _LOG_PATH.stat().st_size >= _resolve_max_bytes():
        _rotate_in_place(_LOG_PATH, _ARCHIVE_COUNT)
    is_new = not _LOG_PATH.exists()
    with open(_LOG_PATH, "a", buffering=1, encoding="utf-8") as fp:
        fp.write(entry_json + "\n")
    if is_new:
        os.chmod(_LOG_PATH, 0o600)


async def append(entry: AuditEntry) -> None:
    """Async wrapper for :func:`_blocking_append` (REL-02).

    Serializes ``entry`` via ``model_dump_json`` (Pydantic v2 idiom — the
    canonical JSON path; handles datetime / nested serialization
    correctly even though the v0.1 schema is flat) and dispatches the
    file write to a worker thread so the event loop is never blocked
    on disk I/O.
    """
    payload = entry.model_dump_json()
    await asyncio.to_thread(_blocking_append, payload)

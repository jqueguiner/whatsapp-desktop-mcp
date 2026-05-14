"""Unit tests for ``sender.audit`` — D-12 / D-13 / D-14 / SEND-06.

Covers:

* **D-13 SCHEMA-LEVEL STRUCTURAL invariant** — ``AuditEntry`` has NO
  ``body`` / ``body_text`` / ``body_preview`` field. Reflected via
  ``AuditEntry.model_fields``.
* :data:`Outcome` literal includes exactly the 5 enum values per D-12.
* ``append`` round-trips: writes one JSONL line readable as
  :class:`AuditEntry`; mode 0600 on first create; no plaintext body
  field in the serialized line.
* ``body_sha256`` produces 64-char lowercase hex SHA-256.
* :class:`AuditEntry` validation rejects bogus outcome values.

All file-write tests use the ``tmp_audit_log`` fixture so the
maintainer's real audit log is never touched.
"""

from __future__ import annotations

import json
import os
import typing
from pathlib import Path

import pytest
from pydantic import ValidationError

from whatsapp_desktop_mcp.sender import audit
from whatsapp_desktop_mcp.sender.audit import AuditEntry, Outcome, body_sha256

# ---------------------------------------------------------------------------
# D-13 SCHEMA-LEVEL STRUCTURAL invariant — no body field, ever
# ---------------------------------------------------------------------------


def test_audit_entry_schema_has_no_plaintext_body_field() -> None:
    """D-13 STRUCTURAL: AuditEntry has NO body / body_text / body_preview field.

    The audit log's three use cases (ban-recovery investigation,
    rate-limit tuning, compromise detection) need NONE of plaintext
    bodies and ALL of them leak privately if the log file is
    exfiltrated. Pydantic cannot serialize what isn't declared to hold;
    this schema-level test reflects on ``model_fields`` to assert no
    body-shaped key sneaks in via a future refactor.
    """
    fields = set(AuditEntry.model_fields.keys())
    assert "body" not in fields
    assert "body_text" not in fields
    assert "body_preview" not in fields


def test_audit_entry_only_body_sha256_field() -> None:
    """The only body-shaped field is ``body_sha256`` (the hex fingerprint)."""
    fields = set(AuditEntry.model_fields.keys())
    # Exactly one body-related field; named explicitly per the D-13 contract.
    body_related = {f for f in fields if "body" in f}
    assert body_related == {"body_sha256"}


# ---------------------------------------------------------------------------
# Outcome literal — D-12 5-value enum
# ---------------------------------------------------------------------------


def test_outcome_literal_values() -> None:
    """:data:`Outcome` has exactly the 5 enum values per D-12."""
    expected = ("sent", "sent_unverified", "cancelled", "rate_limited", "error")
    assert typing.get_args(Outcome) == expected


def test_audit_entry_rejects_bogus_outcome() -> None:
    """A non-enum outcome value → :class:`ValidationError`."""
    with pytest.raises(ValidationError):
        AuditEntry(
            chat_id=1,
            chat_name="Alice",
            body_sha256="a" * 64,
            outcome="bogus",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# body_sha256 helper
# ---------------------------------------------------------------------------


def test_body_sha256_helper_returns_64_char_lowercase_hex() -> None:
    """``body_sha256("hello")`` matches the standard SHA-256 hex digest."""
    import hashlib

    expected = hashlib.sha256(b"hello").hexdigest()
    actual = body_sha256("hello")
    assert actual == expected
    assert len(actual) == 64
    assert actual == actual.lower()  # all-lowercase


def test_body_sha256_handles_unicode() -> None:
    """``body_sha256`` handles non-ASCII bodies via UTF-8 encoding."""
    import hashlib

    body = "héllo 🎉"
    expected = hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert body_sha256(body) == expected


# ---------------------------------------------------------------------------
# append — round-trip with file-level guarantees
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_roundtrip_to_tmp_path(tmp_audit_log: Path) -> None:
    """One append writes a valid JSONL line readable as ``AuditEntry``."""
    entry = AuditEntry(
        chat_id=42,
        chat_name="Alice",
        body_sha256=body_sha256("hello world"),
        outcome="sent",
        message_id="STANZA-X",
        confirm_skipped=False,
        elapsed_ms=123,
    )

    await audit.append(entry)

    # File exists; one line; parses as JSON; round-trips through AuditEntry.
    raw = tmp_audit_log.read_text(encoding="utf-8")
    assert raw.endswith("\n"), "JSONL line must terminate with newline (D-14)"
    parsed = json.loads(raw.strip())
    assert parsed["chat_id"] == 42
    assert parsed["chat_name"] == "Alice"
    assert parsed["outcome"] == "sent"
    # D-13 runtime invariant: NO body / body_text / body_preview key in the JSON.
    assert "body" not in parsed
    assert "body_text" not in parsed
    assert "body_preview" not in parsed
    # Round-trip the line through the schema.
    round_tripped = AuditEntry.model_validate(parsed)
    assert round_tripped.chat_id == entry.chat_id
    assert round_tripped.body_sha256 == entry.body_sha256


@pytest.mark.asyncio
async def test_append_sets_mode_0600_on_first_create(tmp_audit_log: Path) -> None:
    """First append creates the file with mode ``0o600``."""
    entry = AuditEntry(
        chat_id=1,
        chat_name="Alice",
        body_sha256="a" * 64,
        outcome="sent",
    )

    await audit.append(entry)

    mode = tmp_audit_log.stat().st_mode & 0o777
    assert mode == 0o600, f"expected mode 0o600 on first create; got {oct(mode)}"


@pytest.mark.asyncio
async def test_append_does_not_re_chmod_existing(
    tmp_audit_log: Path,
) -> None:
    """If the file pre-exists, mode is NOT modified (chmod runs on create only).

    Pattern 6 lock: ``is_new`` is computed BEFORE the open call, so the
    create-then-chmod path runs only on the first ever append. If a user
    has manually chmod'd the file to 0644 (their choice), subsequent
    appends respect that.
    """
    # Pre-create the file with mode 0644.
    tmp_audit_log.parent.mkdir(parents=True, exist_ok=True)
    tmp_audit_log.write_text("")
    os.chmod(tmp_audit_log, 0o644)
    assert tmp_audit_log.stat().st_mode & 0o777 == 0o644

    entry = AuditEntry(
        chat_id=1,
        chat_name="Alice",
        body_sha256="a" * 64,
        outcome="sent",
    )
    await audit.append(entry)

    # Mode stays 0644 — chmod did NOT re-run.
    mode = tmp_audit_log.stat().st_mode & 0o777
    assert mode == 0o644, f"pre-existing file mode mutated; got {oct(mode)}"


@pytest.mark.asyncio
async def test_append_writes_multiple_lines_in_order(tmp_audit_log: Path) -> None:
    """N appends produce N newline-terminated JSONL lines in call order."""
    outcomes: list[Outcome] = ["sent", "cancelled", "rate_limited"]
    for outcome in outcomes:
        entry = AuditEntry(
            chat_id=1,
            chat_name="Alice",
            body_sha256="a" * 64,
            outcome=outcome,
        )
        await audit.append(entry)

    raw = tmp_audit_log.read_text(encoding="utf-8")
    lines = [line for line in raw.split("\n") if line]
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert [p["outcome"] for p in parsed] == ["sent", "cancelled", "rate_limited"]


@pytest.mark.asyncio
async def test_append_body_sha256_appears_in_line_but_not_plaintext_body(
    tmp_audit_log: Path,
) -> None:
    """The hex fingerprint appears; the original body string does NOT.

    Belt-and-braces on the D-13 STRUCTURAL invariant: even when a
    contributor explicitly stuffs a body-shaped string into a NON-body
    field, the canonical body string itself must not surface as a
    substring of the logged JSONL line. We test the structural form
    here (body_sha256 present; body absent) and the runtime form in
    test_send_message.py (the actual orchestrator's audit-append call).
    """
    body = "this is the secret body that must never appear in the log"
    sha = body_sha256(body)

    entry = AuditEntry(
        chat_id=1,
        chat_name="Alice",
        body_sha256=sha,
        outcome="sent",
    )
    await audit.append(entry)

    raw = tmp_audit_log.read_text(encoding="utf-8")
    # The hex fingerprint must be present in the line.
    assert sha in raw
    # The plaintext body must NOT appear anywhere in the line.
    assert body not in raw

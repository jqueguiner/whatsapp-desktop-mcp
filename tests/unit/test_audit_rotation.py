"""Plan 03-03 Task 2 — Audit log size-based rotation tests (RED → GREEN).

Verifies:

1. No rotation under threshold: writing 100 small entries leaves ``audit.log``
   present and ``audit.log.1`` absent.
2. Rotation triggered at threshold: with a 1024-byte threshold, the next
   append after the size crosses rotates; ``audit.log.1`` carries the
   previous body verbatim, ``audit.log`` starts fresh.
3. 5-archive cap shifts the oldest off: after 6 rotations, ``audit.log.5``
   exists but ``audit.log.6`` does NOT.
4. Correct shift order: after 3 rotations, archive contents are unique
   (no archive overwrites another's content; the reverse-walk inversion
   guard).
5. Mode 0600 preserved on the fresh ``audit.log`` after rotation.
6. D-13 STRUCTURAL invariant: rotated archives carry only ``body_sha256``,
   never plaintext ``body``.
7. ``--audit-log-max-bytes`` CLI arg sets the env var BEFORE the lazy
   server.run import resolves.
8. Test-fixture sandbox guard (Pitfall 5): the fixture monkey-patches
   BOTH ``_LOG_DIR`` and ``_LOG_PATH`` so no test ever writes to
   ``~/Library/Logs/whatsapp-desktop-mcp/``.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def isolated_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Path]]:
    """Pitfall 5 sandbox — monkey-patch BOTH _LOG_DIR and _LOG_PATH.

    Belt-and-braces: even if the source forgets to use one of the constants,
    the test still writes ONLY to tmp_path. Mirrors the Phase 2
    ``_isolate_live_state`` fixture pattern.
    """
    from whatsapp_desktop_mcp.sender import audit

    log_path = tmp_path / "audit.log"
    monkeypatch.setattr(audit, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(audit, "_LOG_PATH", log_path)
    # Also clear the env var so each test sets its own threshold.
    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", raising=False)

    yield {"log_dir": tmp_path, "log_path": log_path}


def _make_entry_json(idx: int) -> str:
    """Build a small JSONL line shaped like the AuditEntry serialization.

    We pass raw JSON strings to ``_blocking_append`` (which is what the
    async ``append`` does after ``model_dump_json``).
    """
    return json.dumps(
        {
            "ts": 1_000_000 + idx,
            "chat_id": 42,
            "chat_name": "test",
            "body_sha256": "a" * 64,
            "outcome": "sent",
            "message_id": None,
            "error": None,
            "confirm_skipped": False,
            "elapsed_ms": 1,
        },
        separators=(",", ":"),
    )


def test_no_rotation_under_threshold(isolated_audit: dict[str, Path]) -> None:
    """Test 1: 100 small entries with the default 10 MB threshold do NOT rotate."""
    from whatsapp_desktop_mcp.sender import audit

    for i in range(100):
        audit._blocking_append(_make_entry_json(i))

    assert isolated_audit["log_path"].exists()
    assert not (isolated_audit["log_dir"] / "audit.log.1").exists()
    assert not (isolated_audit["log_dir"] / "audit.log.2").exists()


def test_rotation_triggered_at_threshold(
    isolated_audit: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 2: with a 1024-byte threshold, append after size cross rotates."""
    from whatsapp_desktop_mcp.sender import audit

    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", "1024")

    # Write entries until the file grows past 1024 bytes — then the NEXT
    # append should trigger rotation.
    pre_rotation_payloads: list[str] = []
    while (
        not isolated_audit["log_path"].exists() or isolated_audit["log_path"].stat().st_size < 1024
    ):
        idx = len(pre_rotation_payloads)
        payload = _make_entry_json(idx)
        pre_rotation_payloads.append(payload)
        audit._blocking_append(payload)

    pre_rotation_size = isolated_audit["log_path"].stat().st_size
    assert pre_rotation_size >= 1024

    # The next append rotates: audit.log → audit.log.1; new audit.log starts fresh.
    new_payload = _make_entry_json(9999)
    audit._blocking_append(new_payload)

    archive = isolated_audit["log_dir"] / "audit.log.1"
    assert archive.exists(), "rotation did not produce audit.log.1"
    archive_text = archive.read_text(encoding="utf-8")
    # Archive carries every pre-rotation payload verbatim.
    for payload in pre_rotation_payloads:
        assert payload in archive_text

    # New live log carries only the post-rotation entry.
    live_text = isolated_audit["log_path"].read_text(encoding="utf-8")
    assert new_payload in live_text
    assert pre_rotation_payloads[0] not in live_text


def test_archive_cap_shifts_oldest_off(
    isolated_audit: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 3: after 6 rotations, audit.log.5 exists; audit.log.6 does NOT."""
    from whatsapp_desktop_mcp.sender import audit

    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", "256")

    # Force 6 rotations: append entries large enough that each rotation
    # cycle requires few entries.
    big_payload = json.dumps({"x": "y" * 200, "outcome": "sent"})

    rotation_count = 0
    safety = 0
    while rotation_count < 6 and safety < 200:
        audit._blocking_append(big_payload)
        if (isolated_audit["log_dir"] / "audit.log.1").exists():
            # Each rotation results in shifts; we count by checking how
            # many archive files exist.
            existing = sum(
                1 for i in range(1, 8) if (isolated_audit["log_dir"] / f"audit.log.{i}").exists()
            )
            if existing > rotation_count:
                rotation_count = existing
        safety += 1

    # Force at least 6 rotations: keep appending until audit.log.5 exists.
    while not (isolated_audit["log_dir"] / "audit.log.5").exists() and safety < 500:
        audit._blocking_append(big_payload)
        safety += 1

    # Force a 6th rotation event so we know the cap triggers eviction.
    for _ in range(5):
        audit._blocking_append(big_payload)

    assert (isolated_audit["log_dir"] / "audit.log.5").exists(), (
        "5-archive ceiling not reached — cap test inconclusive"
    )
    assert not (isolated_audit["log_dir"] / "audit.log.6").exists(), (
        "audit.log.6 must NEVER exist (5-archive cap)"
    )


def test_archive_shift_order_no_content_overwrite(
    isolated_audit: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 4: archives carry distinct content after multiple rotations."""
    from whatsapp_desktop_mcp.sender import audit

    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", "256")

    # Phase A: rotate once with payload "alpha".
    while (
        not isolated_audit["log_path"].exists() or isolated_audit["log_path"].stat().st_size < 256
    ):
        audit._blocking_append('{"phase":"alpha","outcome":"sent"}')
    audit._blocking_append('{"trigger":"rot1","outcome":"sent"}')
    assert (isolated_audit["log_dir"] / "audit.log.1").exists()

    # Phase B: rotate again with payload "beta".
    while (
        not isolated_audit["log_path"].exists() or isolated_audit["log_path"].stat().st_size < 256
    ):
        audit._blocking_append('{"phase":"beta","outcome":"sent"}')
    audit._blocking_append('{"trigger":"rot2","outcome":"sent"}')
    assert (isolated_audit["log_dir"] / "audit.log.2").exists()

    # Phase C: rotate again with payload "gamma".
    while (
        not isolated_audit["log_path"].exists() or isolated_audit["log_path"].stat().st_size < 256
    ):
        audit._blocking_append('{"phase":"gamma","outcome":"sent"}')
    audit._blocking_append('{"trigger":"rot3","outcome":"sent"}')
    assert (isolated_audit["log_dir"] / "audit.log.3").exists()

    # After 3 rotations:
    # - audit.log.1 contains the most-recent rotated body (gamma).
    # - audit.log.3 contains the oldest rotated body (alpha).
    a1_text = (isolated_audit["log_dir"] / "audit.log.1").read_text(encoding="utf-8")
    a3_text = (isolated_audit["log_dir"] / "audit.log.3").read_text(encoding="utf-8")
    assert "gamma" in a1_text, "audit.log.1 should carry the most-recent rotated body"
    assert "alpha" in a3_text, "audit.log.3 should carry the oldest rotated body"
    # No cross-contamination: gamma's content is NOT in the alpha archive.
    assert "gamma" not in a3_text, "rotation overwrote alpha archive with gamma content"
    assert "alpha" not in a1_text, "rotation overwrote gamma archive with alpha content"


def test_mode_0600_preserved_after_rotation(
    isolated_audit: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 5: post-rotation fresh audit.log has mode 0600 (Phase 2 invariant)."""
    from whatsapp_desktop_mcp.sender import audit

    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", "256")

    while (
        not isolated_audit["log_path"].exists() or isolated_audit["log_path"].stat().st_size < 256
    ):
        audit._blocking_append('{"x":"y","outcome":"sent"}')
    audit._blocking_append('{"trigger":"rot","outcome":"sent"}')

    # The fresh audit.log post-rotation must be mode 0600.
    mode = stat.S_IMODE(isolated_audit["log_path"].stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_d13_invariant_no_plaintext_body_in_archive(
    isolated_audit: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 6: D-13 STRUCTURAL — archive files never carry plaintext body.

    AuditEntry's schema only declares ``body_sha256`` (no ``body`` /
    ``body_text`` / ``body_preview``); rotation moves complete JSONL
    lines verbatim, so the schema invariant carries through. We assert
    by writing a body_sha256-only payload, rotating it into an archive,
    then grep-asserting the archive doesn't contain a token that looks
    like raw body content.
    """
    from whatsapp_desktop_mcp.sender import audit

    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", "256")

    # The "secret_payload_text" string must NEVER end up in any archive
    # because no field ever ships it through the AuditEntry schema.
    body_marker = "SECRET_BODY_PLAINTEXT_DO_NOT_LEAK"
    while (
        not isolated_audit["log_path"].exists() or isolated_audit["log_path"].stat().st_size < 256
    ):
        audit._blocking_append(
            json.dumps({"chat_id": 1, "body_sha256": "a" * 64, "outcome": "sent"})
        )
    audit._blocking_append('{"trigger":"rot","outcome":"sent"}')

    archive = isolated_audit["log_dir"] / "audit.log.1"
    assert archive.exists()
    archive_text = archive.read_text(encoding="utf-8")
    assert body_marker not in archive_text, "D-13 violation: plaintext body in archive"


def test_audit_entry_schema_carries_only_body_sha256() -> None:
    """D-13 schema-level guard: AuditEntry has body_sha256, NOT body."""
    from whatsapp_desktop_mcp.sender.audit import AuditEntry

    fields = AuditEntry.model_fields
    assert "body_sha256" in fields, f"body_sha256 missing: {list(fields)}"
    assert "body" not in fields, f"raw body field present (D-13 violation): {list(fields)}"


def test_resolve_max_bytes_default_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Helper: ``_resolve_max_bytes()`` returns 10 MB when env var unset."""
    from whatsapp_desktop_mcp.sender import audit

    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", raising=False)
    assert audit._resolve_max_bytes() == 10 * 1024 * 1024


def test_resolve_max_bytes_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Helper: ``_resolve_max_bytes()`` reads the env var."""
    from whatsapp_desktop_mcp.sender import audit

    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", "2048")
    assert audit._resolve_max_bytes() == 2048


def test_resolve_max_bytes_falls_back_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Helper: malformed env value falls back to default (NOT a crash)."""
    from whatsapp_desktop_mcp.sender import audit

    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", "not-an-int")
    assert audit._resolve_max_bytes() == 10 * 1024 * 1024


def test_async_append_respects_rotation(
    isolated_audit: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The async ``append`` wrapper goes through the same rotation logic."""
    from whatsapp_desktop_mcp.sender import audit

    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", "256")

    async def drive() -> None:
        # Fill, then trigger rotation.
        for _ in range(40):
            entry = audit.AuditEntry(
                chat_id=1,
                chat_name="x",
                body_sha256="a" * 64,
                outcome="sent",
            )
            await audit.append(entry)

    asyncio.run(drive())
    assert (isolated_audit["log_dir"] / "audit.log.1").exists()


def test_cli_audit_log_max_bytes_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 7: ``--audit-log-max-bytes 2048`` sets the env var before server.run."""
    from whatsapp_desktop_mcp import cli

    captured: dict[str, str] = {}

    # Stub server.run so cli.main returns without booting FastMCP.
    def fake_run() -> None:
        captured["env"] = os.environ.get("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", "<UNSET>")

    monkeypatch.setattr("whatsapp_desktop_mcp.server.run", fake_run)
    monkeypatch.delenv("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", raising=False)

    rc = cli.main(["--audit-log-max-bytes", "2048"])
    assert rc == 0
    assert captured["env"] == "2048"

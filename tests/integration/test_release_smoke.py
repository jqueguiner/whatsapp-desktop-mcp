"""Pre-release maintainer-machine smoke suite (Phase 3 Plan 03-05).

This module composes the live Phase 1 + Phase 2 + Phase 3 surfaces into a
single release-gate suite that the maintainer runs ON THEIR OWN MAC
BEFORE every ``git tag v0.x.0``. It is **NOT** run by GitHub Actions: the
CI ``macos-14`` runners have no WhatsApp.app installed, no ChatStorage
DB, and no TCC grants — the smoke would either skip everything or
false-fail. CONTEXT.md D-23 locks this as a maintainer-local ritual.

Composition (CONTEXT.md D-22)
=============================
Pytest discovers the Phase 1 (`test_live_doctor.py`, `test_live_reader.py`)
and Phase 2 (`test_live_send.py`) live test modules through the standard
``tests/integration/`` directory; running ``RUN_LIVE=1 RUN_LIVE_WHATSAPP=1
uv run pytest -m live`` from the repo root therefore exercises:

- Phase 0 / 1: ``doctor`` (FDA / Automation / Accessibility probes +
  schema fingerprint + WhatsApp.app version + last_message_ts +
  coverage_summary).
- Phase 1: ``list_chats``, ``read_chat``, ``extract_recent``,
  ``search_messages`` (LIKE), ``search_contacts``,
  ``get_chat_metadata``, ``get_message_context``.
- Phase 2: ``send_message`` (real WhatsApp UI send to the maintainer's
  self-chat; B-2 sandbox guards rate-limit + audit log).
- Phase 3 (this module): ``doctor`` post-Plan-03-03 surface
  (``degraded_mode_warning`` + ``supported_version_range``); FTS5
  sidecar lazy-build + ``--fts5-mode=force`` dispatch; FTS5 quote-wrap
  correctness on operator characters; (optional) audit-log rotation
  end-to-end.

D-24 sandbox extension (FTS sidecar)
====================================
Phase 2's ``test_live_send.py`` ships an autouse ``_isolate_live_state``
fixture that monkey-patches ``rate_limit._DB_PATH``, ``audit._LOG_DIR``,
and ``audit._LOG_PATH`` to ``tmp_path``. Phase 3 D-24 mandates the
SAME sandbox semantics PLUS a fourth target: ``reader.search_fts5._DB_PATH``,
so a smoke run never touches the production FTS index at
``~/Library/Application Support/whatsapp-desktop-mcp/fts.sqlite``.

The Phase 2 fixture in ``test_live_send.py`` stays **byte-stable** — the
extension lives ONLY in this module's autouse fixture
(``_isolate_live_state_extended``), which scopes-out the Phase 2 fixture
WITHIN ``test_release_smoke.py`` only. Phase 2 send tests themselves do
NOT touch the FTS5 codepath (the send tool path is search-free), so the
Phase 2 fixture's narrower scope remains correct for those tests.

Module gates
============
``pytestmark`` declares both ``pytest.mark.live`` AND a
``RUN_LIVE_WHATSAPP=1`` env-var skip. Per-module ``RUN_LIVE=1`` gates
already exist on the Phase 1/2 modules; the maintainer ritual sets BOTH
env vars together. With ``RUN_LIVE_WHATSAPP`` unset (the CI default),
this module's tests skip cleanly without touching WhatsApp.app or any
production state.

Maintainer pre-release ritual::

    RUN_LIVE=1 RUN_LIVE_WHATSAPP=1 \\
        WHATSAPP_DESKTOP_MCP_LIVE_TEST_SELF_NAME="<your-self-chat-display-name>" \\
        uv run pytest -m live

    # All green → optionally cut a release-candidate dry run:
    #     git tag v0.0.1-rc1 && git push origin v0.0.1-rc1
    # Watch .github/workflows/release.yml: pkg-build + tap-update jobs.
    # If the rc completes cleanly, cut the real release:
    #     git tag v0.1.0 && git push --tags
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_WHATSAPP") not in ("1", "true", "yes"),
        reason="set RUN_LIVE_WHATSAPP=1 to run the pre-release smoke suite",
    ),
]


# ---------------------------------------------------------------------------
# D-24 sandbox extension — autouse so every smoke test gets the FTS sidecar
# monkey-patch on top of Phase 2's three sandbox targets. Defined at module
# scope so it overrides Phase 2's _isolate_live_state WITHIN this module
# only (Phase 2's send tests continue to use Phase 2's narrower fixture
# elsewhere — they don't fire FTS5 paths).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_live_state_extended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Path]]:
    """B-2 + D-24: sandbox rate-limit DB, audit log, AND FTS5 sidecar.

    Mirrors Phase 2's ``_isolate_live_state`` semantics verbatim
    (``rate_limit._DB_PATH`` / ``audit._LOG_DIR`` / ``audit._LOG_PATH`` —
    Pitfall 5: BOTH ``_LOG_DIR`` AND ``_LOG_PATH`` must be patched because
    the rotation pattern from Plan 03-03 walks ``_LOG_PATH.with_suffix``
    and the create branch reads ``_LOG_DIR.mkdir``) AND adds the Phase 3
    target: ``reader.search_fts5._DB_PATH`` so the FTS sidecar lazy-build
    lands in ``tmp_path / "fts.sqlite"`` instead of the maintainer's
    production ``~/Library/Application Support/whatsapp-desktop-mcp/fts.sqlite``.

    Real WhatsApp send still fires (the AX-API preflight + deep-link +
    keystroke + post-hoc DB poll all hit the live UI / live ChatStorage RO
    snapshot). Only the guardrail persistence + the FTS index are sandboxed.
    """
    from whatsapp_desktop_mcp.reader import search_fts5
    from whatsapp_desktop_mcp.sender import audit, rate_limit

    rate_db = tmp_path / "rate-limit.db"
    audit_log = tmp_path / "audit.log"
    fts_db = tmp_path / "fts.sqlite"

    monkeypatch.setattr(rate_limit, "_DB_PATH", rate_db)
    monkeypatch.setattr(audit, "_LOG_DIR", tmp_path)  # Pitfall 5: both _LOG_DIR
    monkeypatch.setattr(audit, "_LOG_PATH", audit_log)  # Pitfall 5: AND _LOG_PATH
    monkeypatch.setattr(search_fts5, "_DB_PATH", fts_db)  # D-24 FTS extension

    yield {"rate_db": rate_db, "audit_log": audit_log, "fts_db": fts_db}


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_smoke_doctor_all_green() -> None:
    """``doctor`` returns a fully-populated report on the maintainer's live Mac.

    Composes the Phase 1 (DIAG-01) + Plan 03-03 (D-20) doctor surface:

    - All 3 TCC permissions are granted (the maintainer has the .pkg /
      uvx binary registered with FDA + Accessibility + Automation).
    - Schema fingerprint resolves to ``state == "supported"``.
    - ``degraded_mode_warning is None`` (the maintainer's WhatsApp.app
      version is in ``docs/tested_versions.md``; if a fresh WA build
      slipped past the matrix, this assertion fires and the maintainer
      knows to extend ``tested_versions.md`` per Plan 03-03 Task 1
      before tagging).
    - ``whatsapp_app_version`` is non-None (CFBundleShortVersionString).
    - ``last_message_ts`` is non-None and recent (sanity gate: within
      the last 30 days).
    """
    from whatsapp_desktop_mcp.tools.doctor import doctor

    report = await doctor()

    assert report.all_granted is True, (
        f"all_granted must be True on the maintainer's Mac before release; "
        f"FDA={report.full_disk_access.state!r}, "
        f"Automation={report.automation_whatsapp.state!r}, "
        f"Accessibility={report.accessibility.state!r}"
    )

    assert report.schema_fingerprint.state == "supported", (
        f"schema_fingerprint.state must be 'supported'; "
        f"got {report.schema_fingerprint.state!r} — "
        f"remediation: {report.schema_fingerprint.remediation!r}"
    )

    assert report.schema_fingerprint.degraded_mode_warning is None, (
        f"degraded_mode_warning must be None for a release-blessed WhatsApp.app version; "
        f"got {report.schema_fingerprint.degraded_mode_warning!r} — "
        f"extend docs/tested_versions.md (Plan 03-03 Task 1) before tagging."
    )

    assert report.whatsapp_app_version is not None
    assert re.match(r"^\d+\.\d+\.\d+", report.whatsapp_app_version), (
        f"whatsapp_app_version must be a CFBundleShortVersionString-shaped semver; "
        f"got {report.whatsapp_app_version!r}"
    )

    assert report.last_message_ts is not None
    assert abs(time.time() - report.last_message_ts) < 30 * 86_400, (
        f"last_message_ts seems stale: {report.last_message_ts}"
    )


@pytest.mark.asyncio
async def test_release_smoke_fts5_path() -> None:
    """``search_messages`` under ``fts5_mode='force'`` lazily builds + queries the sidecar.

    Composes the Plan 03-01 surface end-to-end against the live
    ChatStorage corpus:

    1. The autouse fixture pointed ``search_fts5._DB_PATH`` at
       ``tmp_path / "fts.sqlite"`` — guaranteed-absent on first call.
    2. Setting ``server.fts5_mode = "force"`` causes the dispatcher to
       call ``build_or_refresh()`` which runs the full rebuild against
       ``ZWAMESSAGE`` (10-30s on a ~100k-message corpus per RESEARCH §A4;
       sub-second on smaller corpora).
    3. The FTS5 ``MATCH`` query then returns ranked results.

    State reset (``server.fts5_mode = "auto"``) lives in a ``finally``
    block so subsequent tests in the same suite invocation see the
    default mode.
    """
    from whatsapp_desktop_mcp import server
    from whatsapp_desktop_mcp.tools.search_messages import search_messages

    prior_mode = server.fts5_mode
    server.fts5_mode = "force"
    try:
        result = await search_messages(query="test", limit=5)
    finally:
        server.fts5_mode = "auto"
        # Defense-in-depth: if a future test injects a non-default value
        # before this test, restore EXACTLY the prior value (still "auto"
        # in v0.1, but byte-stable against future edits).
        server.fts5_mode = prior_mode

    assert isinstance(result, dict)
    assert "messages" in result
    assert "count" in result
    assert "coverage" in result
    assert isinstance(result["count"], int)
    assert result["count"] >= 0
    # The FTS5 sidecar is now lazy-built at the sandboxed path.
    # CRITICAL invariant for the maintainer's Mac hygiene: the production
    # FTS index path was NOT touched (the fixture monkey-patched _DB_PATH
    # to tmp_path before the build_or_refresh call resolved it).


@pytest.mark.asyncio
async def test_release_smoke_fts5_quote_wrap_smoke() -> None:
    """``search_messages`` survives operator characters in the user query.

    Pitfall 1 / T-03-01-02 mitigation verified live: the FTS5 ``MATCH``
    operator interprets ``*`` ``"`` ``(`` ``)`` ``:`` ``-`` ``+`` ``^`` as
    syntax. ``search_fts5._search_blocking`` quote-wraps the query into
    an FTS5 phrase (``"meeting (test)"``) so naïve queries containing
    parentheses do not raise ``sqlite3.OperationalError``. This test
    queries a body containing ``(`` and ``)`` under ``fts5_mode='force'``
    and asserts a clean (possibly empty) result rather than a crash.
    """
    import sqlite3

    from whatsapp_desktop_mcp import server
    from whatsapp_desktop_mcp.tools.search_messages import search_messages

    prior_mode = server.fts5_mode
    server.fts5_mode = "force"
    try:
        # The exact body doesn't have to match — the test's contract is
        # "operator chars don't crash the search", regardless of corpus
        # content. result["count"] >= 0 always holds; the meaningful
        # assertion is the absence of sqlite3.OperationalError.
        try:
            result = await search_messages(query="meeting (test)", limit=3)
        except sqlite3.OperationalError as exc:  # pragma: no cover - regression guard
            pytest.fail(
                f"FTS5 quote-wrap defense regressed: operator chars crashed MATCH "
                f"with {exc!r}. Fix: re-verify search_fts5._search_blocking applies "
                f"`fts_query = '\"' + query.replace('\"', '\"\"') + '\"'` before MATCH."
            )
    finally:
        server.fts5_mode = prior_mode

    assert isinstance(result, dict)
    assert "messages" in result
    assert "count" in result
    assert isinstance(result["count"], int)
    assert result["count"] >= 0


@pytest.mark.asyncio
async def test_release_smoke_audit_rotation_observable(
    monkeypatch: pytest.MonkeyPatch,
    _isolate_live_state_extended: dict[str, Path],
) -> None:
    """``sender.audit`` rotation produces ``audit.log.1`` end-to-end (Plan 03-03 D-25).

    Pure-audit-module exercise — does NOT fire a WhatsApp send (so this
    test's correctness does not depend on RUN_LIVE_WHATSAPP enabling
    real WhatsApp UI access; the module-level skip still fires when the
    env var is unset, keeping the smoke suite cleanly gated). Sets the
    rotation threshold to a tiny 512-byte ceiling via the env-var
    override so a few audit appends cross the threshold and trigger
    ``_rotate_in_place``.

    D-13 STRUCTURAL invariant verification: rotated archive lines must
    each contain ``body_sha256`` AND must NOT contain a raw ``body``
    field. Rotation is byte-stable line preservation; the AuditEntry
    schema (no body field) makes this an invariant-by-construction, but
    the smoke check confirms the on-disk shape.
    """
    from whatsapp_desktop_mcp.sender.audit import AuditEntry, append

    monkeypatch.setenv("WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES", "512")

    audit_log = _isolate_live_state_extended["audit_log"]
    archive_1 = audit_log.with_suffix(audit_log.suffix + ".1")

    # Append enough entries to comfortably cross the 512-byte threshold.
    # Each AuditEntry serializes to ~200-300 bytes, so 8 appends should
    # rotate at least once.
    for i in range(8):
        await append(
            AuditEntry(
                ts=int(time.time()) + i,
                chat_id=42,
                chat_name="smoke-rotation-test",
                body_sha256="0" * 64,
                outcome="sent",
                message_id=f"smoke-{i}",
                elapsed_ms=10,
            )
        )

    assert archive_1.exists(), (
        f"audit log rotation must have produced {archive_1} after 8 appends "
        f"with WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES=512; live log size: "
        f"{audit_log.stat().st_size if audit_log.exists() else 'absent'}"
    )

    # D-13 STRUCTURAL invariant: every line in the rotated archive must
    # carry body_sha256 and must NOT carry a raw body field.
    for line in archive_1.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry: dict[str, Any] = json.loads(line)
        assert "body_sha256" in entry, (
            f"D-13 invariant violated: rotated audit line missing body_sha256: {entry!r}"
        )
        assert "body" not in entry, (
            f"D-13 STRUCTURAL invariant violated: rotated audit line "
            f"contains raw 'body' field: {entry!r}"
        )
        assert "body_text" not in entry
        assert "body_preview" not in entry

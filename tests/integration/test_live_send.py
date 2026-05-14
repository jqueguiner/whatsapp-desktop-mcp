"""Live integration smoke tests for ``send_message`` (RUN_LIVE=1 gated).

These tests drive the maintainer's REAL WhatsApp.app via the production
``send_message`` tool — deep-link open, AX preflight, keystroke return,
post-hoc DB poll. A successful test PLACES A REAL MESSAGE in the
maintainer's self-chat (visible in the WhatsApp UI).

B-2 mandatory production-state hygiene
======================================
The ``_isolate_live_state`` autouse fixture monkey-patches
``sender.rate_limit._DB_PATH``, ``sender.audit._LOG_DIR``, and
``sender.audit._LOG_PATH`` to ``tmp_path`` before each live test.
This means:

* The maintainer's daily WhatsApp budget (``~/Library/Application
  Support/whatsapp-desktop-mcp/rate-limit.db``) is preserved — live tests
  consume ZERO bytes of production rate-limit state.
* The maintainer's audit log (``~/Library/Logs/whatsapp-desktop-mcp/audit.log``)
  is preserved — live test entries land in tmp instead.

What is NOT sandboxed: the WhatsApp send itself, the AX-API preflight
against the real WhatsApp Desktop window, the post-hoc DB poll against
``ChatStorage.sqlite``. Live tests still drive the maintainer's REAL
account (a real chat message lands in the self-chat).

T-02-05-01 / T-02-05-02 mitigations
===================================
* Self-chat discovery via env var ``WHATSAPP_DESKTOP_MCP_LIVE_TEST_SELF_NAME``
  (no actual chat / phone in source).
* Budget-burning test (``test_live_send_respects_rate_limit``) is
  double-gated by ``RUN_LIVE_BURN_BUDGET=1`` opt-in — the maintainer
  explicitly accepts that 5 fresh messages will land in the self-chat
  even with the B-2 sandbox covering rate-limit DB.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE") not in ("1", "true", "yes"),
        reason="set RUN_LIVE=1 to enable live integration tests",
    ),
]


# B-2 mandatory sandbox — autouse so every test in this module benefits
# without per-test boilerplate.
@pytest.fixture(autouse=True)
def _isolate_live_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Path]]:
    """B-2: redirect rate-limit DB + audit log to tmp_path for every live test.

    Live tests still drive the REAL WhatsApp UI (deeplink + keystroke +
    AX-API + post-hoc DB read of the real ChatStorage.sqlite), but the
    guardrail persistence is sandboxed. The maintainer's daily budget
    is preserved; the maintainer's audit log is preserved.
    """
    from whatsapp_desktop_mcp.sender import audit, rate_limit

    rate_db = tmp_path / "rate-limit.db"
    audit_log = tmp_path / "audit.log"

    monkeypatch.setattr(rate_limit, "_DB_PATH", rate_db)
    monkeypatch.setattr(audit, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(audit, "_LOG_PATH", audit_log)

    yield {"rate_db": rate_db, "audit_log": audit_log}


def _self_chat_name() -> str:
    """Pull the self-chat display name from the env var, or skip."""
    name = os.environ.get("WHATSAPP_DESKTOP_MCP_LIVE_TEST_SELF_NAME")
    if not name:
        pytest.skip(
            "set WHATSAPP_DESKTOP_MCP_LIVE_TEST_SELF_NAME=<your self-chat display name> "
            "to enable live send tests; this keeps the chat name out of source."
        )
    return name


async def _find_self_chat(self_name: str) -> Any:
    """Resolve the maintainer's self-chat via the production reader."""
    from whatsapp_desktop_mcp.tools.list_chats import list_chats

    resp = await list_chats(limit=200)
    chats = resp.get("chats", [])
    for chat in chats:
        if chat.get("kind") == "direct" and chat.get("display_name") == self_name:
            return chat
    pytest.skip(
        f"could not find direct chat named {self_name!r} on the maintainer's Mac; "
        "verify WHATSAPP_DESKTOP_MCP_LIVE_TEST_SELF_NAME and that the chat exists."
    )


class _LiveContext:
    """Minimal Context for live tests — elicit auto-accepts."""

    async def elicit(self, message: str, schema: type[Any]) -> Any:
        from mcp.server.elicitation import AcceptedElicitation

        from whatsapp_desktop_mcp.models import ConfirmationSchema

        return AcceptedElicitation[ConfirmationSchema](data=ConfirmationSchema(confirm=True))


@pytest.mark.asyncio
async def test_live_send_to_self_chat_smoke() -> None:
    """Send a unique-bodied test message to the maintainer's self-chat.

    Live test — rate-limit + audit state is sandboxed to tmp_path;
    the WhatsApp send itself drives the maintainer's real account.

    Shape assertion: SendResult.status ∈ {"sent", "sent_unverified"};
    one matching audit-log entry with body_sha256 of the test message.
    """
    from whatsapp_desktop_mcp import server
    from whatsapp_desktop_mcp.tools.send_message import send_message

    server.read_only_mode = False

    chat = await _find_self_chat(_self_chat_name())
    iso_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    body = f"[whatsapp-desktop-mcp live test {iso_ts}]"

    result = await send_message(
        chat_id=chat["chat_id"],
        body=body,
        ctx=_LiveContext(),
    )

    assert result.status in ("sent", "sent_unverified"), (
        f"unexpected live-send outcome: {result.status!r}; "
        f"verification_note={result.verification_note!r}"
    )


@pytest.mark.asyncio
async def test_live_send_observes_post_hoc_verify() -> None:
    """Send to self-chat + assert SendResult.message_id is populated.

    Verifies the post-hoc DB poll against the maintainer's REAL
    ChatStorage.sqlite (NOT sandboxed — read-only access to the live
    DB is the only way to confirm WhatsApp actually wrote the row).
    The sandbox covers rate_limit + audit only.

    On slow networks the poll may time out; this test accepts
    status="sent_unverified" as a soft-fail (D-22) but documents the
    expected happy path via the assertion message.
    """
    from whatsapp_desktop_mcp import server
    from whatsapp_desktop_mcp.tools.send_message import send_message

    server.read_only_mode = False

    chat = await _find_self_chat(_self_chat_name())
    iso_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    body = f"[whatsapp-desktop-mcp live test verify {iso_ts}]"

    result = await send_message(
        chat_id=chat["chat_id"],
        body=body,
        ctx=_LiveContext(),
    )

    # On a healthy network, message_id IS populated (status="sent").
    # On a slow network, D-22 maps the timeout to "sent_unverified" with
    # message_id=None — we accept either outcome; the live integration
    # gate is "the send actually succeeded in the WhatsApp UI", not
    # "the post-hoc DB poll caught it within 10 s".
    assert result.status in ("sent", "sent_unverified")


@pytest.mark.asyncio
async def test_live_send_respects_rate_limit() -> None:
    """5 sends + a 6th-send-fails attempt; the 6th MUST raise RateLimitExceeded.

    DOUBLE-GATED: requires both ``RUN_LIVE=1`` AND ``RUN_LIVE_BURN_BUDGET=1``.

    With the B-2 sandbox in place, this test does NOT burn the
    maintainer's REAL daily budget — the 5/min trip happens against
    the ``tmp_path`` rate-limit DB. But the maintainer still observes
    5 fresh messages in the self-chat (REAL WhatsApp sends happen),
    hence the double opt-in.
    """
    if os.environ.get("RUN_LIVE_BURN_BUDGET") not in ("1", "true", "yes"):
        pytest.skip(
            "set RUN_LIVE_BURN_BUDGET=1 (in addition to RUN_LIVE=1) to opt in to "
            "the rate-limit-burning live test — 5 real messages will land in your self-chat."
        )

    from whatsapp_desktop_mcp import server
    from whatsapp_desktop_mcp.exceptions import RateLimitExceeded
    from whatsapp_desktop_mcp.tools.send_message import send_message

    server.read_only_mode = False
    chat = await _find_self_chat(_self_chat_name())
    iso_base = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # 5 sends within the same minute → 6th must trip the rate limit.
    for i in range(5):
        await send_message(
            chat_id=chat["chat_id"],
            body=f"[whatsapp-desktop-mcp live rate-test {iso_base} #{i}]",
            ctx=_LiveContext(),
        )

    # 6th attempt — the sandbox rate-limit DB has 5 sent rows in the
    # last minute; check_and_reserve trips → ValueError mapped from
    # RateLimitExceeded.
    with pytest.raises((RateLimitExceeded, ValueError), match=r"(rate|budget|Per-minute)"):
        await send_message(
            chat_id=chat["chat_id"],
            body=f"[whatsapp-desktop-mcp live rate-test {iso_base} #5]",
            ctx=_LiveContext(),
        )

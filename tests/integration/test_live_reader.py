"""Live integration smoke tests for the Phase 1 read tools (RUN_LIVE=1 gated).

Mirrors the Phase 0 ``test_live_doctor.py`` shape verbatim:

- Module-scope :data:`pytestmark` declares the ``live`` marker AND the
  ``RUN_LIVE`` env-var skip — every test in this module is skipped under
  the default CI invocation (``pytest -m "not live"``); the maintainer
  runs ``RUN_LIVE=1 uv run pytest -m live`` before tagging a release.
- Shape-correct assertions only — never value-correct (the user's
  WhatsApp data changes between runs). E.g. we assert
  ``len(chats) > 0`` and ``each chat has a chat_id`` but never
  hard-code chat counts or names.
- Per-test budget ≤ 5 seconds (REL-03 per-tool timeout); the full live
  suite stays within ~30 s on the maintainer's Mac.

T-06-04 mitigation: the ``RUN_LIVE`` env-var skip is module-scoped so
``ci.yml`` (which invokes ``pytest -m "not live"``) never runs these
tests. T-06-02 mitigation: shape asserts only — never print or log
message bodies / JIDs.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import pytest

from whatsapp_mcp.tools.doctor import doctor
from whatsapp_mcp.tools.extract_recent import extract_recent
from whatsapp_mcp.tools.get_chat_metadata import get_chat_metadata
from whatsapp_mcp.tools.get_message_context import get_message_context
from whatsapp_mcp.tools.list_chats import list_chats
from whatsapp_mcp.tools.read_chat import read_chat
from whatsapp_mcp.tools.search_contacts import search_contacts
from whatsapp_mcp.tools.search_messages import search_messages

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE") not in ("1", "true", "yes"),
        reason="set RUN_LIVE=1 to enable live integration tests",
    ),
]


@pytest.mark.asyncio
async def test_live_list_chats() -> None:
    """``list_chats`` returns a non-empty list with each chat shape-correct."""
    result = await list_chats(limit=10)
    assert isinstance(result, dict)
    assert "chats" in result
    assert "count" in result
    chats: list[dict[str, Any]] = result["chats"]
    assert len(chats) > 0, "expected the maintainer's Mac to have at least one chat"
    for chat in chats:
        assert "chat_id" in chat
        assert "kind" in chat
        assert "display_name" in chat
        assert "coverage" in chat


@pytest.mark.asyncio
async def test_live_read_chat() -> None:
    """``read_chat`` against the most-recent chat returns shape-correct + ≤60k bytes."""
    chats_resp = await list_chats(limit=5)
    chats: list[dict[str, Any]] = chats_resp["chats"]
    assert chats, "no chats available for read_chat smoke"
    target = chats[0]["chat_id"]

    result = await read_chat(chat_id=target, limit=10)
    assert "messages" in result
    assert "coverage" in result
    assert len(json.dumps(result)) <= 60_000


@pytest.mark.asyncio
async def test_live_extract_recent() -> None:
    """``extract_recent`` returns the human-readable 'asked Xh, have Yh' summary."""
    chats_resp = await list_chats(limit=5)
    chats: list[dict[str, Any]] = chats_resp["chats"]
    assert chats
    target = chats[0]["chat_id"]

    result = await extract_recent(chat_id=target, hours=24)
    assert "summary" in result
    summary = result["summary"]
    assert isinstance(summary, str)
    assert "asked" in summary and "have" in summary


@pytest.mark.asyncio
async def test_live_search_messages() -> None:
    """``search_messages`` returns shape-correct results (LIKE search across history)."""
    result = await search_messages(query="hi", limit=5)
    assert "messages" in result
    assert "coverage" in result


@pytest.mark.asyncio
async def test_live_search_contacts_dedup() -> None:
    """``search_contacts`` returns deduplicated rows (no two contacts share the same phone)."""
    result = await search_contacts(query="a", limit=5)
    assert "contacts" in result
    contacts: list[dict[str, Any]] = result["contacts"]
    phones = [c["jid"]["phone"] for c in contacts if c.get("jid", {}).get("phone")]
    assert len(phones) == len(set(phones)), "duplicate phone in dedup'd contacts"


@pytest.mark.asyncio
async def test_live_get_chat_metadata_for_group() -> None:
    """``get_chat_metadata`` against a group chat returns a non-empty members list."""
    chats_resp = await list_chats(limit=200)
    chats: list[dict[str, Any]] = chats_resp["chats"]
    group_chat = next((c for c in chats if c.get("kind") == "group"), None)
    if group_chat is None:
        pytest.skip("no group chat available on the maintainer's Mac")

    result = await get_chat_metadata(chat_id=group_chat["chat_id"])
    assert "members" in result
    # Live group chats typically have ≥2 members; we assert non-empty.
    assert len(result["members"]) > 0


@pytest.mark.asyncio
async def test_live_get_message_context() -> None:
    """``get_message_context`` returns ≤5 messages around a known stanza_id."""
    chats_resp = await list_chats(limit=5)
    chats: list[dict[str, Any]] = chats_resp["chats"]
    assert chats
    target = chats[0]["chat_id"]
    read_resp = await read_chat(chat_id=target, limit=5)
    messages = read_resp.get("messages", [])
    if not messages:
        pytest.skip("no messages in the most-recent chat")

    msg_id = messages[0]["message_id"]
    result = await get_message_context(message_id=msg_id, before=2, after=2)
    assert "window" in result
    assert len(result["window"]) <= 5


@pytest.mark.asyncio
async def test_live_doctor_full_payload() -> None:
    """``doctor`` returns a fully-populated DoctorReport on the maintainer's live Mac."""
    report = await doctor()

    # Permission triplet — maintainer's Mac is set up with FDA granted.
    assert report.full_disk_access.state == "granted", (
        f"FDA must be granted to run live integration tests; got {report.full_disk_access.state}"
    )

    # Schema fingerprint resolves to "supported" with v1.
    assert report.schema_fingerprint.state == "supported"
    assert report.schema_fingerprint.observed_version == 1

    # WhatsApp.app version follows the X.Y.Z semver shape.
    assert report.whatsapp_app_version is not None
    assert re.match(r"^\d+\.\d+\.\d+", report.whatsapp_app_version)

    # last_message_ts is non-None and within the last 30 days (sanity gate).
    import time as _time

    assert report.last_message_ts is not None
    assert abs(_time.time() - report.last_message_ts) < 30 * 86_400, (
        f"last_message_ts seems stale: {report.last_message_ts}"
    )

    # Coverage summary is populated.
    assert report.coverage_summary.from_ts is not None
    assert report.coverage_summary.to_ts is not None
    assert report.coverage_summary.from_ts <= report.coverage_summary.to_ts

"""Chat — the locked DATA-01 surface for ``ZWACHATSESSION`` rows.

A ``Chat`` represents one row of ``ZWACHATSESSION`` after JID parsing,
Cocoa->Unix timestamp conversion, and ``ZSESSIONTYPE`` -> ``ChatKind``
mapping. Plan 02's reader populates this; Plan 04's tools surface it.

``ChatKind`` mapping (from verified-live ``ZSESSIONTYPE`` distribution
on the user's Mac, 2026-05-13):

- ``0`` -> ``"direct"``    (588 rows)
- ``1`` -> ``"group"``     (384 rows)
- ``2`` -> ``"other"``     (1 row, unknown semantics — RESEARCH §"Open
  Questions Q1"; the "other" bucket absorbs this without surfacing
  raw integers to callers)
- ``3`` -> ``"broadcast"`` (6 rows)
- ``4`` -> ``"community"`` (9 rows; "community-announcement" in raw
  schema, surfaced as ``"community"``)

``coverage`` is per-chat: ``list_chats`` includes a ``Coverage`` summary
for each row so callers see at-a-glance "this chat has data from X to Y"
without a follow-up call (P1 mitigation in the list response itself).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from whatsapp_desktop_mcp.models.contact import Jid
from whatsapp_desktop_mcp.models.coverage import Coverage

ChatKind = Literal["direct", "group", "broadcast", "community", "other"]


class Chat(BaseModel):
    """One ``ZWACHATSESSION`` row, normalized for tool output (DATA-01)."""

    chat_id: int
    kind: ChatKind
    jid: Jid
    display_name: str
    last_activity_ts: int | None
    last_message_preview: str | None
    unread_count: int
    is_archived: bool
    is_hidden: bool
    coverage: Coverage

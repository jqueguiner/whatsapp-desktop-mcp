"""Group — the locked DATA-01 surface for ``ZWAGROUPINFO`` + ``ZWAGROUPMEMBER``.

A :class:`GroupInfo` joins one ``ZWAGROUPINFO`` row with the matching
``ZWAGROUPMEMBER`` rows for the same ``ZCHATSESSION`` FK. Plan 02's
reader populates this; Plan 04's ``get_chat_metadata`` surfaces it.

Open questions deferred to Plan 02 row-level inspection (RESEARCH §"Open
Questions Q2 / Q3"):

- ``description``: the live Catalyst schema for ``ZWAGROUPINFO`` has no
  obvious description column; surfaced as ``None`` until Plan 02 finds
  it (or confirms its absence).
- ``is_muted``: surfaced as ``False`` until Plan 02 locates the mute
  column.

``subject`` is sourced from ``ZWACHATSESSION.ZPARTNERNAME`` joined via
``ZWACHATSESSION.ZGROUPINFO`` — the live Catalyst schema has no
``ZSUBJECT`` column on ``ZWAGROUPINFO`` itself.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from whatsapp_mcp.models.contact import Jid


class GroupMember(BaseModel):
    """One ``ZWAGROUPMEMBER`` row (DATA-01)."""

    jid: Jid
    display_name: str
    is_admin: bool
    is_active: bool


class GroupInfo(BaseModel):
    """Group metadata: ``ZWAGROUPINFO`` row + member roster (DATA-01)."""

    chat_id: int
    subject: str
    description: str | None
    creation_ts: int | None
    creator_jid: Jid | None
    owner_jid: Jid | None
    members: list[GroupMember] = Field(default_factory=list)
    is_muted: bool

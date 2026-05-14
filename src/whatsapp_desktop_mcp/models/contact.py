"""Contact / Jid types — kind-tagged, never compared as strings (P11 mitigation).

CLAUDE.md hard rule #6: "Never compare JID strings directly. A person may
appear as ``<phone>@s.whatsapp.net`` and ``<lid>@lid`` in different chats.
Use the ``Jid`` type and resolve via ``LID.sqlite``."

Phase 1 reader (Plan 02) parses the raw ``ZCONTACTJID`` / ``ZFROMJID`` /
``ZTOJID`` / ``ZMEMBERJID`` strings into :class:`Jid` instances by
inspecting the suffix:

- ``@s.whatsapp.net``  -> ``kind="phone"``
- ``@lid``             -> ``kind="lid"``
- ``@g.us``            -> ``kind="group"``
- ``@broadcast``       -> ``kind="broadcast"``
- ``0@status`` (exact) -> ``kind="status"``

The ``Contact`` model carries every known representation of a person via
``known_identifiers`` so dedup logic (search_contacts, P11) can merge
rows that resolve to the same underlying identity through ``LID.sqlite``.

Threat model (T-01-02, plan 01-01): ``Jid.raw`` exposes the user's own
data (already accessible to anyone with FDA on this Mac) and is therefore
not a privilege boundary; Plan 04 tools MUST NOT log full JIDs at INFO
level — that mitigation lives in Plan 04.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JidKind = Literal["phone", "lid", "group", "broadcast", "status"]


class Jid(BaseModel):
    """A WhatsApp identifier, kind-tagged so comparisons are always typed.

    ``raw`` is the full JID as stored in the SQLite tables (e.g.
    ``"33612345678@s.whatsapp.net"`` or ``"17439234581234@lid"``).
    ``phone`` is the E.164 form without leading ``+`` (resolved via
    ``LID.sqlite`` for ``lid`` kind, parsed from ``raw`` for ``phone``
    kind). ``lid`` is the lid integer string (always set when a
    ``@lid`` representation is known).
    """

    kind: JidKind
    raw: str
    phone: str | None = None
    lid: str | None = None


class Contact(BaseModel):
    """A WhatsApp contact / chat partner with all known identifiers merged.

    ``known_identifiers`` carries every representation the local data has
    seen for this person — typically a ``phone`` plus a ``lid`` after
    LID.sqlite resolution. ``disambiguation_required`` is set when the
    only known representation is ``@lid`` and no phone resolution
    succeeded; the caller can elect to surface or filter these.
    """

    display_name: str
    jid: Jid
    known_identifiers: list[Jid] = Field(default_factory=list)
    chat_id: int | None = None
    last_message_preview: str | None = None
    last_message_ts: int | None = None
    disambiguation_required: bool = False

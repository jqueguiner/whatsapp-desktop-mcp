"""Message — the locked DATA-02 surface for ``ZWAMESSAGE`` rows.

A ``Message`` represents one row of ``ZWAMESSAGE`` after JID parsing,
Cocoa->Unix timestamp conversion, ``ZMESSAGETYPE`` -> ``MessageKind``
mapping, ``ZSTANZAID`` -> ``message_id`` projection, and (when present)
``ZWAMEDIAITEM`` -> :class:`MediaRef` resolution. Plan 02's reader
populates this; Plan 04's tools surface it.

``MessageKind`` mapping (from verified-live ``ZMESSAGETYPE`` distribution
on the user's Mac, 2026-05-13 — top 15 types):

- ``0`` -> ``"text"``      (67 711 rows)
- ``1`` -> ``"image"``     (6 882)
- ``2`` -> ``"video"``     (1 466 — also covers voice notes pre-3)
- ``3`` -> ``"audio"``     (481)
- ``6`` -> ``"system"``    (2 446 — group join/leave, settings change)
- ``7`` -> ``"location"``  (2 563)
- ``8`` -> ``"contact"``   (340)
- ``10`` -> ``"sticker"``  (282)
- ``11`` -> ``"call"``     (119)
- ``14`` -> ``"revoked"``  (532 — deleted-for-everyone, P10 tombstone)
- ``15`` -> ``"ephemeral"`` (55)
- ``59`` -> ``"poll"``     (739)
- ``66`` -> ``"reaction"`` (410)

Unknown integers (verified live: 12 = 86 rows, 20 = 57 rows, ...) map
to ``"other"`` — the reader (Plan 02) is responsible for the projection
and never raises on novel integers; new schema versions just surface as
``"other"`` until the table above is widened.

B2 lock (do NOT add a public ``z_sort`` field): ``ZSORT`` is reader
internal — ``reader.window`` returns ``(Message, z_sort)`` tuples; the
cursor codec carries the float separately. Surfacing ``z_sort`` on the
public ``Message`` would invite callers to filter / sort on it, breaking
the opaque-cursor contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from whatsapp_desktop_mcp.models.contact import Jid
from whatsapp_desktop_mcp.models.media import MediaRef

MessageKind = Literal[
    "text",
    "image",
    "video",
    "audio",
    "system",
    "location",
    "contact",
    "sticker",
    "call",
    "revoked",
    "ephemeral",
    "poll",
    "reaction",
    "other",
]


class Message(BaseModel):
    """One ``ZWAMESSAGE`` row, normalized for tool output (DATA-02)."""

    message_id: str
    chat_id: int
    sender_jid: Jid
    timestamp: int
    body: str | None
    kind: MessageKind
    is_outgoing: bool
    is_starred: bool
    quoted_message_id: str | None
    media: MediaRef | None

"""Public Pydantic surface for whatsapp-mcp.

Re-exports the locked DATA-01 / DATA-02 / DATA-03 / DATA-04 model surface
plus the opaque pagination cursor codec and the doctor surface inherited
from Phase 0. ``__all__`` enumerates the entire public API; downstream
code (Plans 02-05) imports exclusively from this module:

    from whatsapp_mcp.models import Chat, Message, Coverage, encode_cursor

Phase 0 surface preserved unchanged — ``DoctorReport``, ``PermissionStatus``,
``PermissionState``, and ``PermissionBucket`` remain importable both from
this module and from ``whatsapp_mcp.models.doctor``.
"""

from __future__ import annotations

from whatsapp_mcp.models.chat import Chat, ChatKind
from whatsapp_mcp.models.contact import Contact, Jid, JidKind
from whatsapp_mcp.models.coverage import Coverage
from whatsapp_mcp.models.cursor import (
    AnchorKind,
    CursorError,
    decode_cursor,
    encode_cursor,
)
from whatsapp_mcp.models.doctor import (
    DoctorReport,
    PermissionBucket,
    PermissionState,
    PermissionStatus,
)
from whatsapp_mcp.models.group import GroupInfo, GroupMember
from whatsapp_mcp.models.media import MediaRef
from whatsapp_mcp.models.message import Message, MessageKind

__all__ = [
    "AnchorKind",
    "Chat",
    "ChatKind",
    "Contact",
    "Coverage",
    "CursorError",
    "DoctorReport",
    "GroupInfo",
    "GroupMember",
    "Jid",
    "JidKind",
    "MediaRef",
    "Message",
    "MessageKind",
    "PermissionBucket",
    "PermissionState",
    "PermissionStatus",
    "decode_cursor",
    "encode_cursor",
]

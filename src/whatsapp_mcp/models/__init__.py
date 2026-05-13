"""Public Pydantic surface for whatsapp-mcp.

Re-exports the locked DATA-01 / DATA-02 / DATA-03 / DATA-04 model surface
plus the opaque pagination cursor codec and the doctor surface inherited
from Phase 0. ``__all__`` enumerates the entire public API; downstream
code (Plans 02-05) imports exclusively from this module:

    from whatsapp_mcp.models import Chat, Message, Coverage, encode_cursor

Phase 0 surface preserved unchanged — ``DoctorReport``, ``PermissionStatus``,
``PermissionState``, and ``PermissionBucket`` remain importable both from
this module and from ``whatsapp_mcp.models.doctor``.

Phase 2 extension (Plan 02-02)
==============================
Adds four send-side public names:

- :class:`AuditEntry` — re-exported FROM ``whatsapp_mcp.sender.audit`` so
  the tool tier imports it through the ``models`` package uniformly.
  This introduces the FIRST edge from ``models/`` into ``sender/``
  (single source of truth: the Pydantic class lives in ``sender/audit.py``
  because that's where it's also used internally; ``models/`` is the
  public re-export point). ``models/`` is NOT subject to REL-05's
  reader↔sender isolation — it's the shared contract surface both
  packages depend on.

- :class:`ConfirmationSchema` — single-bool MCP-elicit schema (Pitfall 3).
- :class:`OffendingSource` — PYDANTIC re-shape of the dataclass in
  ``whatsapp_mcp.sender.cross_chat_quote``. The bridge helper
  ``offending_source_to_pydantic`` lives in ``models.send`` and uses a
  string forward-reference to avoid import-time circularity.
- :class:`SendResult` — frozen v0.1 ``send_message`` return shape.
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
    SchemaFingerprint,
    SchemaState,
)
from whatsapp_mcp.models.group import GroupInfo, GroupMember
from whatsapp_mcp.models.media import MediaRef
from whatsapp_mcp.models.message import Message, MessageKind
from whatsapp_mcp.models.send import (
    ConfirmationSchema,
    OffendingSource,
    SendResult,
    offending_source_to_pydantic,
)
from whatsapp_mcp.sender.audit import AuditEntry

__all__ = [
    "AnchorKind",
    "AuditEntry",
    "Chat",
    "ChatKind",
    "ConfirmationSchema",
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
    "OffendingSource",
    "PermissionBucket",
    "PermissionState",
    "PermissionStatus",
    "SchemaFingerprint",
    "SchemaState",
    "SendResult",
    "decode_cursor",
    "encode_cursor",
    "offending_source_to_pydantic",
]

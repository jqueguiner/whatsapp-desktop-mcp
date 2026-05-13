"""Public surface for the reader package — the single point of contact with SQLite.

Every public function is ``async def`` (REL-02). Every blocking SQL
call is dispatched via :func:`asyncio.to_thread` inside the sibling
modules. The reader package is the only place in the codebase that
opens ``ChatStorage.sqlite``, ``ContactsV2.sqlite``, or ``LID.sqlite``;
no other package imports :mod:`sqlite3`.

REL-05 invariant: ``reader/`` does NOT import from
:mod:`whatsapp_mcp.sender`. Plan 06 re-tests this with an AST walk.

Plans 04/05 consume this surface; do NOT reach past it into the
sibling modules (e.g. don't ``from whatsapp_mcp.reader.connection
import open_ro`` outside this package).

Public surface (19 names — :data:`__all__` is authoritative):

- 14 async data accessors: :func:`list_chats`, :func:`find_chat_by_id`,
  :func:`find_chat_by_jid`, :func:`window`, :func:`since`,
  :func:`context_around_stanza`, :func:`parent_of_stanza`,
  :func:`latest_timestamp`, :func:`get_group_info`, :func:`get_members`,
  :func:`search_contacts`, :func:`resolve_lid_to_phone`,
  :func:`resolve_phone_to_lid`, :func:`like_search`.
- 5 plumbing helpers: :func:`open_ro`, :func:`probe_z_version`,
  :data:`SUPPORTED_VERSIONS`, :func:`is_supported`, :func:`is_tombstone`,
  :func:`resolve_media_ref`.
"""

from __future__ import annotations

from whatsapp_mcp.reader.chats import (
    find_chat_by_id,
    find_chat_by_jid,
    list_chats,
)
from whatsapp_mcp.reader.connection import open_ro
from whatsapp_mcp.reader.contacts import (
    resolve_lid_to_phone,
    resolve_phone_to_lid,
    search_contacts,
)
from whatsapp_mcp.reader.groups import get_group_info, get_members
from whatsapp_mcp.reader.media import resolve_media_ref
from whatsapp_mcp.reader.messages import (
    context_around_stanza,
    latest_timestamp,
    parent_of_stanza,
    since,
    window,
)
from whatsapp_mcp.reader.schema_v1 import (
    SUPPORTED_VERSIONS,
    is_supported,
    probe_z_version,
)
from whatsapp_mcp.reader.search import like_search
from whatsapp_mcp.reader.tombstones import is_tombstone

__all__ = [
    "SUPPORTED_VERSIONS",
    "context_around_stanza",
    "find_chat_by_id",
    "find_chat_by_jid",
    "get_group_info",
    "get_members",
    "is_supported",
    "is_tombstone",
    "latest_timestamp",
    "like_search",
    "list_chats",
    "open_ro",
    "parent_of_stanza",
    "probe_z_version",
    "resolve_lid_to_phone",
    "resolve_media_ref",
    "resolve_phone_to_lid",
    "search_contacts",
    "since",
    "window",
]

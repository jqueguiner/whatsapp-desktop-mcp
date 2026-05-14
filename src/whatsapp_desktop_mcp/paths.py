"""Path resolver for the WhatsApp Desktop SQLite store.

The macOS WhatsApp Desktop app stores its message history at
``~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite``.
This path was VERIFIED LIVE on 2026-05-13 against the user's machine
(WhatsApp 26.16.74 on macOS 26.4 Tahoe; ~89 MB SQLite WAL-mode database).
See ``.planning/research/SUMMARY.md`` §3 ("Verified Facts About the Target
Environment / Filesystem layout") for the full provenance.

This module is **pure** — it performs no file I/O and makes no syscalls. It
returns the resolved absolute path string only. Phase 1 will extend the
resolver to auto-detect across user home directories without renaming
``resolve_chatstorage_path`` (the function name and ``str`` return type are
the frozen contract surface for downstream callers).

Plan 01-01 expansion (Phase 1 Wave 1): adds three sibling resolvers —
``resolve_lid_path()`` for ``LID.sqlite`` (JID/LID dedup, P11),
``resolve_contactsv2_path()`` for ``ContactsV2.sqlite`` (search_contacts,
READ-05), and ``resolve_media_root()`` for the media tree
(``ZWAMEDIAITEM.ZMEDIALOCALPATH`` resolution + path-traversal guard,
DATA-03). All four resolvers share the same shape: pure, no I/O, returns
a fully expanded absolute path string.
"""

from __future__ import annotations

import os

# Suffix relative to the user's home directory. Exposed as a module-level
# constant so tests and downstream resolvers can reference the canonical
# sub-path without re-deriving it.
_CHATSTORAGE_SUFFIX = (
    "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"
)

# Sibling SQLite databases inside the same App Group container — verified
# live on 2026-05-13 (CLAUDE.md §"Verified facts").
_LID_SUFFIX = "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/LID.sqlite"
_CONTACTSV2_SUFFIX = "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ContactsV2.sqlite"

# Root of WhatsApp's per-message media tree. Plan 02's ``reader/media.py``
# uses this as the prefix-check root for the path-traversal defense
# applied to ``ZWAMEDIAITEM.ZMEDIALOCALPATH`` (T-01-04 mitigation).
_MEDIA_ROOT_SUFFIX = "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/Message"


def resolve_chatstorage_path() -> str:
    """Return the absolute filesystem path to ``ChatStorage.sqlite``.

    Resolves ``~`` via :func:`os.path.expanduser` so the returned string never
    starts with ``~``. Performs no file existence check — callers (Phase 1
    ``fda`` probe, future readers) are responsible for handling
    :class:`FileNotFoundError` / :class:`PermissionError` on actual access.
    """
    return os.path.expanduser("~/" + _CHATSTORAGE_SUFFIX)


def resolve_lid_path() -> str:
    """Return the absolute filesystem path to the sibling ``LID.sqlite``.

    Pure: no file existence check. Plan 02's reader opens this in
    ``?mode=ro`` to dedup phone <-> lid identifiers (P11 mitigation).
    """
    return os.path.expanduser("~/" + _LID_SUFFIX)


def resolve_contactsv2_path() -> str:
    """Return the absolute filesystem path to the sibling ``ContactsV2.sqlite``.

    Pure: no file existence check. Plan 02's reader opens this in
    ``?mode=ro`` for ``search_contacts`` (READ-05) to surface contacts
    that have no active chat session.
    """
    return os.path.expanduser("~/" + _CONTACTSV2_SUFFIX)


def resolve_media_root() -> str:
    """Return the absolute filesystem path to WhatsApp's media tree root.

    Pure: no file existence check. Plan 02's ``reader/media.py`` uses
    this as the prefix-check root when resolving
    ``ZWAMEDIAITEM.ZMEDIALOCALPATH`` to an absolute ``MediaRef.local_path``;
    any resolved path that does NOT start with this root is refused
    (path-traversal defense, T-01-04).
    """
    return os.path.expanduser("~/" + _MEDIA_ROOT_SUFFIX)

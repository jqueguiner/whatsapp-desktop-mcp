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
"""

from __future__ import annotations

import os

# Suffix relative to the user's home directory. Exposed as a module-level
# constant so tests and downstream resolvers can reference the canonical
# sub-path without re-deriving it.
_CHATSTORAGE_SUFFIX = (
    "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"
)


def resolve_chatstorage_path() -> str:
    """Return the absolute filesystem path to ``ChatStorage.sqlite``.

    Resolves ``~`` via :func:`os.path.expanduser` so the returned string never
    starts with ``~``. Performs no file existence check — callers (Phase 1
    ``fda`` probe, future readers) are responsible for handling
    :class:`FileNotFoundError` / :class:`PermissionError` on actual access.
    """
    return os.path.expanduser("~/" + _CHATSTORAGE_SUFFIX)

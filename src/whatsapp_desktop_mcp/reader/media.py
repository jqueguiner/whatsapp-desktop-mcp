"""MediaRef resolver with path-traversal defense (DATA-03, DATA-04).

CLAUDE.md hard rule #4: "Never inline media bytes in tool responses.
Surface attachments as ``MediaRef { filename, mime, local_path,
size_bytes }``." This module produces those :class:`MediaRef`
instances from a ``ZWAMEDIAITEM`` row joined into the ``ZWAMESSAGE``
window query, and applies the path-traversal defense that defends
against the same threat class as ``lharries/whatsapp-desktop-mcp#241`` (T-02-02):

- ``Path(media_root / rel).resolve()`` collapses ``..`` segments and
  follows symlinks.
- The resolved absolute path MUST start with ``Path(media_root).resolve()``
  — anything escaping the WhatsApp media root returns ``None``.

DATA-04 invariant: this module reads ONLY metadata columns
(``ZMEDIALOCALPATH``, ``ZFILESIZE``, ``ZMOVIEDURATION``, ``ZLATITUDE``,
``ZLONGITUDE``, ``ZTITLE``). The encrypted/protobuf BLOB columns
named in CLAUDE.md hard rule #4 anti-pattern (the encryption key
column and the protobuf metadata column on ``ZWAMEDIAITEM``, plus
the receipt-info column on ``ZWAMESSAGEINFO``) are silently omitted
— their literal column names are left out of this entire package's
source so the threat-model file-wide grep gate stays at zero across
``src/whatsapp_desktop_mcp/reader/``.

Pure-synchronous: ``resolve_media_ref`` is a path computation, no I/O.
``reader/messages.py`` calls it inside the already-blocking
``_blocking_*`` impl after the ``LEFT JOIN ZWAMEDIAITEM`` row select;
no separate ``asyncio.to_thread`` dispatch needed here.
"""

from __future__ import annotations

import mimetypes
import sqlite3
from pathlib import Path

from whatsapp_desktop_mcp.models.media import MediaRef


def resolve_media_ref(row: sqlite3.Row, media_root: str | Path) -> MediaRef | None:
    """Build a :class:`MediaRef` from a joined ``ZWAMEDIAITEM`` row, or ``None``.

    Returns ``None`` if:

    - ``ZMEDIALOCALPATH`` is ``NULL`` or empty (no attachment), or
    - The resolved absolute path escapes ``media_root`` (path-traversal
      defense, T-02-02 — same threat class as ``lharries#241``).

    Args:
        row: A :class:`sqlite3.Row` from one of the reader SQL templates
            that ``LEFT JOIN ZWAMEDIAITEM mi ON mi.Z_PK = m.ZMEDIAITEM``.
            Columns expected (may be NULL for non-media rows):
            ``ZMEDIALOCALPATH``, ``ZFILESIZE``, ``ZMOVIEDURATION``,
            ``ZLATITUDE``, ``ZLONGITUDE``.
        media_root: The WhatsApp media tree root, typically
            :func:`whatsapp_desktop_mcp.paths.resolve_media_root`. The prefix
            check refuses any resolved path that does NOT start with
            ``Path(media_root).resolve()``.

    DATA-04: this function NEVER reads the encryption key or the
    protobuf metadata BLOB columns (their literal names are left out of
    this file's source so the file-wide grep gate stays clean); only
    the metadata columns listed above are touched.
    """
    # Tolerate rows that were SELECTed without the LEFT JOIN columns —
    # ``sqlite3.Row.keys()`` lookup is O(n) but the row width is small.
    rel: str | None = None
    try:
        rel = row["ZMEDIALOCALPATH"]
    except (IndexError, KeyError):
        return None
    if not rel:
        return None

    root_path = Path(media_root)
    try:
        root_abs = root_path.resolve()
    except OSError:
        # Resolution failure (root vanished / inaccessible) — fail closed.
        return None

    candidate = root_path / rel
    try:
        absolute = candidate.resolve()
    except OSError:
        return None

    # Path-traversal defense (T-02-02). ``startswith`` on stringified
    # paths is the stdlib-recommended prefix check after ``Path.resolve()``;
    # we also enforce the trailing separator semantics by requiring
    # equality OR a separator-bounded prefix so e.g. ``/foo/bar`` does
    # NOT pass as a prefix of ``/foo/barbar``.
    root_str = str(root_abs)
    abs_str = str(absolute)
    if abs_str != root_str and not abs_str.startswith(root_str + "/"):
        return None

    # Stdlib mimetypes — guess from extension; fall back to a
    # generic binary type so the field is never empty.
    mime_guess, _ = mimetypes.guess_type(absolute.name)
    mime = mime_guess or "application/octet-stream"

    size_bytes = _coerce_int(_safe_get(row, "ZFILESIZE"), default=0)
    duration_seconds = _coerce_float_or_none(_safe_get(row, "ZMOVIEDURATION"))
    latitude = _coerce_float_or_none(_safe_get(row, "ZLATITUDE"))
    longitude = _coerce_float_or_none(_safe_get(row, "ZLONGITUDE"))

    return MediaRef(
        local_path=abs_str,
        filename=absolute.name,
        mime=mime,
        size_bytes=size_bytes,
        duration_seconds=duration_seconds,
        latitude=latitude,
        longitude=longitude,
    )


def _safe_get(row: sqlite3.Row, key: str) -> object:
    """Return ``row[key]`` or ``None`` if the column is missing from the row.

    ``sqlite3.Row`` raises :class:`IndexError` on a missing column name
    rather than returning a sentinel — we tolerate that so callers can
    pass rows from SELECTs that did not include the optional media
    columns (e.g. a context query that already filtered NULL ZMEDIAITEM).
    """
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _coerce_int(value: object, *, default: int) -> int:
    """Best-effort ``int`` coercion; falls back to ``default`` on None / non-numeric."""
    if value is None:
        return default
    if isinstance(value, bool):  # bool is an int subclass; coerce explicitly.
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _coerce_float_or_none(value: object) -> float | None:
    """Best-effort ``float`` coercion; returns ``None`` for None / non-numeric."""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None

"""``resolve_media_ref`` tests — DATA-03 + DATA-04 + path-traversal defense.

Plan 02's ``reader/media.py`` resolves ``ZWAMEDIAITEM.ZMEDIALOCALPATH``
to an absolute :class:`MediaRef.local_path` AND rejects any resolved
path that escapes ``media_root`` (T-02-02 — same threat class as
``lharries#241``). DATA-04 mandates this module reads ONLY metadata
columns; the encrypted/protobuf BLOB columns are not even named here.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from whatsapp_mcp.reader.media import resolve_media_ref


def _row_with(media_root: str, *, rel_path: str | None, **extras: object) -> sqlite3.Row:
    """Build a synthetic ``sqlite3.Row`` with the columns ``resolve_media_ref`` reads."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE r (ZMEDIALOCALPATH TEXT, ZFILESIZE INTEGER, ZMOVIEDURATION REAL, "
        "ZLATITUDE REAL, ZLONGITUDE REAL)"
    )
    conn.execute(
        "INSERT INTO r VALUES (?, ?, ?, ?, ?)",
        (
            rel_path,
            extras.get("size", 0),
            extras.get("duration"),
            extras.get("lat"),
            extras.get("lon"),
        ),
    )
    row: sqlite3.Row = conn.execute("SELECT * FROM r").fetchone()
    conn.close()
    # Ensure the expected media_root path exists for resolution to succeed.
    Path(media_root).mkdir(parents=True, exist_ok=True)
    return row


def test_resolve_media_ref_returns_none_for_empty_path(media_root_fixture: str) -> None:
    """Empty / NULL ZMEDIALOCALPATH returns None (no attachment)."""
    row = _row_with(media_root_fixture, rel_path=None)
    assert resolve_media_ref(row, media_root_fixture) is None
    row = _row_with(media_root_fixture, rel_path="")
    assert resolve_media_ref(row, media_root_fixture) is None


def test_resolve_media_ref_returns_absolute_path(media_root_fixture: str) -> None:
    """A valid relative path resolves to an absolute path under media_root."""
    row = _row_with(
        media_root_fixture,
        rel_path="images/abc/photo.jpg",
        size=12_345,
    )
    media = resolve_media_ref(row, media_root_fixture)
    assert media is not None
    assert media.local_path.startswith(media_root_fixture)
    assert media.local_path.endswith("/images/abc/photo.jpg")
    assert media.filename == "photo.jpg"
    assert media.mime == "image/jpeg"
    assert media.size_bytes == 12_345


def test_resolve_media_ref_refuses_traversal(media_root_fixture: str) -> None:
    """Path traversal attempts return None (T-02-02)."""
    row = _row_with(media_root_fixture, rel_path="../../../etc/passwd")
    assert resolve_media_ref(row, media_root_fixture) is None


def test_resolve_media_ref_mime_guess(media_root_fixture: str) -> None:
    """Common extensions map to expected MIME; unknown maps to octet-stream."""
    # .jpg -> image/jpeg
    Path(media_root_fixture, "x.jpg").write_bytes(b"")
    row = _row_with(media_root_fixture, rel_path="x.jpg")
    media = resolve_media_ref(row, media_root_fixture)
    assert media is not None
    assert media.mime == "image/jpeg"

    # .mp4 -> video/mp4
    Path(media_root_fixture, "x.mp4").write_bytes(b"")
    row = _row_with(media_root_fixture, rel_path="x.mp4")
    media = resolve_media_ref(row, media_root_fixture)
    assert media is not None
    assert media.mime == "video/mp4"

    # unknown extension -> application/octet-stream
    Path(media_root_fixture, "x.zzz").write_bytes(b"")
    row = _row_with(media_root_fixture, rel_path="x.zzz")
    media = resolve_media_ref(row, media_root_fixture)
    assert media is not None
    assert media.mime == "application/octet-stream"


def test_resolve_media_ref_prefix_safety(media_root_fixture: str, tmp_path: Path) -> None:
    """A sibling directory whose name shares a prefix with media_root must not pass.

    e.g. media_root = ``/tmp/xy/Message`` — a candidate resolving to
    ``/tmp/xy/MessageEvil/file`` would pass a naive ``str.startswith``
    prefix check; the implementation requires the trailing-separator
    boundary so this case correctly fails.
    """
    sibling_attack = Path(media_root_fixture + "Evil")
    sibling_attack.mkdir(parents=True, exist_ok=True)
    (sibling_attack / "evil.jpg").write_bytes(b"")
    # Construct a relative path that, after resolve(), points into the
    # sibling directory. ``../MessageEvil/evil.jpg`` from media_root ends
    # up at /tmp/.../MessageEvil/evil.jpg.
    row = _row_with(media_root_fixture, rel_path="../MessageEvil/evil.jpg")
    assert resolve_media_ref(row, media_root_fixture) is None

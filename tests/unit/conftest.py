"""Pytest fixtures: synthetic ChatStorage / ContactsV2 / LID sqlite fixtures.

The fixture schema is derived directly from RESEARCH §"Core Data Schema
Essentials" (verified live against the user's WhatsApp Desktop 26.16.74
on 2026-05-13) — only the column shapes the Plan 02 reader actually
references are materialised, but they MUST match the live names exactly
(``ZWACHATSESSION.ZSESSIONTYPE``, ``ZWAMESSAGE.ZSORT``, etc.) so the
``schema_v1`` SQL templates execute against the fixture without rewrite.

Fixtures provided:

- ``chatstorage_fixture`` — function-scoped tempfile.sqlite in WAL mode
  with the 5 tables (Z_METADATA / ZWACHATSESSION / ZWAMESSAGE /
  ZWAGROUPINFO / ZWAGROUPMEMBER / ZWAMEDIAITEM) the v1 reader touches.
  Seeds 3 chats (direct/group/broadcast), 50+ messages including
  tombstones in all 4 observed flag patterns + 1 quote-reply + 1 media
  message. Returns the absolute path to the temp DB.
- ``large_chat_fixture`` — separate fixture with 5000 messages on one
  chat for the read_chat char-cap test.
- ``lid_fixture`` — tempfile sqlite with ZWAPHONENUMBERLIDPAIR seeded
  with 3 phone↔lid mappings.
- ``contactsv2_fixture`` — tempfile sqlite with ZWAADDRESSBOOKCONTACT.
- ``monkeypatch_paths`` — repoints every ``whatsapp_mcp.paths.resolve_*``
  to a fixture path. Tests that need it accept it explicitly; the
  fixture is NOT autouse so unit tests of pure helpers don't pay the
  monkeypatch cost.
- ``media_root_fixture`` — tempdir with one realistic media file at
  ``images/abc/photo.jpg`` for the resolve_media_ref tests.

T-06-05 mitigation: the fixture schema is derived from RESEARCH (which
is verified live); the live integration suite (``tests/integration/
test_live_reader.py``) is the second-line defence — if the fixture
diverges from reality, the live tests catch it before release.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

# Cocoa epoch offset — duplicated locally so this fixture file does not
# depend on whatsapp_mcp.time at import time (some isolation tests may
# otherwise see a circular import path during conftest collection).
_COCOA_EPOCH_OFFSET = 978_307_200


def _now_cocoa() -> float:
    return float(int(time.time()) - _COCOA_EPOCH_OFFSET)


# ---------------------------------------------------------------------------
# Schema CREATE-TABLE statements — verified-live column shapes (RESEARCH
# §"Core Data Schema Essentials"). Only the columns the Plan 02 reader
# touches are materialised; live tables have many more columns we do not
# need for unit tests.
# ---------------------------------------------------------------------------

_CHATSTORAGE_SCHEMA: list[str] = [
    "CREATE TABLE Z_METADATA (Z_VERSION INTEGER PRIMARY KEY, Z_UUID VARCHAR, Z_PLIST BLOB)",
    """
    CREATE TABLE ZWACHATSESSION (
        Z_PK INTEGER PRIMARY KEY,
        ZSESSIONTYPE INTEGER,
        ZCONTACTJID VARCHAR,
        ZPARTNERNAME VARCHAR,
        ZLASTMESSAGEDATE TIMESTAMP,
        ZLASTMESSAGETEXT VARCHAR,
        ZUNREADCOUNT INTEGER,
        ZARCHIVED INTEGER,
        ZHIDDEN INTEGER,
        ZGROUPINFO INTEGER,
        ZREMOVED INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE ZWAMESSAGE (
        Z_PK INTEGER PRIMARY KEY,
        ZCHATSESSION INTEGER,
        ZGROUPMEMBER INTEGER,
        ZMESSAGETYPE INTEGER,
        ZISFROMME INTEGER,
        ZSORT REAL,
        ZMESSAGEDATE TIMESTAMP,
        ZFROMJID VARCHAR,
        ZTOJID VARCHAR,
        ZSTANZAID VARCHAR,
        ZTEXT VARCHAR,
        ZPUSHNAME VARCHAR,
        ZFLAGS INTEGER,
        ZMEDIAITEM INTEGER,
        ZPARENTMESSAGE INTEGER,
        ZSTARRED INTEGER
    )
    """,
    """
    CREATE TABLE ZWAGROUPINFO (
        Z_PK INTEGER PRIMARY KEY,
        ZCREATIONDATE TIMESTAMP,
        ZCREATORJID VARCHAR,
        ZOWNERJID VARCHAR
    )
    """,
    """
    CREATE TABLE ZWAGROUPMEMBER (
        Z_PK INTEGER PRIMARY KEY,
        ZCHATSESSION INTEGER,
        ZMEMBERJID VARCHAR,
        ZCONTACTNAME VARCHAR,
        ZFIRSTNAME VARCHAR,
        ZISADMIN INTEGER,
        ZISACTIVE INTEGER
    )
    """,
    """
    CREATE TABLE ZWAMEDIAITEM (
        Z_PK INTEGER PRIMARY KEY,
        ZMEDIALOCALPATH VARCHAR,
        ZFILESIZE INTEGER,
        ZMOVIEDURATION REAL,
        ZLATITUDE REAL,
        ZLONGITUDE REAL,
        ZTITLE VARCHAR
    )
    """,
]

_LID_SCHEMA: list[str] = [
    """
    CREATE TABLE ZWAPHONENUMBERLIDPAIR (
        Z_PK INTEGER PRIMARY KEY,
        ZPHONENUMBER VARCHAR,
        ZLID VARCHAR
    )
    """,
]

_CONTACTSV2_SCHEMA: list[str] = [
    """
    CREATE TABLE ZWAADDRESSBOOKCONTACT (
        Z_PK INTEGER PRIMARY KEY,
        ZFULLNAME VARCHAR,
        ZWHATSAPPID VARCHAR,
        ZPHONENUMBER VARCHAR,
        ZLID VARCHAR
    )
    """,
]


def _create_schema(conn: sqlite3.Connection, statements: list[str]) -> None:
    for sql in statements:
        conn.execute(sql)


def _seed_chatstorage(conn: sqlite3.Connection, *, group_id: int = 2) -> None:
    """Seed the chatstorage fixture with 3 chats + 50+ messages + tombstones.

    Returns the well-known chat ids:
    - chat 1: direct chat (Alice), 50 messages over the last 30 days
    - chat 2: group chat
    - chat 3: broadcast list
    """
    now_cocoa = _now_cocoa()
    one_day = 86_400.0

    # Z_METADATA — REL-04 fingerprint = version 1 (verified live).
    conn.execute("INSERT INTO Z_METADATA (Z_VERSION) VALUES (1)")

    # 3 chats: direct / group / broadcast.
    conn.execute(
        "INSERT INTO ZWACHATSESSION VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            0,  # ZSESSIONTYPE=0 -> direct
            "33612345678@s.whatsapp.net",
            "Alice",
            now_cocoa,
            "hello",
            2,
            0,
            0,
            None,
            0,
        ),
    )
    conn.execute(
        "INSERT INTO ZWACHATSESSION VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            2,
            1,  # ZSESSIONTYPE=1 -> group
            "111-222@g.us",
            "Weekend Plans",
            now_cocoa,
            "see you saturday",
            0,
            0,
            0,
            group_id,
            0,
        ),
    )
    conn.execute(
        "INSERT INTO ZWACHATSESSION VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            3,
            3,  # ZSESSIONTYPE=3 -> broadcast
            "9999@broadcast",
            "Friends Broadcast",
            now_cocoa - one_day,
            "broadcast announcement",
            0,
            0,
            0,
            None,
            0,
        ),
    )

    # ZWAGROUPINFO row for the group chat.
    creator_jid = "33612345678@s.whatsapp.net"
    conn.execute(
        "INSERT INTO ZWAGROUPINFO VALUES (?, ?, ?, ?)",
        (group_id, now_cocoa - 30 * one_day, creator_jid, creator_jid),
    )

    # 5 group members: 1 admin + 4 non-admin; mix active / inactive.
    members: list[tuple[object, ...]] = [
        (1, 2, "33612345678@s.whatsapp.net", "Alice Admin", "Alice", 1, 1),
        (2, 2, "33687654321@s.whatsapp.net", "Bob", "Bob", 0, 1),
        (3, 2, "33611111111@s.whatsapp.net", "Carol", "Carol", 0, 1),
        (4, 2, "33622222222@s.whatsapp.net", "Dave", "Dave", 0, 0),  # inactive
        (5, 2, "33633333333@s.whatsapp.net", "Eve", "Eve", 0, 1),
    ]
    for member_row in members:
        conn.execute("INSERT INTO ZWAGROUPMEMBER VALUES (?, ?, ?, ?, ?, ?, ?)", member_row)

    # 50 normal text messages on chat 1 over the last 30 days.
    pk = 1
    for i in range(50):
        msg_cocoa = now_cocoa - (i * one_day / 1.66)  # spans ~30 days
        z_sort = float(1_000_000_000 + (50 - i))  # newest = highest ZSORT
        conn.execute(
            "INSERT INTO ZWAMESSAGE VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pk,
                1,
                None,
                0,  # text
                0 if i % 2 == 0 else 1,  # mix incoming / outgoing
                z_sort,
                msg_cocoa,
                "33612345678@s.whatsapp.net",
                "me@s.whatsapp.net",
                f"STANZA-CHAT1-{pk:04d}",
                f"normal message {i}",
                "Alice",
                0x01000000,  # normal flags pattern
                None,
                None,
                0,
            ),
        )
        pk += 1

    # 4 tombstones on chat 1: 2 with ZMESSAGETYPE=14, 2 with high-bit
    # flags + null text (all 4 of the observed flag bit patterns are
    # exercised across the test rows for the test_tombstones tests).
    tombstone_rows: list[tuple[object, ...]] = [
        # ZMESSAGETYPE=14 (deleted-for-everyone) — also exercises the
        # "type 14 always tombstone regardless of flags or text" branch.
        (
            pk,
            1,
            None,
            14,
            0,
            float(1_000_000_500),
            now_cocoa,
            "33612345678@s.whatsapp.net",
            "me@s.whatsapp.net",
            f"STANZA-TOMB-{pk}",
            "deleted text",
            "Alice",
            0x01000000,
            None,
            None,
            0,
        ),
        (
            pk + 1,
            1,
            None,
            14,
            1,
            float(1_000_000_501),
            now_cocoa,
            "me@s.whatsapp.net",
            "33612345678@s.whatsapp.net",
            f"STANZA-TOMB-{pk + 1}",
            None,
            "Me",
            0x05000000,
            None,
            None,
            0,
        ),
        # high-bit + null text: 0x05000000
        (
            pk + 2,
            1,
            None,
            1,  # original was an image (type 1)
            0,
            float(1_000_000_502),
            now_cocoa,
            "33612345678@s.whatsapp.net",
            "me@s.whatsapp.net",
            f"STANZA-TOMB-{pk + 2}",
            None,
            "Alice",
            0x05000000,
            None,
            None,
            0,
        ),
        # high-bit + null text: 0x05008000
        (
            pk + 3,
            1,
            None,
            2,  # original was a video
            0,
            float(1_000_000_503),
            now_cocoa,
            "33612345678@s.whatsapp.net",
            "me@s.whatsapp.net",
            f"STANZA-TOMB-{pk + 3}",
            None,
            "Alice",
            0x05008000,
            None,
            None,
            0,
        ),
    ]
    for row in tombstone_rows:
        conn.execute(
            "INSERT INTO ZWAMESSAGE VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
    pk += 4

    # 1 control message: 0x05000180 high-bit pattern but WITH text — must
    # NOT be filtered (test_tombstones exercises this).
    conn.execute(
        "INSERT INTO ZWAMESSAGE VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            pk,
            1,
            None,
            0,
            0,
            float(1_000_000_504),
            now_cocoa,
            "33612345678@s.whatsapp.net",
            "me@s.whatsapp.net",
            f"STANZA-CTRL-{pk}",
            "still has text",
            "Alice",
            0x05000180,
            None,
            None,
            0,
        ),
    )
    pk += 1

    # 1 quote-reply message — references one of the seeded normal messages.
    parent_pk = 5  # one of the normal messages near the top
    conn.execute(
        "INSERT INTO ZWAMESSAGE VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            pk,
            1,
            None,
            0,
            1,
            float(1_000_000_600),
            now_cocoa,
            "me@s.whatsapp.net",
            "33612345678@s.whatsapp.net",
            f"STANZA-QUOTE-{pk}",
            "yes I agree",
            "Me",
            0x01000000,
            None,
            parent_pk,
            0,
        ),
    )
    pk += 1

    # 1 media message — joins ZWAMEDIAITEM.
    conn.execute(
        "INSERT INTO ZWAMEDIAITEM VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "images/abc/photo.jpg", 12345, None, None, None, None),
    )
    conn.execute(
        "INSERT INTO ZWAMESSAGE VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            pk,
            1,
            None,
            1,  # image
            0,
            float(1_000_000_700),
            now_cocoa,
            "33612345678@s.whatsapp.net",
            "me@s.whatsapp.net",
            f"STANZA-MEDIA-{pk}",
            "photo caption",
            "Alice",
            0x01000000,
            1,  # ZMEDIAITEM FK
            None,
            0,
        ),
    )
    pk += 1


def _seed_lid(conn: sqlite3.Connection) -> None:
    """Seed LID with 3 phone↔lid mappings (P11 dedup test fixture)."""
    pairs = [
        (1, "33612345678", "99887766554433"),
        (2, "33687654321", "11223344556677"),
        (3, "33611111111", "55544433322211"),
    ]
    for row in pairs:
        conn.execute("INSERT INTO ZWAPHONENUMBERLIDPAIR VALUES (?, ?, ?)", row)


def _seed_contactsv2(conn: sqlite3.Connection) -> None:
    """Seed ContactsV2 with 5 address-book contacts."""
    contacts = [
        (1, "Alice Smith", "33612345678@s.whatsapp.net", "33612345678", "99887766554433"),
        (2, "Bob Jones", "33687654321@s.whatsapp.net", "33687654321", None),
        (3, "Carol", None, "33611111111", "55544433322211"),
        (4, "Dave Williams", None, "33622222222", None),
        (5, "Mr Anderson", None, "33999999999", None),
    ]
    for row in contacts:
        conn.execute("INSERT INTO ZWAADDRESSBOOKCONTACT VALUES (?, ?, ?, ?, ?)", row)


def _open_writable(path: Path) -> sqlite3.Connection:
    """Open ``path`` writable for fixture seeding (NOT for production reads)."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@pytest.fixture
def chatstorage_fixture(tmp_path: Path) -> str:
    """Tempfile chatstorage sqlite with the 3-chat / 50-msg / tombstones seed."""
    db_path = tmp_path / "ChatStorage.sqlite"
    conn = _open_writable(db_path)
    try:
        _create_schema(conn, _CHATSTORAGE_SCHEMA)
        _seed_chatstorage(conn)
        conn.commit()
    finally:
        conn.close()
    return str(db_path)


@pytest.fixture
def empty_chatstorage_fixture(tmp_path: Path) -> str:
    """Empty Z_METADATA chatstorage fixture (probe_z_version raises path)."""
    db_path = tmp_path / "EmptyMeta.sqlite"
    conn = _open_writable(db_path)
    try:
        _create_schema(conn, _CHATSTORAGE_SCHEMA)
        # Deliberately do NOT insert into Z_METADATA.
        conn.commit()
    finally:
        conn.close()
    return str(db_path)


@pytest.fixture
def large_chat_fixture(tmp_path: Path) -> tuple[str, int]:
    """5000-message single-chat fixture for the read_chat char-cap test.

    Returns ``(db_path, chat_id)``.
    """
    db_path = tmp_path / "LargeChat.sqlite"
    conn = _open_writable(db_path)
    try:
        _create_schema(conn, _CHATSTORAGE_SCHEMA)
        conn.execute("INSERT INTO Z_METADATA (Z_VERSION) VALUES (1)")
        now_cocoa = _now_cocoa()
        conn.execute(
            "INSERT INTO ZWACHATSESSION VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                0,
                "33612345678@s.whatsapp.net",
                "Bulky Bob",
                now_cocoa,
                "lots",
                0,
                0,
                0,
                None,
                0,
            ),
        )
        # 5000 messages with realistic-sized bodies (so the body crosses 60k chars).
        body = "this is a relatively typical message body of moderate length " * 3
        for i in range(5000):
            z_sort = float(2_000_000_000 + (5000 - i))
            msg_cocoa = now_cocoa - (i * 60.0)
            conn.execute(
                "INSERT INTO ZWAMESSAGE VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    i + 1,
                    1,
                    None,
                    0,
                    i % 2,
                    z_sort,
                    msg_cocoa,
                    "33612345678@s.whatsapp.net",
                    "me@s.whatsapp.net",
                    f"STANZA-LARGE-{i:05d}",
                    f"{body} #{i}",
                    "Bulky Bob",
                    0x01000000,
                    None,
                    None,
                    0,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return str(db_path), 1


@pytest.fixture
def lid_fixture(tmp_path: Path) -> str:
    """Tempfile LID.sqlite with 3 phone↔lid mappings."""
    db_path = tmp_path / "LID.sqlite"
    conn = _open_writable(db_path)
    try:
        _create_schema(conn, _LID_SCHEMA)
        _seed_lid(conn)
        conn.commit()
    finally:
        conn.close()
    return str(db_path)


@pytest.fixture
def contactsv2_fixture(tmp_path: Path) -> str:
    """Tempfile ContactsV2.sqlite with 5 address-book contacts."""
    db_path = tmp_path / "ContactsV2.sqlite"
    conn = _open_writable(db_path)
    try:
        _create_schema(conn, _CONTACTSV2_SCHEMA)
        _seed_contactsv2(conn)
        conn.commit()
    finally:
        conn.close()
    return str(db_path)


@pytest.fixture
def media_root_fixture(tmp_path: Path) -> str:
    """Tempdir media root with one realistic file at ``images/abc/photo.jpg``."""
    root = tmp_path / "Message"
    (root / "images" / "abc").mkdir(parents=True)
    (root / "images" / "abc" / "photo.jpg").write_bytes(b"\xff\xd8fakejpegdata")
    return str(root)


@pytest.fixture
def monkeypatch_paths(
    monkeypatch: pytest.MonkeyPatch,
    chatstorage_fixture: str,
    lid_fixture: str,
    contactsv2_fixture: str,
    media_root_fixture: str,
) -> None:
    """Repoint every ``whatsapp_mcp.paths.resolve_*`` to a fixture path.

    Tests that exercise reader/* via the public async surface accept this
    fixture explicitly. Pure helper tests (``test_tombstones``,
    ``test_media``) do NOT need it.
    """
    import whatsapp_mcp.paths
    import whatsapp_mcp.reader.chats
    import whatsapp_mcp.reader.contacts
    import whatsapp_mcp.reader.groups
    import whatsapp_mcp.reader.messages
    import whatsapp_mcp.reader.search

    # Patch the canonical resolvers — affects callers that look up paths
    # at call time. Some Plan 02 modules import the resolver function by
    # name at module import time; patch those attributes too.
    monkeypatch.setattr(whatsapp_mcp.paths, "resolve_chatstorage_path", lambda: chatstorage_fixture)
    monkeypatch.setattr(whatsapp_mcp.paths, "resolve_lid_path", lambda: lid_fixture)
    monkeypatch.setattr(whatsapp_mcp.paths, "resolve_contactsv2_path", lambda: contactsv2_fixture)
    monkeypatch.setattr(whatsapp_mcp.paths, "resolve_media_root", lambda: media_root_fixture)

    for module in (
        whatsapp_mcp.reader.chats,
        whatsapp_mcp.reader.contacts,
        whatsapp_mcp.reader.groups,
        whatsapp_mcp.reader.messages,
        whatsapp_mcp.reader.search,
    ):
        if hasattr(module, "resolve_chatstorage_path"):
            monkeypatch.setattr(module, "resolve_chatstorage_path", lambda: chatstorage_fixture)
        if hasattr(module, "resolve_lid_path"):
            monkeypatch.setattr(module, "resolve_lid_path", lambda: lid_fixture)
        if hasattr(module, "resolve_contactsv2_path"):
            monkeypatch.setattr(module, "resolve_contactsv2_path", lambda: contactsv2_fixture)
        if hasattr(module, "resolve_media_root"):
            monkeypatch.setattr(module, "resolve_media_root", lambda: media_root_fixture)


@pytest.fixture
def writer_db_fixture(tmp_path: Path) -> Iterator[str]:
    """Tempfile WAL sqlite for the concurrency stress test.

    Provides a database with one ``test_table`` ready for the writer
    thread's INSERTs and the reader coroutines' SELECTs. NOT a
    chatstorage clone — the concurrency test exercises sqlite WAL
    primitives, not WhatsApp schema.
    """
    db_path = tmp_path / "concurrency.sqlite"
    conn = _open_writable(db_path)
    try:
        conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, payload TEXT, ts REAL)")
        conn.commit()
    finally:
        conn.close()
    yield str(db_path)

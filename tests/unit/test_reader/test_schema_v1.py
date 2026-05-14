"""Schema-fingerprint probe tests (REL-04).

Codifies :data:`whatsapp_desktop_mcp.reader.SUPPORTED_VERSIONS`,
:func:`probe_z_version`, and :func:`is_supported`. Together they form
the doctor's fallback path: when ``Z_VERSION`` is outside the supported
set, doctor surfaces a structured ``unsupported`` ``SchemaFingerprint``
without crashing.
"""

from __future__ import annotations

import pytest

from whatsapp_desktop_mcp.reader.connection import open_ro
from whatsapp_desktop_mcp.reader.schema_v1 import (
    SUPPORTED_VERSIONS,
    is_supported,
    probe_z_version,
)


def test_supported_versions_includes_1() -> None:
    """v1 is the verified-live version on the user's Mac (2026-05-13)."""
    assert 1 in SUPPORTED_VERSIONS


def test_probe_z_version_returns_int(chatstorage_fixture: str) -> None:
    """Against the seeded fixture (Z_VERSION=1), ``probe_z_version`` returns 1."""
    with open_ro(chatstorage_fixture) as conn:
        assert probe_z_version(conn) == 1


def test_probe_z_version_raises_on_empty_z_metadata(empty_chatstorage_fixture: str) -> None:
    """An empty Z_METADATA table raises RuntimeError (Core Data invariant violated)."""
    with open_ro(empty_chatstorage_fixture) as conn:
        with pytest.raises(RuntimeError, match="Z_METADATA empty"):
            probe_z_version(conn)


def test_is_supported_predicate() -> None:
    """``is_supported(1) is True``; arbitrary unknown versions return False."""
    assert is_supported(1) is True
    assert is_supported(99) is False
    assert is_supported(0) is False

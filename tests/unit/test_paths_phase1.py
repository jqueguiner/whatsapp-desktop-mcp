"""Path-resolver tests for the Plan 01-01 Phase 1 expansion (4 paths).

Phase 0's ``tests/unit/test_permissions/test_fda.py`` covers the
``resolve_chatstorage_path`` resolver from the FDA-probe angle. Plan
01-01 adds three sibling resolvers (``resolve_lid_path``,
``resolve_contactsv2_path``, ``resolve_media_root``); this file tests
the shape of all four (absolute path, no ``~``, expected suffix) without
asserting that the files actually exist on disk (the resolvers are
intentionally pure — ``test_paths.py`` would over-assert by demanding
the live WhatsApp container).
"""

from __future__ import annotations

import os

from whatsapp_desktop_mcp.paths import (
    resolve_chatstorage_path,
    resolve_contactsv2_path,
    resolve_lid_path,
    resolve_media_root,
)


def _assert_absolute_no_tilde(path: str) -> None:
    assert os.path.isabs(path), f"path must be absolute, got: {path!r}"
    assert not path.startswith("~"), f"path must not contain unexpanded ~, got: {path!r}"


def test_phase0_resolve_chatstorage_unchanged() -> None:
    """The Phase 0 frozen contract: resolver still returns the expected suffix."""
    p = resolve_chatstorage_path()
    _assert_absolute_no_tilde(p)
    assert p.endswith(
        "/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"
    )


def test_lid_path_shape() -> None:
    """``resolve_lid_path()`` returns an absolute path ending in ``LID.sqlite``."""
    p = resolve_lid_path()
    _assert_absolute_no_tilde(p)
    assert p.endswith("/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/LID.sqlite")


def test_contactsv2_path_shape() -> None:
    """``resolve_contactsv2_path()`` returns an absolute path ending in ``ContactsV2.sqlite``."""
    p = resolve_contactsv2_path()
    _assert_absolute_no_tilde(p)
    assert p.endswith(
        "/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ContactsV2.sqlite"
    )


def test_media_root_shape() -> None:
    """``resolve_media_root()`` returns the WhatsApp ``Message`` directory (no trailing slash)."""
    p = resolve_media_root()
    _assert_absolute_no_tilde(p)
    assert p.endswith("/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/Message")
    assert not p.endswith("/")


def test_all_paths_share_app_group_root() -> None:
    """All four resolvers anchor on the same Group Container root (sanity)."""
    base = "/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/"
    for fn in (
        resolve_chatstorage_path,
        resolve_lid_path,
        resolve_contactsv2_path,
        resolve_media_root,
    ):
        assert base in fn(), f"{fn.__name__} not anchored on the app-group root"

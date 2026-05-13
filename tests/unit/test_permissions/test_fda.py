"""Full Disk Access probe tests — exercise every branch of ``fda.check()``.

The probe dispatches a blocking ``os.stat`` to ``asyncio.to_thread``; the
tests patch the ``os.stat`` symbol *as imported into* ``permissions.fda`` so
the production code path is exercised verbatim. The DB path is also mocked
via ``resolve_chatstorage_path`` so the test never depends on the user's
actual WhatsApp install state.

Branch coverage:
- ``test_fda_granted_when_stat_succeeds``: live tmp file -> ``granted``
- ``test_fda_not_installed_when_file_missing``: non-existent path -> ``whatsapp_not_installed``
- ``test_fda_denied_on_eacces``: ``PermissionError(EACCES)`` -> ``denied`` with Privacy_AllFiles URL
- ``test_fda_denied_on_eperm``: ``PermissionError(EPERM)`` -> ``denied``
- ``test_fda_denied_on_unexpected_errno``: ``PermissionError(EIO)`` -> ``denied`` (other-errno)
"""

from __future__ import annotations

import errno
from pathlib import Path
from typing import Any

import pytest

from whatsapp_mcp.permissions import fda


@pytest.mark.asyncio
async def test_fda_granted_when_stat_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Real tmp file present -> state=granted, db_path is the tmp file."""
    db_file = tmp_path / "ChatStorage.sqlite"
    db_file.write_bytes(b"fake")
    monkeypatch.setattr(fda, "resolve_chatstorage_path", lambda: str(db_file))

    status = await fda.check()
    assert status.bucket == "fda"
    assert status.state == "granted"
    assert status.db_path == str(db_file)
    assert status.binary_path  # non-empty (sys.executable)
    assert "Privacy_AllFiles" in status.system_settings_url


@pytest.mark.asyncio
async def test_fda_not_installed_when_file_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Non-existent path -> state=whatsapp_not_installed."""
    missing = tmp_path / "does-not-exist.sqlite"
    monkeypatch.setattr(fda, "resolve_chatstorage_path", lambda: str(missing))

    status = await fda.check()
    assert status.bucket == "fda"
    assert status.state == "whatsapp_not_installed"
    assert status.db_path == str(missing)


@pytest.mark.asyncio
async def test_fda_denied_on_eacces(monkeypatch: pytest.MonkeyPatch) -> None:
    """PermissionError(EACCES) -> state=denied with Privacy_AllFiles URL + remediation."""
    monkeypatch.setattr(fda, "resolve_chatstorage_path", lambda: "/fake/path/ChatStorage.sqlite")

    def _raise_eacces(*_args: Any, **_kwargs: Any) -> None:
        raise PermissionError(errno.EACCES, "denied")

    monkeypatch.setattr("whatsapp_mcp.permissions.fda.os.stat", _raise_eacces)

    status = await fda.check()
    assert status.bucket == "fda"
    assert status.state == "denied"
    assert "Privacy_AllFiles" in status.system_settings_url
    # The EACCES branch carries a Full Disk Access remediation hint.
    assert "Full Disk Access" in status.remediation


@pytest.mark.asyncio
async def test_fda_denied_on_eperm(monkeypatch: pytest.MonkeyPatch) -> None:
    """PermissionError(EPERM) -> state=denied (same branch as EACCES)."""
    monkeypatch.setattr(fda, "resolve_chatstorage_path", lambda: "/fake/path/ChatStorage.sqlite")

    def _raise_eperm(*_args: Any, **_kwargs: Any) -> None:
        raise PermissionError(errno.EPERM, "operation not permitted")

    monkeypatch.setattr("whatsapp_mcp.permissions.fda.os.stat", _raise_eperm)

    status = await fda.check()
    assert status.state == "denied"
    assert "Full Disk Access" in status.remediation


@pytest.mark.asyncio
async def test_fda_denied_on_unexpected_errno(monkeypatch: pytest.MonkeyPatch) -> None:
    """PermissionError with non-EACCES/EPERM errno -> state=denied via unexpected_errno branch."""
    monkeypatch.setattr(fda, "resolve_chatstorage_path", lambda: "/fake/path/ChatStorage.sqlite")

    def _raise_eio(*_args: Any, **_kwargs: Any) -> None:
        raise PermissionError(errno.EIO, "io error")

    monkeypatch.setattr("whatsapp_mcp.permissions.fda.os.stat", _raise_eio)

    status = await fda.check()
    assert status.bucket == "fda"
    assert status.state == "denied"
    # The unexpected-errno branch carries a different remediation hint.
    assert "Unexpected filesystem error" in status.remediation
    assert str(errno.EIO) in status.remediation

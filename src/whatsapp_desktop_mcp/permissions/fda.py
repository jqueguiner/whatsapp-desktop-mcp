"""Full Disk Access probe — ``os.stat()`` against ``ChatStorage.sqlite``.

Try-and-catch on a real filesystem action (CONTEXT.md D-09): the alternative
— reading ``~/Library/Application Support/com.apple.TCC/TCC.db`` directly —
itself requires Full Disk Access, so it would fail in exactly the situation we
are trying to detect. ``os.stat()`` against the WhatsApp DB path is cheap,
side-effect-free, and unambiguous:

- ``FileNotFoundError`` -> WhatsApp Desktop is not installed at the expected
  path. State: ``whatsapp_not_installed``.
- ``PermissionError`` (errno EACCES / EPERM) -> the file exists but the
  current binary lacks Full Disk Access. State: ``denied``.
- Any other ``PermissionError`` errno (EROFS, EIO, ...) -> surface as
  ``denied`` with a generic remediation; logged at WARNING for diagnosis.
- Otherwise -> ``granted``.

The blocking ``os.stat`` call is dispatched to a thread via
``asyncio.to_thread`` (D-10), so the stdio JSON-RPC loop never blocks on a
slow filesystem.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import sys

from whatsapp_desktop_mcp.exceptions import FullDiskAccessRequired
from whatsapp_desktop_mcp.models.doctor import PermissionStatus
from whatsapp_desktop_mcp.paths import resolve_chatstorage_path

logger = logging.getLogger(__name__)

# Single source of truth for the System Settings deep-link — read off the
# exception class (Plan 02 frozen surface) so future renames cascade.
_FDA_URL = FullDiskAccessRequired.system_settings_url


async def check() -> PermissionStatus:
    """Async entry point. Resolves the DB path, then dispatches the blocking stat to a thread."""
    db_path = resolve_chatstorage_path()
    return await asyncio.to_thread(_check_blocking, db_path)


def _check_blocking(db_path: str) -> PermissionStatus:
    try:
        os.stat(db_path)
    except FileNotFoundError:
        return PermissionStatus(
            bucket="fda",
            state="whatsapp_not_installed",
            binary_path=sys.executable,
            db_path=db_path,
            system_settings_url=_FDA_URL,
            remediation=(
                "WhatsApp Desktop is not installed at the expected path. "
                "Install WhatsApp from the App Store and run `doctor` again."
            ),
        )
    except PermissionError as e:
        if e.errno in (errno.EACCES, errno.EPERM):
            return PermissionStatus(
                bucket="fda",
                state="denied",
                binary_path=sys.executable,
                db_path=db_path,
                system_settings_url=_FDA_URL,
                remediation=(
                    f"Grant Full Disk Access to: {sys.executable}\n"
                    "Open System Settings -> Privacy & Security -> Full Disk Access, "
                    "click '+', and add the path above."
                ),
            )
        # Other errno (EROFS, EIO, ...) — treat as denied with a different remediation hint.
        logger.warning("os.stat(%s) failed with unexpected errno=%s", db_path, e.errno)
        return PermissionStatus(
            bucket="fda",
            state="denied",
            binary_path=sys.executable,
            db_path=db_path,
            system_settings_url=_FDA_URL,
            remediation=f"Unexpected filesystem error (errno={e.errno}); see logs.",
        )
    return PermissionStatus(
        bucket="fda",
        state="granted",
        binary_path=sys.executable,
        db_path=db_path,
        system_settings_url=_FDA_URL,
    )

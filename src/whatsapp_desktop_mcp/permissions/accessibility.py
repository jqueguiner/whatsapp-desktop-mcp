"""Accessibility probe — try to query System Events.

The cheapest action that requires Accessibility permission is asking the
``System Events`` AppleScript bridge for the running process count. When
Accessibility is granted to the requesting binary, ``osascript`` exits 0 with
an integer on stdout. When it is not, the script fails with one of the
empirically-observed denial codes:

| osascript outcome                            | Accessibility status     |
| -------------------------------------------- | ------------------------ |
| ``exit_code == 0``                           | granted                  |
| ``error_code == -1719`` (errAEAccessibility) | denied                   |
| ``error_code == -25211`` (variant)           | denied                   |
| anything else                                | denied (unexpected)      |

All payloads carry ``binary_path = sys.executable`` (D-11). ``db_path`` is
``None`` here \\u2014 only the FDA bucket carries a DB path.
"""

from __future__ import annotations

import logging
import sys

from whatsapp_desktop_mcp.exceptions import AccessibilityPermissionRequired
from whatsapp_desktop_mcp.models.doctor import PermissionStatus
from whatsapp_desktop_mcp.permissions.osascript import run_osascript

logger = logging.getLogger(__name__)

# Single source of truth for the System Settings deep-link.
_ACCESSIBILITY_URL = AccessibilityPermissionRequired.system_settings_url

_PROBE = 'tell application "System Events" to count processes'


async def check() -> PermissionStatus:
    """Probe Accessibility permission via System Events ``count processes``."""
    result = await run_osascript(_PROBE, timeout=3.0)
    binary_path = sys.executable

    if result.exit_code == 0:
        return PermissionStatus(
            bucket="accessibility",
            state="granted",
            binary_path=binary_path,
            system_settings_url=_ACCESSIBILITY_URL,
        )
    if result.error_code in (-1719, -25211):
        return PermissionStatus(
            bucket="accessibility",
            state="denied",
            binary_path=binary_path,
            system_settings_url=_ACCESSIBILITY_URL,
            remediation=(
                f"Grant Accessibility permission to: {binary_path}\n"
                "Open System Settings -> Privacy & Security -> Accessibility, "
                "click '+', add the binary above, and tick its checkbox."
            ),
        )
    logger.warning(
        "accessibility probe unexpected: exit=%s error_code=%s stderr=%r",
        result.exit_code,
        result.error_code,
        result.stderr,
    )
    return PermissionStatus(
        bucket="accessibility",
        state="denied",
        binary_path=binary_path,
        system_settings_url=_ACCESSIBILITY_URL,
        remediation=(
            f"osascript probe returned an unexpected result (exit={result.exit_code}, "
            f"error_code={result.error_code}). See logs."
        ),
    )

"""Apple Events / Automation probe for WhatsApp.

**Empirically corrected probe (CONTEXT.md D-09 PATCHED, 2026-05-13).** The
original probe shape that walked WhatsApp's window collection is empirically
broken on WhatsApp Catalyst: WhatsApp does not implement that command, so
even when Automation is fully granted the probe returns exit-code 1 with
trailing ``(-1708)`` (``errAEEventNotHandled``). That would mis-classify the
granted state as denied (P-PHASE0-03).

The corrected primary probe is::

    id of application "WhatsApp"

When the app is installed and Automation is granted to the requesting binary,
``osascript`` exits 0 with stdout ``net.whatsapp.WhatsApp``. The error-code
decision matrix below covers every other empirically-observed outcome.

| osascript outcome                                | Automation status            |
| ------------------------------------------------ | ---------------------------- |
| ``exit_code == 0``                               | granted                      |
| ``error_code == -1708`` (handler not found)      | granted (event reached app)  |
| ``error_code == -600`` (app not running)         | granted (permission OK)      |
| ``error_code == -1743`` (errAEEventNotPermitted) | denied                       |
| ``error_code == -1728`` (errAENoSuchObject)      | whatsapp_not_installed       |
| timeout / unknown                                | denied (unexpected_result)   |

All payloads carry ``binary_path = sys.executable`` (D-11). ``db_path`` is
``None`` here \\u2014 only the FDA bucket carries a DB path.
"""

from __future__ import annotations

import logging
import sys

from whatsapp_mcp.exceptions import AutomationPermissionRequired
from whatsapp_mcp.models.doctor import PermissionStatus
from whatsapp_mcp.permissions.osascript import run_osascript

logger = logging.getLogger(__name__)

# Single source of truth for the System Settings deep-link.
_AUTOMATION_URL = AutomationPermissionRequired.system_settings_url

# Empirically corrected primary probe (D-09 PATCHED). Returns the app's bundle
# id cleanly when Automation is granted; never relies on the broken
# window-enumeration shape (P-PHASE0-03).
_PROBE = 'id of application "WhatsApp"'


async def check_whatsapp() -> PermissionStatus:
    """Probe Automation permission for WhatsApp via the bundle-id query."""
    result = await run_osascript(_PROBE, timeout=3.0)
    binary_path = sys.executable

    # Granted: clean exit OR app handled the event (regardless of dictionary support)
    # OR app is installed but not running (permission itself is fine).
    if result.exit_code == 0 or result.error_code == -1708 or result.error_code == -600:
        return PermissionStatus(
            bucket="automation",
            state="granted",
            binary_path=binary_path,
            system_settings_url=_AUTOMATION_URL,
        )
    # Not authorized: Automation prompt was denied or never accepted.
    if result.error_code == -1743:
        return PermissionStatus(
            bucket="automation",
            state="denied",
            binary_path=binary_path,
            system_settings_url=_AUTOMATION_URL,
            remediation=(
                f"Grant Automation permission for WhatsApp to: {binary_path}\n"
                "Open System Settings -> Privacy & Security -> Automation, "
                "find the row for the binary above, and tick the WhatsApp checkbox. "
                "If the row does not exist, run `tccutil reset AppleEvents` and re-run doctor."
            ),
        )
    # Target not installed.
    if result.error_code == -1728:
        return PermissionStatus(
            bucket="automation",
            state="whatsapp_not_installed",
            binary_path=binary_path,
            system_settings_url=_AUTOMATION_URL,
            remediation="WhatsApp Desktop is not installed. Install it from the App Store.",
        )
    # Timeout or unknown — surface as denied so the user investigates.
    logger.warning(
        "automation probe unexpected: exit=%s error_code=%s stderr=%r",
        result.exit_code,
        result.error_code,
        result.stderr,
    )
    return PermissionStatus(
        bucket="automation",
        state="denied",
        binary_path=binary_path,
        system_settings_url=_AUTOMATION_URL,
        remediation=(
            f"osascript probe returned an unexpected result (exit={result.exit_code}, "
            f"error_code={result.error_code}). Try restarting WhatsApp and re-running doctor. "
            "If the problem persists, open an issue with the doctor output."
        ),
    )

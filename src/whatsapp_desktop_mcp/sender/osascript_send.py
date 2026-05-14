"""AppleScript keystroke wrappers for the send path (D-01 step 3 / D-02 step 8).

WhatsApp Desktop is a Catalyst app with **no AppleScript dictionary** (``sdef``
returns -192 — verified in research). The only mechanism we have for firing
the actual send action is to drive ``System Events`` keystroke events at the
focused window: ``keystroke return`` to press Enter (sends the body that was
pre-filled by the deep-link URL handler), and ``keystroke <string>`` to type
the chat name into the sidebar search box on the group-chat fallback.

Two callables live here:

* :func:`press_return` — fires Enter at the focused window. Used by both
  the 1:1 path (after the deep-link settle) and the group fallback (after
  typing the body in the chat-pane compose box).
* :func:`type_string` — types a string at the focused window. Used only by
  the group fallback to populate the sidebar search box AND the body. The
  1:1 path does NOT call this because the body is URL-encoded into the
  deep-link and pre-filled by the macOS URL handler.

**TCC error-code mapping** (locale-blind via Phase 0's regex; see
``permissions/osascript.py``):

* ``error_code == -1743`` (errAEEventNotPermitted) → :class:`AutomationRevoked`.
  T-6 mid-send TCC revocation — user opened System Settings → Privacy &
  Security → Automation and unchecked the WhatsApp box between server
  start and the keystroke. The doctor probe at startup succeeded; this
  keystroke now fails. Distinct from
  :class:`AutomationPermissionRequired` (raised by the doctor probe
  itself).
* Any other non-zero exit (including parser errors, target-not-running
  ``-1728``, or the ``"timeout"`` / ``"osascript-missing"`` synthetic
  outcomes) → :class:`OsascriptError` carrying the raw stderr.

**BMP-only constraint on ``keystroke <string>``** (research P12 — verified
historically): AppleScript's ``keystroke`` action truncates non-BMP code
points (anything above U+FFFF — emoji, less-common CJK extensions, etc.).
For v0.1 the group-send fallback REJECTS non-BMP bodies up-front via
:class:`OsascriptError` so the caller surfaces a clean error rather than
silently truncating. The 1:1 deep-link path does NOT have this constraint:
``build_send_url`` URL-encodes the full Unicode body and WhatsApp's URL
scheme handler renders it correctly.

**Escape rules for keystroke strings:** AppleScript string literals are
double-quoted; literal backslashes and double-quotes must be escaped. The
escape order is **backslashes first, then double quotes** — escaping
double-quotes first would convert ``"`` to ``\\"`` and then the subsequent
backslash escape would mangle the ``\\`` into ``\\\\``. Verified by
inspection.
"""

from __future__ import annotations

import logging

from whatsapp_desktop_mcp.exceptions import AutomationRevoked, OsascriptError
from whatsapp_desktop_mcp.permissions.osascript import run_osascript

logger = logging.getLogger(__name__)

# AppleScript error code for "Apple Events permission not granted to this
# process for the target app" — the T-6 mid-send revocation signature.
_ERR_NOT_PERMITTED = -1743

# Upper bound for the BMP (Basic Multilingual Plane). Code points above this
# are encoded as UTF-16 surrogate pairs in AppleScript string literals, and
# `keystroke` historically truncates them (P12 — research). Reject up-front
# so the audit log captures the violation rather than silently sending a
# partial body.
_BMP_MAX = 0xFFFF


async def press_return(timeout: float = 3.0) -> None:
    """Fire a ``Return`` keystroke at the focused window.

    On clean exit (``exit_code == 0``), returns ``None``. On
    ``error_code == -1743`` (T-6 Automation revoked), raises
    :class:`AutomationRevoked`. On any other non-zero exit, raises
    :class:`OsascriptError` carrying the raw stderr.

    The 3 s default timeout matches Phase 0's ``run_osascript`` default and
    is generous: a single Return keystroke is sub-millisecond AppleScript
    work; the 3 s wall is for the osascript spawn + Apple Events dispatch
    round trip, not the keystroke itself.
    """
    result = await run_osascript(
        'tell application "System Events" to keystroke return',
        timeout=timeout,
    )
    if result.exit_code == 0:
        return
    if result.error_code == _ERR_NOT_PERMITTED:
        raise AutomationRevoked(
            "Automation TCC revoked mid-keystroke; grant Automation in "
            "System Settings → Privacy & Security → Automation"
        )
    raise OsascriptError(
        f"keystroke return failed: exit={result.exit_code} stderr={result.stderr!r}"
    )


async def type_string(text: str, timeout: float = 3.0) -> None:
    """Type ``text`` as keystrokes at the focused window.

    The string is escaped for AppleScript embedding (backslash-replace
    first, then double-quote-replace) and dispatched as
    ``tell application "System Events" to keystroke "<escaped>"``.

    :raises OsascriptError: if ``text`` contains any code point above U+FFFF
        (non-BMP — emoji, less-common scripts). AppleScript's ``keystroke``
        action truncates surrogate pairs historically (research P12); for
        v0.1 the group-send fallback rejects non-BMP up-front so the audit
        log records the violation rather than silently sending a partial
        body. The error message identifies the offending code point so the
        caller can surface it to the user.
    :raises AutomationRevoked: when osascript returns error_code ``-1743``
        mid-typing (T-6).
    :raises OsascriptError: on any other non-zero osascript exit, carrying
        the raw stderr.
    """
    for c in text:
        if ord(c) > _BMP_MAX:
            raise OsascriptError(
                f"Body contains non-BMP character U+{ord(c):X}; AppleScript "
                "keystroke truncates non-BMP — group send body is BMP-only in v0.1"
            )

    # Escape order: backslash first, then double-quote. Reversing this would
    # double-escape the backslashes that came from the double-quote pass.
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "System Events" to keystroke "{escaped}"'

    result = await run_osascript(script, timeout=timeout)
    if result.exit_code == 0:
        # log only the length, never the body itself (T-02-01-05 mitigation).
        logger.debug("type_string: keystroke of %d chars succeeded", len(text))
        return
    if result.error_code == _ERR_NOT_PERMITTED:
        raise AutomationRevoked(
            "Automation TCC revoked mid-keystroke; grant Automation in "
            "System Settings → Privacy & Security → Automation"
        )
    raise OsascriptError(
        f"keystroke <string> failed: exit={result.exit_code} stderr={result.stderr!r}"
    )

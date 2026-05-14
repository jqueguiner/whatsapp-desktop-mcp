"""WhatsApp ``whatsapp://send`` deep-link primitives (D-01 / SEND-03).

This module owns the **1:1 send primary path**: build the URL, hand it to
``/usr/bin/open -g`` so macOS's URL-scheme handler raises WhatsApp into the
AX-API-reachable foreground without stealing Cmd-Tab order, settle-poll for
1.5 s until the front-window probe sees ``"WhatsApp"`` in its stdout, and
return to the caller. The caller (the Plan 02-03 ``send_message`` tool) is
responsible for the load-bearing D-03 AX preflight and the keystroke-return
that actually fires the message — this module only opens the chat with the
body pre-filled in the compose box.

Concrete D-01 sequence implemented here:

1. ``build_send_url(phone_e164, body)`` normalises ``+33 612-345-678`` → the
   digits-only ``33612345678`` and percent-encodes the body via
   ``urllib.parse.quote(safe='')`` (RFC 3986 — ``quote`` not ``quote_plus``;
   ``+`` in the body must stay literal, never become a space).
2. ``send_deeplink(phone_e164, body)`` spawns ``/usr/bin/open -g <url>`` via
   ``asyncio.create_subprocess_exec`` with a 5 s hard timeout (re-uses the
   project's async-throughout discipline; never blocks the event loop).
3. After ``open`` returns, the settle-poll runs up to 30 × 50 ms = 1.5 s
   (D-01 budget) calling Phase 0's ``run_osascript`` against
   ``tell application "System Events" to tell process "WhatsApp" to get
   name of front window``. Predicate: ``"WhatsApp" in result.stdout``
   (substring; NOT equality — verified live on this Mac the actual front
   window name is ``"‎WhatsApp"`` with a leading U+200E LRM mark; equality
   silently fails). On exhaustion, raises :class:`SendTimeout`.

SP-2 locked decision (see ``02-01-SPIKES.md``): keep the ``-g`` flag. The
spike showed that ``open -g`` raises WhatsApp into the AX tree on the very
first poll (~0.6 s wall, dominated by the osascript spawn cost) without
making it frontmost — exactly the property the deep-link path needs so the
user's active window keeps Cmd-Tab order.

**CLAUDE.md hard rule #5 compliance:** this module opens no network endpoints
of any flavour — no TCP / UDP listener, no outbound HTTP, no IPC channel
beyond the two listed below. Its only subprocess is ``/usr/bin/open`` (the
macOS URL-scheme local handler, which itself dispatches into WhatsApp.app
via LaunchServices) and Phase 0's already-shipped ``run_osascript``
wrapper. ``urllib.parse.quote`` is pure-string URL encoding — RFC 3986
percent-escape arithmetic, not networking — despite the module path.

**Threat model (Plan 02-01 ``threat_model`` T-02-01-01):** phone parameter is
rejected unless every character after stripping ``+`` / space / ``-`` is a
digit. Body parameter goes through ``urllib.parse.quote(safe='')`` — every
non-alphanumeric byte percent-escaped. ``open`` is invoked via
``asyncio.create_subprocess_exec`` with an explicit argv list — no shell
parse, no metachar interpretation.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse

from whatsapp_desktop_mcp.exceptions import OsascriptError, SendTimeout
from whatsapp_desktop_mcp.permissions.osascript import run_osascript

logger = logging.getLogger(__name__)

# Front-window settle-poll budget (D-01). 30 iterations × 50 ms = 1.5 s wall.
_SETTLE_MAX_ITERS = 30
_SETTLE_INTERVAL_S = 0.05

# Hard timeout for /usr/bin/open. URL-scheme handlers are cheap; 5 s is the
# wall the planner picked in D-01 and is plenty for the LaunchServices dispatch.
_OPEN_TIMEOUT_S = 5.0

# osascript timeout per settle-poll iteration. Each probe shells out to
# /usr/bin/osascript — the spawn cost itself dominates (~0.5 s observed live).
# 1.0 s is enough margin for the probe AppleScript to run; if osascript itself
# times out, the underlying wrapper returns OsascriptResult(stderr="timeout").
_PROBE_TIMEOUT_S = 1.0

# Front-window probe script. The substring match against ``"WhatsApp"`` in the
# result's stdout is mandatory because the actual front-window name is
# ``"‎WhatsApp"`` with a leading U+200E LRM (verified live 2026-05-13 — see
# 02-RESEARCH.md §"Pattern 3: Deep-Link Send Path"). Equality compare would
# silently fail on the bidi mark.
_FRONT_WINDOW_PROBE = (
    'tell application "System Events" to tell process "WhatsApp" to get name of front window'
)


def build_send_url(phone_e164: str, body: str) -> str:
    """Build a ``whatsapp://send?phone=...&text=...`` URL from caller inputs.

    The phone parameter is normalised by stripping a leading ``+`` (if any),
    all space characters, and all hyphens, then asserted to be all digits.
    The body is percent-encoded via ``urllib.parse.quote(safe='')`` — RFC
    3986 form, NOT ``quote_plus``: the WhatsApp URL handler interprets ``+``
    as a literal ``+`` in the body and would render ``quote_plus``'s
    space-as-``+`` substitution incorrectly.

    >>> build_send_url("+33 612-345-678", "Hello!")
    'whatsapp://send?phone=33612345678&text=Hello%21'

    :raises ValueError: when the phone string contains non-digit characters
        after the leading ``+`` / spaces / hyphens are stripped. This is the
        T-02-01-01 tampering mitigation — every byte that reaches the
        ``open`` subprocess is either an ASCII digit (in the phone slot)
        or already percent-encoded (in the body slot).
    """
    cleaned = phone_e164.lstrip("+").replace(" ", "").replace("-", "")
    if not cleaned.isdigit():
        raise ValueError(f"phone must be E.164 digits-only after stripping +/-: got {phone_e164!r}")
    quoted_body = urllib.parse.quote(body, safe="")
    return f"whatsapp://send?phone={cleaned}&text={quoted_body}"


async def send_deeplink(phone_e164: str, body: str) -> None:
    """Open WhatsApp with the chat pre-filled, then settle-poll for foreground.

    Steps (D-01):

    1. Build the deep-link URL via :func:`build_send_url`.
    2. Spawn ``/usr/bin/open -g <url>`` (5 s timeout). The ``-g`` flag keeps
       focus from being aggressively stolen — WhatsApp surfaces into the AX
       tree but does NOT become frontmost (verified SP-2).
    3. Settle-poll: up to 30 × 50 ms calls of the front-window-name probe;
       break on the first poll whose stdout contains ``"WhatsApp"`` as a
       substring.

    On settle-poll exhaustion, :class:`SendTimeout` is raised — the caller
    (Plan 02-03 ``send_message``) treats this as an audit-loggable failure
    and surfaces a structured error to the MCP client. On ``/usr/bin/open``
    process timeout (5 s), :class:`OsascriptError` is raised wrapping the
    timeout — that condition shouldn't happen unless the LaunchServices
    dispatch itself is wedged, which is a system-level pathology.

    The keystroke-return that actually fires the message is NOT done here;
    it lives in :mod:`whatsapp_desktop_mcp.sender.osascript_send`. This split keeps
    the D-03 AX preflight insertable between the settle and the keystroke
    in the Plan 02-03 orchestrator.
    """
    url = build_send_url(phone_e164, body)
    logger.debug("send_deeplink: opening %s", url)

    try:
        proc = await asyncio.create_subprocess_exec(
            "/usr/bin/open",
            "-g",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=_OPEN_TIMEOUT_S)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise OsascriptError(
                f"/usr/bin/open hung past {_OPEN_TIMEOUT_S}s for URL scheme dispatch"
            ) from exc
    except FileNotFoundError as exc:
        # /usr/bin/open is part of every macOS; absent only on non-mac
        # runners. Re-raise as OsascriptError for consistency with the
        # osascript wrapper's stderr="osascript-missing" pattern.
        raise OsascriptError("/usr/bin/open not found; non-macOS environment") from exc

    # Settle-poll: bounded loop, never blocks the event loop, exhaustion is
    # the documented failure mode (T-02-01-03 DoS mitigation).
    for _ in range(_SETTLE_MAX_ITERS):
        result = await run_osascript(_FRONT_WINDOW_PROBE, timeout=_PROBE_TIMEOUT_S)
        if result.exit_code == 0 and "WhatsApp" in result.stdout:
            logger.debug("send_deeplink: WhatsApp front window reached")
            return
        await asyncio.sleep(_SETTLE_INTERVAL_S)

    raise SendTimeout(
        "WhatsApp window did not settle within "
        f"{_SETTLE_MAX_ITERS * _SETTLE_INTERVAL_S}s after deep-link open"
    )

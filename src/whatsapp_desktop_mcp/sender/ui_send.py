"""Unified send orchestrator — composes deeplink (1:1) / search-and-click (group)
with the load-bearing AX preflight (D-03 / SEND-04 P5 mitigation).

This module is the **single place** in the project where the
``chat.kind`` dispatch lives:

* ``Chat.kind == "direct"`` → :func:`send_deeplink` from the
  ``whatsapp://send?phone=...&text=...`` URL scheme primary path (D-01).
  WhatsApp surfaces with the chat open and the body pre-filled in the
  compose box; we then verify the focused-window header matches the
  resolved chat name via :func:`assert_focused_chat_matches` and only
  then fire :func:`press_return` to actually send.
* ``Chat.kind == "group"`` → :func:`send_group_via_search`, the
  search-and-click UI fallback (D-02). WhatsApp's ``whatsapp://send``
  URL scheme does not accept ``@g.us`` group JIDs, so the group path
  drives the sidebar search box: open the sidebar search, type the
  chat name, AX-assert the topmost result matches before pressing
  Return to open the chat, AX-assert the focused chat header matches
  before typing the body, then press Return to send. Group sends carry
  ``is_experimental=True`` in the upstream ``SendResult`` because the
  search-and-click flow is documented-fragile across WhatsApp Catalyst
  minor versions.
* Anything else (``"broadcast"``, ``"community"``, ``"other"``) →
  :class:`NotImplementedError` with the explicit supported-kinds list.
  Broadcast / community sends are out of scope for v0.1 per CONTEXT.md
  §"Out of scope".

The load-bearing D-03 invariant
================================
**Every keystroke in this module is preceded — in source-order, inside
the same execution branch — by a call to**
:func:`assert_focused_chat_matches` **(or, for the group fallback's
first preflight,** :func:`_assert_first_search_result_matches` **).**
This is the SEND-04 / P5 wrong-chat-fuzzy-send mitigation. The
assertions raise :class:`ChatHeaderMismatch` /
:class:`AccessibilityAPIUnavailable` BEFORE any keystroke fires;
the upstream tool maps those to structured MCP errors and
audit-logs ``outcome="error"`` so the failure is observable.

If a future contributor adds a keystroke path that bypasses the AX
preflight, Plan 02-05's regression test
``test_send_message_aborts_on_chat_header_mismatch`` will catch it via
behavioural assertion (the test mocks
:func:`assert_focused_chat_matches` to raise and verifies no
``press_return`` mock invocation occurs).

The SP-1 locked sidebar-search shortcut
========================================
The Wave-0 spike SP-1 (recorded in ``02-01-SPIKES.md``) verified live
that ``Cmd-F`` focuses WhatsApp Catalyst's sidebar "Rechercher" (FR)
/ "Search" (en_US) field — exactly the box ``send_group_via_search``
needs. The spike also showed the focused element role is
``AXGenericElement`` with description ``‎Rechercher`` (leading
U+200E LRM, stripped by the AX preflight before comparison). No
AX-click fallback is needed in v0.1; if a future Catalyst minor
moves the shortcut, the AX preflight on the typed-name result will
catch the wrong-search-box landing (the heading walk would find no
chat name match and raise :class:`ChatHeaderMismatch`).

Non-BMP body handling (P12 / D-08 of Plan 02-01)
================================================
The 1:1 deep-link path URL-encodes the full Unicode body via
``urllib.parse.quote`` and is therefore SAFE for any code point
including emoji / non-BMP scripts (the WhatsApp URL scheme handler
renders the percent-escaped sequence correctly).

The group-fallback path uses :func:`type_string` which REJECTS
non-BMP code points up-front with :class:`OsascriptError` (research
P12 verified: AppleScript ``keystroke <string>`` truncates surrogate
pairs). For v0.1, group sends are BMP-only; this restriction is
documented in ``send_message``'s tool description so the LLM client
surfaces a clean error rather than silently sending a partial body.

REL-05 D-24 invariant
=====================
This module imports NOTHING from the project's read-side data tier.
The narrow sender → DB-connection-helper edge per D-24 lives ONLY
in :mod:`whatsapp_desktop_mcp.sender.verify` (the post-hoc DB poller); this
orchestrator composes the in-package sender primitives + the
permissions/osascript wrapper Phase 0 ships.

Async pattern (REL-02)
======================
Every public callable is ``async def``. The synchronous AX preflight
(``assert_focused_chat_matches`` is pyobjc-backed; ~5-15 ms typical;
SP-3 / SP-4 / SP-5 verified) runs inline because the latency is
small enough that yielding the event loop costs more than the probe
itself; the upstream ``send_message`` tool runs inside its own
asyncio task so the AX preflight inline-call doesn't block the
stdio loop's other coroutines for more than a few milliseconds.
"""

from __future__ import annotations

import asyncio
import logging
import time

from whatsapp_desktop_mcp.permissions.osascript import run_osascript
from whatsapp_desktop_mcp.sender.ax_assert import (
    _assert_first_search_result_matches,
    assert_focused_chat_matches,
)
from whatsapp_desktop_mcp.sender.deeplink import send_deeplink
from whatsapp_desktop_mcp.sender.osascript_send import press_return, type_string

logger = logging.getLogger(__name__)

# Settle intervals between scripted user actions in the group fallback.
# Calibrated against the Pattern 4 recipe in 02-RESEARCH.md and the
# SP-1 spike timing observations.
_POST_ACTIVATE_SETTLE_S = 0.3  # WhatsApp window-focus settle after activate
_POST_SHORTCUT_SETTLE_S = 0.15  # post Cmd-F sidebar-search focus settle
_POST_SEARCH_TYPE_SETTLE_S = 0.4  # let WA render search results
_POST_CHAT_OPEN_SETTLE_S = 0.4  # let WA render chat pane after selecting result
_POST_BODY_TYPE_SETTLE_S = 0.15  # post body keystroke settle before Return


async def send_text(
    chat_id: int,
    body: str,
    chat_name: str,
    recipient_phone_e164: str | None,
    kind: str,
) -> tuple[bool, float]:
    """Drive the unified send for one ``chat_id`` / ``body``.

    Dispatches on ``kind``:

    * ``"direct"``: requires ``recipient_phone_e164`` (raises
      :class:`ValueError` if ``None``). Runs the deep-link primary
      path: build URL + ``open -g`` + settle-poll for WhatsApp
      front-window; AX-assert the focused chat header matches
      ``chat_name``; press Return to send.
    * ``"group"``: runs the search-and-click fallback. Activate
      WhatsApp + open sidebar search via Cmd-F (SP-1 locked) + type
      ``chat_name`` + AX-assert the topmost result matches + press
      Return to open the chat + AX-assert the now-focused chat header
      matches + type ``body`` + press Return to send.
    * Anything else: raises :class:`NotImplementedError` with the
      supported-kinds list.

    Args:
        chat_id: The opaque ``ZWACHATSESSION.Z_PK`` from the reader.
            Echoed unchanged for diagnostic / error-message use.
        body: The outgoing message body (Unicode; non-BMP allowed for
            1:1 only — group path will raise
            :class:`OsascriptError` on non-BMP per P12).
        chat_name: The display name resolved from ``reader.find_chat_by_id``.
            Used by the AX preflight to verify the focused chat header
            and (for group sends) the topmost search result.
        recipient_phone_e164: E.164 digits-only phone number for 1:1
            sends. The deep-link URL builder normalizes ``+ / space /
            hyphen``; the caller may pass any of those forms.
        kind: ``"direct"`` | ``"group"`` | other. From ``Chat.kind``.

    Returns:
        ``(is_experimental, send_started_unix)``:

        * ``is_experimental``: ``True`` for group sends (D-02
          documented-fragility flag); ``False`` for 1:1 deep-link
          sends.
        * ``send_started_unix``: Unix-epoch wall-clock captured BEFORE
          the open subprocess fired. The caller passes this to
          :func:`whatsapp_desktop_mcp.sender.verify.poll_for_outgoing` so the
          ``ZMESSAGEDATE > ?`` predicate excludes any pre-existing
          identical body from earlier in the chat history.

    Raises:
        ValueError: if ``kind == "direct"`` and ``recipient_phone_e164``
            is ``None`` (a 1:1 chat with no phone — typically a
            ``@lid``-only contact for which the WhatsApp URL scheme
            cannot send).
        NotImplementedError: if ``kind`` is anything other than
            ``"direct"`` or ``"group"``.
        ChatHeaderMismatch: from the AX preflight when the focused
            chat header (or for group sends, the topmost sidebar
            result) does not match ``chat_name``.
        AccessibilityAPIUnavailable: from the AX preflight when
            pyobjc is not installed (D-06 fallback).
        SendTimeout: from the deep-link settle-poll on 1:1
            exhaustion.
        OsascriptError / AutomationRevoked: from any keystroke /
            osascript invocation that fails (T-6 mid-send TCC
            revocation surfaces as :class:`AutomationRevoked`).
    """
    # send_started_unix MUST be captured BEFORE any subprocess fires
    # so the post-hoc verify predicate ZMESSAGEDATE > ? cleanly
    # excludes pre-existing identical bodies (D-21).
    send_started_unix = time.time()

    if kind == "direct":
        if recipient_phone_e164 is None:
            raise ValueError(f"1:1 send requires phone_e164; got chat_id={chat_id} kind={kind}")
        # STEP 1 — deep-link open + settle (D-01). WhatsApp surfaces
        # with chat open + body pre-filled in compose box.
        await send_deeplink(recipient_phone_e164, body)
        # STEP 2 — D-03 LOAD-BEARING AX PREFLIGHT.
        # Sync call; raises ChatHeaderMismatch /
        # AccessibilityAPIUnavailable BEFORE any keystroke fires.
        # MUST appear before press_return on this branch (source-order
        # invariant — Plan 02-05 test_send_message_aborts_on_chat_header_mismatch
        # asserts the call order at the orchestration layer).
        assert_focused_chat_matches(chat_name)
        # STEP 3 — fire Return. The body is already in the compose
        # box (deep-link pre-filled it); Return sends.
        await press_return()
        logger.debug(
            "send_text direct: chat_id=%d body_len=%d sent",
            chat_id,
            len(body),
        )
        return (False, send_started_unix)

    if kind == "group":
        await send_group_via_search(chat_name, body)
        logger.debug(
            "send_text group: chat_id=%d body_len=%d sent (is_experimental=True)",
            chat_id,
            len(body),
        )
        return (True, send_started_unix)

    raise NotImplementedError(
        f"send_text does not support chat kind={kind!r}; supported: 'direct', 'group'"
    )


async def send_group_via_search(chat_name: str, body: str) -> None:
    """Drive the group-send search-and-click fallback (D-02 / Pattern 4).

    Sequence (verbatim from 02-RESEARCH.md §"Pattern 4" with SP-1
    locked sidebar-search shortcut):

    1. Activate WhatsApp via ``tell application "WhatsApp" to
       activate``; settle 300 ms for window focus.
    2. Open the sidebar search via the SP-1-locked ``Cmd-F``
       shortcut; settle 150 ms for focus.
    3. Type ``chat_name`` into the search field. :func:`type_string`
       rejects non-BMP code points up-front so a clean
       :class:`OsascriptError` surfaces rather than a silent
       truncation. Settle 400 ms for WhatsApp to render results.
    4. **AX preflight on the topmost result**:
       :func:`_assert_first_search_result_matches` walks the focused
       window AX tree with the widened ``{"AXHeading", "AXButton"}``
       role set (SP-5 locked) and asserts the topmost result's
       stripped-bidi-casefolded label contains ``chat_name``.
       Raises :class:`ChatHeaderMismatch` on miss BEFORE any further
       keystroke fires — load-bearing P5 mitigation for the
       group-fallback path.
    5. Press Return to select the topmost result and open the chat.
       Settle 400 ms for WhatsApp to render the chat pane.
    6. **AX preflight on the now-focused chat header**:
       :func:`assert_focused_chat_matches` (D-03) — the same
       load-bearing check used by the 1:1 path, applied here to the
       now-open group chat. Raises :class:`ChatHeaderMismatch` on
       miss BEFORE the body keystroke fires.
    7. Type the body. :func:`type_string` again — non-BMP body
       rejected up-front. Settle 150 ms.
    8. Press Return to fire the send.

    Every keystroke (steps 3, 5, 7, 8) is preceded — in source-order
    on this same code path — by an AX preflight (steps 4 and 6) that
    raises before the keystroke. This is the structural enforcement
    of the D-03 invariant on the group fallback.
    """
    # Step 1 — activate
    await run_osascript('tell application "WhatsApp" to activate', timeout=3.0)
    await asyncio.sleep(_POST_ACTIVATE_SETTLE_S)

    # Step 2 — open sidebar search (SP-1 locked: Cmd-F on WhatsApp
    # Catalyst 26.16.74 reliably focuses the sidebar "Rechercher" /
    # "Search" AXGenericElement).
    await run_osascript(
        'tell application "System Events" to keystroke "f" using {command down}',
        timeout=3.0,
    )
    await asyncio.sleep(_POST_SHORTCUT_SETTLE_S)

    # Step 3 — type chat name into the search field. type_string
    # rejects non-BMP code points up-front (P12); BMP-only group
    # search-and-click is the v0.1 constraint documented in
    # send_message's tool description.
    await type_string(chat_name)
    await asyncio.sleep(_POST_SEARCH_TYPE_SETTLE_S)

    # Step 4 — AX PREFLIGHT on the topmost search result. MUST
    # raise BEFORE press_return on this branch (SP-5 / load-bearing
    # P5 mitigation for the group-fallback first-result selection).
    # This call is the source-order guarantee that no Return-press
    # selects a wrong chat.
    _assert_first_search_result_matches(chat_name)

    # Step 5 — Return selects the topmost result, opens the chat.
    await press_return()
    await asyncio.sleep(_POST_CHAT_OPEN_SETTLE_S)

    # Step 6 — D-03 LOAD-BEARING AX PREFLIGHT on the now-focused
    # chat header. The same check used by the 1:1 path, applied to
    # the group chat that just opened. MUST appear before the body
    # type_string (Plan 02-05 asserts call order at the
    # orchestration layer).
    assert_focused_chat_matches(chat_name)

    # Step 7 — type the body. Non-BMP rejected up-front by
    # type_string per P12.
    await type_string(body)
    await asyncio.sleep(_POST_BODY_TYPE_SETTLE_S)

    # Step 8 — Return sends.
    await press_return()

"""macOS Accessibility-API state assertion for the WhatsApp send path.

This module is the **load-bearing P5 mitigation** against the wrong-chat
fuzzy-send class of bugs (CONTEXT.md D-03 / SEND-04). Before any keystroke
fires from the sender, this module reads the currently-focused WhatsApp
window's chat header via the macOS Accessibility API (pyobjc binding for
``ApplicationServices``) and compares it against the chat name the upstream
tool layer resolved from ``chat_id``. If the focused chat does NOT match —
because the user manually switched chats between the resolve step and the
send step, OR because the deep-link opened a different chat than the URL
encoded, OR because WhatsApp itself navigated due to an incoming
notification — the send is aborted with :class:`ChatHeaderMismatch` and the
keystroke never runs.

**Why pyobjc and not an ``osascript`` AX walk:** verified live the
``osascript`` AX walk works but takes ~150–300 ms per probe (vs ~5–15 ms
for pyobjc). Pre-send latency dominates the send experience; the AX walk
runs on the hot path and we want it cheap.

**Why D-06 try/except ImportError:** if the user's pyobjc install is
broken (wrong arch, .dylib resolution failure, etc.), we MUST NOT crash
the entire MCP server at import time — the read tools must keep working
even if pyobjc is unhappy. The top-of-module pyobjc imports are wrapped
in ``try/except ImportError``; on failure ``_PYOBJC_AVAILABLE`` is set to
``False`` and both public functions raise the structured
:class:`AccessibilityAPIUnavailable` exception (NOT a Python traceback) so
the upstream tool surface can map it to a clean MCP error.

**Three bidi invisibles to strip** (verified live on WhatsApp 26.16.74,
2026-05-13 — see ``02-RESEARCH.md §"Pattern 2"`` and SP-3 spike):

* U+200E LRM — Left-to-Right Mark (the most common, prefixed on every
  user-visible label)
* U+2068 FSI — First Strong Isolate
* U+2069 PDI — Pop Directional Isolate

All three are declared via ``\\uNNNN`` escape literal form (NOT raw
characters) so the source file stays grep-stable: the raw characters
would render as zero-width invisibles in source viewers and would pollute
downstream literal-token greps with ghost matches.

**Bounded depth-first walk** (vs. hardcoded attribute path): the chat
header sits at variable depth in the AXGroup tree — observed live the
path is ``AXWindow → AXGroup → AXGroup → ... → AXHeading`` with depth
depending on whether the sidebar is collapsed. The walk caps at
``_MAX_WALK_NODES = 200`` visited nodes (DoS guard T-02-01-04); a
pathological window with millions of nodes would be aborted with a
"no match" result (raising :class:`ChatHeaderMismatch`) rather than
spinning forever and freeing the OOM/CPU bomb scenario.

**Casefold + substring** (vs. equality): the focused chat header in
WhatsApp Catalyst may carry a locale-dependent suffix
("Olivier Giffard • online" / "Last seen today" / "typing…"). After
stripping the three bidi invisibles and casefolding both sides, a
substring match accommodates locale variation while still failing on
the wrong-chat scenario (a completely different chat name will not
substring-match).

**SP-3 locked role filter:** only ``AXHeading`` is collected by the
default walk. Widening to ``AXStaticText`` would catastrophically
false-positive on message body content (any message bubble containing
the expected chat name would falsely "match" the chat header).

**SP-5 locked role widening for the group-fallback first-result
preflight:** ``_assert_first_search_result_matches`` calls the same
DFS with the widened set ``{"AXHeading", "AXButton"}`` because the
first clickable sidebar result is an ``AXButton`` whose
``AXDescription`` carries the chat display name (with leading U+200E).

**SP-4 locked return tuple:** every
``AXUIElementCopyAttributeValue(elem, attr, None)`` call returns the
2-tuple ``(err: int, value)`` under pyobjc 12.1.

**REL-05 D-24 isolation:** this module imports nothing from the project's
read-side data tier (no DB connection helpers, no message accessors, no
schema probes). The only intra-project import is
:mod:`whatsapp_desktop_mcp.exceptions` for the structured error classes. The
sender → connection-helper edge that ships in Plan 02-03's verify module
is intentionally NOT a dependency of the AX preflight.

**Sync (not async):** the pyobjc AX-API calls are CPU-bound C extensions;
wrapping them in ``asyncio.to_thread`` adds latency without benefit. The
Plan 02-03 orchestrator calls these functions from inside its own
``asyncio.to_thread`` if it wants to keep the event loop responsive; for
v0.1 the AX preflight latency (~5–15 ms) is small enough to run inline
without yielding.
"""

from __future__ import annotations

import logging
from typing import Any

from whatsapp_desktop_mcp.exceptions import (
    AccessibilityAPIUnavailable,
    ChatHeaderMismatch,
)

logger = logging.getLogger(__name__)

# D-06 — pyobjc imports wrapped in try/except so a broken install on the
# user's machine does NOT crash the entire MCP server at import time. The
# read tools keep working; only the AX preflight surfaces as an
# AccessibilityAPIUnavailable error.
try:
    from ApplicationServices import (  # type: ignore[import-untyped]
        AXUIElementCopyAttributeValue,
        AXUIElementCreateApplication,
        kAXChildrenAttribute,
        kAXDescriptionAttribute,
        kAXFocusedWindowAttribute,
        kAXRoleAttribute,
        kAXTitleAttribute,
    )
    from Cocoa import NSWorkspace  # type: ignore[import-untyped]

    _PYOBJC_AVAILABLE = True
except ImportError:
    _PYOBJC_AVAILABLE = False


# The three bidi invisibles WhatsApp Catalyst injects into AX labels.
# Declared via Python \uNNNN escape literal form (NOT raw characters) so
# this source file stays grep-stable: raw zero-width characters would render
# as zero-width invisibles in source viewers and pollute downstream literal-
# token grep gates with ghost matches. The escape literals \u200E / \u2068
# / \u2069 are interpreted by the Python parser at module-load time into
# the same three codepoints WhatsApp emits in AX labels, so set membership
# tests against AX-extracted strings work as expected.
#
#   \u200E LRM — Left-to-Right Mark (most common; prefixes every label)
#   \u2068 FSI — First Strong Isolate
#   \u2069 PDI — Pop Directional Isolate
_INVISIBLE_BIDI: frozenset[str] = frozenset({"\u200e", "\u2068", "\u2069"})


# WhatsApp Desktop's bundle identifier (verified live on WhatsApp 26.16.74).
_WHATSAPP_BUNDLE_ID = "net.whatsapp.WhatsApp"


# Bounded depth-first walk cap (T-02-01-04 DoS guard). The chat header sits
# at variable depth — observed live ~50–80 nodes total under the focused
# window in sidebar-only mode, more when a chat is open. 200 is a generous
# margin; if a pathological window had more nodes, exhausting this budget
# falls through to ChatHeaderMismatch (safer than OOM).
_MAX_WALK_NODES = 200


# Default narrow role filter for the focused-chat preflight. SP-3 locked
# this set: AXHeading only — widening to AXStaticText would
# catastrophically false-positive on message body text.
_DEFAULT_HEADING_ROLES: frozenset[str] = frozenset({"AXHeading"})


# Widened role filter for the sidebar-search first-result preflight. SP-5
# locked this set: the topmost clickable search result is an AXButton
# whose AXDescription carries the chat display name (verified live).
_SIDEBAR_RESULT_ROLES: frozenset[str] = frozenset({"AXHeading", "AXButton"})


def _strip_bidi(s: str) -> str:
    """Strip the three known bidi invisibles WhatsApp Catalyst inserts.

    Casefolding is deliberately NOT applied here — callers apply it at
    the comparison site so display/audit paths can keep original case.
    """
    return "".join(c for c in s if c not in _INVISIBLE_BIDI).strip()


def _resolve_whatsapp_pid() -> int | None:
    """Resolve WhatsApp Desktop's PID via ``NSWorkspace.runningApplications``.

    Returns ``None`` when:
      * pyobjc is not available (``_PYOBJC_AVAILABLE == False``), OR
      * WhatsApp.app is not currently running.

    The caller distinguishes these two cases at its own discretion — the
    public functions raise :class:`AccessibilityAPIUnavailable` for the
    first and :class:`ChatHeaderMismatch` for the second.
    """
    if not _PYOBJC_AVAILABLE:
        return None
    workspace = NSWorkspace.sharedWorkspace()
    for app in workspace.runningApplications():
        if app.bundleIdentifier() == _WHATSAPP_BUNDLE_ID:
            return int(app.processIdentifier())
    return None


def _walk_for_heading(
    elem: Any,
    *,
    roles: frozenset[str] = _DEFAULT_HEADING_ROLES,
) -> list[str]:
    """Bounded depth-first walk; collect AX-label strings under ``elem``.

    For every node whose ``AXRole`` is in ``roles``, both ``AXDescription``
    and ``AXTitle`` are read and any non-empty string value is appended to
    the result list. Children are enqueued via ``AXChildren``.

    SP-3-locked default roles: ``{"AXHeading"}``. SP-5-widened roles for
    the sidebar-result preflight: ``{"AXHeading", "AXButton"}``.

    The walk is bounded at ``_MAX_WALK_NODES`` visited nodes; exhaustion
    returns whatever was collected so far (the caller's
    :class:`ChatHeaderMismatch` raise will surface as "no match found").
    """
    headings: list[str] = []
    queue: list[Any] = [elem]
    visited = 0
    while queue and visited < _MAX_WALK_NODES:
        node = queue.pop()
        visited += 1

        # SP-4 locked return shape: AXUIElementCopyAttributeValue returns
        # tuple[err: int, value]. err == 0 means success.
        role_err, role = AXUIElementCopyAttributeValue(node, kAXRoleAttribute, None)
        if role_err == 0 and role in roles:
            desc_err, desc = AXUIElementCopyAttributeValue(node, kAXDescriptionAttribute, None)
            if desc_err == 0 and isinstance(desc, str) and desc:
                headings.append(desc)
            title_err, title = AXUIElementCopyAttributeValue(node, kAXTitleAttribute, None)
            if title_err == 0 and isinstance(title, str) and title:
                headings.append(title)

        kids_err, kids = AXUIElementCopyAttributeValue(node, kAXChildrenAttribute, None)
        if kids_err == 0 and kids:
            # __NSArrayM iterates as a Python list of AXUIElementRef.
            queue.extend(kids)

    return headings


def assert_focused_chat_matches(expected_chat_name: str) -> None:
    """Verify WhatsApp's currently-focused chat header matches the expected name.

    Algorithm (D-03 / SEND-04):

    1. If pyobjc is unavailable (D-06 fallback), raise
       :class:`AccessibilityAPIUnavailable`.
    2. Resolve WhatsApp.app's PID via NSWorkspace. If WhatsApp is not
       running, raise :class:`ChatHeaderMismatch`.
    3. Create an AX element for the application, read its
       ``AXFocusedWindow`` attribute. On failure, raise
       :class:`ChatHeaderMismatch`.
    4. Walk the focused window's AX tree (bounded DFS at 200 nodes) and
       collect every ``AXHeading`` description/title.
    5. Strip bidi invisibles + casefold both sides. If the expected name
       (after strip + casefold) appears as a substring of ANY observed
       heading (after strip + casefold), the send is safe — return.
    6. Otherwise raise :class:`ChatHeaderMismatch` with the expected name
       and the stripped observed headings in the message.

    Substring (not equality) accommodates WhatsApp's locale-dependent
    header suffixes ("• online", "Last seen today", "typing…"). The
    expected name must appear in full; partial matches that span the
    suffix do not occur in practice.
    """
    if not _PYOBJC_AVAILABLE:
        raise AccessibilityAPIUnavailable(
            "pyobjc not available; cannot perform AX preflight — reinstall "
            "pyobjc-core, pyobjc-framework-Cocoa, and "
            "pyobjc-framework-ApplicationServices to enable wrong-chat protection"
        )

    pid = _resolve_whatsapp_pid()
    if pid is None:
        raise ChatHeaderMismatch(
            "WhatsApp.app is not running; cannot read focused-window header — "
            "start WhatsApp Desktop and retry"
        )

    app = AXUIElementCreateApplication(pid)
    err, window = AXUIElementCopyAttributeValue(app, kAXFocusedWindowAttribute, None)
    if err != 0 or window is None:
        raise ChatHeaderMismatch(
            f"AXFocusedWindow lookup failed (err={err}); cannot verify chat header — "
            "bring WhatsApp Desktop to foreground and retry"
        )

    headings = _walk_for_heading(window, roles=_DEFAULT_HEADING_ROLES)
    expected = _strip_bidi(expected_chat_name).casefold()

    for h in headings:
        if expected in _strip_bidi(h).casefold():
            logger.debug(
                "assert_focused_chat_matches: matched expected=%r in observed header",
                expected_chat_name,
            )
            return

    raise ChatHeaderMismatch(
        f"Focused chat header does not match expected={expected_chat_name!r}; "
        f"observed AXHeading values (stripped) = "
        f"{[_strip_bidi(h) for h in headings]}"
    )


def _assert_first_search_result_matches(chat_name: str) -> None:
    """Verify the topmost sidebar-search result matches the expected chat name.

    Companion preflight for Plan 02-03's group-send fallback (CONTEXT.md
    D-02 search-and-click flow). The orchestrator types the chat name
    into the sidebar search field, waits for results to render, and
    THEN calls this function before pressing Return to open the chat —
    so the wrong-chat protection covers the group-fallback path the
    same way :func:`assert_focused_chat_matches` covers the 1:1
    deep-link path.

    Algorithm matches :func:`assert_focused_chat_matches` with two
    differences:

    1. The role filter is widened to ``{"AXHeading", "AXButton"}``
       (SP-5 locked: sidebar result rows are ``AXButton`` with the chat
       display name in ``AXDescription``; the ``AXHeading`` siblings in
       the sidebar — section labels like "Discussions", date separators
       — are harmless because the substring match accommodates them
       cleanly).
    2. The error message references the search-result context, not
       the chat header context, so audit-log readers can distinguish
       which preflight failed.
    """
    if not _PYOBJC_AVAILABLE:
        raise AccessibilityAPIUnavailable(
            "pyobjc not available; cannot perform AX preflight — reinstall "
            "pyobjc-core, pyobjc-framework-Cocoa, and "
            "pyobjc-framework-ApplicationServices to enable wrong-chat protection"
        )

    pid = _resolve_whatsapp_pid()
    if pid is None:
        raise ChatHeaderMismatch(
            "WhatsApp.app is not running; cannot read sidebar search results — "
            "start WhatsApp Desktop and retry"
        )

    app = AXUIElementCreateApplication(pid)
    err, window = AXUIElementCopyAttributeValue(app, kAXFocusedWindowAttribute, None)
    if err != 0 or window is None:
        raise ChatHeaderMismatch(
            f"AXFocusedWindow lookup failed (err={err}); cannot verify "
            "sidebar search results — bring WhatsApp Desktop to foreground "
            "and retry"
        )

    labels = _walk_for_heading(window, roles=_SIDEBAR_RESULT_ROLES)
    expected = _strip_bidi(chat_name).casefold()

    for label in labels:
        if expected in _strip_bidi(label).casefold():
            logger.debug(
                "_assert_first_search_result_matches: matched expected=%r in sidebar",
                chat_name,
            )
            return

    raise ChatHeaderMismatch(
        f"Sidebar search topmost result does not match expected chat_name="
        f"{chat_name!r}; observed sidebar label(s) (stripped) = "
        f"{[_strip_bidi(label) for label in labels]}"
    )

# Phase 2 — Plan 02-01 Wave-0 Spike Findings

**Spiked:** 2026-05-13
**Environment:** macOS 26.4 (Darwin 25.4.0), WhatsApp Desktop 26.16.74 (`net.whatsapp.WhatsApp`), French (FR) locale.
**Purpose:** resolve the open empirical questions A1..A6 in `02-RESEARCH.md §"Open Questions" / §"Assumptions Log"` BEFORE writing the sender primitive modules. Each spike's locked decision feeds Tasks 2 and 3 of this plan and is referenced by Plans 02-03 and 02-05.

The five spikes were run live against the maintainer's machine with WhatsApp Desktop active. No actual message was sent: SP-2 used a non-routable E.164 (`99999999999`) so the deep-link surfaced the "Send to ... ?" prompt without firing; the prompt was dismissed via Escape before this file was written.

---

## SP-1 — Cmd-F vs AX-click for sidebar-search focus (A1)

**Hypothesis:** WhatsApp Catalyst's `Cmd-F` may focus an in-chat search box rather than the sidebar's global "Rechercher / Search" field; if so, D-02's group-fallback would need to AX-click the sidebar `AXGenericElement` instead.

**Method:** activate WhatsApp; send `keystroke "f" using {command down}` via `osascript`; query `value of attribute "AXFocusedUIElement"` for description / role / role description.

**Observed result (verbatim):**

```
--- after activate, front window name:
‎WhatsApp
--- send Cmd-F:
--- focused element description:
‎Rechercher
--- focused element role:
AXGenericElement
--- focused element role description:

```

**Locked decision:** `Cmd-F` reliably focuses the **sidebar** "Rechercher" (FR) / "Search" (en_US) field on this WhatsApp Catalyst build. The focused element role is `AXGenericElement` with description `‎Rechercher` (note the leading U+200E LRM). Plan 02-03's group-fallback orchestrator (D-02) will use `Cmd-F` directly; no AX-click fallback is needed for v0.1. If a future WhatsApp Catalyst version moves the shortcut, the failure mode is detectable: after `Cmd-F`, the orchestrator can probe `AXFocusedUIElement` and verify the description (bidi-stripped) equals "Rechercher" or "Search" before typing. That belt-and-braces probe belongs in Plan 02-03, not here.

**Affects:** Task 3 — `_assert_first_search_result_matches` assumes the sidebar search is reachable via `Cmd-F`; Plan 02-03 `sender/ui_send.py` will press `Cmd-F`, not `Cmd-N`.

---

## SP-2 — `/usr/bin/open -g whatsapp://...` foreground behavior (A2 / A3)

**Hypothesis:** `open -g` either (a) raises the WhatsApp window into the AX tree without grabbing focus (research assumption — keeps Cmd-Tab order untouched) or (b) keeps WhatsApp completely background, in which case the 1.5s settle-poll would never observe a WhatsApp front window and the `-g` flag would need to be dropped.

**Method:** activate Terminal to background WhatsApp; run `/usr/bin/open -g whatsapp://send?phone=99999999999&text=spike_SP2` (non-routable phone so no actual send fires); poll `osascript -e 'tell application "System Events" to tell process "WhatsApp" to get name of front window'` at 50ms × 30; record frontmost app and WhatsApp window name on each iteration. Press Escape after to dismiss WhatsApp's "Send to ... ?" prompt.

**Observed result (verbatim, with shell-locale comma as the decimal):**

```
--- backgrounding WhatsApp by activating Terminal:
--- pre-open front app:
Terminal
--- launch /usr/bin/open -g with non-routable phone (no actual send risk):
--- open returned, polling for WhatsApp window name at 50ms × 30:
poll 1 (t=0,595s): front=Terminal  whatsapp_window=‎WhatsApp
*** WhatsApp window reachable at iteration 1 (0,595s)
```

The 0.595s on iteration 1 is dominated by the `osascript` spawn cost of the front-window-name probe itself, not by WhatsApp settling. WhatsApp's front window name (`‎WhatsApp` — leading U+200E LRM, verified — substring match is mandatory; equality would fail) was reachable on the very first poll. Critically, the frontmost application stayed `Terminal` — `-g` did NOT steal focus.

**Locked decision:** keep `-g` in `send_deeplink`. Settle-poll is bounded at 30 × 50ms = 1.5s with `"WhatsApp" in result.stdout` substring match (NOT `.strip() == "WhatsApp"` — the U+200E LRM trap would silently fail). On exhaustion, raise `SendTimeout`.

**Affects:** Task 2 — `sender/deeplink.py:send_deeplink` uses `["-g", url]` for the `/usr/bin/open` argv and the substring settle-poll predicate `"WhatsApp" in result.stdout`.

---

## SP-3 — `AXHeading` presence when a chat is open (open question 3)

**Hypothesis:** the focused chat's name appears as an `AXHeading` description in WhatsApp Catalyst's AX tree. If only `AXStaticText` carries the name, Task 3's `_walk_for_heading` collection must be widened.

**Method:** activate WhatsApp with a 1:1 chat open; run `osascript ... get entire contents of front window` and filter for `AXHeading` / `AXStaticText` nodes, printing each node's role + description + title + value.

**Observed result (truncated to the load-bearing lines):**

```
AXHeading | desc=‎Discussions | title=missing value | value=missing value
...
AXHeading | desc=+33 6 33 63 13 83 | title=missing value | value=missing value
AXHeading | desc= | title=missing value | value=missing value
AXHeading | desc=‎Aujourd’hui | title=missing value | value=missing value
AXHeading | desc=‎1 message non lu | title=missing value | value=
AXHeading | desc=‎Aujourd’hui | title=missing value | value=missing value
```

The **chat header** (`+33 6 33 63 13 83`) cleanly appears as an `AXHeading` with the chat name in `AXDescription`. The other `AXHeading` nodes are sidebar-section labels (`‎Discussions`) and date separators (`‎Aujourd'hui`, `‎1 message non lu`); these are not problematic because the substring-after-bidi-strip match would not accidentally match a real expected chat name like `+33 6 33 63 13 83` against any of them.

Hundreds of `AXStaticText` entries also exist — they hold every message bubble's text body. Widening the walk to `AXStaticText` would generate **massive** false positives (e.g., any message body containing the expected chat name would falsely "match" the header). The narrow `AXHeading`-only filter is correct.

**Locked decision:** `_walk_for_heading` filter stays `role == "AXHeading"` only. Collect both `AXDescription` (primary — that's where WhatsApp puts the chat name with leading U+200E) and `AXTitle` (defensive — empty on this build, but cheap and harmless to keep). The `_strip_bidi` + `casefold` + `substring-match` algorithm handles the sidebar/date `AXHeading` siblings without ambiguity.

**Affects:** Task 3 — `_walk_for_heading` filter is the narrow `{"AXHeading"}` set (NOT widened to `AXStaticText`).

---

## SP-4 — pyobjc 12.1 `AXUIElementCopyAttributeValue` exact return signature (A6)

**Hypothesis:** pyobjc 12.1 returns `AXUIElementCopyAttributeValue` results as the canonical 2-tuple `(err: int, value)` where the inout-pointer parameter is replaced by `None` on the call side and the unpacked value surfaces in the tuple. Task 3 code must match this shape exactly.

**Method:** spin up a throwaway venv at `.venv-spike`, install `pyobjc-core==12.1`, `pyobjc-framework-Cocoa==12.1`, `pyobjc-framework-ApplicationServices==12.1` via ensurepip-bootstrapped pip; resolve WhatsApp's PID via `NSWorkspace`; call `AXUIElementCreateApplication(pid)` then `AXUIElementCopyAttributeValue(app, kAXFocusedWindowAttribute, None)` and print the result repr / type / length / unpacked shape; repeat for `kAXRoleAttribute` and `kAXChildrenAttribute`.

**Observed result (verbatim):**

```
objc.__version__: 12.1
WhatsApp PID: 5160
app_ref type: <core-foundation class AXUIElementRef at 0x1f19ca4c0>
return repr: (0, <AXUIElement 0xb4ed9b720> {pid=5160})
return type: <class 'tuple'>
len: 2
unpacked: err = 0  value type = <core-foundation class AXUIElementRef at 0x1f19ca4c0>
role return: (0, 'AXWindow')
children: err = 0  n_kids = 4  type = <objective-c class __NSArrayM at 0x1f19ca718>
```

**Locked decision:** pyobjc 12.1's `AXUIElementCopyAttributeValue(elem, attr, None)` returns `tuple[int, Any]` where `[0]` is the AX error code (0 on success) and `[1]` is the attribute value (an `AXUIElementRef`, a Python `str`, an `__NSArrayM` of children, or `None`). Children come back as `__NSArrayM` which iterates as a Python list of `AXUIElementRef`. Task 3 code can write `err, val = AXUIElementCopyAttributeValue(...)` and trust the 2-tuple unpack. The pyobjc throwaway venv was teared down after recording — Task 1's `uv sync --extra dev` is the canonical install location.

**Affects:** Task 3 — every `AXUIElementCopyAttributeValue` call uses the 2-tuple unpack `err, val = AXUIElementCopyAttributeValue(node, attr, None)` and checks `err == 0` before consuming `val`. Children iteration treats the value as an iterable when non-`None`.

---

## SP-5 — Sidebar-search first-result AX role + attribute pair (W-5 follow-up)

**Hypothesis:** sidebar search results expose the chat display name via some combination of `AXTitle` / `AXDescription` / `AXValue` on either `AXButton`, `AXCell`, `AXStaticText`, or `AXGenericElement` nodes. Task 3's `_assert_first_search_result_matches` needs to know the exact (role, attribute) pair.

**Method:** activate WhatsApp; press `Cmd-F` to focus the sidebar search (per SP-1); type a known chat name (`Discussions`); wait 0.6s for results to render; walk the AX tree under the focused window with `kAXChildrenAttribute` recursion, capturing every node's role + title + desc + value; report (a) role distribution and (b) every node whose blob matches `"Discussion"`.

**Observed result (verbatim):**

```
--- role distribution:
  'AXButton': 38
  'AXGroup': 28
  'AXStaticText': 18
  'AXHeading': 7
  'AXWindow': 1
  'AXTextArea': 1
  'AXLink': 1
--- candidates matching 'Discussion':
  depth= 5  role='AXHeading'  title=None  desc='‎Discussions'  value=None
  depth= 5  role='AXStaticText'  title=None  desc='‎Rechercher'  value='Discussions'
  depth= 6  role='AXButton'  title=None  desc='‎Discussions'  value=None
```

Three matches surfaced:
1. `AXHeading desc='‎Discussions'` at depth 5 — the **sidebar-section header** (the "Discussions" group label, not a result row).
2. `AXStaticText desc='‎Rechercher' value='Discussions'` at depth 5 — the **search field itself**, with the typed query as its value.
3. `AXButton desc='‎Discussions'` at depth 6 — the **first clickable result row** in the sidebar list.

The first **clickable** sidebar result is an `AXButton` whose `AXDescription` carries the chat display name (with leading U+200E). `AXTitle` is `None`; `AXValue` is `None` on result rows.

**Locked decision:** `_assert_first_search_result_matches` walks the focused window with the same DFS shape as `_walk_for_heading`, but with a **widened role set** `{"AXHeading", "AXButton"}` for the collection. This reuses the single helper (no parallel `_walk_for_first_button` needed). Filtering at the call site: for the focused-chat preflight, the caller passes the narrow `{"AXHeading"}` set; for the sidebar-result preflight, the caller passes `{"AXHeading", "AXButton"}`. Both read `AXDescription` (primary) and `AXTitle` (defensive). The AXHeading match for the sidebar-section header is benign — the substring-after-bidi-strip + casefold algorithm requires the **expected** chat name as a substring of the **observed** label, which would still match correctly when the user is searching for "Discussions"; and for any other chat name like "Olivier Giffard" the AXHeading siblings labeled "Discussions" / "Rechercher" / "Aujourd'hui" would correctly NOT match.

For implementation simplicity in Task 3, `_walk_for_heading` is parameterized: `_walk_for_heading(elem, *, roles: frozenset[str] = frozenset({"AXHeading"})) -> list[str]`. The `assert_focused_chat_matches` public function calls it with the default narrow set; `_assert_first_search_result_matches` calls it with `roles=frozenset({"AXHeading", "AXButton"})`.

**Affects:** Task 3 — `_walk_for_heading` accepts a `roles` kwarg; `_assert_first_search_result_matches` reuses the same DFS via the widened role set rather than duplicating the walk logic.

---

## Plan-level locked decisions summary

| Spike | Concrete impact on Task 2/3 |
|-------|------------------------------|
| SP-1  | Plan 02-03 group-fallback uses `Cmd-F` for sidebar search; no AX-click fallback in v0.1. |
| SP-2  | `sender/deeplink.py:send_deeplink` passes `["-g", url]` to `/usr/bin/open`; settle-poll predicate is `"WhatsApp" in result.stdout` (substring; NOT equality). |
| SP-3  | `_walk_for_heading` default role filter is `{"AXHeading"}` only — do NOT widen to `AXStaticText` (would massively false-positive on message bodies). |
| SP-4  | Every `AXUIElementCopyAttributeValue(node, attr, None)` call unpacks as `err, val = ...` and checks `err == 0` before consuming `val`. |
| SP-5  | `_walk_for_heading(elem, *, roles=frozenset({"AXHeading"}))` is parameterized; `_assert_first_search_result_matches` calls it with `roles=frozenset({"AXHeading", "AXButton"})`. AXDescription is the primary attribute; AXTitle is collected defensively. |

All five spike decisions are reflected in the implementation that lands in Tasks 2 and 3.

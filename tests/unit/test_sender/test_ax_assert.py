"""Unit tests for ``sender.ax_assert`` — load-bearing D-03 / SEND-04 P5 mitigation.

Covers:

* ``_strip_bidi`` — removes the three known bidi invisibles (U+200E LRM,
  U+2068 FSI, U+2069 PDI) WhatsApp Catalyst injects in AX labels.
* ``assert_focused_chat_matches`` — the load-bearing preflight:
  - pyobjc unavailable → :class:`AccessibilityAPIUnavailable`.
  - WhatsApp not running → :class:`ChatHeaderMismatch`.
  - focused-window AX lookup failure → :class:`ChatHeaderMismatch`.
  - matching heading (after bidi-strip + casefold) → returns None.
  - non-matching heading → :class:`ChatHeaderMismatch`.
* AX walk DoS guard (``_MAX_WALK_NODES = 200``).
* Case-fold substring match (locale variation tolerance).

The verified-live regression string ``"‎⁨Olivier Giffard⁩"`` (with U+200E
LRM, U+2068 FSI, U+2069 PDI invisibles) MUST strip cleanly to
``"Olivier Giffard"`` — that's the Pattern 2 / SP-3 verified-live
regression.
"""

from __future__ import annotations

import pytest

from whatsapp_mcp.exceptions import (
    AccessibilityAPIUnavailable,
    ChatHeaderMismatch,
)
from whatsapp_mcp.sender import ax_assert

# ---------------------------------------------------------------------------
# _strip_bidi — pure helper, no AX-API dependency
# ---------------------------------------------------------------------------


def test_strip_bidi_removes_lrm_fsi_pdi() -> None:
    """VERIFIED-LIVE regression: the user's chat name with bidi invisibles strips cleanly.

    Per Pattern 2 verified-live on WhatsApp 26.16.74 (2026-05-13), the
    AX heading description for a contact named "Olivier Giffard" arrives
    as ``"\\u200E\\u2068Olivier Giffard\\u2069"``. After
    :func:`_strip_bidi` the three invisibles are gone and the result
    is the plain name.
    """
    # The verified-live observed string. Literal codepoints declared as
    # escape sequences to keep the source grep-stable (raw chars render
    # as zero-width invisibles).
    observed = "‎⁨Olivier Giffard⁩"
    assert ax_assert._strip_bidi(observed) == "Olivier Giffard"


def test_strip_bidi_preserves_normal_text() -> None:
    """Text with no bidi invisibles passes through unchanged."""
    assert ax_assert._strip_bidi("Plain text") == "Plain text"


def test_strip_bidi_strips_only_three_known_invisibles() -> None:
    """Other Unicode invisibles (e.g. U+200B ZWSP) are NOT stripped.

    The three bidi codepoints stripped are exactly U+200E / U+2068 / U+2069
    per the verified-live observation. Stripping a wider set (e.g. all
    Cf-category characters) would be a scope expansion that may produce
    surprising matches; keep the strip set narrow.
    """
    s = "hello​world"  # contains a Zero Width Space
    # ZWSP is NOT in the strip set — it remains.
    assert "​" in ax_assert._strip_bidi(s)


# ---------------------------------------------------------------------------
# assert_focused_chat_matches
# ---------------------------------------------------------------------------


def test_pyobjc_unavailable_raises_accessibility_api_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_PYOBJC_AVAILABLE = False`` (D-06 fallback) → AccessibilityAPIUnavailable."""
    monkeypatch.setattr(ax_assert, "_PYOBJC_AVAILABLE", False)
    with pytest.raises(AccessibilityAPIUnavailable, match="pyobjc"):
        ax_assert.assert_focused_chat_matches("Alice")


def test_whatsapp_not_running_raises_chat_header_mismatch(
    mock_pyobjc: object,
) -> None:
    """``runningApplications`` returns no WhatsApp → ChatHeaderMismatch."""
    # mock_pyobjc returns the _AXFake; access via cast.
    from tests.unit.conftest import _AXFake

    fake: _AXFake = mock_pyobjc  # type: ignore[assignment]
    fake.whatsapp_running = False

    with pytest.raises(ChatHeaderMismatch, match="not running"):
        ax_assert.assert_focused_chat_matches("Alice")


def test_focused_window_lookup_fail_raises_chat_header_mismatch(
    mock_pyobjc: object,
) -> None:
    """``AXFocusedWindow`` returns non-zero err → ChatHeaderMismatch."""
    from tests.unit.conftest import _AXFake

    fake: _AXFake = mock_pyobjc  # type: ignore[assignment]
    # Simulate the AX error -25212 (kAXErrorCannotComplete) on focused-window lookup.
    fake.focused_window_err = -25212

    with pytest.raises(ChatHeaderMismatch, match="AXFocusedWindow"):
        ax_assert.assert_focused_chat_matches("Alice")


def test_matching_heading_returns_cleanly(mock_pyobjc: object) -> None:
    """A heading whose stripped/casefolded form contains the expected name → returns None."""
    from tests.unit.conftest import _AXFake

    fake: _AXFake = mock_pyobjc  # type: ignore[assignment]
    fake.walk_returns = ["‎⁨Olivier Giffard⁩"]

    # Should NOT raise — the stripped heading "Olivier Giffard" contains
    # the expected name as a substring.
    ax_assert.assert_focused_chat_matches("Olivier Giffard")


def test_non_matching_heading_raises_chat_header_mismatch(
    mock_pyobjc: object,
) -> None:
    """A heading that doesn't contain the expected name → ChatHeaderMismatch."""
    from tests.unit.conftest import _AXFake

    fake: _AXFake = mock_pyobjc  # type: ignore[assignment]
    fake.walk_returns = ["Mom"]

    with pytest.raises(ChatHeaderMismatch, match="does not match"):
        ax_assert.assert_focused_chat_matches("Momentum project")


def test_strip_bidi_casefold_substring_match(mock_pyobjc: object) -> None:
    """Lowercase expected name matches mixed-case observed heading via casefold."""
    from tests.unit.conftest import _AXFake

    fake: _AXFake = mock_pyobjc  # type: ignore[assignment]
    fake.walk_returns = ["Alice In Wonderland"]

    # Expected lowercase; observed mixed-case. Should match.
    ax_assert.assert_focused_chat_matches("alice in wonderland")


def test_walk_caps_at_200_nodes(mock_pyobjc: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """DoS guard: the DFS visits at most ``_MAX_WALK_NODES`` (200) nodes.

    Build a pathological focused-window AX tree where the root has 500
    direct children, all of which are AXHeading roles but with
    non-matching descriptions. The walk MUST terminate at ≤200 nodes;
    expected behavior is ``ChatHeaderMismatch`` (no match found within
    the visited budget) rather than infinite loop.
    """
    from tests.unit.conftest import _AXFake

    fake: _AXFake = mock_pyobjc  # type: ignore[assignment]
    # 500 heading nodes — exceeds the 200-node DFS budget.
    fake.walk_returns = [f"Heading-{i}" for i in range(500)]

    with pytest.raises(ChatHeaderMismatch):
        ax_assert.assert_focused_chat_matches("Nonexistent Chat Name")

    # role_calls should have plateaued at the DFS cap (200 nodes).
    # The walk explicitly bounds at _MAX_WALK_NODES per the source.
    assert fake.role_calls <= ax_assert._MAX_WALK_NODES + 1


def test_assert_first_search_result_matches_uses_widened_role_set(
    mock_pyobjc: object,
) -> None:
    """``_assert_first_search_result_matches`` exposes the SP-5 widened role filter.

    The companion preflight (for the group-fallback sidebar-search path)
    uses ``{"AXHeading", "AXButton"}`` so the topmost search result row
    (which is an AXButton with the chat display name in AXDescription)
    matches. The mock_pyobjc fixture's walk yields AXHeading by default;
    if we feed in the expected chat name, the matching code path returns
    cleanly without raising.
    """
    from tests.unit.conftest import _AXFake

    fake: _AXFake = mock_pyobjc  # type: ignore[assignment]
    fake.walk_returns = ["‎Alice Smith"]

    # Should NOT raise — the AX preflight on the sidebar's topmost
    # result matches.
    ax_assert._assert_first_search_result_matches("Alice Smith")


def test_assert_focused_chat_matches_error_message_includes_observed_headings(
    mock_pyobjc: object,
) -> None:
    """On mismatch, the exception message names the stripped observed headings."""
    from tests.unit.conftest import _AXFake

    fake: _AXFake = mock_pyobjc  # type: ignore[assignment]
    fake.walk_returns = ["‎Alice Smith", "‎Bob Jones"]

    with pytest.raises(ChatHeaderMismatch) as exc_info:
        ax_assert.assert_focused_chat_matches("Carol Williams")

    msg = str(exc_info.value)
    assert "Carol Williams" in msg
    # The stripped names should appear in the diagnostic.
    assert "Alice Smith" in msg
    assert "Bob Jones" in msg

"""Content invariants for ``README.md`` (Plan 03-04).

Plan 03-04 revamps the Phase 0 README quickstart into a Phase 3 surface:

* a 3-row install matrix (Brew / .pkg / uvx)
* 3 TCC permission cards (Full Disk Access / Accessibility / Automation)
  each carrying its `x-apple.systempreferences:` deep-link
* a "Sending Messages" section that documents the rate-limit defaults,
  the `whatsapp-desktop-mcp dev reset-rate-limit` recovery command, the
  `WHATSAPP_DESKTOP_MCP_SKIP_CONFIRM=1` opt-out (with a stark
  prompt-injection warning), and the WhatsApp ToS account-ban risk

while ALSO preserving the Phase 0 D-20 ToS automation-risk blockquote
and the D-22 "personal account, not a bot" framing line.

These invariants are verified here by lightweight grep / regex matches
against the file bytes — fast (<1s), no network, no subprocesses.

The test deliberately uses a parametrized table so a future contributor
can see at a glance exactly which strings are load-bearing in the
README and why (the description column cross-references the relevant
CONTEXT.md decision ID).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Resolve the repo's README.md from this test file's location. tests/unit/
# is two parents below the repo root.
_README = Path(__file__).resolve().parent.parent.parent / "README.md"
_TEXT = _README.read_text(encoding="utf-8")


# (description, regex_pattern, min_count). All patterns use re.IGNORECASE
# unless otherwise noted; the deep-link URLs and exact env-var names are
# case-sensitive in the wild but lowercasing them is harmless for grep.
_INVARIANTS: list[tuple[str, str, int]] = [
    # Phase 0 D-20 ToS automation-risk blockquote — 4 required clauses.
    ("D-20 ToS clause: bulk messaging", r"automated or bulk messaging", 1),
    ("D-20 ToS clause: irrecoverable ban", r"irrecoverable account ban", 1),
    ("D-20 ToS clause: conservative rate limits", r"conservative rate limits", 1),
    # Phase 0 D-22 framing.
    ("D-22 framing: personal account, not a bot", r"personal account, not a bot", 1),
    # Phase 3 D-31 — 3-row install matrix.
    (
        "D-31 brew install command",
        r"brew install jqueguiner/whatsapp-desktop-mcp/whatsapp-desktop-mcp",
        1,
    ),
    ("D-31 uvx install command", r"uvx whatsapp-desktop-mcp", 1),
    ("D-31 .pkg distribution path (GitHub releases)", r"releases", 1),
    (
        "D-31 Apple Silicon brew binary path",
        r"/opt/homebrew/bin/whatsapp-desktop-mcp",
        1,
    ),
    (
        "D-31 Intel brew / .pkg binary path",
        r"/usr/local/bin/whatsapp-desktop-mcp",
        1,
    ),
    # Phase 3 D-32 — 3 TCC permission cards (deep-link URLs match the
    # exceptions.py single source of truth).
    (
        "D-32 TCC FDA deep-link",
        r"x-apple\.systempreferences:com\.apple\.preference\.security\?Privacy_AllFiles",
        1,
    ),
    (
        "D-32 TCC Accessibility deep-link",
        r"x-apple\.systempreferences:com\.apple\.preference\.security\?Privacy_Accessibility",
        1,
    ),
    (
        "D-32 TCC Automation deep-link",
        r"x-apple\.systempreferences:com\.apple\.preference\.security\?Privacy_Automation",
        1,
    ),
    # Phase 3 D-33 — Sending Messages section content.
    (
        "D-33 dev reset-rate-limit recovery command",
        r"whatsapp-desktop-mcp dev reset-rate-limit",
        1,
    ),
    ("D-33 skip-confirm env var", r"WHATSAPP_DESKTOP_MCP_SKIP_CONFIRM", 1),
    ("D-33 rate limit per minute", r"5 sends.*?min", 1),
    ("D-33 rate limit per day", r"30 sends.*?day", 1),
    # DIST-03 — platform requirements explicit.
    ("DIST-03 macOS only", r"macOS only|macOS-only", 1),
    ("DIST-03 Python 3.12 floor", r"Python 3\.12", 1),
    ("DIST-03 WhatsApp Desktop named", r"WhatsApp Desktop", 1),
    # Pitfall 6 — TCC churn caveat for the uvx row.
    (
        "Pitfall 6 TCC-churn caveat (uvx row)",
        r"TCC.*?churn|re-grant|permission.*?change",
        1,
    ),
    # D-33 stark prompt-injection warning paragraph.
    (
        "D-33 skip-confirm strong warning paragraph",
        r"removes.*?line of defense|prompt[- ]injection|silently obey",
        1,
    ),
]


@pytest.mark.parametrize(
    ("description", "pattern", "min_count"),
    _INVARIANTS,
    ids=[row[0] for row in _INVARIANTS],
)
def test_readme_contains(description: str, pattern: str, min_count: int) -> None:
    """``README.md`` MUST contain ``pattern`` at least ``min_count`` times.

    The ``description`` parameter is surfaced as the parametrize id so
    pytest's failure output names the broken invariant directly (e.g.
    ``test_readme_contains[D-32 TCC FDA deep-link]``).
    """
    matches = re.findall(pattern, _TEXT, re.IGNORECASE | re.DOTALL)
    assert len(matches) >= min_count, (
        f"README.md is missing required content: {description!r}. "
        f"Pattern {pattern!r} matched {len(matches)} times "
        f"(expected >= {min_count}). "
        f"See .planning/phases/03-hardening-and-distribution/03-04-PLAN.md "
        f"and 03-CONTEXT.md (D-20, D-22, D-31, D-32, D-33) for the spec."
    )


def test_readme_does_not_carry_old_package_name() -> None:
    """No ``whatsapp-mcp`` (legacy binary name) in the README.

    The package was renamed to ``whatsapp-desktop-mcp`` in commit 7332f0a;
    the README's install commands MUST point at the new binary name.
    Allow ``whatsapp-mcp`` to appear ONLY when it's part of the longer
    ``whatsapp-desktop-mcp`` string — we test the negative by looking for
    the bare token with a non-``-desktop-`` neighborhood.
    """
    # Match the literal "whatsapp-mcp" only when NOT followed by "-desktop"
    # (i.e. catch the OLD bare binary name; allow ``whatsapp-desktop-mcp``).
    bare_old_name = re.compile(r"whatsapp-mcp(?!-desktop)", re.IGNORECASE)
    # Walk every match and discard those that are actually inside the
    # full new name "whatsapp-desktop-mcp" (that won't match the regex
    # above anyway, but be explicit) or inside an inline-code path the
    # rename leaves untouched (none expected). Any surviving match is a
    # carry-over of the old binary name.
    leaks = []
    for m in bare_old_name.finditer(_TEXT):
        # m.start() points at the start of "whatsapp-mcp". Look back to
        # check it's not preceded by "-desktop" (which would mean we're
        # actually matching inside "whatsapp-desktop-mcp" — impossible
        # given the negative lookahead, but the back-direction protects
        # against future regex tweaks).
        prefix = _TEXT[max(0, m.start() - 8) : m.start()]
        if prefix.endswith("desktop-"):
            continue
        leaks.append((m.start(), _TEXT[max(0, m.start() - 20) : m.end() + 20]))
    assert not leaks, (
        "README.md still references the OLD binary name 'whatsapp-mcp' "
        f"(should be 'whatsapp-desktop-mcp'). Leaks: {leaks!r}"
    )


def test_readme_does_not_carry_placeholder_repo_owner() -> None:
    """No ``gladia/whatsapp-desktop-mcp`` placeholder owner in the README.

    The repo migrated to ``jqueguiner/whatsapp-desktop-mcp`` in commit
    c9d45b8; any surviving ``gladia/whatsapp-desktop-mcp`` is a stale
    placeholder.
    """
    assert "gladia/whatsapp-desktop-mcp" not in _TEXT, (
        "README.md still references the OLD repo owner 'gladia'; "
        "should be 'jqueguiner/whatsapp-desktop-mcp'."
    )


def test_readme_is_substantive() -> None:
    """``README.md`` MUST be at least 4 KB after the Phase 3 revamp.

    The Phase 0 stub README clocked in around 5 KB; Phase 3's 3-row
    install matrix + 3 TCC cards + Sending Messages section roughly
    doubles that. A README dramatically smaller than 4 KB indicates a
    section was accidentally dropped.
    """
    size = _README.stat().st_size
    assert size >= 4096, f"README.md is suspiciously small ({size} bytes)"

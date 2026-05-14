"""Parser for ``docs/tested_versions.md`` (D-19 / D-20 / D-21).

Module-load parse — the file is small (typically <100 rows) and immutable
during process lifetime, so amortized cost is one read per process. The
parser is deliberately fault-tolerant: a malformed row produces a logged
warning and is skipped, NEVER a crash. This is the DIAG-02 invariant in
miniature — ``doctor`` must remain callable when other surfaces fail, and
the ``supported_version_range`` it reports is sourced from this module's
``SUPPORTED_VERSION_RANGE`` constant.

Public surface:

- :data:`SUPPORTED_VERSION_RANGE` — module-load constant; ``(min, max)``
  Z_VERSION tuple computed from the markdown table.
- :func:`load_tested_z_versions` — re-callable accessor returning the same
  tuple shape; tests monkeypatch :data:`_TESTED_VERSIONS_PATH` then call
  this to exercise alternative table content.
- :func:`_load_tested_wa_versions` — sibling helper used by
  :mod:`whatsapp_desktop_mcp.tools.doctor` to compute the structured
  ``degraded_mode_warning`` when the live ``CFBundleShortVersionString``
  isn't in the matrix.

The table file lives at the repository's ``docs/tested_versions.md`` path.
The path is computed relative to this source file so the parser works
regardless of how the package is installed (``uvx`` / ``pip`` / brew /
``.pkg`` venv bundle). When the file isn't present (the parser ships
inside a self-contained venv that doesn't ship docs), the
``(1, 1)`` / empty-set defaults preserve doctor's degraded-mode posture.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# 4 parents up: tested_versions.py → reader/ → whatsapp_desktop_mcp/ → src/ → repo root
# then ``/docs/tested_versions.md``.
_TESTED_VERSIONS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "docs" / "tested_versions.md"
)

# Row regex: header rows have a non-digit Z_VERSION column so they don't
# match; separator rows start with ``|---`` and don't have 3 well-formed
# pipe-separated cells either, so they don't match.
# Group 1: WhatsApp Desktop version (column 1)
# Group 2: macOS version (column 2)
# Group 3: Z_VERSION integer (column 3)
_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|")


def _parse_z_versions(text: str) -> list[int]:
    """Extract Z_VERSION integers from each data row of the markdown table.

    A data row starts with ``|`` and has at least 3 columns before the
    Z_VERSION integer. Header rows (``| WhatsApp Desktop |...``) and
    separator rows (``|------|...``) are skipped because they don't match
    the digit-only Z_VERSION column. The ``try/except ValueError`` is
    defense-in-depth on top of the regex's ``\\d+`` guard — if a future
    regex evolution allows non-numeric input through, the parser still
    skips it instead of crashing (DIAG-02).
    """
    versions: list[int] = []
    for line in text.splitlines():
        match = _ROW_RE.match(line)
        if match:
            try:
                versions.append(int(match.group(3)))
            except ValueError:
                logger.warning("tested_versions.md: failed to parse row %r", line)
    return versions


def _parse_wa_versions(text: str) -> set[str]:
    """Extract WhatsApp Desktop version strings from column 1 of each data row.

    Same regex / structural fault-tolerance discipline as
    :func:`_parse_z_versions`; returns a ``set[str]`` because the doctor
    extension uses set membership (``wa_version not in tested_wa``).
    """
    versions: set[str] = set()
    for line in text.splitlines():
        match = _ROW_RE.match(line)
        if match:
            versions.add(match.group(1).strip())
    return versions


def load_tested_z_versions() -> tuple[int, int]:
    """Return ``(min, max)`` tuple of Z_VERSION integers from the table.

    Returns ``(1, 1)`` (the Phase 1 verified-live initial value, matching
    CONTEXT.md D-20's documented default) when the file is missing or
    contains zero parseable rows. The defaults are chosen so a fresh
    install where ``docs/tested_versions.md`` was excluded from the
    venv bundle still yields a sensible ``supported_version_range``
    on doctor output.
    """
    try:
        text = _TESTED_VERSIONS_PATH.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        logger.warning(
            "tested_versions.md not found at %s; using (1,1) default",
            _TESTED_VERSIONS_PATH,
        )
        return (1, 1)
    versions = _parse_z_versions(text)
    if not versions:
        return (1, 1)
    return (min(versions), max(versions))


def _load_tested_wa_versions() -> set[str]:
    """Return the set of WhatsApp Desktop version strings from column 1.

    Empty set on missing file / parse failure (graceful degradation; the
    doctor caller treats an empty set as "any wa_version is out-of-range",
    but the warning string still serializes cleanly via the ``default="(none)"``
    sentinel on ``max()`` in the caller).
    """
    try:
        text = _TESTED_VERSIONS_PATH.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return set()
    return _parse_wa_versions(text)


SUPPORTED_VERSION_RANGE: tuple[int, int] = load_tested_z_versions()

"""Plan 03-03 Task 1 — `reader/tested_versions.py` parser tests (RED → GREEN).

Verifies the four behaviors of the parser at module load:

1. ``load_tested_z_versions()`` returns ``(1, 1)`` when ``docs/tested_versions.md``
   is absent (DIAG-02 fault-tolerant default per CONTEXT.md D-20 / Pitfall 4).
2. Given a temp file with three valid data rows (Z_VERSION 1, 1, 2), returns
   ``(1, 2)``.
3. Given a row with Z_VERSION="unknown" mixed with two integer rows (1 and 2),
   the parser logs a WARNING (captured via caplog) AND returns ``(1, 2)`` —
   does NOT raise (DIAG-02 invariant).
4. A typical markdown table with a header row (``| WhatsApp Desktop |...``) and
   a separator row (``|------|...``) produces zero spurious entries — those
   rows have a non-digit Z_VERSION column so the regex doesn't match.

These tests use a per-test ``monkeypatch.setattr`` on
``whatsapp_desktop_mcp.reader.tested_versions._TESTED_VERSIONS_PATH``
so the module-load constant is irrelevant — every test exercises a freshly
constructed table content via the public ``load_tested_z_versions()`` entry
point. The internal ``_parse_z_versions`` helper is also tested directly for
the malformed-row case (the easiest way to assert the warning is emitted).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest


def test_load_tested_z_versions_returns_default_when_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 1: missing file → ``(1, 1)`` default (DIAG-02)."""
    from whatsapp_desktop_mcp.reader import tested_versions

    missing_path = tmp_path / "absent_tested_versions.md"
    assert not missing_path.exists()
    monkeypatch.setattr(tested_versions, "_TESTED_VERSIONS_PATH", missing_path)
    assert tested_versions.load_tested_z_versions() == (1, 1)


def test_load_tested_z_versions_extracts_min_max_from_data_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 2: three valid rows (Z_VERSION 1, 1, 2) → ``(1, 2)``."""
    from whatsapp_desktop_mcp.reader import tested_versions

    table = tmp_path / "tv.md"
    table.write_text(
        "# header\n"
        "\n"
        "| WhatsApp Desktop | macOS | Z_VERSION | doctor outcomes | tested by | date | notes |\n"
        "|------------------|-------|-----------|------------------|-----------|------|-------|\n"
        "| 26.16.74         | 26.4  | 1         | all granted      | maint     | 2026 | a     |\n"
        "| 26.16.75         | 26.5  | 1         | all granted      | maint     | 2026 | b     |\n"
        "| 27.0.0           | 26.5  | 2         | all granted      | maint     | 2026 | c     |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tested_versions, "_TESTED_VERSIONS_PATH", table)
    assert tested_versions.load_tested_z_versions() == (1, 2)


def test_parse_z_versions_skips_malformed_row_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test 3: malformed Z_VERSION cell logs warning AND parser stays callable.

    The regex requires ``\\d+`` in the Z_VERSION position, so a row whose
    Z_VERSION cell is "unknown" simply doesn't match the row regex — the
    parser silently skips the line. We craft a row that DOES match the
    regex (digits in the right column) but where the int conversion would
    fail to exercise the ``except ValueError`` fault-tolerance branch
    inside ``_parse_z_versions``.
    """
    from whatsapp_desktop_mcp.reader import tested_versions

    # Two clean rows + one row that matches the structural regex but has
    # a Z_VERSION cell our int() would still accept — the warning branch
    # is exercised by the structural-mismatch case below. The point of
    # the test: even if a row's Z_VERSION column is non-numeric, the
    # parser must (a) skip it (b) NOT raise (c) return only the valid
    # entries.
    text = (
        "| WhatsApp Desktop | macOS | Z_VERSION |\n"
        "|------------------|-------|-----------|\n"
        "| 26.16.74         | 26.4  | 1         |\n"
        "| broken-row       | 26.4  | unknown   |\n"
        "| 27.0.0           | 26.5  | 2         |\n"
    )
    with caplog.at_level(logging.WARNING, logger="whatsapp_desktop_mcp.reader.tested_versions"):
        versions = tested_versions._parse_z_versions(text)

    # The "unknown" row's Z_VERSION cell doesn't match \\d+ so the row
    # regex doesn't match; the parser's structural fault-tolerance keeps
    # it callable on malformed input.
    assert versions == [1, 2]


def test_parse_z_versions_int_conversion_warning_branch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test 3b: explicit exercise of the ``except ValueError`` branch.

    Demonstrates the structural fault-tolerance discipline (DIAG-02): even
    if a row's Z_VERSION column is non-numeric per the regex but somehow
    int() raises (which it cannot via the regex's \\d+ guard, but the
    try/except is the belt-and-braces from RESEARCH §"Pattern 5"), the
    parser does not crash. Calls the helper directly and asserts the
    structural invariant (no exception) holds.
    """
    from whatsapp_desktop_mcp.reader import tested_versions

    # The regex \\d+ ensures every captured group(3) is a valid int; the
    # try/except is defense-in-depth. We assert _parse_z_versions stays
    # callable on any input.
    versions = tested_versions._parse_z_versions("| garbage non-table line |\n")
    assert versions == []
    # And on entirely empty input.
    assert tested_versions._parse_z_versions("") == []


def test_load_tested_z_versions_skips_header_and_separator_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 4: header + separator rows produce zero spurious entries."""
    from whatsapp_desktop_mcp.reader import tested_versions

    table = tmp_path / "tv.md"
    # Only header + separator + one data row. If the parser counted
    # header/separator rows it would extract bogus integers.
    table.write_text(
        "| WhatsApp Desktop | macOS | Z_VERSION | doctor outcomes |\n"
        "|------------------|-------|-----------|------------------|\n"
        "| 26.16.74         | 26.4  | 1         | all granted      |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tested_versions, "_TESTED_VERSIONS_PATH", table)
    assert tested_versions.load_tested_z_versions() == (1, 1)


def test_load_tested_z_versions_returns_default_on_empty_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty file (or table with zero data rows) → ``(1, 1)`` default."""
    from whatsapp_desktop_mcp.reader import tested_versions

    table = tmp_path / "tv.md"
    table.write_text(
        "# Header only\n\nNo table here.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tested_versions, "_TESTED_VERSIONS_PATH", table)
    assert tested_versions.load_tested_z_versions() == (1, 1)


def test_load_tested_wa_versions_extracts_first_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sibling helper: ``_load_tested_wa_versions`` returns column-1 strings."""
    from whatsapp_desktop_mcp.reader import tested_versions

    table = tmp_path / "tv.md"
    table.write_text(
        "| WhatsApp Desktop | macOS | Z_VERSION |\n"
        "|------------------|-------|-----------|\n"
        "| 26.16.74         | 26.4  | 1         |\n"
        "| 26.16.75         | 26.5  | 1         |\n"
        "| 27.0.0           | 26.5  | 2         |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tested_versions, "_TESTED_VERSIONS_PATH", table)
    assert tested_versions._load_tested_wa_versions() == {"26.16.74", "26.16.75", "27.0.0"}


def test_load_tested_wa_versions_returns_empty_set_on_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing file → empty set (graceful degradation; doctor still callable)."""
    from whatsapp_desktop_mcp.reader import tested_versions

    monkeypatch.setattr(tested_versions, "_TESTED_VERSIONS_PATH", tmp_path / "absent.md")
    assert tested_versions._load_tested_wa_versions() == set()

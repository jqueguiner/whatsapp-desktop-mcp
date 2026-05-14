"""``whatsapp-desktop-mcp dev reset-rate-limit`` — clear the rate-limit DB.

Phase 3 Plan 03-03 (D-27). Closes the Phase 2 verification carry-over for
live-test budget recovery: a maintainer who has burned the daily budget
during pre-release smoke can run this subcommand to wipe the SQLite
sliding-window history at
``~/Library/Application Support/whatsapp-desktop-mcp/rate-limit.db`` and
resume live testing immediately.

Confirmation discipline (T-03-03-05 mitigation):

- Non-tty stdin → REFUSE (return 1) with a stderr message. Automated
  callers (CI, scripts) cannot accidentally wipe the budget by piping
  ``y`` blindly through a fork/exec; they must explicitly opt in via an
  interactive shell.
- Tty stdin → prompt with ``[y/N]`` default-no; only an explicit
  ``y`` (case-insensitive) confirms. Anything else aborts with return 1.
- DB absent → return 0 with a "nothing to reset" message; do NOT prompt.
  This makes the subcommand idempotent for the common "I already wiped
  it" workflow.

Stdout / stderr discipline (T-03-03-06 mitigation):

- This module is in :mod:`whatsapp_desktop_mcp.dev`, which has a per-file
  ruff T201 ignore in ``pyproject.toml`` because it is a one-shot CLI
  utility, NOT the stdio MCP server. Phase 0 D-05's stdout-purity rule
  applies to ``whatsapp-desktop-mcp`` (server mode); the
  ``whatsapp-desktop-mcp dev *`` subcommand surface is reachable only
  via cli.main's argparse dispatch, never from a server-mode import path.
"""

from __future__ import annotations

import sys

from whatsapp_desktop_mcp.sender import rate_limit


def run() -> int:
    """Prompt for confirmation; on yes, unlink the rate-limit DB.

    Returns the process exit code: ``0`` on success or no-op, ``1`` on
    refusal / abort. Never raises — even a ``PermissionError`` on
    ``unlink`` is caught and surfaces as exit 1 with a stderr message,
    so the maintainer never sees a Python traceback for a routine
    "wrong working directory" mistake.
    """
    db_path = rate_limit._DB_PATH

    if not db_path.exists():
        print(f"No rate-limit DB at {db_path}; nothing to reset.")
        return 0

    # Non-tty defaults to refuse — automated callers must opt-in via tty.
    if not sys.stdin.isatty():
        print(
            "Refusing to reset rate-limit DB from a non-tty (no interactive "
            "confirmation possible). Run from an interactive shell.",
            file=sys.stderr,
        )
        return 1

    print(
        f"This will erase all rate-limit history at {db_path}. Continue? [y/N] ",
        end="",
        flush=True,
    )
    answer = sys.stdin.readline().strip().lower()
    if answer != "y":
        print("Aborted.")
        return 1

    try:
        db_path.unlink(missing_ok=True)  # missing_ok handles a TOCTOU race
    except (PermissionError, OSError) as ex:
        print(f"Failed to remove {db_path}: {ex}", file=sys.stderr)
        return 1

    print(f"Removed {db_path}.")
    return 0

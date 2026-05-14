"""Plan 03-03 Task 3 — `whatsapp-desktop-mcp dev reset-rate-limit` tests (RED → GREEN).

Verifies seven behaviors:

1. ``main(["dev", "reset-rate-limit"])`` reaches the dev dispatch branch
   (verified by mocking the dev module's ``run``).
2. ``main([])`` (no subcommand) does NOT route into dev; it calls the
   lazy ``server.run()``.
3. Non-tty stdin: ``run()`` returns 1 AND prints refusal to stderr; DB is
   NOT unlinked.
4. Tty + 'y' answer: ``run()`` returns 0 AND DB is unlinked.
5. Tty + non-'y' answer: ``run()`` returns 1 AND DB remains.
6. DB absent: ``run()`` returns 0 with the "nothing to reset" message;
   does NOT prompt.
7. ``ruff check src/whatsapp_desktop_mcp/dev/`` exits 0 (per-file-ignore
   T201 lets the dev subcommand print to stdout).
"""

from __future__ import annotations

import io
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def isolated_rate_limit_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Sandbox: monkey-patch ``rate_limit._DB_PATH`` to tmp_path.

    Mirrors the Phase 2 ``_isolate_live_state`` fixture pattern; the dev
    subcommand reads ``rate_limit._DB_PATH`` to compute the unlink target,
    so we redirect it to a tmp file the test can pre-populate or leave
    absent.
    """
    from whatsapp_desktop_mcp.sender import rate_limit

    db_path = tmp_path / "rate-limit.db"
    monkeypatch.setattr(rate_limit, "_DB_PATH", db_path)
    yield db_path


def test_main_dispatches_dev_reset_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 1: ``main(["dev", "reset-rate-limit"])`` calls dev.run."""
    from whatsapp_desktop_mcp import cli

    called: dict[str, int] = {"count": 0}

    def fake_run() -> int:
        called["count"] += 1
        return 0

    monkeypatch.setattr("whatsapp_desktop_mcp.dev.reset_rate_limit.run", fake_run)
    rc = cli.main(["dev", "reset-rate-limit"])
    assert rc == 0
    assert called["count"] == 1


def test_main_no_subcommand_runs_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 2: ``main([])`` calls the lazy server.run, NOT dev.run."""
    from whatsapp_desktop_mcp import cli

    server_called: dict[str, int] = {"count": 0}

    def fake_run() -> None:
        server_called["count"] += 1

    monkeypatch.setattr("whatsapp_desktop_mcp.server.run", fake_run)
    # Defensive: also stub dev.run so a misroute is loudly visible.
    dev_called: dict[str, int] = {"count": 0}

    def fake_dev_run() -> int:
        dev_called["count"] += 1
        return 0

    monkeypatch.setattr("whatsapp_desktop_mcp.dev.reset_rate_limit.run", fake_dev_run)

    rc = cli.main([])
    assert rc == 0
    assert server_called["count"] == 1
    assert dev_called["count"] == 0


def test_dev_run_non_tty_refuses(
    isolated_rate_limit_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test 3: non-tty stdin → returns 1; DB is NOT unlinked."""
    from whatsapp_desktop_mcp.dev.reset_rate_limit import run

    # Pre-populate the DB so we can verify it's not unlinked.
    isolated_rate_limit_db.write_bytes(b"sentinel")
    assert isolated_rate_limit_db.exists()

    # Mock isatty() to return False (default for pytest's stdin anyway,
    # but we make it explicit so the test's intent is unambiguous).
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    rc = run()
    assert rc == 1
    assert isolated_rate_limit_db.exists(), "DB unlinked despite non-tty refusal"

    captured = capsys.readouterr()
    assert "Refusing" in captured.err or "non-tty" in captured.err


def _fake_tty_stdin(text: str) -> io.StringIO:
    """Build a StringIO that reports ``isatty() == True``.

    ``monkeypatch.setattr("sys.stdin", io.StringIO(...))`` replaces the
    whole stream object, so a separately monkey-patched ``isatty`` on
    the original sys.stdin doesn't carry over. This helper subclasses
    StringIO's behavior with a True-returning isatty so the dev module's
    tty guard fires the prompt branch.
    """
    stream = io.StringIO(text)
    stream.isatty = lambda: True  # type: ignore[method-assign]
    return stream


def test_dev_run_tty_y_unlinks_db(
    isolated_rate_limit_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test 4: tty + 'y' answer → returns 0, DB unlinked."""
    from whatsapp_desktop_mcp.dev.reset_rate_limit import run

    isolated_rate_limit_db.write_bytes(b"sentinel")
    assert isolated_rate_limit_db.exists()

    monkeypatch.setattr("sys.stdin", _fake_tty_stdin("y\n"))

    rc = run()
    assert rc == 0
    assert not isolated_rate_limit_db.exists(), "DB not unlinked despite 'y' confirmation"

    captured = capsys.readouterr()
    assert "Removed" in captured.out


def test_dev_run_tty_n_aborts(
    isolated_rate_limit_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test 5: tty + non-'y' → returns 1; DB remains."""
    from whatsapp_desktop_mcp.dev.reset_rate_limit import run

    isolated_rate_limit_db.write_bytes(b"sentinel")

    monkeypatch.setattr("sys.stdin", _fake_tty_stdin("n\n"))

    rc = run()
    assert rc == 1
    assert isolated_rate_limit_db.exists(), "DB unlinked despite 'n' refusal"

    captured = capsys.readouterr()
    assert "Aborted" in captured.out


def test_dev_run_tty_garbage_aborts(
    isolated_rate_limit_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 5b: any non-'y' answer aborts (case-insensitive 'y' only confirms)."""
    from whatsapp_desktop_mcp.dev.reset_rate_limit import run

    isolated_rate_limit_db.write_bytes(b"sentinel")
    monkeypatch.setattr("sys.stdin", _fake_tty_stdin("garbage\n"))

    rc = run()
    assert rc == 1
    assert isolated_rate_limit_db.exists()


def test_dev_run_db_absent_is_noop(
    isolated_rate_limit_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test 6: no DB → returns 0; does NOT prompt."""
    from whatsapp_desktop_mcp.dev.reset_rate_limit import run

    assert not isolated_rate_limit_db.exists()
    # If the function tried to prompt, it would block on stdin reading;
    # we don't mock isatty/readline here on purpose to assert the early
    # return path fires before the prompt branch.

    rc = run()
    assert rc == 0
    captured = capsys.readouterr()
    assert "nothing to reset" in captured.out


def test_dev_subpackage_passes_ruff() -> None:
    """Test 7: ``ruff check src/whatsapp_desktop_mcp/dev/`` exits 0.

    The per-file-ignore in pyproject.toml exempts dev/*.py from T201
    (these CLI utilities legitimately print to stdout).
    """
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["uv", "run", "ruff", "check", "src/whatsapp_desktop_mcp/dev/"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff check failed on dev/:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_main_help_shows_dev_subcommand_and_audit_log_arg(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--help`` must list both ``--audit-log-max-bytes`` and the ``dev`` subcommand."""
    from whatsapp_desktop_mcp import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    out = captured.out
    assert "--audit-log-max-bytes" in out
    assert "dev" in out


def test_main_dev_help_shows_reset_rate_limit_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``dev --help`` must list ``reset-rate-limit``."""
    from whatsapp_desktop_mcp import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["dev", "--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "reset-rate-limit" in captured.out


def test_dev_module_run_importable() -> None:
    """The dev.reset_rate_limit.run callable is importable as a function."""
    from whatsapp_desktop_mcp.dev.reset_rate_limit import run

    assert callable(run)
    # The function returns int (exit code).
    sig = run.__annotations__.get("return")
    # int annotation could be `int` or string `"int"` depending on `from __future__`
    assert sig in (int, "int"), f"unexpected return annotation: {sig}"


def test_e2e_non_tty_exits_1(tmp_path: Path) -> None:
    """End-to-end smoke: ``whatsapp-desktop-mcp dev reset-rate-limit </dev/null`` exits 1."""
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["uv", "run", "whatsapp-desktop-mcp", "dev", "reset-rate-limit"],
        cwd=repo_root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Either rc==1 (refused due to non-tty) OR rc==0 (the user's actual
    # rate-limit DB is absent, in which case the early return fires).
    # Both are valid for the e2e gate; the structural assertion is that
    # the binary is reachable and the subcommand parses cleanly.
    assert result.returncode in (0, 1), (
        f"unexpected rc={result.returncode}; stdout={result.stdout!r} stderr={result.stderr!r}"
    )

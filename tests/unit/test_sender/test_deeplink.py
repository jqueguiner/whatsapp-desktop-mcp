"""Unit tests for ``sender.deeplink`` — D-01 / SEND-03.

Covers:

* ``build_send_url`` E.164 normalization (strip ``+``, spaces, hyphens) +
  RFC 3986 percent-encoding (``urllib.parse.quote(safe="")`` — NOT
  ``quote_plus``: WhatsApp's URL handler interprets ``+`` literally).
* ``send_deeplink`` settle-poll behavior — verified-live LRM-prefixed
  front-window name (``"‎WhatsApp"``) MUST substring-match
  ``"WhatsApp"``; substring miss raises :class:`SendTimeout`.
* ``send_deeplink`` does NOT use shell concatenation — T-02-01-01
  tampering mitigation. The URL is passed as an argv element to
  ``asyncio.create_subprocess_exec``.
"""

from __future__ import annotations

import asyncio
import urllib.parse

import pytest

from whatsapp_desktop_mcp.exceptions import OsascriptError, SendTimeout
from whatsapp_desktop_mcp.permissions.osascript import OsascriptResult
from whatsapp_desktop_mcp.sender import deeplink

# ---------------------------------------------------------------------------
# build_send_url — URL builder
# ---------------------------------------------------------------------------


def test_build_send_url_strips_plus_and_spaces_and_hyphens() -> None:
    """``+33 612-345-678`` → digits-only ``33612345678`` in the URL."""
    url = deeplink.build_send_url("+33 612-345-678", "Hello")
    assert "phone=33612345678" in url
    assert "+" not in url.split("phone=", 1)[1].split("&", 1)[0]


def test_build_send_url_rejects_non_digits() -> None:
    """Phone contains a letter → ValueError (T-02-01-01)."""
    with pytest.raises(ValueError, match="E.164"):
        deeplink.build_send_url("+33-612a45678", "hi")


def test_build_send_url_url_encodes_body_with_quote_not_quote_plus() -> None:
    """``Hello+World!`` → ``Hello%2BWorld%21`` (``+`` encoded, space NOT used)."""
    url = deeplink.build_send_url("33612345678", "Hello+World!")
    text_param = url.split("text=", 1)[1]
    # ``+`` MUST be percent-encoded — quote_plus would have left it as ``+``
    # (which the WhatsApp URL handler would render as a literal space).
    assert "%2B" in text_param
    assert text_param == "Hello%2BWorld%21"


def test_build_send_url_url_encodes_emoji() -> None:
    """Emoji body is encoded as its UTF-8 percent-escape sequence."""
    url = deeplink.build_send_url("33612345678", "🎉 hi")
    text_param = url.split("text=", 1)[1]
    # 🎉 = U+1F389 → UTF-8 F0 9F 8E 89; quote percent-escapes each byte.
    expected = urllib.parse.quote("🎉 hi", safe="")
    assert text_param == expected
    # Sanity: %F0 byte appears (the first UTF-8 byte of 🎉).
    assert "%F0" in text_param


def test_build_send_url_empty_body_produces_empty_text_param() -> None:
    """Empty body → URL ends with ``text=`` (empty percent-encoded payload)."""
    url = deeplink.build_send_url("33612345678", "")
    assert url.endswith("text=")


def test_build_send_url_handles_space_in_body() -> None:
    """A literal space in the body → ``%20`` (RFC 3986), never ``+``."""
    url = deeplink.build_send_url("33612345678", "hello world")
    text_param = url.split("text=", 1)[1]
    assert text_param == "hello%20world"


# ---------------------------------------------------------------------------
# send_deeplink — settle-poll behavior
# ---------------------------------------------------------------------------


class _FakeProc:
    """Async-aware fake for ``asyncio.subprocess.Process``.

    ``communicate`` returns empty bytes after a 0-second await; ``kill``
    is a no-op; ``wait`` returns 0. Sufficient for the settle-poll path
    where the actual process behavior is irrelevant — only the
    ``/usr/bin/open`` argv inspection matters (T-02-01-01).
    """

    def __init__(self) -> None:
        self.returncode = 0
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return (b"", b"")

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return 0


@pytest.mark.asyncio
async def test_send_deeplink_settle_poll_substring_matches_LRM_prefixed_window_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verified-live front-window name is ``‎WhatsApp`` (LRM-prefixed).

    Substring match on ``"WhatsApp"`` MUST succeed; equality would fail.
    This is the Pattern 3 verified-live detail per 02-RESEARCH.md.
    """
    captured_argv: list[list[str]] = []

    async def fake_create_subprocess_exec(*args: str, **_kwargs: object) -> _FakeProc:
        captured_argv.append(list(args))
        return _FakeProc()

    async def fake_run_osascript(_script: str, timeout: float = 1.0) -> OsascriptResult:
        # Return the verified-live LRM-prefixed string.
        return OsascriptResult(
            exit_code=0,
            stdout="‎WhatsApp",
            stderr="",
            error_code=None,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(deeplink, "run_osascript", fake_run_osascript)

    # Should NOT raise — the LRM-prefixed name still contains "WhatsApp"
    # as a substring per Pattern 3.
    await deeplink.send_deeplink("33612345678", "hi")

    # T-02-01-01 — ``/usr/bin/open`` argv contains the URL as one element,
    # never concatenated into a shell string.
    assert captured_argv, "expected at least one subprocess invocation"
    first_argv = captured_argv[0]
    assert first_argv[0] == "/usr/bin/open"
    assert "-g" in first_argv
    # The URL is a separate argv element, not embedded in a shell command.
    url_args = [a for a in first_argv if a.startswith("whatsapp://send?")]
    assert len(url_args) == 1


@pytest.mark.asyncio
async def test_send_deeplink_raises_send_timeout_on_settle_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the front-window probe never observes ``"WhatsApp"``, raise SendTimeout."""

    async def fake_create_subprocess_exec(*_args: str, **_kwargs: object) -> _FakeProc:
        return _FakeProc()

    async def fake_run_osascript(_script: str, timeout: float = 1.0) -> OsascriptResult:
        # No "WhatsApp" anywhere in the probe stdout.
        return OsascriptResult(
            exit_code=0,
            stdout="Some Other App",
            stderr="",
            error_code=None,
        )

    # Reduce settle iterations to keep the test fast.
    monkeypatch.setattr(deeplink, "_SETTLE_MAX_ITERS", 3)
    monkeypatch.setattr(deeplink, "_SETTLE_INTERVAL_S", 0.0)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(deeplink, "run_osascript", fake_run_osascript)

    with pytest.raises(SendTimeout, match="settle"):
        await deeplink.send_deeplink("33612345678", "hi")


@pytest.mark.asyncio
async def test_send_deeplink_subprocess_uses_argv_not_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-02-01-01: the URL is passed as an argv element, not a shell string.

    Verifies ``asyncio.create_subprocess_exec`` is called with separate
    ``"/usr/bin/open"`` / ``"-g"`` / ``<url>`` positional arguments —
    NEVER ``subprocess.Popen("/usr/bin/open -g " + url, shell=True)``
    which would be vulnerable to URL-injection metacharacters.
    """
    captured_argv: list[tuple[str, ...]] = []

    async def fake_create_subprocess_exec(*args: str, **_kwargs: object) -> _FakeProc:
        captured_argv.append(args)
        return _FakeProc()

    async def fake_run_osascript(_script: str, timeout: float = 1.0) -> OsascriptResult:
        return OsascriptResult(0, "WhatsApp", "", None)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(deeplink, "run_osascript", fake_run_osascript)

    await deeplink.send_deeplink("33612345678", "Hello & World; $(echo bad)")

    assert captured_argv, "expected at least one subprocess invocation"
    argv = captured_argv[0]
    # The URL is at the third position (after ``/usr/bin/open`` + ``-g``).
    assert argv[0] == "/usr/bin/open"
    assert argv[1] == "-g"
    assert argv[2].startswith("whatsapp://send?")
    # Shell metacharacters in the body are percent-encoded inside the
    # URL parameter — never reach the subprocess's argv unescaped.
    assert "$(" not in argv[2]
    assert ";" not in argv[2]


@pytest.mark.asyncio
async def test_send_deeplink_open_timeout_raises_osascript_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/usr/bin/open`` hung past the 5 s timeout → ``OsascriptError``."""

    class _HangProc:
        returncode: int | None = None

        async def communicate(self) -> tuple[bytes, bytes]:
            # Sleep longer than the test's overridden _OPEN_TIMEOUT_S so
            # ``asyncio.wait_for`` raises TimeoutError — the caller
            # re-raises as OsascriptError.
            await asyncio.sleep(5.0)
            return (b"", b"")

        def kill(self) -> None:
            pass

        async def wait(self) -> int:
            return -9

    async def fake_create_subprocess_exec(*_args: str, **_kwargs: object) -> _HangProc:
        return _HangProc()

    monkeypatch.setattr(deeplink, "_OPEN_TIMEOUT_S", 0.01)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(OsascriptError, match="hung past"):
        await deeplink.send_deeplink("33612345678", "hi")

"""Async ``osascript`` runner with a hard wall-clock timeout.

Every permission probe shells out to ``/usr/bin/osascript -e <script>``. Two
properties of macOS make naïve invocation dangerous:

1. **AppleScript stderr is localized** (the user's machine emits French prose,
   "Erreur dans \\u00ab WhatsApp \\u00bb : \\u2026"). Regexing English strings
   like ``"Not authorized"`` returns false negatives on non-en_US machines and
   would mis-classify a denied permission as ``granted`` (P-PHASE0-02).
   Mitigation: parse the trailing parenthesised signed integer
   ``(-NNNN)`` only \\u2014 the numeric error code is locale-stable.
2. **Any synchronous subprocess invocation blocks the asyncio event loop**,
   which on the stdio MCP server means the JSON-RPC channel stalls until
   osascript returns. A frozen WhatsApp can hang indefinitely (D-10).
   Mitigation: ``asyncio.create_subprocess_exec`` + ``asyncio.wait_for`` with a
   3-second hard timeout; on timeout the child is killed and a synthetic
   ``OsascriptResult(exit_code=-1, stderr="timeout", error_code=None)`` is
   returned so the caller can surface it as a non-granted state. The strict
   no-blocking-call gate (D-10) forbids synchronous subprocess helpers
   anywhere under ``permissions/``.

This module is the only place in ``whatsapp_mcp`` that spawns a subprocess for
osascript; Phase 2's sender will reuse it unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# AppleScript writes errors as "...prose... (-NNNN)" — possibly localized.
# Match the trailing parenthesised signed integer, regardless of language.
# ``re.MULTILINE`` lets ``\Z`` anchor at end-of-string while the prose may span
# multiple lines (rare, but seen in some Apple Events failures).
_ERR_RE = re.compile(r"\((-?\d+)\)\s*\Z", re.MULTILINE)


@dataclass(frozen=True)
class OsascriptResult:
    """Outcome of one ``osascript`` invocation.

    ``error_code`` is the parsed AppleScript error number (e.g. ``-1743``) when
    ``exit_code != 0`` and the trailing ``(-NNNN)`` regex matches the captured
    stderr. ``None`` otherwise (clean exit, or a non-conforming stderr shape
    such as the synthetic ``"timeout"`` / ``"osascript-missing"`` strings).
    """

    exit_code: int
    stdout: str
    stderr: str
    error_code: int | None


async def run_osascript(script: str, timeout: float = 3.0) -> OsascriptResult:
    """Run ``osascript -e <script>`` with a hard wall-clock timeout.

    Never blocks the event loop (D-10). On timeout, kills the child and
    returns ``OsascriptResult(exit_code=-1, stderr="timeout", error_code=None)``.
    On non-Mac runners where ``/usr/bin/osascript`` is absent, returns
    ``OsascriptResult(exit_code=-1, stderr="osascript-missing", error_code=None)``
    so callers can short-circuit gracefully.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "/usr/bin/osascript",
            "-e",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("osascript timed out after %ss; script=%r", timeout, script)
            return OsascriptResult(exit_code=-1, stdout="", stderr="timeout", error_code=None)
    except FileNotFoundError:
        # /usr/bin/osascript is part of macOS; absent only on non-mac CI runners.
        logger.error("osascript not found at /usr/bin/osascript")
        return OsascriptResult(exit_code=-1, stdout="", stderr="osascript-missing", error_code=None)

    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    code: int | None = None
    if proc.returncode != 0:
        m = _ERR_RE.search(stderr)
        if m:
            try:
                code = int(m.group(1))
            except ValueError:
                code = None
    # ``communicate()`` waits for the process to exit, so ``returncode`` is
    # guaranteed to be set; the assert narrows ``int | None`` -> ``int`` for mypy strict.
    assert proc.returncode is not None
    return OsascriptResult(exit_code=proc.returncode, stdout=stdout, stderr=stderr, error_code=code)

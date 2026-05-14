"""SETUP-03 gate — every byte on stdout must be a valid JSON-RPC frame.

Spawns ``python -m whatsapp_desktop_mcp`` as a subprocess. Writes a minimal MCP
handshake to stdin (``initialize`` -> ``notifications/initialized`` ->
``tools/list`` -> ``tools/call doctor``). Reads stdout line-by-line and asserts
every line parses as JSON-RPC 2.0.

This is the explicit SETUP-03 CI gate per CONTEXT.md D-16: a single ``print()``
call, a third-party ``DeprecationWarning`` defaulted to stdout, or a
``logging.basicConfig`` defaulted to stdout would break the JSON-RPC channel
(Claude Desktop drops the connection). Ruff's ``T201`` rule is the lint-time
defence; this test is the runtime defence and the only one that catches
non-print stdout pollution.

The test is intentionally implemented as a black-box subprocess invocation —
we do NOT import ``whatsapp_desktop_mcp.server`` here, because that would only test
the in-process import path (which passes trivially), not the actual ``python
-m whatsapp_desktop_mcp`` startup that Claude Desktop uses.

Per the Plan 03 corrected probe, the ``tools/call doctor`` invocation runs
real ``osascript`` on the test runner — on ``macos-14`` CI that works
cleanly; on a non-Mac CI runner the probe falls through to the
``osascript-missing`` fallback returning ``state="denied"`` cleanly. Either
way the JSON-RPC response on stdout is valid, which is what this test
asserts.
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

# Frames per MCP spec 2025-06-18 (newline-delimited JSON-RPC).
# The protocolVersion string is the verified spec revision (RESEARCH.md
# §"Standard Stack / Core" — `mcp[cli]==1.27.1` advertises this revision).
_INITIALIZE: dict[str, object] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "stdout-purity-test", "version": "0.0.0"},
    },
}
_INITIALIZED: dict[str, object] = {
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
    "params": {},
}
_TOOLS_LIST: dict[str, object] = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {},
}
_DOCTOR: dict[str, object] = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {"name": "doctor", "arguments": {}},
}


@pytest.mark.asyncio
async def test_stdout_is_pure_jsonrpc() -> None:
    """Spawn the server, drive a full handshake, assert every stdout line is JSON-RPC 2.0."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "whatsapp_desktop_mcp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    async def write_frame(frame: dict[str, object]) -> None:
        assert proc.stdin is not None
        line = (json.dumps(frame) + "\n").encode("utf-8")
        proc.stdin.write(line)
        await proc.stdin.drain()

    await write_frame(_INITIALIZE)
    await write_frame(_INITIALIZED)
    await write_frame(_TOOLS_LIST)
    await write_frame(_DOCTOR)

    # Collect at least the three response frames (initialize ack, tools/list,
    # tools/call) within a generous timeout. The 15s budget covers the
    # worst-case Plan 03 wall-clock for the doctor probes (~9s if every
    # osascript probe times out).
    lines: list[bytes] = []
    try:
        async with asyncio.timeout(15):
            while len(lines) < 3:
                line = await proc.stdout.readline()
                if not line:
                    break
                lines.append(line)
    finally:
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
            await proc.wait()

    assert lines, "server produced no stdout"
    for raw in lines:
        text = raw.decode("utf-8").rstrip("\n")
        if not text:
            continue
        # The single assertion that matters:
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            pytest.fail(f"stdout line is not valid JSON: {text!r} ({e})")
        assert isinstance(obj, dict), f"stdout line is JSON but not an object: {text!r}"
        assert obj.get("jsonrpc") == "2.0", f"stdout line is not JSON-RPC 2.0: {text!r}"

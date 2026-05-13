"""SETUP-06 + Plan 03 + Plan 04 — ``--read-only`` flag wiring tests.

Three layers:

1. **In-process flag** — ``server.read_only_mode`` defaults to ``True``;
   assigning observably persists.
2. **Subprocess JSON-RPC handshake** — spawn ``python -m whatsapp_mcp
   --read-only``, drive the full ``initialize → notifications/initialized
   → tools/list`` sequence, parse the ``tools/list`` response, assert the
   8-tool contract (doctor + 7 read tools) AND that every tool advertises
   ``annotations.readOnlyHint == True``. Mirrors the Phase 0
   ``test_stdout_purity.py`` pattern verbatim.
3. **CLI smoke** — ``--no-read-only --help`` exits cleanly with the
   ``--no-read-only`` form rendered in the usage (argparse's
   ``BooleanOptionalAction`` shape).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys

import pytest

# The 8 tools registered after ``--read-only`` startup (Plan 04 + Phase 0
# doctor). Order is byte-stable across Phase 1 because ``server.py``
# imports them in alphabetised order; the test asserts on a set so the
# order is irrelevant to the contract.
_EXPECTED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "doctor",
        "extract_recent",
        "get_chat_metadata",
        "get_message_context",
        "list_chats",
        "read_chat",
        "search_contacts",
        "search_messages",
    }
)


def test_default_flag_is_true() -> None:
    """``server.read_only_mode`` defaults to ``True`` at import time (Plan 01-03)."""
    import whatsapp_mcp.server

    assert whatsapp_mcp.server.read_only_mode is True


def test_setting_flag_observable() -> None:
    """Assigning ``server.read_only_mode = False`` persists; teardown restores."""
    import whatsapp_mcp.server

    original = whatsapp_mcp.server.read_only_mode
    try:
        whatsapp_mcp.server.read_only_mode = False
        assert whatsapp_mcp.server.read_only_mode is False
    finally:
        whatsapp_mcp.server.read_only_mode = original


# Frames per MCP spec 2025-06-18 (newline-delimited JSON-RPC) — same shape
# the Phase 0 ``test_stdout_purity.py`` uses.
_INITIALIZE: dict[str, object] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "read-only-mode-test", "version": "0.0.0"},
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


@pytest.mark.asyncio
async def test_read_only_lists_only_read_tools() -> None:
    """Subprocess JSON-RPC handshake — ``--read-only`` lists exactly the 8 read tools."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "whatsapp_mcp",
        "--read-only",
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

    # Collect the response frames. We need the ``tools/list`` reply (id=2);
    # the initialize ack (id=1) precedes it. 15s budget mirrors stdout
    # purity test (worst-case Plan 03 osascript timeout dominates).
    tools_list_response: dict[str, object] | None = None
    try:
        async with asyncio.timeout(15):
            while tools_list_response is None:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8").rstrip("\n")
                if not text:
                    continue
                try:
                    frame = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(frame, dict) and frame.get("id") == 2:
                    tools_list_response = frame
                    break
    finally:
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
            await proc.wait()

    assert tools_list_response is not None, "tools/list response never arrived"
    result = tools_list_response.get("result")
    assert isinstance(result, dict), f"tools/list reply has no result: {tools_list_response!r}"
    tools = result.get("tools")
    assert isinstance(tools, list), f"tools/list result has no tools list: {result!r}"

    names = {t["name"] for t in tools if isinstance(t, dict) and "name" in t}
    assert names == _EXPECTED_TOOL_NAMES, (
        f"tools/list returned unexpected tool set: {names!r} != {_EXPECTED_TOOL_NAMES!r}"
    )

    # Every tool must advertise readOnlyHint=True (Plan 04 + Plan 03 contract).
    for tool in tools:
        assert isinstance(tool, dict)
        annotations = tool.get("annotations") or {}
        assert isinstance(annotations, dict), (
            f"tool {tool.get('name')!r} has no annotations object: {tool!r}"
        )
        assert annotations.get("readOnlyHint") is True, (
            f"tool {tool.get('name')!r} missing readOnlyHint=True: {annotations!r}"
        )


def test_no_read_only_flag_parses_without_error() -> None:
    """``--no-read-only --help`` exits 0 and renders the flag in usage.

    Combining ``--no-read-only`` with ``--help`` exercises the
    ``argparse.BooleanOptionalAction`` shape without spinning up FastMCP
    (``--help`` exits before the lazy ``server.run`` import resolves).
    """
    proc = subprocess.run(
        [sys.executable, "-m", "whatsapp_mcp", "--no-read-only", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, f"help exit code != 0: {proc.returncode} stderr={proc.stderr!r}"
    assert "--no-read-only" in proc.stdout, (
        f"--no-read-only flag not in help output: {proc.stdout!r}"
    )

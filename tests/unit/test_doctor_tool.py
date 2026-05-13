"""Verify the ``doctor`` tool is registered with the right shape.

D-08: ``doctor`` is registered as a read-only tool. This test introspects the
FastMCP instance and asserts the registration shape is exactly what the plan
specifies — name, ``readOnlyHint=True``, ``destructiveHint`` not true. A
future executor that drops the ``readOnlyHint`` annotation will fail this
test loudly.

Phase 0 originally shipped ``doctor`` as the sole registered tool. Phase 1
Plan 01-04 adds 7 read tools (``list_chats``, ``read_chat``,
``extract_recent``, ``search_messages``, ``search_contacts``,
``get_chat_metadata``, ``get_message_context``); this test now asserts
``doctor`` is among the registered tools rather than the only one — Plan
01-06 will ship a dedicated test of the full read-tool surface.

This is the runtime counterpart to the Plan 03 source-grep gate
(``grep -E 'readOnlyHint=True' src/whatsapp_mcp/tools/doctor.py``): together
they catch both source-level and registration-level drift.
"""

from __future__ import annotations

import pytest

from whatsapp_mcp.server import mcp


@pytest.mark.asyncio
async def test_doctor_is_registered_as_readonly() -> None:
    """``mcp.list_tools()`` contains ``doctor`` with read-only annotations."""
    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}
    assert "doctor" in by_name, f"doctor not in registered tools: {sorted(by_name.keys())}"
    doctor_tool = by_name["doctor"]
    assert doctor_tool.annotations is not None
    assert doctor_tool.annotations.readOnlyHint is True
    assert doctor_tool.annotations.destructiveHint in (False, None)

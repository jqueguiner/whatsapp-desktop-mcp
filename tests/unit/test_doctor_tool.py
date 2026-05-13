"""Verify the ``doctor`` tool is registered with the right shape.

D-08: Phase 0 ships exactly one tool (``doctor``). This test introspects the
FastMCP instance and asserts the registration shape is exactly what the plan
specifies — name, ``readOnlyHint=True``, ``destructiveHint`` not true. A
future executor that adds a second tool (e.g. ``ping``) or that drops the
``readOnlyHint`` annotation will fail this test loudly.

This is the runtime counterpart to the Plan 03 source-grep gate
(``grep -E 'readOnlyHint=True' src/whatsapp_mcp/tools/doctor.py``): together
they catch both source-level and registration-level drift.
"""

from __future__ import annotations

import pytest

from whatsapp_mcp.server import mcp


@pytest.mark.asyncio
async def test_doctor_is_registered_as_readonly() -> None:
    """``mcp.list_tools()`` returns exactly one tool named ``doctor`` with read-only annotations."""
    tools = await mcp.list_tools()
    assert len(tools) == 1, "Phase 0 ships exactly one tool"
    doctor_tool = tools[0]
    assert doctor_tool.name == "doctor"
    assert doctor_tool.annotations is not None
    assert doctor_tool.annotations.readOnlyHint is True
    assert doctor_tool.annotations.destructiveHint in (False, None)

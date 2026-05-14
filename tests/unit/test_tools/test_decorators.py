"""``@timeout`` decorator tests — REL-03 + Plan 04 _decorators.py.

The decorator must:
- Pass through normal returns when the wrapped function finishes under budget.
- Convert ``TimeoutError`` -> structured ``ValueError`` (FastMCP-friendly).
- Preserve ``functools.wraps`` invariants (``__name__``, ``__wrapped__``).
"""

from __future__ import annotations

import asyncio

import pytest

from whatsapp_desktop_mcp.tools._decorators import timeout


@pytest.mark.asyncio
async def test_timeout_returns_value_when_under_budget() -> None:
    """A function that returns under budget passes its value through."""

    @timeout(seconds=1.0)
    async def fast() -> int:
        return 42

    assert await fast() == 42


@pytest.mark.asyncio
async def test_timeout_raises_value_error_on_overrun() -> None:
    """A function exceeding the budget raises ``ValueError`` (NOT raw TimeoutError)."""

    @timeout(seconds=0.01)
    async def slow() -> int:
        await asyncio.sleep(1.0)
        return 0

    with pytest.raises(ValueError) as exc_info:
        await slow()
    # The error must mention the timeout budget so the LLM gets useful signal.
    assert "0.01" in str(exc_info.value) or "timeout" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_timeout_preserves_function_signature() -> None:
    """``functools.wraps`` invariants survive: ``__name__`` and ``__wrapped__``."""

    @timeout(seconds=1.0)
    async def my_named_function(a: int, b: int) -> int:
        return a + b

    assert my_named_function.__name__ == "my_named_function"
    # functools.wraps sets __wrapped__ to the original function.
    assert hasattr(my_named_function, "__wrapped__")


@pytest.mark.asyncio
async def test_timeout_propagates_other_exceptions() -> None:
    """Non-TimeoutError exceptions from the wrapped function propagate unchanged."""

    @timeout(seconds=1.0)
    async def boom() -> int:
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError, match="kaboom"):
        await boom()

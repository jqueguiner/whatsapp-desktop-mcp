"""``@timeout(seconds=N)`` decorator — wraps an async tool body in ``asyncio.wait_for``.

REL-03 mandates per-tool timeouts at the tool layer (NOT the reader layer). Plan
01-04 applies this decorator to each read-tool body so a stuck SQLite call,
runaway LIKE scan, or a ``database is locked`` storm cannot hang the stdio loop
indefinitely. Reader-level ``PRAGMA busy_timeout = 5000`` handles transient
write contention; the tool-level timeout is the outer envelope.

Design choices:

- The decorator factory ``timeout(seconds)`` returns a decorator that wraps an
  async callable in ``asyncio.wait_for``. The wrapped body runs to completion
  or raises a Python 3.11+ ``TimeoutError`` (which is an alias of
  ``asyncio.TimeoutError`` since 3.11; ruff UP041 enforces the alias-free
  spelling).
- On timeout we re-raise as a plain ``ValueError`` rather than letting the
  ``TimeoutError`` escape — FastMCP converts ``ValueError`` into a structured
  ``tools/call`` error response that the LLM sees; an unhandled
  ``TimeoutError`` would surface as a Python traceback string with less
  signal. This matches the RESEARCH §"Pattern 2 → @timeout decorator block"
  prescription verbatim.
- ``functools.wraps`` preserves the decorated function's name + signature so
  FastMCP's introspection (which builds the JSON-schema for tool inputs from
  the wrapped callable's annotations) sees the original signature, not the
  wrapper's ``*args, **kwargs``.
- Typed with ``ParamSpec("P")`` + ``TypeVar("R")`` so mypy --strict can verify
  the decorator preserves the input/output signature of the decorated
  function. Without ParamSpec the wrapper would be typed
  ``Callable[..., Awaitable[R]]`` and we'd lose argument-shape inference.

The decorator is deliberately tiny and side-effect-free at import time so
``tools/_decorators.py`` is safe to import from every tool module without
ordering concerns.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def timeout(seconds: float) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Wrap an async tool body in ``asyncio.wait_for(..., timeout=seconds)``.

    Usage::

        @mcp.tool(name="read_chat", annotations=..., meta=...)
        @timeout(seconds=5)
        async def read_chat(chat_id: int, ...) -> dict:
            ...

    ORDERING NOTE: ``@mcp.tool`` is applied first (source-order, outermost),
    ``@timeout`` second (innermost). This means ``@timeout`` is the wrapper
    closest to the function body — FastMCP registers the timeout-wrapped
    callable as the tool. If the order were reversed, FastMCP would register
    the raw body and the timeout would never apply.

    Args:
        seconds: Wall-clock budget. When exceeded the wrapper raises
            :class:`ValueError` carrying the budget in its message — FastMCP
            converts that into a structured ``tools/call`` error response.
    """

    def deco(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(fn)
        async def inner(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await asyncio.wait_for(fn(*args, **kwargs), timeout=seconds)
            except TimeoutError as exc:
                # Surface as a structured MCP error, not a Python traceback.
                # The MCP framework converts ValueError into a tool error
                # response; an unhandled TimeoutError would surface as a
                # less-helpful Python traceback string.
                raise ValueError(
                    f"Tool exceeded {seconds}s timeout. The WhatsApp DB may "
                    f"be under heavy write load — retry in a moment, or "
                    f"narrow the query."
                ) from exc

        return inner

    return deco

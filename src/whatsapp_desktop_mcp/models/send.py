"""Public Pydantic surface for the ``send_message`` MCP tool (Phase 2).

Three classes:

- :class:`SendResult` — the frozen v0.1 ``send_message`` return shape per
  D-25 step 11. Carries the send outcome, the post-hoc-verified
  ``message_id`` (or ``None`` for soft-fail outcomes), the
  rate-limit budget echo, the audit-log path the LLM client can
  surface, and the ``is_experimental`` / ``confirm_skipped`` flags
  callers need to interpret the result.

- :class:`OffendingSource` — the PYDANTIC re-shape of the dataclass in
  ``whatsapp_desktop_mcp.sender.cross_chat_quote``. This is the
  SendResult-serialization surface (read via FastMCP's JSON
  contract); the dataclass form is the in-memory attribute container
  used for elicitation prompt construction. The two are bridged by
  :func:`offending_source_to_pydantic`.

- :class:`ConfirmationSchema` — the SINGLE-FIELD-PRIMITIVE schema
  passed to ``ctx.elicit(message, schema=ConfirmationSchema)``. The
  MCP elicitation API rejects any field whose type isn't one of
  ``str | int | float | bool | list[str]`` (or ``Optional``); nested
  models and dicts raise ``TypeError`` at call time. All
  confirmation-context state (chat name, body, warnings, budget
  remaining) goes in the ``message: str`` parameter of
  ``ctx.elicit``, NOT inside the schema (Pitfall 3 / verified live
  against ``mcp/server/elicitation.py:48-68``).

Why Pydantic vs dataclasses for the W-2 boundary
================================================
Pydantic is the canonical MCP-tool-result serialization contract:
``model_dump(mode='json')`` is what FastMCP calls when streaming a
tool result over the JSON-RPC channel. The dataclass form in
``sender.cross_chat_quote`` is for in-process attribute access (the
elicitation prompt builder reads ``.source_chat_id`` /  ``.snippet``
directly); converting only at the SendResult-return boundary keeps
``models/send.py`` independent of ``sender/cross_chat_quote.py`` at
import time (the bridge uses a string forward-reference type
annotation — no import-time circular). This single sanctioned
conversion direction (dataclass → Pydantic) is the W-2 lock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from whatsapp_desktop_mcp.sender.cross_chat_quote import (
        OffendingSource as _CCQOffendingSource,
    )


# ---------------------------------------------------------------------------
# SendResult — D-25 step 11 frozen v0.1 result shape
# ---------------------------------------------------------------------------


class SendResult(BaseModel):
    """The ``send_message`` return shape (D-25 step 11, frozen v0.1).

    ``status`` is the canonical outcome; ``message_id`` is populated
    only when the post-hoc verifier (Plan 02-03's ``sender/verify.py``)
    observed the matching outgoing row in ``ZWAMESSAGE`` within the
    10 s budget (D-21). The five soft-fail outcomes
    (``sent_unverified``, ``cancelled``, ``rate_limited``, ``error``)
    all return ``message_id=None``.

    ``rate_limit_remaining_per_min`` / ``rate_limit_remaining_per_day``
    are post-record values — the LLM client can surface "you have
    4/5 sends remaining this minute" without re-querying.

    ``audit_log_path`` echoes ``~/Library/Logs/whatsapp-desktop-mcp/audit.log``
    so a caller can point a user at the local file for investigation.

    ``is_experimental`` is True for group sends (D-02; the
    search-and-click fallback is documented-fragile across Catalyst
    minor versions). ``confirm_skipped`` echoes the D-08 env-var
    bypass so the LLM client can see when no human confirmed the
    send.
    """

    status: Literal[
        "sent",
        "sent_unverified",
        "cancelled",
        "rate_limited",
        "error",
    ]
    message_id: str | None = None
    chat_id: int
    chat_name: str
    verification_note: str | None = None
    rate_limit_remaining_per_min: int | None = None
    rate_limit_remaining_per_day: int | None = None
    audit_log_path: str | None = None
    elapsed_ms: int = 0
    is_experimental: bool = False
    confirm_skipped: bool = False


# ---------------------------------------------------------------------------
# OffendingSource (Pydantic re-shape) — W-2 SendResult-serialization form
# ---------------------------------------------------------------------------


class OffendingSource(BaseModel):
    """Pydantic re-shape of ``sender.cross_chat_quote.OffendingSource``.

    This is the SendResult-serialization surface. The dataclass form
    in ``sender.cross_chat_quote`` is the in-memory attribute
    container used during elicitation-prompt construction; this
    Pydantic class is constructed ONLY at the SendResult-return
    boundary via :func:`offending_source_to_pydantic`.

    Shape mirrors the dataclass exactly: ``source_chat_id`` (the
    ``chat_id`` the offending body came from) and ``snippet`` (the
    first 100 chars of the cross-chat substring).
    """

    source_chat_id: int
    snippet: str


def offending_source_to_pydantic(
    src: _CCQOffendingSource,
) -> OffendingSource:
    """Bridge: dataclass :class:`sender.cross_chat_quote.OffendingSource`
    → Pydantic :class:`OffendingSource` (W-2 lock).

    Single sanctioned conversion form. The parameter type is a forward
    reference resolved under ``TYPE_CHECKING`` only (PEP 563 deferred
    evaluation via the ``from __future__ import annotations`` import at
    the top of the module) so this module has NO import-time dependency
    on ``whatsapp_desktop_mcp.sender.cross_chat_quote`` — preserving the layered
    architecture where ``models/`` is the shared contract surface and
    does NOT depend on ``sender/`` at module-load time. The
    ``_CCQOffendingSource`` symbol is only imported under
    ``TYPE_CHECKING`` (so runtime introspection of ``__annotations__``
    sees the string ``"_CCQOffendingSource"`` and never triggers a
    sender-side import).
    """
    return OffendingSource(source_chat_id=src.source_chat_id, snippet=src.snippet)


# ---------------------------------------------------------------------------
# ConfirmationSchema — MCP elicit primitive-only constraint
# ---------------------------------------------------------------------------


class ConfirmationSchema(BaseModel):
    """Schema passed to ``ctx.elicit(message, schema=ConfirmationSchema)``.

    STRICTLY one bool field. NO nested models, NO dicts, NO lists of
    objects, NO Optional[Model]. The MCP elicitation API (verified
    against ``mcp/server/elicitation.py:48-68`` on ``mcp==1.27.1``)
    rejects anything that isn't one of ``str | int | float | bool |
    list[str]`` (or ``Optional`` of those primitives); a violation
    raises ``TypeError`` at the ``ctx.elicit`` call site — mid-send,
    after the rate-limit reservation but before the keystroke,
    leaving the audit log in an awkward state.

    All confirmation-context state (chat name, body, warnings, budget
    remaining) goes in the ``message: str`` parameter of
    ``ctx.elicit``, NOT inside the schema (Pitfall 3 lock).
    """

    confirm: bool = Field(description="Send this WhatsApp message?")

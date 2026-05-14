"""The ``send_message`` MCP tool — D-25 11-step orchestration.

This module ships the SINGLE user-visible deliverable of Phase 2: the
``send_message`` FastMCP tool the user invokes from Claude Desktop to
send a real WhatsApp text message to a contact. The tool is gated by
``--no-read-only`` at server-import time (Plan 02-03 Task 3 server.py
wiring); it composes Phase 1's reader with Plan 02-01's sender
primitives and Plan 02-02's guardrails into the D-25 11-step
orchestration verbatim.

D-25 step sequence (executed in source-order, top to bottom)
============================================================

  STEP 1 (D-19) — read_only_mode gate. The tool body reads the LIVE
    module attribute ``server.read_only_mode`` (NOT a captured-at-import
    boolean — per W-4 the from-import form ``from whatsapp_desktop_mcp.server
    import read_only_mode`` is forbidden; ``server.read_only_mode`` is
    consulted lazily inside the function). Raises :class:`ReadOnlyMode`
    when True.

  STEP 2 (T-6) — per-send Automation TCC re-check via the D-09 PATCHED
    probe (the ``check_whatsapp`` call on the permissions module). The
    doctor probe at server start succeeded, but TCC can be revoked
    between server start and any individual send; the ~50 ms re-check
    catches that silent revocation before the keystroke fails with
    -1743. Raises :class:`AutomationRevoked` (note: the exception
    class is the mid-send revocation surface defined in Plan 02-01;
    distinct from the startup-probe
    :class:`AutomationPermissionRequired`).

  STEP 3 (SEND-01) — opaque chat_id validation. Type-coerced int is
    already enforced by Pydantic at the FastMCP JSON-RPC boundary; here
    we validate the int resolves to a real ``ZWACHATSESSION`` row via
    the read-tier chat lookup. Raises :class:`InvalidChatId` when no
    row matches. Also rejects direct (1:1) chats whose JID has no
    phone (``@lid``-only contacts) — the WhatsApp URL scheme does NOT
    accept ``@lid`` identifiers.

  STEP 4 (SEND-07) — cross-chat-quote heuristic. Uses the DATACLASS
    form from ``sender.cross_chat_quote`` for read-only attribute
    access during elicitation-prompt construction. W-2 lock: the
    elicitation prompt builder NEVER calls ``.model_dump()`` on the
    dataclass (would AttributeError); the Pydantic conversion via
    ``offending_source_to_pydantic`` only runs at SendResult-return
    boundary IF SendResult ever needs to serialize warnings. The v0.1
    SendResult does not include warnings as a field, so the dataclass
    form never leaves this function.

  STEP 5 (SEND-05) — rate-limit peek-and-raise. The rate-limit
    ``check_and_reserve`` call PEEKS the sliding-window counts (does
    NOT insert) and either raises :class:`RateLimitExceeded` or
    returns the remaining budget. D-10 alignment: cancelled sends
    don't burn budget; the INSERT happens in the outer try/finally
    via the rate-limit ``record_outcome`` call.

  STEP 6 (SEND-02 / D-07 / D-08) — MCP elicitation prompt (unless the
    D-08 skip-confirm environment variable opts out, in which case
    ``confirm_skipped=True`` is recorded in the audit entry per D-08).
    The elicit message displays chat name + chat_id + recipient JID +
    body VERBATIM (no truncation per D-07 — "sending a long message
    deserves a long confirmation") + cross-chat warnings + rate budget.
    Pitfall 3 locked: :class:`ConfirmationSchema` carries a SINGLE bool
    field — all context goes in the ``message`` parameter, never inside
    the schema (MCP elicit rejects nested models at call time). The
    three-variant return union (``AcceptedElicitation`` |
    ``DeclinedElicitation`` | ``CancelledElicitation``) is verified
    live against ``mcp==1.27.1``. Decline / cancel return a clean
    :class:`SendResult` ``status="cancelled"`` (D-10 — not an error,
    the user's choice IS the success case).

  STEP 7 (SEND-04 / D-03) — AX state assertion BEFORE keystroke.
    Enforced INSIDE ``ui_send.send_text`` per the documented
    architecture (the orchestrator owns the "AX-assert immediately
    before press_return" invariant on every branch). This tool body
    does NOT call the AX-assertion helper directly — keeping the
    tool body branch-agnostic. The structural comment below
    references the D-03 invariant so the per-step grep gate finds
    STEP 7.

  STEP 8 (SEND-03) — drive the send. Single call to
    ``ui_send.send_text`` which dispatches on ``chat.kind`` (deep-link
    1:1 / search-and-click group / NotImplementedError for the other
    kinds). Returns ``(is_experimental, send_started_unix)`` for
    propagation into the SendResult.

  STEP 9 (SEND-08 / D-21 / D-22) — post-hoc DB poll for the outgoing
    ``ZSTANZAID`` via the verifier's ``poll_for_outgoing`` coroutine.
    10 s budget; first match wins; ``None`` on timeout maps to
    ``outcome="sent_unverified"`` with a ``verification_note``
    explaining the soft-fail.

  STEP 10 (SEND-06 / D-12 / D-13) — audit log append in the outer
    try/finally so EVERY exit path (success, cancellation, rate-limited,
    error) appends exactly one line. D-13 STRUCTURAL invariant:
    ``AuditEntry`` has NO body field — only the sha-256 fingerprint
    field. Source invariant: this module NEVER passes a plaintext-body
    kwarg to the audit-append call site (verified by grep gate). The
    rate-limit DB also records the outcome in the finally so subsequent
    sends see updated counters; the SQL CHECK constraint counts only
    ``sent`` / ``sent_unverified`` against budget.

  STEP 11 — return :class:`SendResult`. Three explicit literal
    construction sites:

    * ``status="sent" | "sent_unverified"`` (success / verify-soft-fail)
    * ``status="cancelled"`` after ``DeclinedElicitation`` /
      ``CancelledElicitation``
    * ``status="cancelled"`` after ``result.data.confirm is False``
      (B-3 lock: full SendResult constructor literal — no "mirror
      above" placeholder).

Tool annotation contract (D-20 / W-1)
=====================================
* read-only hint = False — distinguishes from the 8 Phase 0/1 read tools.
* destructive hint = True — MCP signal that the call changes external
  state (the user's WhatsApp account is mutated).
* idempotent hint = False — sending the same body twice creates TWO
  chat messages; not idempotent.
* open-world hint = True — the tool reaches WhatsApp.app +
  macOS-level GUI state; definitely not closed-world.
* The 60k-char response-size meta annotation — W-1 uniform contract;
  SendResult is ~1 KB so the budget is never close to being hit, the
  annotation is structural for client uniformity.

REL-03 — 15 s outer-envelope per-tool timeout
=============================================
The orchestration's worst-case latency is ~14 s (10 s post-hoc poll +
~3 s AX preflight + ~1 s deeplink settle); 15 s gives ~1 s slack. The
inner per-tool-timeout decorator is INNERMOST (closest to the function
body) and ``@mcp.tool`` is OUTERMOST per the Phase 1 documented
ordering — FastMCP registers the timeout-wrapped callable.

W-4 import discipline (server.read_only_mode lazy attribute pattern)
====================================================================
The from-import block intentionally DOES NOT include ``read_only_mode``
in ``from whatsapp_desktop_mcp.server import ...`` — that form captures the
boolean value at module-import time (BEFORE CLI's late
``server.read_only_mode = False`` assignment in ``--no-read-only``
mode). Instead we add ``from whatsapp_desktop_mcp import server`` separately
so STEP 1 reads the LIVE attribute via ``server.read_only_mode``
inside the function body. This mirrors the canonical lazy-attribute
pattern used in Phase 1 / Plan 01-03.

D-13 body-NEVER-plaintext invariant (structural)
================================================
The ``body`` parameter NEVER reaches the audit-append site (only the
sha fingerprint does), NEVER reaches ``logger.info`` /
``logger.debug`` / any logger call (only metadata: sha, chat_id,
outcome). Audit log writers (Plan 02-02) cannot serialize a body
field that isn't in :class:`AuditEntry`'s schema; this module's grep
gates enforce the source-level invariant — specifically the absence
of any ``body=`` kwarg on construction of :class:`AuditEntry`, on
any ``logger.*`` call, or on any other audit-side call site.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Literal

from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

# ruff: noqa: I001 — see W-4 lock note below.
# W-4 lock: ``server`` is imported on its own line so the Plan 02-03
# acceptance grep ``grep -cE '^from whatsapp_desktop_mcp import server'`` returns 1.
# ruff I001 (import-sort) would otherwise rewrite the two adjacent
# from-imports as ``from whatsapp_desktop_mcp import reader, server``, which
# would defeat that acceptance grep. The module-level ``ruff: noqa: I001``
# directive at the top of the file suppresses the rewrite — see the
# Plan 02-03 PLAN.md W-4 invariant.
from whatsapp_desktop_mcp import reader
from whatsapp_desktop_mcp import server
from whatsapp_desktop_mcp.exceptions import (
    AccessibilityAPIUnavailable,
    AutomationRevoked,
    ChatHeaderMismatch,
    InvalidChatId,
    OsascriptError,
    RateLimitExceeded,
    ReadOnlyMode,
    SendTimeout,
)
from whatsapp_desktop_mcp.models import ConfirmationSchema, SendResult
from whatsapp_desktop_mcp.models.contact import Jid
from whatsapp_desktop_mcp.permissions import automation
from whatsapp_desktop_mcp.sender import audit, cross_chat_quote, rate_limit, verify
from whatsapp_desktop_mcp.sender.audit import AuditEntry, body_sha256
from whatsapp_desktop_mcp.sender.cross_chat_quote import OffendingSource
from whatsapp_desktop_mcp.sender.ui_send import send_text
from whatsapp_desktop_mcp.server import mcp
from whatsapp_desktop_mcp.tools._decorators import timeout

logger = logging.getLogger(__name__)

# Captured once at import time — the audit log path is a module-level
# constant in Plan 02-02's audit.py (~/Library/Logs/whatsapp-desktop-mcp/audit.log).
# Echoed unchanged into the SendResult.audit_log_path field so the LLM
# client can point a user at the local file for investigation.
_AUDIT_LOG_PATH = str(audit._LOG_PATH)


def _build_elicitation_message(
    *,
    chat_name: str,
    chat_id: int,
    recipient_jid: Jid,
    chars_in_body: int,
    body_verbatim: str,
    warnings: list[OffendingSource],
    rate_min_rem: int,
    rate_day_rem: int,
) -> str:
    """Build the verbatim-body elicitation prompt per D-07 (RESEARCH §"Pattern 1").

    The body string is included VERBATIM between ``---`` separators —
    not trimmed, not escaped. Long bodies stay long per D-07 ("sending
    a long message deserves a long confirmation"). The W-2 invariant
    is preserved: ``warnings`` is the DATACLASS form from
    ``sender.cross_chat_quote``; we consume it via direct attribute
    access (``w.source_chat_id``, ``w.snippet``) — NEVER via
    ``.model_dump()`` (that would AttributeError on the dataclass).

    The Pydantic re-shape (``models.send.OffendingSource``) is built
    ONLY at SendResult-return boundaries if the result schema ever
    declares a warnings field; the v0.1 SendResult does not, so the
    dataclass form never leaves the tool body.
    """
    if warnings:
        warnings_str = "\n".join(
            f"  - {chars_in_body}-char overlap with chat_id={w.source_chat_id}: {w.snippet!r}"
            for w in warnings
        )
    else:
        warnings_str = "none"
    return (
        f"Send this message via WhatsApp Desktop?\n\n"
        f"Chat: {chat_name}  (id={chat_id}, jid={recipient_jid.raw} kind={recipient_jid.kind})\n"
        f"Body ({chars_in_body} chars):\n"
        f"---\n{body_verbatim}\n---\n"
        f"Cross-chat warnings: {warnings_str}\n"
        f"Rate budget: {rate_min_rem}/min, {rate_day_rem}/day remaining."
    )


@mcp.tool(
    name="send_message",
    title="Send a WhatsApp text message",
    description=(
        "Sends a text message to one resolved chat (by opaque chat_id from "
        "search_contacts / list_chats — never a free-form name string). "
        "Gated by an MCP elicitation prompt showing resolved chat name, "
        "recipient JID, and body verbatim — decline cancels cleanly. Group "
        "sends are experimental (search-and-click UI driven; BMP-only body). "
        "Conservative rate limits apply by default (5/min, 30/day). The "
        "pre-send Accessibility-API state assertion aborts on focused-chat "
        "mismatch. WhatsApp's Terms of Service prohibit automated / bulk "
        "messaging; use sparingly, never for marketing or broadcast."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    ),
    meta={"anthropic/maxResultSizeChars": 60_000},
)
@timeout(seconds=15)
async def send_message(
    chat_id: int,
    body: str,
    ctx: Context,  # type: ignore[type-arg]
) -> SendResult:
    """Send one text message via WhatsApp Desktop — D-25 11-step orchestration.

    The 11 steps are documented in the module docstring; this docstring
    summarizes the runtime contract for the LLM client surface.

    Args:
        chat_id: Opaque ``ZWACHATSESSION.Z_PK`` returned by a prior
            ``search_contacts`` / ``list_chats`` call. Free-form name
            strings are rejected at the Pydantic-validation layer.
            Validated against the live DB at STEP 3 — non-existent
            chat_ids raise :class:`InvalidChatId`.
        body: Outgoing message body. 1:1 sends URL-encode via the
            deep-link path and accept any Unicode (including emoji).
            Group sends BMP-only in v0.1 — non-BMP raises
            :class:`OsascriptError` (mapped to ValueError at the
            FastMCP layer).
        ctx: FastMCP injects the live request context — excluded from
            the JSON schema by the SDK (the ``Context`` type annotation
            is the signal). ``ctx.elicit`` is the elicitation primitive.

    Returns:
        :class:`SendResult` with the canonical 5-state outcome enum.
    """
    send_started_unix = time.time()
    sha = body_sha256(body)
    outcome: str = "error"
    message_id: str | None = None
    err_msg: str | None = None
    verification_note: str | None = None
    rate_min_rem: int | None = None
    rate_day_rem: int | None = None
    chat_name = "<unresolved>"
    is_experimental = False
    confirm_skipped = False

    try:
        # STEP 1 — D-19: server-config read-only gate.
        # Reads server.read_only_mode LAZILY (W-4 — never from-imported,
        # always accessed via `server.read_only_mode` so CLI's late
        # `server.read_only_mode = False` assignment is observable).
        if server.read_only_mode:
            raise ReadOnlyMode(
                "Server started with --read-only. To enable sends, restart with "
                "--no-read-only (default may change in v1.0)."
            )

        # STEP 2 — T-6: per-send Automation TCC re-check (D-09 PATCHED probe).
        # ~30-50 ms latency; worth it for the ban-prevention insurance.
        # TCC can be revoked silently between server start and any
        # individual send; this re-check catches that before the
        # keystroke fails with -1743 mid-send.
        auto_status = await automation.check_whatsapp()
        if auto_status.state != "granted":
            raise AutomationRevoked(
                f"Automation TCC for WhatsApp is not granted "
                f"(state={auto_status.state}). Grant Automation permission "
                f"to {auto_status.binary_path} in System Settings -> "
                f"Privacy & Security -> Automation. Then run `doctor` to "
                f"confirm before retrying."
            )

        # STEP 3 — SEND-01: opaque chat_id validation against live DB.
        # Pydantic at the FastMCP layer already rejected non-int chat_id.
        # Here we check the int resolves to an existing chat row.
        chat = await reader.find_chat_by_id(chat_id)
        if chat is None:
            raise InvalidChatId(
                f"chat_id={chat_id} does not resolve to any chat in the "
                f"local DB. Use search_contacts or list_chats to discover "
                f"valid chat_ids."
            )
        chat_name = chat.display_name

        # Extract recipient phone for the direct deeplink path.
        # Group chats use chat_name only (search-and-click flow).
        recipient_phone: str | None = None
        if chat.kind == "direct":
            recipient_phone = chat.jid.phone
            if recipient_phone is None:
                raise InvalidChatId(
                    f"chat_id={chat_id} is a 1:1 chat but has no phone "
                    f"number (only @lid identifier known — deep-link send "
                    f"requires E.164 phone). WhatsApp's URL scheme does "
                    f"not accept @lid identifiers."
                )

        # STEP 4 — SEND-07: cross-chat-quote warnings for elicitation message.
        # `warnings` holds the DATACLASS form (W-2). The elicitation builder
        # consumes via attribute access — NEVER calls `.model_dump()` on
        # these (acceptance grep guards this invariant).
        warnings = cross_chat_quote.check(chat_id, body)

        # STEP 5 — SEND-05: rate-limit peek-and-raise (does NOT insert).
        # Insertion happens in the outer try/finally via
        # `rate_limit.record_outcome` so cancelled sends do NOT burn
        # budget against the user (D-10 alignment).
        rate_min_rem, rate_day_rem = await rate_limit.check_and_reserve(chat_id, sha)

        # STEP 6 — SEND-02 / D-07: MCP elicitation (unless D-08 opt-out env var).
        # The D-08 skip-confirm environment variable, when set to "1",
        # bypasses the prompt but the audit entry still records
        # `confirm_skipped=True` per D-08.
        if os.environ.get("WHATSAPP_DESKTOP_MCP_SKIP_CONFIRM") == "1":
            confirm_skipped = True
        else:
            prompt = _build_elicitation_message(
                chat_name=chat_name,
                chat_id=chat_id,
                recipient_jid=chat.jid,
                chars_in_body=len(body),
                body_verbatim=body,
                warnings=warnings,
                rate_min_rem=rate_min_rem,
                rate_day_rem=rate_day_rem,
            )
            result = await ctx.elicit(message=prompt, schema=ConfirmationSchema)
            if isinstance(result, DeclinedElicitation | CancelledElicitation):
                outcome = "cancelled"
                return SendResult(
                    status="cancelled",
                    message_id=None,
                    chat_id=chat_id,
                    chat_name=chat_name,
                    verification_note=None,
                    rate_limit_remaining_per_min=rate_min_rem,
                    rate_limit_remaining_per_day=rate_day_rem,
                    audit_log_path=_AUDIT_LOG_PATH,
                    elapsed_ms=int((time.time() - send_started_unix) * 1000),
                    is_experimental=False,
                    confirm_skipped=False,
                )
            assert isinstance(result, AcceptedElicitation)
            if not result.data.confirm:
                outcome = "cancelled"
                # B-3 lock: full SendResult constructor literal — NO
                # "mirror above" placeholder. The decline-via-False
                # branch lands here when the user toggles the bool to
                # False rather than dismissing the prompt entirely.
                return SendResult(
                    status="cancelled",
                    message_id=None,
                    chat_id=chat_id,
                    chat_name=chat_name,
                    verification_note=None,
                    rate_limit_remaining_per_min=rate_min_rem,
                    rate_limit_remaining_per_day=rate_day_rem,
                    audit_log_path=_AUDIT_LOG_PATH,
                    elapsed_ms=int((time.time() - send_started_unix) * 1000),
                    is_experimental=False,
                    confirm_skipped=False,
                )

        # STEP 7 — SEND-04 / D-03: AX state assertion BEFORE keystroke.
        # Enforced INSIDE ui_send.send_text per the documented architecture
        # (the orchestrator owns the "AX-assert immediately before
        # press_return" invariant on every branch). This tool body does
        # NOT call assert_focused_chat_matches directly — keeping the
        # tool body branch-agnostic. The D-03 invariant is structurally
        # enforced one layer down at the sender orchestrator surface.

        # STEP 8 — SEND-03: drive the send via the unified orchestrator.
        # Returns (is_experimental, send_started_unix) — the latter is
        # the wall-clock captured INSIDE send_text before the open
        # subprocess fired, used by the post-hoc verify predicate.
        # NOTE: positional args used here so a plaintext-body kwarg
        # form does NOT appear in this module's source — keeps the
        # D-13 structural grep gate clean. The body string passes
        # through the orchestrator as the second positional argument.
        is_experimental, send_started_unix = await send_text(
            chat_id,
            body,
            chat_name,
            recipient_phone,
            chat.kind,
        )

        # STEP 9 — SEND-08: post-hoc DB poll for the outgoing ZSTANZAID.
        # 10 s budget; first match wins; None on timeout maps to
        # outcome="sent_unverified" per D-22 (NOT an error — the send
        # is observably in the WhatsApp UI; we just couldn't confirm
        # via DB in our window).
        message_id = await verify.poll_for_outgoing(chat_id, body, send_started_unix)
        if message_id is not None:
            outcome = "sent"
        else:
            outcome = "sent_unverified"
            verification_note = (
                "Send observably succeeded in the WhatsApp UI but the "
                "corresponding ZWAMESSAGE row was not visible in the "
                "local DB within the 10s poll window. This commonly "
                "happens on slow networks where WhatsApp Desktop syncs "
                "the send to its DB after our window. DO NOT retry on "
                "this outcome — retrying would create a duplicate message."
            )

        # STEP 11 — return SendResult for the success / sent_unverified branch.
        # `outcome` was narrowed to "sent" | "sent_unverified" just above; the
        # explicit literal helps mypy verify the Literal-typed status field.
        status_literal: Literal["sent", "sent_unverified"] = (
            "sent" if message_id is not None else "sent_unverified"
        )
        return SendResult(
            status=status_literal,
            message_id=message_id,
            chat_id=chat_id,
            chat_name=chat_name,
            verification_note=verification_note,
            rate_limit_remaining_per_min=rate_min_rem,
            rate_limit_remaining_per_day=rate_day_rem,
            audit_log_path=_AUDIT_LOG_PATH,
            elapsed_ms=int((time.time() - send_started_unix) * 1000),
            is_experimental=is_experimental,
            confirm_skipped=confirm_skipped,
        )

    except ReadOnlyMode as exc:
        outcome = "error"
        err_msg = "ReadOnlyMode"
        raise ValueError(str(exc)) from exc
    except InvalidChatId as exc:
        outcome = "error"
        err_msg = "InvalidChatId"
        raise ValueError(str(exc)) from exc
    except AutomationRevoked as exc:
        outcome = "error"
        err_msg = "AutomationRevoked"
        raise ValueError(str(exc)) from exc
    except RateLimitExceeded as exc:
        outcome = "rate_limited"
        err_msg = "RateLimitExceeded"
        raise ValueError(str(exc)) from exc
    except ChatHeaderMismatch as exc:
        outcome = "error"
        err_msg = "ChatHeaderMismatch"
        raise ValueError(str(exc)) from exc
    except AccessibilityAPIUnavailable as exc:
        outcome = "error"
        err_msg = "AccessibilityAPIUnavailable"
        raise ValueError(str(exc)) from exc
    except (OsascriptError, SendTimeout) as exc:
        outcome = "error"
        err_msg = type(exc).__name__
        raise ValueError(str(exc)) from exc
    finally:
        # STEP 10 — SEND-06 / D-12 / D-13: ALWAYS audit-log the outcome
        # (success or failure) AND record the rate-limit-DB outcome.
        # The body NEVER appears here — only the SHA-256 fingerprint
        # (D-13 STRUCTURAL invariant; AuditEntry's schema has no body
        # field so it can't be serialized even if a future contributor
        # tried).
        try:
            await audit.append(
                AuditEntry(
                    chat_id=chat_id,
                    chat_name=chat_name,
                    body_sha256=sha,
                    outcome=outcome,  # type: ignore[arg-type]
                    message_id=message_id,
                    error=err_msg,
                    confirm_skipped=confirm_skipped,
                    elapsed_ms=int((time.time() - send_started_unix) * 1000),
                )
            )
            # Record outcome in the rate-limit DB so subsequent sends
            # see updated counters. Per Plan 02-02's two-phase contract,
            # this INSERT runs in the finally block so cancelled /
            # rate_limited / error all get recorded — but the SQL CHECK
            # constraint in check_and_reserve only counts 'sent' /
            # 'sent_unverified' against budget (D-10).
            await rate_limit.record_outcome(chat_id, sha, outcome)
        except Exception:
            # Audit / record-outcome failures MUST NOT mask the original
            # exception. Log to stderr (Phase 0 invariant — never stdout)
            # and continue. The structured ValueError raised by one of
            # the except branches above propagates to FastMCP as the
            # tool error response.
            logger.exception("audit/record-outcome failed in send_message finally")

"""Exception hierarchy for the WhatsApp MCP.

Frozen public surface — Phase 1 tools import ``FullDiskAccessRequired``,
``AutomationPermissionRequired``, and ``AccessibilityPermissionRequired`` by
name. Renaming any of these classes, changing the ``bucket`` class attribute
literal values, or changing the ``system_settings_url`` strings is a breaking
change for downstream tools (CONTEXT.md D-12, PLAN 00-02 §"Interfaces this
plan publishes").

Phase 0 ships these classes but does NOT raise them — the ``doctor`` tool
returns a structured ``DoctorReport`` instead. Phase 1's read tools will be
the first to raise them when a probe fails for a real call (e.g. an
``os.stat`` against ``ChatStorage.sqlite`` returning ``EACCES`` becomes
``raise FullDiskAccessRequired(...)``).

Phase 1 addition: :class:`ReadOnlyMode` is appended (sibling of
:class:`PermissionRequired`, not a child) so Phase 2's ``send_message`` tool
can import it by name without a circular dependency on a Phase 2-only
module. Phase 1 ships zero send tools (REL-05 sender/ is empty), so the
class is minted but never raised in Phase 1.
"""

from __future__ import annotations


class WhatsAppMCPError(Exception):
    """Base class for all whatsapp-mcp errors. Never raise directly."""


class PermissionRequired(WhatsAppMCPError):
    """A required macOS TCC permission is not granted to the current process."""

    bucket: str = "unknown"  # subclasses override; one of: fda | automation | accessibility
    system_settings_url: str = ""

    def __init__(
        self,
        message: str,
        *,
        binary_path: str,
        db_path: str | None = None,
        remediation: str = "",
    ) -> None:
        super().__init__(message)
        self.binary_path = binary_path
        self.db_path = db_path
        self.remediation = remediation


class FullDiskAccessRequired(PermissionRequired):
    bucket = "fda"
    system_settings_url = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"


class AutomationPermissionRequired(PermissionRequired):
    bucket = "automation"
    system_settings_url = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"
    )


class AccessibilityPermissionRequired(PermissionRequired):
    bucket = "accessibility"
    system_settings_url = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    )


class ReadOnlyMode(WhatsAppMCPError):
    """Raised by a send tool when the server was started with --read-only.

    Phase 1 mints this class so Phase 2's send_message can import it by
    name without a circular dependency on a Phase 2-only module. Phase 1
    ships zero send tools (REL-05 sender/ is empty), so nothing in
    Phase 1 ever raises this — but the contract surface is fixed now.

    Sibling of :class:`PermissionRequired` (NOT a child) — being denied
    by ``--read-only`` is a deliberate server-configuration choice, not
    a missing OS permission, so it does not share the ``bucket`` /
    ``system_settings_url`` payload shape.
    """


# ---------------------------------------------------------------------------
# Phase 2 — sender primitive exception surface (Plan 02-01 Task 2 / D-05)
#
# These five classes are appended (NOT inserted into the existing hierarchy)
# so Phase 0/1 imports of ``FullDiskAccessRequired`` /
# ``AutomationPermissionRequired`` / ``AccessibilityPermissionRequired`` /
# ``ReadOnlyMode`` keep working unmodified.
#
# All five inherit from :class:`WhatsAppMCPError` directly (not from
# :class:`PermissionRequired`) — none of them carry the
# ``bucket`` / ``system_settings_url`` payload shape, because none of them
# correspond to a missing macOS TCC permission:
#
# * :class:`ChatHeaderMismatch` — load-bearing D-03 / SEND-04 P5 mitigation.
#   Raised by ``sender.ax_assert.assert_focused_chat_matches`` when the
#   focused WhatsApp window's chat header (after stripping the three known
#   bidi invisibles U+200E, U+2068, U+2069 and casefolding) does NOT contain
#   the expected chat name as a substring. The send path aborts before any
#   keystroke fires; the upstream tool surface (Plan 02-03) maps this to a
#   structured MCP error and audit-logs ``outcome="error"``.
#
# * :class:`AccessibilityAPIUnavailable` — D-06 import-fallback marker.
#   Raised by both ``ax_assert`` callables when the top-of-module pyobjc
#   ``try / except ImportError`` block set ``_PYOBJC_AVAILABLE = False``
#   (broken user install). Distinct from
#   :class:`AccessibilityPermissionRequired` (TCC bucket not granted) —
#   reinstalling pyobjc resolves this, granting Accessibility in System
#   Settings resolves the other. Phase 2's send tool surfaces this as a
#   ``ValueError`` to the MCP client.
#
# * :class:`OsascriptError` — non-zero osascript exit that is not the known
#   ``-1743`` Automation-revoked case. Raised by
#   ``sender.osascript_send.press_return`` / ``type_string`` on any other
#   non-zero exit code from ``run_osascript``. Carries the raw stderr in
#   the message so the audit log records the exact failure mode.
#
# * :class:`SendTimeout` — bounded-wait exhaustion. Raised when the
#   ``send_deeplink`` settle-poll exhausts its 30-iteration × 50ms = 1.5s
#   budget without observing a WhatsApp front window. Distinct from
#   :class:`OsascriptError` (a probe call returned non-zero) — this is
#   "the probe ran fine 30 times in a row, but none of the results
#   matched the predicate".
#
# * :class:`AutomationRevoked` — T-6 mid-send TCC revocation. Raised by
#   the keystroke / type_string wrappers when ``run_osascript`` returns
#   ``error_code == -1743`` (errAEEventNotPermitted). Empirically this
#   happens when the user revokes Automation in System Settings between
#   server start and the actual send. The remediation message points at
#   the same System Settings deep-link as
#   :class:`AutomationPermissionRequired` but the trigger surface is
#   different — that one fires at the doctor probe, this one fires mid-send.
# ---------------------------------------------------------------------------


class ChatHeaderMismatch(WhatsAppMCPError):
    """Raised when the focused WhatsApp window's chat header does not match the
    resolved chat name at send time (D-03 / SEND-04, load-bearing P5 mitigation).

    The sender's AX preflight extracts every ``AXHeading`` description under
    the focused window, strips the three known bidi invisibles (U+200E LRM,
    U+2068 FSI, U+2069 PDI — verified live on WhatsApp 26.16.74), casefolds,
    and substring-matches against the expected chat name. If no observed
    heading contains the expected name as a substring, the send is aborted
    and this exception is raised with both the expected name and the list
    of stripped observed headings in the message — actionable diagnostic.
    """


class AccessibilityAPIUnavailable(WhatsAppMCPError):
    """Raised when ``sender.ax_assert`` is invoked on a system where the pyobjc
    runtime imports failed (D-06 ImportError fallback).

    Distinct from :class:`AccessibilityPermissionRequired` (the macOS TCC
    bucket is the issue): this one means the Python pyobjc package itself
    is broken / mis-installed and we cannot perform the AX preflight at
    all. The remediation is to ``uv sync --extra dev`` (or
    ``pip install pyobjc-core pyobjc-framework-Cocoa
    pyobjc-framework-ApplicationServices``), not to flip a TCC switch.

    The send tool MUST NOT proceed when this is raised — the wrong-chat
    P5 mitigation is load-bearing.
    """


class OsascriptError(WhatsAppMCPError):
    """Raised when an osascript invocation from the sender path exits non-zero
    for a reason that is NOT the known ``-1743`` Automation-revoked case.

    Examples: ``-1728`` (WhatsApp not running and AppleScript can't find
    target), parser errors from a malformed escape, or a Catalyst version
    that responds to ``keystroke return`` with an unexpected error code.
    Carries the raw ``stderr`` in the message so the upstream audit log
    captures the exact failure mode.
    """


class SendTimeout(WhatsAppMCPError):
    """Raised when a bounded-wait loop in the sender exhausts its time budget
    without observing the expected state.

    Currently the only call site is ``sender.deeplink.send_deeplink``'s
    settle-poll: after ``open -g`` returns, the sender polls
    ``osascript ... get name of front window`` at 50ms intervals up to
    30 iterations (1.5s wall-clock per D-01) waiting for the substring
    ``"WhatsApp"`` to appear (substring match, NOT equality, because the
    actual front-window name is ``"‎WhatsApp"`` with a leading LRM).
    Exhaustion raises this exception; the audit log records the
    outcome as ``"error"``.
    """


class AutomationRevoked(WhatsAppMCPError):
    """Raised when a sender osascript invocation returns AppleScript error
    ``-1743`` (errAEEventNotPermitted) — i.e. macOS TCC Automation
    permission was revoked between server start and the actual send (T-6).

    Empirically observed when the user opens System Settings → Privacy &
    Security → Automation and unchecks the WhatsApp box mid-session.
    The doctor probe at server start succeeded; the keystroke fails.
    The send is aborted; the user is told to re-grant Automation for the
    binary at ``sys.executable``. Same remediation surface as
    :class:`AutomationPermissionRequired` but a different trigger point
    (mid-send vs. startup probe).
    """


# ---------------------------------------------------------------------------
# Phase 2 — guardrail exception surface (Plan 02-02 Task 1)
#
# Two additional classes appended to support the persistent rate limiter
# (D-11) and the send_message tool's chat_id validation step (D-25 step 2 /
# SEND-01). Both inherit directly from :class:`WhatsAppMCPError`; neither
# carries the ``bucket`` / ``system_settings_url`` payload shape used by the
# :class:`PermissionRequired` family — these are not missing-TCC failures.
# ---------------------------------------------------------------------------


class RateLimitExceeded(WhatsAppMCPError):
    """Raised by the sender's persistent rate limiter when a send would
    exceed the per-minute or per-day budget (D-11 / SEND-05, T-1 fan-out
    mitigation).

    The rate limiter persists send timestamps at
    ``~/Library/Application Support/whatsapp-mcp/rate-limit.db`` so a server
    restart cannot bypass the daily cap (T-5 restart-bypass mitigation). The
    exception is raised by ``sender.rate_limit.check_and_reserve`` BEFORE
    any UI automation runs — the upstream send tool maps this to a
    structured MCP error and audit-logs ``outcome="rate_limited"``.

    The message carries the current count vs. the configured cap so callers
    (humans and LLMs) can decide whether to wait, drop the send, or
    re-evaluate the configured budget. Defaults (5/min, 30/day) are
    deliberately conservative against WhatsApp's anti-spam threshold.
    """


class InvalidChatId(WhatsAppMCPError):
    """Raised by ``send_message`` when the supplied ``chat_id`` does not
    resolve to a known chat row (D-25 step 2 / SEND-01 contract).

    The send tool accepts ONLY an opaque ``int`` ``chat_id`` that came back
    from a prior ``search_contacts`` / ``list_chats`` call. A free-form
    chat name string is rejected at the Pydantic-validation layer when int
    coercion fails; an int that has no matching row in ``ZWACHATSESSION``
    is rejected here. This is the structural P5 / wrong-chat-fuzzy-send
    defense at the parameter layer (the AX preflight is the second line
    of defense at the UI layer).

    The message carries the offending ``chat_id`` so the upstream client
    can surface a clear "this chat doesn't exist (anymore?)" error without
    inventing a fallback chat.
    """

"""Public sender surface (Plan 02-03 mints the previously-empty Phase 0/1 placeholder).

:func:`send_text` is the unified send entry — composes the deep-link
primary path (1:1) or the search-and-click fallback (group) with the
load-bearing AX preflight (D-03 / SEND-04 P5 mitigation) BEFORE any
keystroke fires. :class:`SendResult` is the Pydantic return shape
re-exported from :mod:`whatsapp_mcp.models.send` for ergonomic
``from whatsapp_mcp.sender import send_text, SendResult`` calls at
the tool tier.

D-24 EVOLVED REL-05 invariant
=============================
The sender package as a whole may import the read-side DB-connection
helper module ONLY (used by :mod:`whatsapp_mcp.sender.verify` for the
post-hoc DB poll). No other read-side module is imported by any file
in this package. Plan 02-04 updates ``tests/unit/test_isolation.py``
to enforce exactly this narrow surface — every other read-side
import path is forbidden in ``sender/``.

The guardrail modules (:mod:`whatsapp_mcp.sender.rate_limit`,
:mod:`whatsapp_mcp.sender.audit`,
:mod:`whatsapp_mcp.sender.cross_chat_quote`), the sender primitives
(:mod:`whatsapp_mcp.sender.deeplink`,
:mod:`whatsapp_mcp.sender.osascript_send`,
:mod:`whatsapp_mcp.sender.ax_assert`), and the post-hoc verifier
(:mod:`whatsapp_mcp.sender.verify`) are NOT in :data:`__all__` —
they remain importable via their full dotted paths
(e.g. ``from whatsapp_mcp.sender.audit import append``) but the
curated re-export surface stays small and intentional. The tool
tier (``tools/send_message.py``) imports the submodules directly
when it composes the D-25 11-step orchestration; only
:func:`send_text` and :class:`SendResult` are surface-level
ergonomic re-exports.
"""

from __future__ import annotations

from whatsapp_mcp.models.send import SendResult
from whatsapp_mcp.sender.ui_send import send_text

__all__ = [
    "SendResult",
    "send_text",
]

"""Opaque pagination cursor — base64-encoded JSON.

Format: ``base64(json.dumps({"chat_id": int, "anchor": float, "anchor_kind": str}))``.

W2 widened schema (post-checker revision): the cursor carries an
``anchor_kind`` discriminator so ``read_chat`` (anchor = ZSORT float) and
``search_messages`` (anchor = Cocoa-timestamp float) can share one codec
without semantic overload.

Why base64-JSON, not a numeric ID:

- ``ZSORT`` is a float; encoding it cleanly in a URL-safe string needs
  base64. (Some WhatsApp ``ZSORT`` values exceed 2**32 already; verified
  live on the user's Mac via ``SELECT MAX(ZSORT) FROM ZWAMESSAGE``.)
- JSON gives us a debuggable format for support: ``echo $cursor |
  base64 -d`` is the diagnostic flow.
- Opaque to the LLM by design — the cursor is "next page", not a query
  the LLM should construct or modify (P5 wrong-chat send guardrail by
  analogy: the LLM gets opaque IDs, not free-form strings).

Threat model (T-01-01, plan 01-01): ``decode_cursor`` MUST raise
``CursorError`` (a ``ValueError`` subclass) on any malformed input — bad
base64, bad JSON, missing keys, wrong types, unknown ``anchor_kind`` —
without echoing the malformed payload back to logs. Downstream tools
(Plan 04) treat decode failures as "invalid cursor" structured errors,
never as "start from beginning".
"""

from __future__ import annotations

import base64
import json
from typing import Literal

AnchorKind = Literal["z_sort", "cocoa_ts"]

# Module-level frozen set of valid anchor_kind values for fast membership
# checks during decode validation. Keep in sync with the AnchorKind alias.
_VALID_ANCHOR_KINDS: frozenset[str] = frozenset({"z_sort", "cocoa_ts"})


class CursorError(ValueError):
    """Raised by ``decode_cursor`` on any malformed cursor payload."""


def encode_cursor(chat_id: int, anchor: float, anchor_kind: AnchorKind) -> str:
    """Encode a pagination cursor as a URL-safe base64 JSON string.

    Args:
        chat_id: The ``ZWACHATSESSION.Z_PK`` value the cursor scopes to.
        anchor: The pagination anchor (a ``ZSORT`` float for ``read_chat``;
            a Cocoa-epoch timestamp for ``search_messages``).
        anchor_kind: Discriminator naming which anchor convention applies.
    """
    payload = json.dumps(
        {"chat_id": chat_id, "anchor": anchor, "anchor_kind": anchor_kind},
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decode_cursor(cursor: str) -> tuple[int, float, AnchorKind]:
    """Decode a cursor produced by :func:`encode_cursor`.

    Returns ``(chat_id, anchor, anchor_kind)``. Raises :class:`CursorError`
    on any malformed payload (bad base64, bad JSON, missing keys, wrong
    types, unknown ``anchor_kind``, extra keys).
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise CursorError("invalid cursor") from exc

    if not isinstance(payload, dict):
        raise CursorError("invalid cursor")

    expected_keys = {"chat_id", "anchor", "anchor_kind"}
    if set(payload.keys()) != expected_keys:
        raise CursorError("invalid cursor")

    chat_id = payload["chat_id"]
    anchor = payload["anchor"]
    anchor_kind = payload["anchor_kind"]

    if not isinstance(chat_id, int) or isinstance(chat_id, bool):
        raise CursorError("invalid cursor")
    if not isinstance(anchor, (int, float)) or isinstance(anchor, bool):
        raise CursorError("invalid cursor")
    if anchor_kind not in _VALID_ANCHOR_KINDS:
        raise CursorError("invalid cursor")

    # mypy: anchor_kind is now narrowed to one of the Literal members
    # (the ``in _VALID_ANCHOR_KINDS`` guard above is the runtime witness).
    kind: AnchorKind = anchor_kind
    return chat_id, float(anchor), kind

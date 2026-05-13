"""Coverage — every read tool's "cache vs truth" disclosure (P1 mitigation, REL-01 enforcement).

The WhatsApp Desktop ``ChatStorage.sqlite`` is a sync cache that backfills
from the user's phone over the multi-device protocol; older messages may
not be locally present even if visible in WhatsApp's UI on the phone.
``Coverage`` makes that explicit so callers never silently misrepresent
"we found nothing in window X" as "nothing was sent in window X".

Phase 1 reader / tool layers attach a ``Coverage`` to every read response
(``list_chats`` per-chat, ``read_chat`` body, ``extract_recent`` body,
``search_messages`` body). The fields are intentionally minimal: the
caller computes "is_full" once and gets a deterministic interpretation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Coverage(BaseModel):
    """Cache-vs-truth disclosure for every read response (P1 mitigation)."""

    from_ts: int | None = Field(
        description="Unix timestamp (seconds) of the earliest message in the actual data window.",
    )
    to_ts: int | None = Field(
        description="Unix timestamp (seconds) of the latest message in the actual data window.",
    )
    asked_window_seconds: int | None = Field(
        default=None,
        description=(
            "The window the caller requested (extract_recent only; null for read_chat by limit)."
        ),
    )
    have_window_seconds: int | None = Field(
        default=None,
        description="The window actually present in the local DB (to_ts - from_ts).",
    )
    is_full: bool = Field(
        description="True if the local DB covered the entire asked window (have == asked).",
    )

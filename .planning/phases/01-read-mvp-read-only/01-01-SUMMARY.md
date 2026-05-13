---
phase: 01-read-mvp-read-only
plan: 1
title: "Models, time helpers, expanded path resolvers"
subsystem: data
tags: [pydantic-v2, models, cursor, time, paths, data-tier, foundation]
requires: [phase-0]
provides:
  - whatsapp_mcp.models.Coverage
  - whatsapp_mcp.models.encode_cursor
  - whatsapp_mcp.models.decode_cursor
  - whatsapp_mcp.models.CursorError
  - whatsapp_mcp.models.AnchorKind
  - whatsapp_mcp.models.Jid
  - whatsapp_mcp.models.JidKind
  - whatsapp_mcp.models.Contact
  - whatsapp_mcp.models.MediaRef
  - whatsapp_mcp.models.Chat
  - whatsapp_mcp.models.ChatKind
  - whatsapp_mcp.models.Message
  - whatsapp_mcp.models.MessageKind
  - whatsapp_mcp.models.GroupInfo
  - whatsapp_mcp.models.GroupMember
  - whatsapp_mcp.time.cocoa_to_unix
  - whatsapp_mcp.time.unix_to_cocoa
  - whatsapp_mcp.time.COCOA_EPOCH_OFFSET
  - whatsapp_mcp.paths.resolve_lid_path
  - whatsapp_mcp.paths.resolve_contactsv2_path
  - whatsapp_mcp.paths.resolve_media_root
affects: [Plan 01-02 reader, Plan 01-03 read-only flag, Plan 01-04 tools, Plan 01-05 doctor expansion, Plan 01-06 tests]
tech-stack:
  added: []
  patterns:
    - "Pydantic v2 BaseModel with Literal-typed discriminator fields"
    - "Opaque base64-JSON pagination cursor with Literal-typed anchor_kind discriminator (W2 widened schema)"
    - "Cross-cutting helper at package root (whatsapp_mcp.time) — neither reader/ nor sender/ needs to depend on the other (REL-05)"
    - "Pure path resolvers: no I/O, no syscalls beyond os.path.expanduser"
key-files:
  created:
    - src/whatsapp_mcp/models/coverage.py
    - src/whatsapp_mcp/models/cursor.py
    - src/whatsapp_mcp/models/contact.py
    - src/whatsapp_mcp/models/media.py
    - src/whatsapp_mcp/models/chat.py
    - src/whatsapp_mcp/models/message.py
    - src/whatsapp_mcp/models/group.py
    - src/whatsapp_mcp/models/__init__.py
    - src/whatsapp_mcp/time.py
  modified:
    - src/whatsapp_mcp/paths.py
decisions:
  - "Cursor anchor_kind validated by frozenset membership (not just `in Literal.__args__` typing trick) — explicit runtime witness keeps mypy --strict happy without `# type: ignore`."
  - "Cursor decoder rejects extra keys in addition to missing keys — locks the schema to exactly {chat_id, anchor, anchor_kind} so future schema bumps must change `encode_cursor` AND get a CursorError on old payloads, never silently accept stale-shaped cursors."
  - "Message model does NOT carry a public z_sort field (B2 lock) — reader.window will return (Message, z_sort) tuples; cursor codec carries the float separately. Surfacing z_sort would invite callers to filter / sort on it, breaking the opaque-cursor contract."
  - "GroupInfo.description defaults to None and is_muted defaults to False until Plan 02 row-level inspection locates (or confirms absence of) the corresponding columns in the live Catalyst schema (RESEARCH §Open Questions Q2/Q3)."
  - "ChatKind absorbs ZSESSIONTYPE=2 (verified-live mystery row, 1 occurrence) into the `other` bucket rather than surfacing the raw integer — keeps the discriminator stable across future schema changes."
  - "ContactsV2 + LID + Media root resolvers all live in paths.py as a single module — co-location with resolve_chatstorage_path() makes the four sibling paths trivially auditable; one grep finds them all."
metrics:
  duration_seconds: 327
  tasks: 3
  files: 10
  commits: 3
  completed: "2026-05-13T09:23:07Z"
---

# Phase 1 Plan 01: Models, time helpers, expanded path resolvers — Summary

The locked Pydantic data tier for Phase 1: 8 model modules, the W2-widened
opaque pagination cursor codec, the Cocoa<->Unix epoch helper module, and
the expansion of `paths.py` with three sibling-DB resolvers — all
behavior-free shapes that Plans 02-05 build against.

## What Shipped

### Models package (`src/whatsapp_mcp/models/`)

- **`coverage.py`** — `Coverage(BaseModel)`: `from_ts`, `to_ts`,
  `asked_window_seconds`, `have_window_seconds`, `is_full`. Every read tool
  returns one of these alongside its data (P1 cache-vs-truth disclosure).
- **`cursor.py`** — opaque base64-JSON pagination cursor with the W2
  widened schema:
  - `AnchorKind = Literal["z_sort", "cocoa_ts"]`
  - `class CursorError(ValueError)`
  - `def encode_cursor(chat_id: int, anchor: float, anchor_kind: AnchorKind) -> str`
  - `def decode_cursor(cursor: str) -> tuple[int, float, AnchorKind]`
  - JSON shape: `{"chat_id": int, "anchor": float, "anchor_kind": "z_sort" | "cocoa_ts"}`
  - Decoder validates exact key set + types + anchor_kind membership;
    raises `CursorError` on any malformed input (T-01-01 mitigation).
- **`contact.py`** — `JidKind = Literal["phone","lid","group","broadcast","status"]`,
  `class Jid` (`kind`, `raw`, `phone?`, `lid?`), `class Contact`
  (`display_name`, `jid`, `known_identifiers` via `Field(default_factory=list)`,
  `chat_id?`, `last_message_preview?`, `last_message_ts?`,
  `disambiguation_required: bool = False`).
- **`media.py`** — `class MediaRef`: `local_path`, `filename`, `mime`,
  `size_bytes`, optional `duration_seconds`/`latitude`/`longitude`. No
  bytes field. Path-traversal guard lives in Plan 02 (`reader/media.py`).
- **`chat.py`** — `ChatKind = Literal["direct","group","broadcast","community","other"]`,
  `class Chat`: `chat_id`, `kind`, `jid`, `display_name`, `last_activity_ts?`,
  `last_message_preview?`, `unread_count`, `is_archived`, `is_hidden`,
  `coverage`. Per-chat `Coverage` included in the model so `list_chats`
  surfaces it without a follow-up call.
- **`message.py`** — `MessageKind = Literal[14 kinds incl. "other"]`,
  `class Message`: `message_id` (ZSTANZAID), `chat_id` (ZCHATSESSION),
  `sender_jid`, `timestamp` (Unix int — Cocoa converted), `body?`,
  `kind`, `is_outgoing`, `is_starred`, `quoted_message_id?`, `media?`.
  **B2 lock honored — no public `z_sort` field.**
- **`group.py`** — `class GroupMember` (`jid`, `display_name`, `is_admin`,
  `is_active`), `class GroupInfo` (`chat_id`, `subject`, `description?`,
  `creation_ts?`, `creator_jid?`, `owner_jid?`, `members` via
  `Field(default_factory=list)`, `is_muted`).
- **`__init__.py`** — explicit `__all__` re-exports of the entire public
  surface (16 names: `AnchorKind`, `Chat`, `ChatKind`, `Contact`,
  `Coverage`, `CursorError`, `DoctorReport`, `GroupInfo`, `GroupMember`,
  `Jid`, `JidKind`, `MediaRef`, `Message`, `MessageKind`,
  `PermissionBucket`, `PermissionState`, `PermissionStatus`,
  `decode_cursor`, `encode_cursor`). Phase 0's `models.doctor` module
  preserved unchanged.

### Time helpers (`src/whatsapp_mcp/time.py`)

- `COCOA_EPOCH_OFFSET: int = 978_307_200`
- `def cocoa_to_unix(cocoa_seconds: float) -> int`
- `def unix_to_cocoa(unix_seconds: int) -> float`

Module placed at the package root (NOT under `reader/`) because both
`reader/` (row projection) and `tools/` (e.g. `extract_recent` "last N
hours") need it. Module name `time` does not shadow stdlib `time`
because it is only ever imported as `whatsapp_mcp.time` and contains
no `import time` calls of its own.

Live anchor verification (matches RESEARCH §"Cocoa Epoch ↔ Unix
Conversion"): `cocoa_to_unix(800_352_916) == 1_778_660_116` =
`2026-05-13 08:15:16 UTC`.

### Path resolvers (`src/whatsapp_mcp/paths.py` — expanded)

- `resolve_chatstorage_path()` — preserved byte-for-byte from Phase 0.
- `resolve_lid_path()` — sibling `LID.sqlite` (P11 JID/LID dedup).
- `resolve_contactsv2_path()` — sibling `ContactsV2.sqlite` (READ-05
  search_contacts).
- `resolve_media_root()` — root of `~/.../Message/` tree (DATA-03 MediaRef
  resolution + Plan 02's path-traversal guard, T-01-04).

All four resolvers are pure: no I/O, no syscalls beyond
`os.path.expanduser`.

## Acceptance Criteria — All Met

- [x] `from whatsapp_mcp.models import Chat, Message, Contact, Jid, JidKind, GroupInfo, GroupMember, MediaRef, Coverage, AnchorKind, encode_cursor, decode_cursor, CursorError, DoctorReport, PermissionStatus, PermissionState, PermissionBucket, ChatKind, MessageKind` works (verified inline).
- [x] `from whatsapp_mcp.time import cocoa_to_unix, unix_to_cocoa, COCOA_EPOCH_OFFSET` works; `cocoa_to_unix(0) == 978_307_200`; round-trip cocoa_to_unix(unix_to_cocoa(N)) == N for any int N.
- [x] `from whatsapp_mcp.paths import resolve_chatstorage_path, resolve_lid_path, resolve_contactsv2_path, resolve_media_root` works; all return absolute paths (no leading `~`).
- [x] Cursor round-trip: `decode_cursor(encode_cursor(42, 1.5e18, "z_sort")) == (42, 1.5e18, "z_sort")` AND `decode_cursor(encode_cursor(7, 1_747_140_000.0, "cocoa_ts")) == (7, 1_747_140_000.0, "cocoa_ts")`. Both `z_sort` and `cocoa_ts` anchor_kind values supported.
- [x] `decode_cursor` raises `CursorError` (NOT raw ValueError) on garbage input, bad base64, missing keys, extra keys, wrong types, and anchor_kind values outside the Literal set.
- [x] `Jid(kind="bogus", raw="x")` raises `ValidationError` (Literal enforced).
- [x] `Chat(..., kind="banana", ...)` raises `ValidationError` (Literal enforced).
- [x] `Message` model carries no public `z_sort` field (B2 lock).
- [x] All 28 Phase 0 tests still pass (REL-05 isolation, stdout-purity, exception shape, doctor probes — all green).
- [x] `uv run ruff check src tests` + `uv run ruff format --check` + `uv run mypy --strict` all clean across the entire project (39 source files).

## Source Assertions

| Pattern | File | Match Count |
|---|---|---|
| `class Coverage(BaseModel)` | `models/coverage.py` | 1 |
| `class CursorError(ValueError)` | `models/cursor.py` | 1 |
| `AnchorKind = Literal[` | `models/cursor.py` | 1 |
| `JidKind = Literal[` | `models/contact.py` | 1 |
| `class MediaRef(BaseModel)` | `models/media.py` | 1 |
| `ChatKind = Literal[` | `models/chat.py` | 1 |
| `MessageKind = Literal[` | `models/message.py` | 1 |
| `class GroupInfo(BaseModel)` | `models/group.py` | 1 |
| `__all__ =` | `models/__init__.py` | 1 |
| `^COCOA_EPOCH_OFFSET\s*:\s*int\s*=\s*978_307_200` | `time.py` | 1 |
| `^def cocoa_to_unix\(` | `time.py` | 1 |
| `^def unix_to_cocoa\(` | `time.py` | 1 |
| `^def resolve_chatstorage_path\(` | `paths.py` | 1 |
| `^def resolve_lid_path\(` | `paths.py` | 1 |
| `^def resolve_contactsv2_path\(` | `paths.py` | 1 |
| `^def resolve_media_root\(` | `paths.py` | 1 |

## Commits

| Task | Hash | Description |
|---|---|---|
| 1 | `497a5f5` | `feat(01-01): add Coverage, Cursor, Jid/Contact, MediaRef leaf models` |
| 2 | `c1c7742` | `feat(01-01): add Chat, Message, GroupInfo models + models/__init__ re-exports` |
| 3 | `4610ce2` | `feat(01-01): add Cocoa<->Unix time helpers and sibling-DB path resolvers` |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused `# type: ignore[assignment]` comment in `cursor.py`**
- **Found during:** Task 1 mypy --strict pass
- **Issue:** mypy --strict's `warn_unused_ignores = true` flagged the
  `# type: ignore[assignment]` on the `kind: AnchorKind = anchor_kind`
  line because the preceding `anchor_kind not in _VALID_ANCHOR_KINDS`
  guard (a frozenset membership check) is sufficient narrowing for mypy
  to accept the assignment without a cast.
- **Fix:** removed the `# type: ignore` comment, kept the comment text
  describing the runtime witness.
- **Files modified:** `src/whatsapp_mcp/models/cursor.py`
- **Outcome:** mypy --strict green; runtime behavior unchanged
  (frozenset check still raises `CursorError` on invalid kinds).

### Out-of-band Notes

- **Executor prompt expected-value typo (informational only, no fix
  required):** the executor context's success criteria asserted
  `cocoa_to_unix(800_352_916) == 1747124116`, but the live RESEARCH
  anchor (`SELECT MAX(ZMESSAGEDATE)... -> 800_352_916 -> 2026-05-13
  08:15:16`) plus the canonical `COCOA_EPOCH_OFFSET = 978_307_200`
  gives `1_778_660_116`, which is `2026-05-13 08:15:16 UTC` (matches
  RESEARCH verbatim). The implementation matches RESEARCH; the
  executor context's literal value was a copy-paste typo. No code
  change needed — verified the conversion against the RESEARCH-claimed
  human-readable timestamp instead of the typo'd integer.

## Authentication Gates

None.

## Known Stubs

None. Plan 01-01 ships pure data shapes; behavior arrives in Plans 02-04.

`GroupInfo.description` defaults to `None` and `GroupInfo.is_muted`
defaults to `False` — these are NOT stubs but documented "absent until
Plan 02 row-level inspection finds them" defaults (RESEARCH §"Open
Questions Q2 / Q3"). The reader will continue to populate them this way
unless / until Plan 02 locates a corresponding column in the live
Catalyst schema; if absent in v1.0, the surface stays as-is.

## Threat Flags

None — Plan 01-01 introduces no new attack surface beyond what the
plan's `<threat_model>` already covers (T-01-01 cursor tampering, T-01-02
JID surfacing, T-01-03 Literal enforcement, T-01-04 deferred path
traversal, T-01-05 `__all__` hygiene).

## Self-Check: PASSED

All eight new model files + `time.py` + the modified `paths.py` exist on
disk; all three task commits are present in `git log`; full lint / format
/ type-check / Phase 0 test gates green.

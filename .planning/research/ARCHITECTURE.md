# Architecture Research

**Domain:** Local MCP server bridging an LLM client to WhatsApp Desktop on macOS (read = local SQLite, write = UI automation)
**Researched:** 2026-05-13
**Confidence:** HIGH for DB layout (verified directly on this machine against WhatsApp Desktop 26.16.74), HIGH for send-path (no scripting dictionary exists, UI automation is the only path), MEDIUM for FTS / LID nuances (verified schema, less verified semantics).

> **Note:** All schema, paths, and behaviors below were verified by direct inspection of `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/` on macOS 26.4 with WhatsApp Desktop 26.16.74 installed and running, on 2026-05-13. WhatsApp Desktop schema can change between releases; isolate the schema knowledge in a single module (see Pattern 3 below).

---

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                       MCP Client (Claude Desktop / Code)             │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │  JSON-RPC over stdio
┌──────────────────────────────────▼───────────────────────────────────┐
│                       whatsapp-mcp server (this project)             │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  (1) MCP Boundary                                              │  │
│  │      - tool registration, JSON-Schema in/out                   │  │
│  │      - stdio transport, lifecycle, error → MCP error mapping   │  │
│  └─────────────────┬──────────────────────────────┬───────────────┘  │
│                    │                              │                  │
│  ┌─────────────────▼─────────────────┐  ┌─────────▼───────────────┐  │
│  │  (5) Tool Layer                   │  │  (6) CLI (debug-only)   │  │
│  │      list_chats / read_chat /     │  │      same operations,   │  │
│  │      extract_recent / search_*    │  │      pretty-printed     │  │
│  │      / send_message               │  │                         │  │
│  └─────┬───────────────────┬─────────┘  └─────────┬───────────────┘  │
│        │                   │                      │                  │
│  ┌─────▼─────────────┐ ┌───▼─────────────┐ ┌──────▼───────────────┐  │
│  │  (2) DB Reader    │ │  (3) Sender     │ │  (4) Models          │  │
│  │   - path resolver │ │   - URL-scheme  │ │   - Chat / Message / │  │
│  │   - schema adapter│ │     deeplink    │ │     Contact / Group  │  │
│  │   - query builder │ │   - System      │ │     dataclasses      │  │
│  │   - WAL-safe RO   │ │     Events      │ │   - JID parsing      │  │
│  │     connection    │ │     keystroke   │ │   - Cocoa-epoch ts   │  │
│  │   - FTS adapter   │ │   - verify-send │ │     converter        │  │
│  └─────┬─────────────┘ └───────┬─────────┘ └──────────────────────┘  │
└────────┼─────────────────────────┼─────────────────────────────────--┘
         │ read-only SQLite        │ AppleScript via osascript subprocess
         ▼                         ▼
┌──────────────────────────────────────────────────────────────────────┐
│ ~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/       │
│   ChatStorage.sqlite (+ .sqlite-wal, .sqlite-shm)                    │
│   ContactsV2.sqlite                                                  │
│   LID.sqlite                                                         │
│   fts/ChatSearchV5f.sqlite                                           │
│   Message/Media/                                                     │
│                                                                      │
│ /Applications/WhatsApp.app  (running, target of UI automation)       │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| # | Component | Owns | Does NOT own |
|---|-----------|------|--------------|
| 1 | **MCP Boundary** (`server.py`) | Tool registry, JSON-Schema validation, stdio transport, MCP error mapping, request/response logging | Business logic, SQL, AppleScript |
| 2 | **DB Reader** (`reader/`) | DB path discovery, opening read-only WAL connection, schema-versioned queries, FTS query, mapping rows → Models | What the LLM sees, send mechanics |
| 3 | **Sender** (`sender/`) | Opening chats via `whatsapp://` URL scheme, AppleScript/UI-automation send, send verification, retry on UI race | Reading history, model shape |
| 4 | **Models** (`models.py`) | Typed dataclasses (`Chat`, `Message`, `Contact`, `GroupInfo`, `MediaRef`), JID parser/normalizer, Cocoa-epoch ↔ Unix conversion, JSON serialization | DB queries, MCP framing |
| 5 | **Tool Layer** (`tools/`) | Mapping each MCP tool name → reader/sender call sequence, parameter coercion, output trimming/pagination | Transport, schema details |
| 6 | **CLI** (`cli.py`) | `whatsapp-mcp-cli list-chats / read / send` for local debugging without an MCP client | Anything runtime-MCP-only |

**Boundary rule:** MCP Boundary (1) and CLI (6) both call only into Tool Layer (5). Tool Layer calls only into Reader (2), Sender (3), and Models (4). Reader and Sender never call each other and never import Tool Layer or MCP Boundary code.

This isolates the two highest-volatility surfaces:
- **DB Reader** absorbs every WhatsApp schema change (rename of `ZSESSIONTYPE` values, addition of `LID` join requirements, new tables).
- **Sender** absorbs every UI change (search bar location, keystroke that focuses the message input).

A future schema bump = update Reader. A future UI redesign = update Sender. The Tool Layer JSON contracts seen by the LLM stay stable.

---

## Verified Filesystem Layout (macOS, 2026-05)

```
~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/
├── ChatStorage.sqlite             ← messages + chat sessions + groups (89 MB on test machine)
├── ChatStorage.sqlite-wal         ← active WAL log (must be readable!)
├── ChatStorage.sqlite-shm         ← shared-memory index for WAL
├── ContactsV2.sqlite              ← address book contacts (ZWAADDRESSBOOKCONTACT)
├── LID.sqlite                     ← phone↔LID mapping (ZWAPHONENUMBERLIDPAIR)
├── CallHistory.sqlite             ← call log (out of scope v1)
├── Labels.sqlite                  ← user-defined chat labels
├── Sticker.sqlite, emoji.sqlite   ← assets, ignore
├── BackedUpKeyValue.sqlite        ← settings cache, ignore
├── LocalKeyValue.sqlite           ← settings cache, ignore
├── fts/
│   └── ChatSearchV5f.sqlite       ← FTS4 virtual-table index (`docs` table)
├── Message/
│   ├── Media/<chatJid>/<x>/<y>/<uuid>.{jpg,mp4,...}  ← media files (relative paths in DB)
│   └── Profile/                   ← profile pictures
└── Media/                         ← legacy media area
```

**Container facts** (verified):
- The app is sandboxed Mac-App-Store build (`com.apple.security.app-sandbox = true`), team `57T9237FN3`, bundle id `net.whatsapp.WhatsApp`.
- The data lives in the **shared group container**, not the per-app container — this is what makes it reachable from a non-WhatsApp process.
- A non-WhatsApp process needs **Full Disk Access** (TCC) to read the group container — without it, opening the file returns `unable to open database file` (we hit exactly that error trying to read a sub-folder file before resolving the right path).

**Critical:** Reader must always operate on `ChatStorage.sqlite` *together with* its `-wal` and `-shm` siblings — copying only the main file produces lost or corrupted data per [SQLite docs](https://sqlite.org/wal.html).

---

## Verified ChatStorage.sqlite Schema (essentials)

WhatsApp Desktop on macOS reuses the iOS Core Data model — every entity gets a `Z` prefix and Core-Data bookkeeping columns (`Z_PK` PK, `Z_ENT` entity-id, `Z_OPT` optimistic-lock counter). All inter-table FKs are integer `Z_PK` references stored in columns named after the relationship target (e.g. `ZCHATSESSION` on `ZWAMESSAGE` → `ZWACHATSESSION.Z_PK`).

### `ZWACHATSESSION` (one row per chat: 1:1, group, broadcast)

| Column | Type | Meaning |
|---|---|---|
| `Z_PK` | INT | Chat session PK — referenced everywhere as "chat id" |
| `ZSESSIONTYPE` | INT | **Verified distribution on this machine:** `0` = 1:1 chat (`@s.whatsapp.net`), `1` = group (`@g.us`), `3` = broadcast/status, `4` = community announcement |
| `ZCONTACTJID` | TEXT | The "remote JID" — `<phone>@s.whatsapp.net`, `<groupid>@g.us`, `<lid>@lid`, `0@status` |
| `ZPARTNERNAME` | TEXT | Display name (group name for groups, contact name for 1:1) |
| `ZLASTMESSAGEDATE` | REAL | Cocoa epoch (seconds since 2001-01-01) |
| `ZLASTMESSAGETEXT` | TEXT | Last message preview (sometimes a base64 protobuf for system events) |
| `ZUNREADCOUNT` | INT | Unread badge |
| `ZARCHIVED` | INT | Archived (0/1) |
| `ZHIDDEN` | INT | Hidden (0/1) |
| `ZREMOVED` | INT | Tombstone — **filter `WHERE ZREMOVED = 0`** to hide deleted chats |
| `ZGROUPINFO` | INT | FK → `ZWAGROUPINFO.Z_PK` (only set for group sessions) |
| `ZLASTMESSAGE` | INT | FK → `ZWAMESSAGE.Z_PK` |

Useful indexes already present: `Z_WAChatSession_byContactJIDIndex`, `Z_WAChatSession_byLastMessageDateIndex`.

### `ZWAMESSAGE` (one row per message)

| Column | Type | Meaning |
|---|---|---|
| `Z_PK` | INT | Message PK |
| `ZCHATSESSION` | INT | FK → `ZWACHATSESSION.Z_PK` |
| `ZGROUPMEMBER` | INT | FK → `ZWAGROUPMEMBER.Z_PK` (only in groups, identifies sender) |
| `ZMESSAGETYPE` | INT | **Verified top values:** `0` = text, `1` = image, `2` = video/voice, `3` = audio, `6` = system event (group rename, member add, etc.), `7` = location, `8` = contact card, `10` = sticker, `11` = call, `14` = revoked, `15` = ephemeral, `59` = poll, `66` = reaction. Distribution skewed: 67k text, 6.9k image, 2.5k system. |
| `ZGROUPEVENTTYPE` | INT | Subtype when `ZMESSAGETYPE=6` (member added/removed/promoted, name changed) |
| `ZISFROMME` | INT | `0` = received, `1` = sent by you |
| `ZMESSAGESTATUS` | INT | Delivery state: pending/sent/delivered/read |
| `ZSORT` | INT | **Use this, not `ZMESSAGEDATE`, for in-chat ordering** — there's a dedicated compound index `(ZCHATSESSION, ZSORT)` |
| `ZMESSAGEDATE` | REAL | Cocoa epoch — convert with `datetime(ZMESSAGEDATE + 978307200, 'unixepoch')` |
| `ZSENTDATE` | REAL | Cocoa epoch (sent vs. received timing differs for queued messages) |
| `ZFROMJID` | TEXT | Sender JID (only populated for received messages — sent messages have `ZTOJID`) |
| `ZTOJID` | TEXT | Recipient JID (populated for sent messages) |
| `ZSTANZAID` | TEXT | WhatsApp protocol message id — globally unique, useful as stable "message_id" in MCP responses |
| `ZTEXT` | TEXT | Message body (NULL for media-only and tombstoned messages) |
| `ZPUSHNAME` | TEXT | Sender's self-set display name at message time |
| `ZFLAGS` | INT | **Bitfield** — `0x05000000` and `0x05008000` correlate with deleted/revoked-for-me messages on this machine; `0x01000000` is the common "normal" baseline. Treat as opaque flags; do not assume bit meanings without testing on a fresh machine. |
| `ZMEDIAITEM` | INT | FK → `ZWAMEDIAITEM.Z_PK` when message has attachment |
| `ZPARENTMESSAGE` | INT | FK → another `ZWAMESSAGE.Z_PK` for replies |
| `ZSTARRED` | INT | Starred (0/1) |

Indexes: compound index `Z_WAMessage_compoundIndex (ZCHATSESSION, ZSORT)` is the killer one — every chat-window read should hit it. `Z_WAMessage_byStanzaIDIndex` for message-id lookup. `Z_WAMessage_byMessageDateIndex` for global recency queries.

### `ZWAGROUPINFO`

| Column | Meaning |
|---|---|
| `ZCHATSESSION` | FK → `ZWACHATSESSION.Z_PK` |
| `ZCREATIONDATE` | Group creation (Cocoa epoch) |
| `ZCREATORJID`, `ZOWNERJID`, `ZSUBJECTOWNERJID` | Provenance JIDs |
| `ZPICTUREPATH` | Local thumbnail path |

### `ZWAGROUPMEMBER`

| Column | Meaning |
|---|---|
| `ZCHATSESSION` | FK → `ZWACHATSESSION.Z_PK` |
| `ZMEMBERJID` | Phone or LID JID of member |
| `ZCONTACTNAME`, `ZFIRSTNAME` | Cached display names |
| `ZISADMIN`, `ZISACTIVE` | Role flags |

### `ZWAMEDIAITEM`

| Column | Meaning |
|---|---|
| `ZMESSAGE` | FK → `ZWAMESSAGE.Z_PK` |
| `ZMEDIALOCALPATH` | **Relative path** like `Media/<chatJid>/<x>/<y>/<uuid>.jpg` — resolve against `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/Message/` |
| `ZTHUMBNAILLOCALPATH` | Same convention for thumbnail |
| `ZFILESIZE`, `ZMOVIEDURATION`, `ZASPECTRATIO` | Media metadata |
| `ZTITLE`, `ZAUTHORNAME` | For shared-link/document messages |
| `ZLATITUDE`, `ZLONGITUDE` | For location messages |
| `ZMEDIAKEY`, `ZMETADATA` | **BLOB, encrypted/protobuf** — leave alone unless we want to decrypt media (not v1) |

### `ZWAMESSAGEINFO`

| Column | Meaning |
|---|---|
| `ZMESSAGE` | FK → `ZWAMESSAGE.Z_PK` |
| `ZRECEIPTINFO` | **BLOB protobuf** — per-recipient delivery/read receipts. Defer parsing to v2; surface as opaque. |

### `ZWABLACKLISTITEM`

Trivial: `ZJID` of blocked contacts. Useful so we can flag/exclude in `list_chats`.

### `ContactsV2.sqlite` → `ZWAADDRESSBOOKCONTACT`

This is the address-book overlay (different DB so it can be sync'd from Apple Contacts independently). Key columns: `ZIDENTIFIER`, `ZFULLNAME`, `ZGIVENNAME`, `ZLASTNAME`, `ZPHONENUMBER`, `ZWHATSAPPID` (the JID), `ZLID`, `ZLIDHASH`, `ZPNHASH` (privacy-preserving hashes).

### `LID.sqlite` → `ZWAPHONENUMBERLIDPAIR`

Maps `ZPHONENUMBER` ↔ `ZLID`. **This is the only authoritative phone↔LID mapping on the local device.** Used to resolve `<id>@lid` JIDs (which appear increasingly in 2025-2026 group threads, see Pitfalls) back to phone numbers when permitted.

### `fts/ChatSearchV5f.sqlite`

```sql
CREATE VIRTUAL TABLE docs USING fts4(text, contact, chat, documentType, tokenize=wa_tokenizer, ...);
```

Custom `wa_tokenizer` — **we cannot use this index from our process** because the tokenizer module is loaded only inside WhatsApp.app. Two options:
1. Skip FTS, do `LIKE %term%` over `ZWAMESSAGE.ZTEXT` filtered by `ZCHATSESSION` window (slow but works for v1).
2. Build our own SQLite FTS5 shadow index on first run, refresh incrementally on `ZMESSAGEDATE > last_seen`.

Recommendation: ship v1 with `LIKE` (good enough up to ~10k messages per chat) and add shadow FTS5 in a follow-up phase.

---

## Schema Risks (must-handle)

| Risk | Reality | Mitigation |
|---|---|---|
| **Encrypted columns** | `ZMEDIAKEY` and `ZMETADATA` on `ZWAMEDIAITEM`, `ZRECEIPTINFO` on `ZWAMESSAGEINFO` are encrypted/protobuf BLOBs | Don't read them. Surface media via `ZMEDIALOCALPATH` only. |
| **JID format heterogeneity** | Same chat may reference participants as `<phone>@s.whatsapp.net` *or* `<id>@lid` even within one row's history | Models module owns a `Jid` type with `.kind ∈ {user, group, lid, status, broadcast}`; never compare JID strings directly |
| **`@lid` ↔ phone resolution** | LID introduced 2024-2025; in some groups admin "hide phone numbers" is on and only `@lid` is exposed even to participants | Try `LID.sqlite` lookup first, return `null` phone if unknown — don't fabricate |
| **Message ordering** | Two timestamps + a sort key. `ZMESSAGEDATE` is when WhatsApp received it, `ZSENTDATE` is when sender sent it, `ZSORT` is the canonical in-chat order | **Always sort by `ZSORT` for in-chat reads, by `ZMESSAGEDATE` for recency/time-window reads** |
| **Cocoa epoch trap** | `ZMESSAGEDATE` is seconds since `2001-01-01`, not Unix epoch. Off by 978,307,200 s | Centralize conversion in Models module; never compare raw values |
| **Deleted-message tombstones** | Message rows survive deletion: `ZTEXT IS NULL` with `ZMESSAGETYPE=1`, certain `ZFLAGS` bits set, and message type `14` (revoked) | Decision per tool: `read_chat` returns "(deleted)" placeholder; `search_messages` excludes them. Implement as a `is_tombstone(row)` predicate in Reader. |
| **Group-event noise** | `ZMESSAGETYPE=6` with `ZGROUPEVENTTYPE` are "X added Y to group" — hundreds of these clutter chats | Default `read_chat` filter: `ZMESSAGETYPE NOT IN (6,15,11)`; expose `include_system_events: bool` |
| **`ZSESSIONTYPE` semantics** | Verified `0`=1:1, `1`=group, `3`=broadcast, `4`=community-announcement on test machine — values are not formally documented and could shift across releases | Treat as enum in Models with a single mapping function; test on a second machine before release |
| **Schema rename risk** | Past Core Data migrations renamed columns (e.g., `ZWASESSION` → `ZWACHATSESSION` historically). Future renames likely. | Reader has a `schema_version` probe (read `Z_METADATA.Z_VERSION`) and a per-version query map. v1 supports one version; future versions add adapters. |
| **`-wal` checkpoint** | Reader holding the file open could prevent WhatsApp from checkpointing the WAL | Use short-lived connections per tool call (open → query → close), not a persistent connection (see Pattern 1) |

---

## Recommended Project Structure

```
whatsapp-mcp/
├── src/whatsapp_mcp/
│   ├── __init__.py
│   ├── server.py              # (1) MCP boundary — registers tools, runs stdio loop
│   ├── cli.py                 # (6) Click-based CLI mirroring the tools
│   ├── models.py              # (4) Chat/Message/Contact/GroupInfo dataclasses + Jid type
│   ├── time.py                #     Cocoa-epoch ↔ datetime helpers
│   ├── reader/                # (2) DB reader package
│   │   ├── __init__.py
│   │   ├── paths.py           #     locate ChatStorage.sqlite, ContactsV2, LID, FTS
│   │   ├── connection.py      #     `with open_ro(path) as conn:` using mode=ro URI
│   │   ├── schema_v1.py       #     SQL templates for current Core Data schema
│   │   ├── chats.py           #     list_chats / find_chat_by_name
│   │   ├── messages.py        #     read_chat / extract_recent / message rows
│   │   ├── search.py          #     LIKE-based search (v1) — FTS5 shadow later
│   │   ├── contacts.py        #     contact lookup across ChatStorage + ContactsV2
│   │   └── tombstones.py      #     is_deleted/is_system_event predicates
│   ├── sender/                # (3) Send package
│   │   ├── __init__.py
│   │   ├── deeplink.py        #     build whatsapp:// URLs, `open` subprocess
│   │   ├── osascript.py       #     `subprocess.run(["osascript","-e",...])` wrapper
│   │   ├── ui_send.py         #     activate → search → select → type → ⏎
│   │   └── verify.py          #     post-send verify by polling DB for new outgoing row
│   └── tools/                 # (5) Thin MCP tool implementations
│       ├── __init__.py
│       ├── list_chats.py
│       ├── read_chat.py
│       ├── extract_recent.py
│       ├── search_messages.py
│       ├── search_contacts.py
│       └── send_message.py
├── tests/
│   ├── fixtures/              # tiny anonymized ChatStorage.sqlite for tests
│   ├── test_models.py
│   ├── test_reader_*.py
│   └── test_sender_smoke.py   # marked @requires_whatsapp, opt-in
├── pyproject.toml
└── README.md
```

### Structure Rationale

- **`reader/` and `sender/` are sibling packages, not subpackages of `tools/`.** Tools depend on them, never the reverse. This is the boundary that makes a future schema or UI change isolated.
- **`reader/schema_vN.py` is named for the schema version.** When WhatsApp ships a breaking change, we add `schema_v2.py` and a dispatcher in `connection.py`; the Tool Layer never knows.
- **`tools/` files are 1-per-MCP-tool.** Each is small (10-40 lines): coerce inputs, call reader/sender, shape output. Easy to read, easy to add a tool.
- **`cli.py` reuses the same Tool Layer** so anything reproducible from Claude Desktop is reproducible from `whatsapp-mcp-cli`.
- **`tests/fixtures/` carries an anonymized SQLite snapshot** so reader tests run without WhatsApp installed; sender tests are opt-in.

---

## Architectural Patterns

### Pattern 1: Short-lived Read-Only WAL Connection

**What:** Open the SQLite database with `?mode=ro` URI flag, run a single query batch, close. Do not cache a persistent connection.

**When to use:** Every Reader call.

**Trade-offs:** Tiny per-call cost (~1ms to open). In return: never blocks WhatsApp's checkpointer, no stale data from a long-held read transaction, file-rotation/migration handled by the next call automatically.

**Verified empirically:** Live queries against a 89 MB `ChatStorage.sqlite` succeeded while WhatsApp Desktop was actively writing (test ran on 2026-05-13).

```python
import sqlite3
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def open_ro(db_path: Path):
    # mode=ro requires that -wal/-shm exist OR that we have write perm on the
    # directory (we do, it's our home dir). Do NOT use immutable=1 — WhatsApp
    # is actively writing, and immutable would let SQLite skip WAL recovery
    # and return stale or corrupt pages.
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    try:
        # Use deferred transaction so we read at consistent snapshot
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    finally:
        conn.close()
```

**Why not `immutable=1`:** the [SQLite WAL docs](https://sqlite.org/wal.html) make clear `immutable` tells SQLite the file *will not change*; pairing it with a live writer is a footgun. `mode=ro` is the right primitive for "I won't write but the file may change under me."

**Why not `copy-then-read`:** copying `ChatStorage.sqlite` without atomically grabbing `-wal` and `-shm` produces silently corrupt copies (also from the WAL docs). And copying 89 MB per tool call is wasteful when SQLite already supports our use case natively.

### Pattern 2: Send via UI Automation (no Scripting Bridge available)

**What:** Open a chat by URL deep-link, then send via System Events keystroke.

**When to use:** Every send.

**Verified empirically (this session):** `sdef /Applications/WhatsApp.app` returns error -192 ("not scriptable"). WhatsApp.app exposes **no AppleScript dictionary**, so Scripting Bridge / native AppleScript objects are unavailable. UI automation is the only path. The `whatsapp:`, `whatsapp-consumer:`, `upi:`, `fb306069495113:` URL schemes are registered (verified in `Info.plist`).

**Reliable selector recipe:**

```osascript
-- 1. Open the chat. URL-scheme deep-link lands on the chat,
--    skipping the search-and-pick UI race entirely when we know the JID.
do shell script "open 'whatsapp://send?phone=" & quoted_phone & "&text=" & url_encoded_text & "'"
delay 0.4

-- 2. Activate WhatsApp and target its (only) main window.
tell application "WhatsApp" to activate
delay 0.2

-- 3. Press Return to send the pre-filled text.
tell application "System Events" to tell process "WhatsApp"
    keystroke return
end tell
```

**Why this is more reliable than search-and-click** (which is what `gfb-47/whatsapp-mcp-server` does):
- No locale dependence (search box label is localized; deep-link is not).
- No UI-tree walk (the AXGroup/AXButton tree we observed has no AXTextField with a stable role — search-bar focus depends on screen position, which breaks if the user resized the window).
- The window title contains an invisible LRM character (we verified: returned name was `‎WhatsApp` not `WhatsApp`) — anything that string-compares window names will silently fail. Deep-link bypasses the issue.

**Trade-offs:** The deep-link path requires **a phone-number JID** (or, per docs, an `abid` Apple-Address-Book id). For group sends, deep-link does not currently support group JIDs from a non-WhatsApp process. Group sends therefore need a fallback: focus search field via Cmd-F (or the documented Cmd-N "new chat"), type the group name, press Return to open the top hit, then `keystroke text` and `keystroke return`. This fallback is fragile — flag it as the failure mode most likely to break on a WhatsApp UI redesign.

**Why not Hammerspoon:** an extra runtime install on the user's machine for a problem that `osascript` solves. Reserve as a future option if Apple ever deprecates AXKeystroke.

**Send verification:** After issuing the keystroke, poll `ZWAMESSAGE` for a new row matching `(ZCHATSESSION=<id>, ZISFROMME=1, ZTEXT=<sent text>, ZMESSAGEDATE > t0)` for up to N seconds. Return the new `ZSTANZAID` to the LLM as proof of delivery; raise an MCP tool error if it doesn't appear.

### Pattern 3: Schema-Versioned Adapter

**What:** Reader queries are templated per schema version, dispatched off `Z_METADATA.Z_VERSION`.

**When to use:** Always, even in v1 with one supported version.

**Why:** Pays off the first time WhatsApp ships a schema migration. Bug reports become "this schema version isn't supported yet, file is at version X" instead of "the server crashes."

```python
# reader/connection.py
SCHEMA_HANDLERS = {
    # Z_VERSION → module
    range(60, 80): schema_v1,   # current observed range; broaden as we test
}

def get_handler(conn):
    v = conn.execute("SELECT Z_VERSION FROM Z_METADATA").fetchone()[0]
    for r, mod in SCHEMA_HANDLERS.items():
        if v in r:
            return mod
    raise UnsupportedSchemaError(v)
```

### Pattern 4: Tool = Pure Function over (Reader, Sender, Inputs)

**What:** Each MCP tool file exports one async function; it does no I/O of its own beyond calling Reader/Sender. Output is always a `dict` (or list of dicts) ready to be JSON-serialized by the MCP boundary.

**Trade-offs:** Tiny indirection; massive testability win — every tool can be unit-tested with a fixture DB and a mock Sender.

```python
# tools/extract_recent.py
async def extract_recent(*, chat: str, hours: int) -> dict:
    chat_row = reader.chats.find_by_name_or_jid(chat)
    if not chat_row:
        raise ToolError(f"No chat named {chat!r}")
    cutoff = datetime.now(tz=UTC) - timedelta(hours=hours)
    msgs = reader.messages.since(chat_row.id, cutoff)
    return {"chat": chat_row.to_json(), "messages": [m.to_json() for m in msgs]}
```

---

## Data Flow

### Read flow (e.g. `read_chat`)

```
LLM client ─JSON-RPC──▶ MCP Boundary
                            │
                            ▼  validate against tool schema, dispatch
                       Tool Layer (read_chat.py)
                            │
                            ▼  reader.chats.find_by_name() / reader.messages.window()
                       Reader (short-lived RO connection)
                            │
                            ▼  raw sqlite3.Row
                       Models.from_row()  →  Message dataclasses
                            │
                            ▼  [m.to_json() for m in messages]
                       Tool Layer returns dict
                            │
                            ▼  serialize, frame, write
                       MCP Boundary  ─JSON-RPC─▶ LLM client
```

Per-call duration target: **< 200 ms** for a 200-message window from a 100k-message DB (the `(ZCHATSESSION, ZSORT)` index makes this trivially fast).

### Send flow (e.g. `send_message`)

```
LLM client ─JSON-RPC──▶ MCP Boundary
                            │
                            ▼
                       Tool Layer (send_message.py)
                            │
                            ▼  reader.chats.find_by_name() to get JID
                       Reader (one-shot RO query)
                            │
                            ▼  Sender.send(jid=..., text=...)
                       Sender
                            ├─ deeplink.open("whatsapp://send?phone=...&text=...")
                            ├─ osascript activate + keystroke return
                            └─ verify.poll_db_for_new_outgoing(timeout=5s)
                            │
                            ▼  StanzaID of new row
                       Tool Layer returns {"sent": true, "message_id": "..."}
                            │
                            ▼
                       MCP Boundary  ─JSON-RPC─▶ LLM client
```

Per-call duration: 1-3 s expected (mostly waiting for WhatsApp to render and confirm).

### State management

There is **no in-memory state that needs syncing.** Each tool call is stateless; the source of truth is always the live SQLite. No background watcher, no caches in v1. (A shadow FTS5 index would be the first stateful component if added later — keep it in `reader/search/` and rebuild lazily.)

---

## Suggested Build Order

The dependency graph dictates a natural order. Each row delivers something testable.

| # | Phase | Delivers | Unblocks |
|---|---|---|---|
| 1 | **Models + paths + RO connection** (`models.py`, `time.py`, `reader/paths.py`, `reader/connection.py`) | A library that opens the DB and gives you a `Chat` dataclass | Everything else |
| 2 | **Reader: chats + messages + tombstones** (`reader/chats.py`, `reader/messages.py`, `reader/tombstones.py`) | `python -c "from reader import …; print(list_chats())"` works on real WhatsApp DB | All read tools, send (needs JID lookup) |
| 3 | **CLI scaffold** (`cli.py`) wiring `list-chats`, `read-chat`, `extract-recent` | End-to-end debug loop without MCP — fastest feedback | Manual validation, dogfooding |
| 4 | **Reader: search + contacts** (`reader/search.py`, `reader/contacts.py`) | `search-messages`, `search-contacts` on CLI | Same tools in MCP |
| 5 | **MCP Boundary + read tools** (`server.py`, `tools/list_chats.py`, `tools/read_chat.py`, `tools/extract_recent.py`, `tools/search_messages.py`, `tools/search_contacts.py`) | Server registers, Claude Desktop can list+read+search chats | Read-only beta usable end-to-end |
| 6 | **Sender: deeplink path** (`sender/deeplink.py`, `sender/osascript.py`, `sender/ui_send.py`) | `cli send --to <phone> --text ...` for 1:1 chats | `tools/send_message.py` |
| 7 | **Sender: group fallback (search-and-select)** | Group sends work, with documented brittleness | Feature-complete v1 |
| 8 | **Sender: verify** (`sender/verify.py`) | Returns stanza-id; raises on no-confirmation | Reliable LLM agent loops |
| 9 | **MCP send tool** (`tools/send_message.py`) | `send_message` available in Claude Desktop | v1 ship |

**Critical path:** 1 → 2 → 5 yields a useful read-only MCP server. Send is independent and can be developed in parallel after step 2 (it depends only on Reader for JID lookup, which step 2 delivers).

**Risk-isolating principle in this ordering:** the most stable layers (Models, Reader, MCP Boundary) ship first; the most fragile (Sender UI automation, especially group sends) is last so it can be patched without disturbing read paths.

---

## Anti-Patterns

### Anti-Pattern 1: Holding a long-lived `sqlite3.Connection`

**What people do:** Open the DB once at server startup, keep the connection for the process lifetime.
**Why it's wrong:** Blocks WhatsApp's WAL checkpointer, accumulates stale read snapshot, breaks if WhatsApp does an in-place schema migration on update.
**Do this instead:** Per-call `with open_ro(path) as conn:` (Pattern 1).

### Anti-Pattern 2: Treating `ZMESSAGEDATE` as Unix epoch

**What people do:** `datetime.fromtimestamp(row["ZMESSAGEDATE"])` → message dated 1970-something.
**Why it's wrong:** It's seconds since 2001-01-01 (Cocoa epoch), off by 978,307,200.
**Do this instead:** Single helper in `models/time.py`: `cocoa_to_dt(s) -> datetime`.

### Anti-Pattern 3: Comparing JIDs as strings

**What people do:** `if msg.from_jid == contact.phone + "@s.whatsapp.net":`
**Why it's wrong:** Same person can appear as `<phone>@s.whatsapp.net` in 1:1 and `<lid>@lid` in groups; comparison silently fails. Also `0@status` is special.
**Do this instead:** `Jid` dataclass with `kind` enum and `Jid.equals(other)` that resolves via `LID.sqlite` when needed.

### Anti-Pattern 4: Search-and-click as the primary send path

**What people do:** Activate WhatsApp, focus the search bar, type contact name, press Down then Enter, type message, press Enter.
**Why it's wrong:** Localized search-bar label, contact-list reordering by recent activity, fuzzy-match picking the wrong "John", hidden invisible LRM in window title. Many failure modes, all silent.
**Do this instead:** `whatsapp://send?phone=...&text=...` deep-link as the primary path; search-and-click only as a fallback for groups (and document the fragility).

### Anti-Pattern 5: Reading `ZWAMESSAGEINFO.ZRECEIPTINFO` or `ZWAMEDIAITEM.ZMETADATA`

**What people do:** Try to parse the BLOB to extract per-recipient read receipts or media metadata.
**Why it's wrong:** Encrypted/protobuf BLOBs whose schema WhatsApp can change without notice. High effort, low value, ratchets fragility for every release.
**Do this instead:** Surface these as `null` / "not parsed" in v1. Defer to v2 if there's user demand and only via reverse-engineered protobuf (.proto) loaded as data, not code.

### Anti-Pattern 6: One module owning both DB and AppleScript

**What people do:** `whatsapp.py` with `def get_messages` and `def send_message` next to each other.
**Why it's wrong:** Couples two volatility surfaces (schema, UI) that change for completely different reasons. A WhatsApp UI redesign forces you to re-read the DB code; a schema bump forces you to re-read the AppleScript. Mental overhead grows multiplicatively.
**Do this instead:** Hard wall between `reader/` and `sender/`; they don't import each other.

---

## Integration Points

### External Services

| Service | Integration | Notes |
|---|---|---|
| WhatsApp Desktop (running) | `open` URL scheme + `osascript` keystrokes | Must already be authenticated; we do not log in |
| macOS TCC (Transparency, Consent, Control) | OS-level prompt | Server process needs **Full Disk Access** (DB read) and **Accessibility / Automation** (send). First-run docs must walk user through System Settings → Privacy & Security |
| Apple Contacts | Indirect, via `ContactsV2.sqlite` | WhatsApp imports — we don't talk to Contacts.app directly |

### Internal Boundaries

| Boundary | Communication | Rule |
|---|---|---|
| MCP Boundary ↔ Tool Layer | Direct function call | Boundary does no business logic |
| CLI ↔ Tool Layer | Direct function call | CLI mirrors MCP tool signatures |
| Tool Layer ↔ Reader | Direct function call returning Models | Tool never writes raw SQL |
| Tool Layer ↔ Sender | Direct function call returning send result | Tool never writes raw AppleScript |
| Reader ↔ Sender | **None** | No imports between them, ever |
| Reader ↔ Models | Reader produces Models, never vice versa | Models has no DB awareness |

---

## Scaling Considerations

This is a single-user local tool, so "scaling" means "DB size on this Mac" not "users."

| DB size on disk | Approach |
|---|---|
| 0-200 MB (most users) | Default queries with index hits return in < 50 ms, no special handling |
| 200 MB - 2 GB (heavy users, multi-year history) | Same, plus enforce default `limit` on `read_chat` (e.g. 200), require `since`/`until` for `extract_recent` |
| 2 GB+ (rare) | Add the FTS5 shadow index for search; otherwise unchanged |

**First bottleneck:** unbounded `read_chat` returning 50,000 messages — fix by capping default limit at 200, exposing pagination cursor on `ZSORT`.

**Second bottleneck:** `LIKE` search across millions of messages — fix by building FTS5 shadow index (deferred to a follow-up phase per build order).

---

## Sources

- [WhatsApp Forensic Artifacts — Group-IB](https://www.group-ib.com/blog/whatsapp-forensic-artifacts/) — confirms `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared` location and Core-Data schema lineage.
- [kacos2000/queries — WhatsApp_Chatstorage_sqlite.sql](https://github.com/kacos2000/queries/blob/master/WhatsApp_Chatstorage_sqlite.sql) — query template using `ZWAMESSAGE`, `ZWACHATSESSION`, `ZWAMEDIAITEM`, `ZWAMESSAGEINFO` joins; corroborates column names.
- [steipete/wacrawl](https://github.com/steipete/wacrawl) — WhatsApp Desktop archeology with encrypted-receipts parsing; reference for what *not* to attempt in v1.
- [SQLite WAL documentation](https://sqlite.org/wal.html) — readers don't block writers; reader needs `-wal`/`-shm` access; WAL must accompany DB on copy.
- [WhatsApp URL scheme reference — fvdm.com](https://fvdm.com/code/note-whatsapp-url-scheme) and [MacStories tutorial](https://www.macstories.net/tutorials/use-whatsapps-url-scheme-with-drafts-launch-center-pro-or-a-bookmarklet/) — `whatsapp://send?phone=...&text=...` and `?abid=...` parameters.
- [WhatsApp LID overview — whapi.cloud help](https://support.whapi.cloud/help-desk/faq/whatsapp-lid-lid) and [Baileys v7 LID migration notes](https://baileys.wiki/docs/migration/to-v7.0.0/) — LID is account-scoped, opaque to outsiders, increasing in 2025-2026 deployments.
- [gfb-47/whatsapp-mcp-server](https://github.com/gfb-47/whatsapp-mcp-server) — existing Node MCP using `osascript`-driven search-and-click; we improve on its send path with deep-links.
- [victor-torres/whatsapp-applescript](https://github.com/victor-torres/whatsapp-applescript) — older AppleScript reference (drives Chrome WhatsApp Web tab, not Desktop — kept for prior-art context).
- **Direct verification on this machine** (2026-05-13, WhatsApp Desktop 26.16.74, macOS 26.4): file paths, schema, journal mode (`wal`), `sdef` returning -192 (no scripting dictionary), URL schemes registered, live RO query during active write succeeded, `ZSESSIONTYPE` distribution, `ZMESSAGETYPE` distribution.

---
*Architecture research for: local MCP server controlling WhatsApp Desktop on macOS*
*Researched: 2026-05-13*

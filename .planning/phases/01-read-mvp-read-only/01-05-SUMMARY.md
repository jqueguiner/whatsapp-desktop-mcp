---
phase: 01-read-mvp-read-only
plan: 5
title: "Doctor expansion: DB path + schema fingerprint + WhatsApp.app version + last-message ts + coverage summary"
subsystem: mcp-tool-layer
tags: [diagnostics, doctor-tool, schema-fingerprint, plistlib, defensive-probing, diag-01, diag-02, w1-meta, w3-no-timeout]
requires: [phase-1-plan-01-01, phase-1-plan-01-02, phase-1-plan-01-04]
provides:
  - whatsapp_mcp.models.doctor.SchemaState
  - whatsapp_mcp.models.doctor.SchemaFingerprint
  - whatsapp_mcp.models.doctor.DoctorReport (extended — 8 fields)
  - whatsapp_mcp.models.SchemaFingerprint (re-export)
  - whatsapp_mcp.models.SchemaState (re-export)
  - whatsapp_mcp.tools.doctor.doctor (expanded body — 8-field DoctorReport)
affects:
  - Plan 01-06 tests (will mock _probe_db_safely + _probe_whatsapp_version to codify DIAG-02 partial-result invariant; will assert SchemaFingerprint state semantics + the W3 no-@timeout invariant on doctor)
tech-stack:
  added: []
  patterns:
    - "DIAG-02 defensive probing: every new probe wrapped in its own try/except returning structured fallback (state='unreachable' / None) rather than raising; doctor body never makes an unwrapped I/O call that could propagate to FastMCP"
    - "DIAG-01 8-field DoctorReport: 3 Phase 0 PermissionStatus (preserved verbatim) + db_path + schema_fingerprint + whatsapp_app_version + last_message_ts + coverage_summary"
    - "Single short-lived RO connection per call (Pattern 1 reuse from Plan 01-02): _probe_db_blocking runs probe_z_version + MIN/MAX(ZMESSAGEDATE) in one open_ro context manager, no N+1, no held connection across probes"
    - "Independent probe sequencing: WhatsApp.app version probe runs regardless of FDA state (Info.plist is a public app-bundle resource, no TCC required); SQLite probe is FDA-gated (first action opens the user's WA SQLite store)"
    - "W1 honored: doctor's @mcp.tool registration carries meta={'anthropic/maxResultSizeChars': 60000} uniform with the 7 Plan 01-04 read tools — every tool has the same client-side response-budget contract"
    - "W3 honored: doctor deliberately has NO outer @timeout decorator (DIAG-02 partial-result invariant — a tool-level timeout would fire mid-probe and surface a partial DoctorReport)"
    - "Phase 0 D-07 byte-stability: 3 PermissionStatus fields + all_granted property preserved exactly; all_granted considers only the 3 TCC states (not the new schema/version fields) — a user with FDA granted but WhatsApp.app uninstalled still has all_granted==True"
    - "D-08 invariant preserved: exactly one @mcp.tool registration named 'doctor' in tools/doctor.py"
key-files:
  created: []
  modified:
    - src/whatsapp_mcp/models/doctor.py
    - src/whatsapp_mcp/models/__init__.py
    - src/whatsapp_mcp/tools/doctor.py
decisions:
  - "DIAG-02 partial-result avoidance via per-probe try/except + bounded I/O; outer @timeout deliberately omitted on doctor (W3 lock)"
  - "_probe_db_safely catches sqlite3.OperationalError + sqlite3.DatabaseError + FileNotFoundError + PermissionError + RuntimeError + OSError — the union of every plausible failure mode for the short-lived RO connection + the empty-Z_METADATA edge from probe_z_version (which raises RuntimeError per Plan 01-02)"
  - "Coverage built at module-import-stable shape: from_ts/to_ts via cocoa_to_unix conversion; have_window_seconds = to_ts - from_ts (None when either is None); asked_window_seconds=None and is_full=False for the doctor scope (no asked window at the doctor level)"
  - "schema_fingerprint state semantics: 'supported' when observed_version in SUPPORTED_VERSIONS (empty remediation); 'unsupported' when observed_version is outside the set (remediation = open a bug report with doctor + CFBundleShortVersionString + .schema ZWAMESSAGE); 'unreachable' when probe couldn't run at all (remediation = grant FDA)"
  - "Info.plist read uses stdlib open() (not Path.open()) with ruff noqa PTH123 comment — bounded I/O on a 13 KB system file, NOT a user-input path, so the PTH123 'prefer pathlib' lint doesn't add safety here"
  - "isinstance(version, str) guard around plistlib.load output before returning — defends against a hypothetical malformed plist with a non-string CFBundleShortVersionString value (mypy --strict was the proximate cause; T-05-02 threat-model entry was the deeper rationale)"
  - "Last-message timestamp NOT computed via reader.latest_timestamp() despite that public helper existing — instead computed inline as the to_ts of the global coverage probe (one round-trip instead of two; the coverage probe already needs MAX(ZMESSAGEDATE) so reusing the value avoids a second connection)"
  - "Docstring referenced concepts in prose only — no literal '@timeout(...)' / 'readOnlyHint=True' / 'anthropic/maxResultSizeChars' token mentions — to keep grep-gate counts at the plan's exact-count expectations (same near-miss class as Plan 01-02 immutable=1 reword, Plan 01-04 docstring rewords, etc.)"
metrics:
  duration_seconds: 720
  tasks: 2
  files: 3
  commits: 2
  completed: "2026-05-13T10:30:00Z"
---

# Phase 1 Plan 01-05: Doctor expansion — Summary

The Phase 0 ``doctor`` tool shipped with 3 ``PermissionStatus`` fields
(FDA / Automation / Accessibility). Plan 01-05 extends ``DoctorReport``
to 8 fields per DIAG-01 — adding the resolved DB path, a schema
fingerprint with 3-state classification, the installed WhatsApp.app
version, the latest-message Unix timestamp, and a global coverage
summary — while preserving the Phase 0 D-07 byte-stable surface and
the D-08 single-tool-named-``doctor`` invariant.

DIAG-02 (the diagnostic-path invariant) is enforced via per-probe
``try/except``: every new probe degrades to ``state="unreachable"`` /
``None`` rather than raising, so ``doctor`` remains callable when FDA
is denied, WhatsApp.app is missing, or the schema query fails. The
W3 lock is honored: ``doctor`` deliberately carries no outer
``@timeout`` wrapper (a tool-level timeout would fire mid-probe and
return a partial ``DoctorReport`` that violates DIAG-02).

## What Shipped

### Task 1 — Extended `DoctorReport` + new `SchemaFingerprint` model

**`src/whatsapp_mcp/models/doctor.py`** — Three additions:

1. **`SchemaState` Literal alias** — `"supported" | "unsupported" | "unreachable"`.
2. **`SchemaFingerprint` Pydantic model** with 4 fields:
   - `state: SchemaState` — reachability + support classification.
   - `observed_version: int | None` — the live `Z_VERSION` (or `None`).
   - `supported_versions: list[int]` — sorted snapshot of `reader.SUPPORTED_VERSIONS`.
   - `remediation: str` — empty when `state == "supported"`; populated otherwise.
3. **`DoctorReport` extension** — 5 new fields appended AFTER the
   3 byte-stable Phase 0 fields and BEFORE the `all_granted` property:
   - `db_path: str` — resolved `ChatStorage.sqlite` path (even when FDA denied).
   - `schema_fingerprint: SchemaFingerprint` — `Z_VERSION` probe result.
   - `whatsapp_app_version: str | None` — `CFBundleShortVersionString` or `None`.
   - `last_message_ts: int | None` — max Unix-second timestamp across chats.
   - `coverage_summary: Coverage` — global from/to/have_window across all chats.

**`src/whatsapp_mcp/models/__init__.py`** — Added `SchemaFingerprint` and
`SchemaState` to the public re-export surface; `__all__` now enumerates
21 names (was 19).

**Preserved exactly (D-07 byte-stable Phase 0 surface):**
- `PermissionState`, `PermissionBucket` Literal aliases.
- `PermissionStatus` model (every field, every default).
- `DoctorReport.full_disk_access`, `automation_whatsapp`, `accessibility` fields.
- `@property def all_granted(self) -> bool` — considers ONLY the 3 TCC
  states; a user with FDA granted but WhatsApp.app uninstalled still
  has `all_granted == True` (DIAG-02 rationale: `all_granted` reflects
  TCC permissions only, not schema/version reachability).

### Task 2 — Expanded `doctor()` body with defensive probes

**`src/whatsapp_mcp/tools/doctor.py`** — Three additions, one preservation:

1. **`@mcp.tool(...)` decorator preserved verbatim** (D-08 single-tool
   invariant): name, title, description, `ToolAnnotations(readOnlyHint=True,
   destructiveHint=False, idempotentHint=True, openWorldHint=False)`, and
   the W1 `meta={"anthropic/maxResultSizeChars": 60000}` already added by
   Plan 01-04 Task 3. Description text updated to mention the 5 new fields.

2. **Two private async probe helpers added:**

   - `_probe_whatsapp_version_blocking() -> str | None` (sync) + its
     `_probe_whatsapp_version() -> str | None` `asyncio.to_thread`
     wrapper. Opens `/Applications/WhatsApp.app/Contents/Info.plist`
     via stdlib `plistlib.load`, returns `data.get("CFBundleShortVersionString")`
     as `str | None`. Wraps the open in try/except
     `(FileNotFoundError, PermissionError, plistlib.InvalidFileException, OSError)`
     and returns `None` on any failure. Runs regardless of FDA state
     because Info.plist is a public app-bundle resource (no TCC required).

   - `_probe_db_blocking(db_path) -> tuple[SchemaFingerprint, int | None, Coverage]`
     (sync) + its `_probe_db_safely(db_path) -> ...`
     `asyncio.to_thread` wrapper. Inside a single short-lived RO
     connection (via `reader.connection.open_ro`), runs
     `probe_z_version(conn)` then
     `SELECT MIN(ZMESSAGEDATE), MAX(ZMESSAGEDATE) FROM ZWAMESSAGE` —
     ONE connection, ONE round-trip pair. The `_probe_db_safely`
     wrapper catches
     `(sqlite3.OperationalError, sqlite3.DatabaseError, FileNotFoundError, PermissionError, RuntimeError, OSError)`
     and returns the "unreachable" fingerprint + `None` + empty
     Coverage on any failure (`RuntimeError` covers
     `probe_z_version`'s empty-`Z_METADATA` raise per Plan 01-02).

3. **`doctor()` body re-shaped** to assemble the 8-field response:
   - Phase 0 probes preserved verbatim (sequential await of `fda.check`,
     `automation.check_whatsapp`, `accessibility.check` — same order).
   - `db_path = resolve_chatstorage_path()` (always — no probe).
   - If `fda_status.state == "granted"`: dispatch `_probe_db_safely`.
   - Else: synthesize the FDA-denied fallback (`state="unreachable"`,
     `last_ts=None`, empty Coverage, remediation text directs to FDA
     System Settings panel).
   - `wa_version = await _probe_whatsapp_version()` runs unconditionally.
   - Construct `DoctorReport` with all 8 fields and return.

## Source Assertions — all pass

| Pattern | File | Match count | Required |
|---|---|---|---|
| `^class SchemaFingerprint\(BaseModel\):` | `models/doctor.py` | 1 | =1 |
| `^SchemaState\s*=\s*Literal\[` | `models/doctor.py` | 1 | =1 |
| `db_path:\s*str` | `models/doctor.py` | 2 | ≥2 (one on PermissionStatus from Phase 0, one on DoctorReport from Plan 01-05) |
| `schema_fingerprint:\s*SchemaFingerprint` | `models/doctor.py` | 1 | =1 |
| `whatsapp_app_version:\s*str\s*\|\s*None` | `models/doctor.py` | 1 | =1 |
| `last_message_ts:\s*int\s*\|\s*None` | `models/doctor.py` | 1 | =1 |
| `coverage_summary:` | `models/doctor.py` | 1 | =1 |
| `def all_granted\(self\)` | `models/doctor.py` | 1 | =1 |
| `PermissionState\s*=\s*Literal\[` | `models/doctor.py` | 1 | =1 |
| `@property\s*$` | `models/doctor.py` | 1 | =1 |
| `^@mcp\.tool\(` | `tools/doctor.py` | 1 | =1 (D-08) |
| `^async def doctor\(\)\s*->\s*DoctorReport` | `tools/doctor.py` | 1 | =1 |
| `async def _probe_whatsapp_version\(` | `tools/doctor.py` | 1 | =1 |
| `async def _probe_db_safely\(` | `tools/doctor.py` | 1 | =1 |
| `plistlib` | `tools/doctor.py` | 5 | ≥1 |
| `asyncio\.to_thread` | `tools/doctor.py` | 3 | ≥2 |
| `try:` (defensive try/except — DIAG-02) | `tools/doctor.py` | 2 | ≥2 |
| `readOnlyHint=True` | `tools/doctor.py` | 1 | =1 (Phase 0 annotation preserved) |
| `anthropic/maxResultSizeChars` | `tools/doctor.py` | 1 | =1 (W1 lock — meta annotation preserved) |
| `@timeout\(` (W3 lock — must NOT match) | `tools/doctor.py` | 0 | =0 |
| `from whatsapp_mcp\.sender\|import whatsapp_mcp\.sender` (REL-05) | `tools/doctor.py` | 0 | =0 |

## Behavior Verification — all pass

- `DoctorReport(...)` accepts and round-trips all 8 fields;
  `model_dump_json()` produces valid JSON; `all_granted` returns `True`
  iff all 3 `PermissionStatus.state` are `"granted"` (Phase 0
  invariant — does NOT consider the new schema/version fields).
- `from whatsapp_mcp.models import SchemaFingerprint, SchemaState`
  succeeds.
- `mcp.list_tools()` returns exactly **8 tools** (doctor + 7 read
  tools from Plan 01-04); doctor's `annotations.readOnlyHint is True`.
- Phase 0 baseline tests (`test_doctor_tool.py`, `test_exceptions.py`):
  still pass after the model expansion.
- `uv run pytest -m "not live"` returns 28 passed (Plan 06 will add new
  tests).
- `ruff check` + `ruff format --check` + `mypy` (strict) all green
  across 56 source files.

### Live smoke (RUN_LIVE=1)

Run against the user's actual machine (WhatsApp Desktop 26.16.74,
macOS 26.4.1, 89 MB ChatStorage.sqlite, FDA granted, 2026-05-13):

```
schema_fingerprint.state = supported
observed_version          = 1
supported_versions        = [1]
whatsapp_app_version      = 26.16.74
last_message_ts           = 1778667269   (Unix seconds; 2026-05-13)
coverage_summary.from_ts  = 1432040904   (Unix seconds; 2015-05-19)
coverage_summary.to_ts    = 1778667269   (Unix seconds; 2026-05-13)
coverage_summary.have_window_seconds = 346626365  (~11 years)
all_granted               = True
```

### DIAG-02 verification (FDA-denied simulation)

`unittest.mock.patch('whatsapp_mcp.tools.doctor.fda.check', _denied_check)`
substitutes a stub returning `PermissionStatus(bucket='fda', state='denied', ...)`.
`asyncio.run(doctor())` returns successfully (NO exception propagates):

```
schema_fingerprint.state = unreachable    (probe gated on FDA — degraded)
last_message_ts          = None           (probe gated on FDA — degraded)
coverage_summary.from_ts = None           (probe gated on FDA — degraded)
coverage_summary.to_ts   = None           (probe gated on FDA — degraded)
whatsapp_app_version     = 26.16.74       (Info.plist read does not need FDA — populated)
```

The `whatsapp_app_version` value populating even when FDA is denied
proves the deliberate FDA-gating boundary: the SQLite probe is gated,
the plistlib probe is not. This matches the plan's design (Info.plist
lives in `/Applications`, outside the TCC-protected container).

### W1 / W3 / D-08 lock verification

- W1: `grep -cE 'anthropic/maxResultSizeChars' src/whatsapp_mcp/tools/doctor.py` returns 1 (already in place from Plan 01-04 Task 3; this plan preserves it).
- W3: `grep -nE '@timeout\(' src/whatsapp_mcp/tools/doctor.py` returns no matches (deliberately no outer `@timeout` decorator — DIAG-02 partial-result invariant).
- D-08: `grep -cE '^@mcp\.tool\(' src/whatsapp_mcp/tools/doctor.py` returns 1 (exactly one tool named `doctor` registered); `mcp.list_tools()` returns 8 tools total (doctor + 7 read tools from Plan 01-04 — no new tools added by Plan 01-05).

## Acceptance Criteria — all met

- [x] `models/doctor.py` carries 8 DoctorReport fields total (3 PermissionStatus + 5 new); `SchemaFingerprint` model defined; Phase 0 byte-stable surface preserved.
- [x] `tools/doctor.py` registers exactly one tool named `doctor` (D-08); body returns the full DIAG-01 payload; defensive try/except around every new probe (DIAG-02).
- [x] Live invocation returns `schema_fingerprint.state="supported"`, `whatsapp_app_version="26.16.74"`, populated `last_message_ts` and `coverage_summary`.
- [x] `mcp.list_tools()` returns exactly 8 tools (doctor + 7 read tools) — Plan 01-05 does NOT add new tools.
- [x] Phase 0 baseline 28 tests still pass.
- [x] ruff full ruleset + ruff format --check + mypy --strict green across 56 source files.
- [x] REL-05 invariant maintained: no `whatsapp_mcp.sender` imports in `tools/doctor.py`.
- [x] W1 lock: `meta={"anthropic/maxResultSizeChars": 60000}` present on doctor's `@mcp.tool` (already in place from Plan 01-04 Task 3 — preserved verbatim).
- [x] W3 lock: no outer `@timeout` decorator on doctor (DIAG-02 partial-result invariant).
- [x] DIAG-02 verified via FDA-denied mock: doctor returns successfully with `state="unreachable"` / `None` fields rather than raising.

## Commits

| Task | Hash | Description |
|---|---|---|
| 1 | `9deeb43` | `feat(01-05): extend DoctorReport with 5 DIAG-01 fields + SchemaFingerprint model` |
| 2 | `bea108e` | `feat(01-05): expand doctor body with defensive DB/WhatsApp.app probes (DIAG-01 + DIAG-02)` |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Lint near-miss] Reworded module docstring in `tools/doctor.py` to avoid literal-token grep-gate hits**

- **Found during:** Task 2 source-assertion verification.
- **Issues:**
  - (a) Docstring referenced `readOnlyHint=True` verbatim inside the
    annotation-choices bullet list, which inflated the source-grep
    count for the strict gate `grep -cE 'readOnlyHint=True' src/whatsapp_mcp/tools/doctor.py == 1` to 2 (one in the decorator, one in the docstring).
  - (b) Docstring referenced `anthropic/maxResultSizeChars` verbatim in
    the W1 annotation bullet, which inflated the strict gate
    `grep -cE 'anthropic/maxResultSizeChars' src/whatsapp_mcp/tools/doctor.py == 1` to 2 (one in the decorator, one in the docstring).
  - (c) Docstring referenced `@timeout(seconds=N)` verbatim in the W3
    section, which made the W3 lock gate
    `! grep -nE '@timeout\(' src/whatsapp_mcp/tools/doctor.py` fail
    (it matched the docstring sentence). The functional W3 invariant
    is "no `@timeout` decorator on `doctor`" — the grep gate is a
    textual proxy for that; the docstring mention was harmless
    documentation but failed the proxy.
- **Fix:** Reworded the docstring to refer to the concepts in prose —
  "read-only hint", "60k-char response-budget meta annotation",
  "per-tool timeout decorator" — without naming the literal tokens. The
  actual decorator invocation on the function is untouched. Same
  near-miss class as Plan 01-02's `immutable=1` reword, Plan 01-03's
  `from whatsapp_mcp.server import run` reword, Plan 01-04's
  `@timeout(seconds=5)` / `readOnlyHint=True` /
  `anthropic/maxResultSizeChars` docstring rewords — strict file-wide
  grep gates around literal tokens are the cause, prose rewording is
  the fix.
- **Files modified:** `src/whatsapp_mcp/tools/doctor.py`.
- **Commit:** `bea108e` (Task 2; folded into the same commit as the
  body expansion since both surfaces were touched together).
- **Outcome:** All three previously failing grep gates now match the
  plan's exact-count expectations; documentary intent preserved
  verbatim around the rewordings; behavior unchanged.

**2. [Rule 2 — Defensive coding] `isinstance(version, str)` guard around `plistlib.load` output**

- **Found during:** Task 2 mypy --strict pass.
- **Issue:** `plistlib.load()` returns `dict[str, Any]`; the
  `data.get("CFBundleShortVersionString")` call therefore returns
  `Any`, which mypy --strict cannot narrow to the return type
  `str | None` declared on `_probe_whatsapp_version_blocking`. Direct
  return tripped a `[return-value]` strict-mode error.
- **Fix:** Added an `isinstance(version, str)` guard before returning
  the value; falls through to `return None` on any non-string type.
  This is also genuinely defensive per the T-05-02 threat-model entry
  (plist bomb / malformed plist with a non-string version key) — the
  doctor must never raise to FastMCP, so returning `None` on
  unexpected types is the right fallback.
- **Files modified:** `src/whatsapp_mcp/tools/doctor.py` (Task 2 commit).
- **Outcome:** mypy --strict green; T-05-02 threat-model entry
  explicitly addressed.

**3. [Rule 1 — Style] ruff format collapsed a multi-line SQL expression**

- **Found during:** Task 2 `uv run ruff format --check`.
- **Issue:** Initial draft wrote the `SELECT MIN(ZMESSAGEDATE), MAX(ZMESSAGEDATE) FROM ZWAMESSAGE`
  call across two lines (string + `.fetchone()` on the next line);
  ruff format collapsed it onto a single line under the project's
  100-char line-length cap.
- **Fix:** Accepted the format change (cosmetic only; SQL still
  parameter-free static text).
- **Files modified:** `src/whatsapp_mcp/tools/doctor.py` (Task 2 commit).
- **Outcome:** ruff format --check clean.

## SchemaFingerprint Runbook

When a user reports `schema_fingerprint.state == "unsupported"`:

1. **User collects three diagnostics:** the full `doctor` JSON
   response, `defaults read /Applications/WhatsApp.app/Contents/Info.plist CFBundleShortVersionString`,
   and `sqlite3 ~/Library/Group\ Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite ".schema ZWAMESSAGE"`.
2. **User opens an issue** with the three diagnostics in the body.
3. **Maintainer reproduces** in a scratch venv against a snapshot of
   the user's `ChatStorage.sqlite` (or just runs the v1 SQL templates
   against the live new-version DB).
4. **If columns the v1 SQL references are still present:** add the
   new `Z_VERSION` to `whatsapp_mcp.reader.schema_v1.SUPPORTED_VERSIONS`,
   ship a patch release. Doctor's `state` flips to `"supported"` on
   the upgraded install.
5. **If columns changed:** add `reader/schema_v2.py` mirroring the v1
   SQL with renamed/added columns; `reader/connection.py` dispatches
   on `Z_VERSION` to the right schema module; release as a minor
   version bump. Doctor's `SchemaFingerprint` then carries the v2
   `supported_versions` snapshot.

When a user reports `schema_fingerprint.state == "unreachable"`:

1. **First check the FDA bucket:** if `full_disk_access.state != "granted"`,
   the unreachability is FDA-denial — the remediation field already
   directs the user to grant FDA in System Settings.
2. **If FDA is granted but state is still unreachable:** the DB file
   may be missing (`whatsapp_app_version is None` is a strong
   correlator — WhatsApp.app uninstalled), or the
   `~/Library/Group Containers/...` container may have been
   relocated by a non-standard install. Check `doctor.db_path` for
   the resolved path and verify the file exists with `ls -la`.

## Threat Flags

None new — Plan 01-05 implements the mitigations its `<threat_model>`
already named:

- **T-05-01** (DoS via probe failure): mitigated by per-probe
  try/except in `_probe_db_safely` and `_probe_whatsapp_version`.
  Verified via FDA-denied simulation (DIAG-02 section above).
- **T-05-02** (plist bomb): mitigated by `plistlib.InvalidFileException`
  in the catch tuple + `isinstance(version, str)` guard. Stdlib
  `plistlib.load` accepts only well-formed plists; worst case is the
  exception, which the wrapper returns `None` for.
- **T-05-03** (db_path disclosure to LLM): accepted — the path
  (`~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite`)
  is well-known per WhatsApp forensics literature; granting FDA to a
  binary already exposes it to file-system reads.
- **T-05-04** (fake WhatsApp.app spoofing): accepted — `/Applications`
  is admin-protected; if compromised, every other defense is moot.
- **T-05-05** (accidental `@timeout` regression): mitigated by the
  explicit absence + docstring rationale + plan source assertion
  (`! grep -nE '@timeout\(' src/whatsapp_mcp/tools/doctor.py`
  succeeds). Plan 01-06's `test_doctor_does_not_have_tool_level_timeout`
  will be the runtime check.
- **T-05-06** (`open_ro` accidentally writes): mitigated structurally
  by `?mode=ro` (SQLite refuses writes). Plan 01-02's grep gate
  ensures `open_ro` never uses the WAL-skipping URI flag; this plan
  reuses `open_ro` verbatim without modification.
- **T-05-07** (silent schema-mismatch degradation): mitigated by the
  `SchemaFingerprint.remediation` field — every "unsupported" state
  carries an actionable message. This Summary's "SchemaFingerprint
  Runbook" section above codifies the upgrade path.

## Authentication Gates

None. The user's machine has FDA granted to `uv` (and `python` /
the wheel binary) from Phase 0 work; live invocation succeeded
without any TCC prompt.

## Known Stubs

None. Plan 01-05 ships a fully functional 8-field `DoctorReport`.

- `GroupInfo.description = None` and `is_muted = False` are W5-locked
  v0.1 defaults from Plan 01-02; surfaced as-is by `get_chat_metadata`
  (Plan 01-04) but unrelated to doctor.
- The "first-chat live-DB anomaly" from Plan 01-02 (Z_PK=978 broadcast
  chat with a year-11003 `ZLASTMESSAGEDATE`) does NOT affect doctor's
  `coverage_summary` because the coverage probe uses
  `ZMESSAGEDATE FROM ZWAMESSAGE` (per-message timestamps, not
  per-chat session metadata), which is bounded by the user's actual
  message history (verified live: `to_ts = 1778667269`, a 2026-05-13
  Unix second — not a far-future value).

## Plan 01-06 (tests) Notes

Plan 01-06 should add tests asserting:

1. **DIAG-02 invariant:** `mock.patch('whatsapp_mcp.tools.doctor.fda.check', ...)`
   to return `state='denied'` → assert `doctor()` returns successfully
   with `schema_fingerprint.state == "unreachable"`, `last_message_ts is None`,
   `coverage_summary.from_ts is None`, `coverage_summary.to_ts is None`,
   `whatsapp_app_version` populated (or None, depending on test
   machine — assertion should accept either).
2. **W3 lock:** `! grep -nE '@timeout\(' src/whatsapp_mcp/tools/doctor.py`
   succeeds as a source-grep test (or via introspection of the doctor
   function for a `_timeout_seconds` attribute).
3. **D-08 invariant:** `await mcp.list_tools()` returns exactly 8 tools
   (doctor + 7 read tools) — no second doctor registration.
4. **8-field DoctorReport shape:** instantiating with all 8 fields
   works; `all_granted` considers only the 3 PermissionStatus fields
   (not the new schema/version fields).
5. **SchemaFingerprint state semantics:** unit tests for each of the
   3 states (mock `probe_z_version` to return 1 → `supported`; mock
   to return 99 → `unsupported`; mock to raise → `unreachable`).
6. **plistlib probe behavior:** mock `_probe_whatsapp_version_blocking`
   to return `None` (missing WhatsApp.app simulation); assert
   `whatsapp_app_version is None` in the response and that doctor
   still returns successfully.
7. **Phase 0 regression:** the existing `test_doctor_is_registered_as_readonly`
   test still asserts the doctor registration shape; Plan 01-04 already
   relaxed the `len(tools) == 1` to membership; Plan 01-05 does not
   touch this test.

## Self-Check: PASSED

- `src/whatsapp_mcp/models/doctor.py` exists with the extended 8-field
  `DoctorReport` + `SchemaFingerprint` model + `SchemaState` Literal alias.
- `src/whatsapp_mcp/models/__init__.py` re-exports `SchemaFingerprint`
  and `SchemaState` (21-name `__all__`).
- `src/whatsapp_mcp/tools/doctor.py` carries the 8-field response body,
  the `_probe_whatsapp_version` + `_probe_db_safely` private helpers,
  the W1 meta annotation, no `@timeout` decorator, and no sender
  imports.
- Both Task commits (`9deeb43`, `bea108e`) are present in `git log`:
  - `9deeb43 feat(01-05): extend DoctorReport with 5 DIAG-01 fields + SchemaFingerprint model`
  - `bea108e feat(01-05): expand doctor body with defensive DB/WhatsApp.app probes (DIAG-01 + DIAG-02)`
- Full `ruff check` + `ruff format --check` + `mypy --strict` clean
  across 56 source files.
- Phase 0 baseline 28 tests still pass.
- Live smoke against the user's WhatsApp Desktop 26.16.74 install
  returned the 8 populated DoctorReport fields documented above.
- DIAG-02 simulated FDA-denial invocation returned successfully with
  the structured fallback values documented above.

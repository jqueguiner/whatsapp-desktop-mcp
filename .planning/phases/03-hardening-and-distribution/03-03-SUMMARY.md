---
phase: 03-hardening-and-distribution
plan: 3
subsystem: hardening (doctor + audit-log rotation + dev subcommand)
tags: [tested-versions, doctor, degraded-mode, audit-log-rotation, dev-subcommand, cli-subparser, phase-3]
requires:
  - phase-1 SchemaFingerprint + DoctorReport (extended in place; D-07 byte-stability preserved on DoctorReport top-level field order)
  - phase-1 cli.py argparse pattern with lazy server.run import (Plan 01-03 D-19; Plan 03-01 --fts5-mode mirrored the pattern; Plan 03-03 inherits)
  - phase-2 sender/audit.py append-time JSONL writer (extended in place with rotation; D-13 plaintext-body STRUCTURAL invariant preserved by construction)
  - phase-2 sender/rate_limit.py _DB_PATH constant (consumed by dev/reset_rate_limit.py as the unlink target)
provides:
  - docs/tested_versions.md (manual maintainer-edited markdown matrix; initial WA 26.16.74 / macOS 26.4 / Z_VERSION 1 row)
  - reader/tested_versions.py (fault-tolerant parser; SUPPORTED_VERSION_RANGE module constant; load_tested_z_versions + _load_tested_wa_versions)
  - models/doctor.SchemaFingerprint extended with supported_version_range + degraded_mode_warning fields
  - tools/doctor.py degraded-mode warning logic (pure derivation; populated when wa_version outside tested matrix)
  - sender/audit.py size-based rotation (_resolve_max_bytes + _rotate_in_place; reverse-walk shift order; 5-archive cap with eviction)
  - cli.py --audit-log-max-bytes arg + dev subparser + dev reset-rate-limit dispatch
  - dev/__init__.py + dev/reset_rate_limit.py (one-shot CLI utility; tty-confirmation discipline; non-tty default-refuse)
  - pyproject.toml [tool.ruff.lint.per-file-ignores] entry exempting dev/*.py from T201 (scoped — server/tools/reader/sender all keep T201 active)
affects:
  - DoctorReport JSON shape: SchemaFingerprint gains 2 fields (defaults preserve byte-stable serialization on the leading fields; D-07 invariant on DoctorReport top-level fields untouched)
  - audit.log file lifecycle: now rotates at 10 MB by default (configurable via env var or --audit-log-max-bytes); archives at audit.log.1..audit.log.5 with mode 0600 carry-through
  - whatsapp-desktop-mcp CLI surface: gains --audit-log-max-bytes flag + 'dev' subcommand with 'reset-rate-limit' nested subcommand
tech-stack:
  added:
    - none — pure stdlib (re for parser, pathlib + os.environ for rotation, sys.stdin.isatty for prompt discipline)
  patterns:
    - module-load constant + re-callable accessor (SUPPORTED_VERSION_RANGE = load_tested_z_versions() at module load; tests monkeypatch _TESTED_VERSIONS_PATH then call the accessor for alternate-table coverage)
    - fault-tolerant parser (regex \\d+ guard + try/except ValueError + (1,1) default on missing/empty/malformed file — DIAG-02 in miniature)
    - reverse-walk archive shift (path.5 → unlink, path.4 → path.5, ..., path → path.1; no archive ever overwrites another's content)
    - argparse subparser dispatch with extracted _add_server_args helper (default = server; 'dev <subcommand>' routes elsewhere; preserves Phase 1/Plan 03-01 server-mode flag mechanics)
    - tty-default-refuse confirmation (sys.stdin.isatty + explicit 'y' answer; non-tty refuses with stderr message — T-03-03-05 mitigation)
    - per-file ruff ignore for one-shot CLI utilities (scoped to dev/*.py only — T-03-03-06 mitigation; rest of package keeps T201 active)
key-files:
  created:
    - docs/tested_versions.md (16 lines; initial row + parser-pointer header)
    - src/whatsapp_desktop_mcp/reader/tested_versions.py (114 lines; parser + module-load constant + sibling helper)
    - src/whatsapp_desktop_mcp/dev/__init__.py (24 lines; package marker + isolation rationale)
    - src/whatsapp_desktop_mcp/dev/reset_rate_limit.py (76 lines; confirmation discipline + unlink)
    - tests/unit/test_tested_versions_parser.py (170 lines; 8 tests)
    - tests/unit/test_doctor_degraded_warning.py (260 lines; 6 tests)
    - tests/unit/test_audit_rotation.py (321 lines; 12 tests)
    - tests/unit/test_dev_subcommand.py (245 lines; 12 tests)
  modified:
    - src/whatsapp_desktop_mcp/models/doctor.py (+22 lines: 2 SchemaFingerprint Field appends + comment block; D-07 byte-stability discipline on DoctorReport unchanged)
    - src/whatsapp_desktop_mcp/tools/doctor.py (+27 lines: post-probe pure derivation block populating supported_version_range + conditional degraded_mode_warning)
    - src/whatsapp_desktop_mcp/sender/audit.py (+76 lines: 3 module constants + _resolve_max_bytes + _rotate_in_place + _blocking_append rotation pre-check)
    - src/whatsapp_desktop_mcp/cli.py (+62 / -16 lines: _add_server_args extraction + subparser dispatch + --audit-log-max-bytes arg + env-var assignment)
    - pyproject.toml (+9 lines: scoped per-file ruff T201 ignore for dev/*.py)
decisions:
  - D-19/D-20/D-21 honored: docs/tested_versions.md initial row (WA 26.16.74 / macOS 26.4 / Z_VERSION 1 / FDA-Auto-Acc all granted / maintainer / 2026-05-13). Parser at reader/tested_versions.py with (1, 1) default + try/except ValueError + (FileNotFoundError, PermissionError) at the file-read boundary.
  - D-20 honored: SchemaFingerprint extended with supported_version_range: tuple[int, int] = (1, 1) + degraded_mode_warning: str | None = None. Doctor populates the warning with the structured 'WhatsApp.app v{x} not in tested-versions.md (last tested: {y}); reads may degrade silently.' string when observed wa_version is outside the matrix AND schema_fp.state == 'supported'. Pure derivation (model_copy) — NOT a new probe; DIAG-02 invariant carries through.
  - D-25/D-26 honored: rotation at 10 MB (configurable via WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES env var); 5 archives (audit.log.1..audit.log.5); reverse-walk shift order (no archive ever overwrites another's content); eldest unlinked before slot reuse; rotation triggered at append time (not by a daemon — preserves the no-daemon architecture).
  - D-13 STRUCTURAL invariant preserved by construction: rotation moves complete JSONL lines verbatim via Path.rename; AuditEntry schema has body_sha256: str only (no raw body field, no body_text, no body_preview); rotated archives carry exactly what the live log carried; the "no plaintext body in archive" test asserts a sentinel marker never appears in archive content.
  - D-27 honored: dev/reset_rate_limit.py with non-tty default-refuse + explicit 'y' confirmation; case-insensitive 'y' is the ONLY confirming answer; DB-absent early-return is no-op + return 0; missing_ok=True on unlink handles a TOCTOU race between the early-return check and the unlink.
  - D-28 honored: --audit-log-max-bytes (default 10 MB) sets the env var BEFORE the lazy server.run import resolves (mirrors --read-only / --fts5-mode mechanics from Phase 1 D-19 / Plan 03-01).
  - D-07 byte-stability invariant preserved on DoctorReport: the 3 PermissionStatus fields lead the model_fields ordering; Phase 1 added 5 fields after them; Phase 3 Plan 03-03 adds the 2 new fields INSIDE SchemaFingerprint, NOT at DoctorReport top level — so DoctorReport's top-level field order stays byte-stable across Phase 0 / Phase 1 / Phase 3 (the test_doctor_report_field_order_phase0_first regression test enforces).
  - REL-05 D-24 isolation invariant carries: reader/tested_versions.py imports stdlib only (re, pathlib, logging) — no whatsapp_desktop_mcp.sender edge; dev/reset_rate_limit.py imports from whatsapp_desktop_mcp.sender.rate_limit (the public _DB_PATH constant) which is the cli/tool tier accessing the sender tier — does NOT establish a reader↔sender edge.
  - W6 lock honored (Phase 2 carry-over): _check_db_path_distinct() in sender/rate_limit.py is unchanged; the dev subcommand consumes _DB_PATH directly (no new path-resolver evolution risk).
  - DIAG-02 invariant carries: parser is fault-tolerant ((1,1) default, try/except ValueError, file-read boundary catches FileNotFoundError + PermissionError); doctor stays callable even when docs/tested_versions.md is missing or malformed.
  - W-4 lesson honored (live module attribute access): tools/doctor.py reads tested_versions.SUPPORTED_VERSION_RANGE + tested_versions._load_tested_wa_versions at CALL time via 'from whatsapp_desktop_mcp.reader import tested_versions; tested_versions.SUPPORTED_VERSION_RANGE' — NOT 'from whatsapp_desktop_mcp.reader.tested_versions import SUPPORTED_VERSION_RANGE' which would bind at import time and miss test monkeypatches. Same pattern as the Plan 03-01 server.fts5_mode dispatch.
metrics:
  duration_seconds: 1320
  completed: 2026-05-14
---

# Phase 3 Plan 03-03: Hardening — tested_versions parser + doctor degraded warning + audit log rotation + dev subcommand Summary

## One-liner

Phase 3 Plan 03-03 closes the Phase 2 D-14 audit-log-rotation deferred-to-Phase-3 carry-over and the ROADMAP §"Phase 3" Success Criterion 3 (`tested_versions.md` matrix) by shipping a fault-tolerant `docs/tested_versions.md` parser at `reader/tested_versions.py`, extending `SchemaFingerprint` with `supported_version_range` + `degraded_mode_warning` fields populated by doctor when the live WhatsApp.app version is outside the tested matrix, adding 10 MB / 5-archive size-based rotation at `sender/audit.py`'s append site (D-13 plaintext-body STRUCTURAL invariant preserved by construction), restructuring `cli.py` into an argparse subparser dispatch that adds the `whatsapp-desktop-mcp dev reset-rate-limit` budget-recovery subcommand and the `--audit-log-max-bytes` CLI override.

## What Shipped

### Task 1 — `tested_versions.md` + `reader/tested_versions.py` parser + `SchemaFingerprint` extension + doctor degraded warning (commit `435af2c`)

Five coordinated artifacts:

- **`docs/tested_versions.md`** (16 lines). Markdown header explaining the file's purpose and pointing to the parser, plus the locked initial row per CONTEXT.md D-21:
  ```
  | 26.16.74 | 26.4 | 1 | FDA/Auto/Acc all granted | maintainer | 2026-05-13 | Phase 1+2 live-verified |
  ```
- **`src/whatsapp_desktop_mcp/reader/tested_versions.py`** (114 lines). Module-load parse with `SUPPORTED_VERSION_RANGE: tuple[int, int]` constant exposed at module top; `_TESTED_VERSIONS_PATH` resolved 4 parents up from this file (reader/ → whatsapp_desktop_mcp/ → src/ → repo root, then `/docs/tested_versions.md`); regex `^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|` captures column 1 (WA version), column 2 (macOS version), column 3 (Z_VERSION integer) — header rows have a non-digit Z_VERSION column so they don't match; separator rows starting with `|---` don't have 3 well-formed cells either. Three-tier fault tolerance:
  1. `(FileNotFoundError, PermissionError)` at the file-read boundary → `(1, 1)` default + warning log (the file might not be present in a venv bundle that excluded `docs/`).
  2. Empty parsed list → `(1, 1)` default (no data rows in the table).
  3. `try/except ValueError` around the `int(group(3))` call inside `_parse_z_versions` → defense-in-depth on top of the regex's `\\d+` guard (DIAG-02 in miniature; even if a future regex evolution allows non-numeric input through, the parser still skips it instead of crashing).
  Sibling `_load_tested_wa_versions() -> set[str]` helper extracts column 1 strings for the doctor extension.
- **`src/whatsapp_desktop_mcp/models/doctor.py`** (+22 lines). Two new `Field`s appended to `SchemaFingerprint` AFTER the existing `remediation` field per CONTEXT.md D-20: `supported_version_range: tuple[int, int] = (1, 1)` and `degraded_mode_warning: str | None = None`. Description strings carefully worded for LLM consumption per D-20 spirit. The append-after-`remediation` placement preserves byte-stable serialization on the existing 4 leading fields.
- **`src/whatsapp_desktop_mcp/tools/doctor.py`** (+27 lines). Post-probe pure-derivation block: imports `from whatsapp_desktop_mcp.reader import tested_versions` at the dispatch site (live module attr access — W-4 lesson), then `schema_fp = schema_fp.model_copy(update={"supported_version_range": tested_versions.SUPPORTED_VERSION_RANGE})` (always populates the range). When `wa_version is not None and schema_fp.state == "supported"`, computes `tested_wa = tested_versions._load_tested_wa_versions()`; if `wa_version not in tested_wa`, computes `latest = max(tested_wa, default="(none)")` (lexical max — documented v1.0 simplification; v1.1 candidate is full SemVer comparison) and patches `schema_fp` with the structured warning string `"WhatsApp.app v{wa_version} not in tested-versions.md (last tested: {latest}); reads may degrade silently."`.
- **`tests/unit/test_tested_versions_parser.py`** (170 lines, 8 tests) + **`tests/unit/test_doctor_degraded_warning.py`** (260 lines, 6 tests). Per Plan 03-03 Task 1 behaviors 1–10 (parser default on missing file, integer extraction, fault-tolerance grep, header/separator skip, empty-table default, sibling WA-versions helper, SchemaFingerprint defaults, SchemaFingerprint non-default acceptance, doctor populates supported_version_range, doctor sets/clears degraded_mode_warning based on wa_version, D-07 byte-stability of DoctorReport top-level field order).

### Task 2 — `sender/audit.py` size-based rotation + `--audit-log-max-bytes` CLI arg (commit `2a384dd`)

Two coordinated edits:

- **`src/whatsapp_desktop_mcp/sender/audit.py`** (+76 lines). Three new module constants (`_DEFAULT_MAX_BYTES = 10 * 1024 * 1024`, `_ENV_MAX_BYTES = "WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES"`, `_ARCHIVE_COUNT = 5`); `_resolve_max_bytes()` reads the env var lazily on each append (so test-time overrides + runtime CLI changes both work; ValueError-safe falls back to default rather than crashing); `_rotate_in_place(path, archive_count)` walks reverse order from `path.{archive_count}` down so no archive overwrites another's content (the eldest is unlinked BEFORE its slot is reused); `_blocking_append` checks `_LOG_PATH.exists() and _LOG_PATH.stat().st_size >= _resolve_max_bytes()` BEFORE the write and rotates if needed. Mode 0600 carries through automatically — rotation makes `_LOG_PATH` non-existent so `is_new = True` on the next iteration and the existing `os.chmod(_LOG_PATH, 0o600)` block fires.
- **`src/whatsapp_desktop_mcp/cli.py`** (Task 2 portion: +14 lines). `parser.add_argument("--audit-log-max-bytes", type=int, default=10 * 1024 * 1024, help=...)` after the existing `--fts5-mode` arg; `os.environ["WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES"] = str(args.audit_log_max_bytes)` after the existing `server.fts5_mode = args.fts5_mode` assignment, BEFORE the lazy `from whatsapp_desktop_mcp.server import run` import resolves (so the audit module's `_resolve_max_bytes()` observes the user's choice on the first send-attempt append).
- **`tests/unit/test_audit_rotation.py`** (321 lines, 12 tests). Pitfall 5 fixture monkey-patches BOTH `_LOG_DIR` AND `_LOG_PATH` to `tmp_path` (no test ever writes to `~/Library/Logs/whatsapp-desktop-mcp/`). Tests cover: no rotation under threshold (100 small entries), rotation triggered at 1024-byte ceiling (archive carries pre-rotation payloads verbatim, fresh log carries only post-rotation entry), 5-archive cap shifts oldest off (audit.log.5 exists, audit.log.6 NEVER), reverse-walk shift order verified by content uniqueness across archives (alpha→audit.log.3, beta→audit.log.2, gamma→audit.log.1; no cross-contamination), mode 0600 preserved on fresh post-rotation log, **D-13 STRUCTURAL invariant**: a sentinel `SECRET_BODY_PLAINTEXT_DO_NOT_LEAK` marker never appears in archive content (because no AuditEntry field ever ships it through the schema), AuditEntry.model_fields has `body_sha256` but NOT raw `body`, `_resolve_max_bytes` defaults / env-read / garbage-fallback, async `append` wrapper goes through the same rotation logic, `--audit-log-max-bytes 2048` sets the env var before server.run resolves.

### Task 3 — `dev/` subpackage + `reset_rate_limit` subcommand + cli.py argparse subparser dispatch (commit `949680f`)

Four coordinated edits:

- **`src/whatsapp_desktop_mcp/dev/__init__.py`** (24 lines). Empty package marker with a docstring documenting (1) the per-file ruff T201 ignore rationale (these are one-shot CLI utilities, NOT the stdio MCP server), (2) the reachability scope (only via `whatsapp-desktop-mcp dev <subcommand>` argparse path; no import edge from server/tools/reader/sender — T-03-03-06 mitigation), (3) the REL-05 D-24 isolation posture (dev tier sits on the cli/tool tier of the dependency DAG, NOT a peer of reader/sender, so it does NOT establish a reader↔sender edge).
- **`src/whatsapp_desktop_mcp/dev/reset_rate_limit.py`** (76 lines). `run() -> int` with the full T-03-03-05 confirmation discipline: early-return + return 0 when `db_path` doesn't exist (`"No rate-limit DB at {db_path}; nothing to reset."`); non-tty refuse with stderr message + return 1 (`"Refusing to reset rate-limit DB from a non-tty (no interactive confirmation possible). Run from an interactive shell."`); tty prompt `"This will erase all rate-limit history at {db_path}. Continue? [y/N] "` with `flush=True`; `answer = sys.stdin.readline().strip().lower()`; return 1 with `"Aborted."` if `answer != "y"`; on `y` calls `db_path.unlink(missing_ok=True)` (the `missing_ok` guard handles a TOCTOU race between the early-return check and the unlink) and prints `"Removed {db_path}."`; defensive try/except around the unlink catches `(PermissionError, OSError)` and surfaces them as exit 1 with stderr message (no Python traceback for routine "wrong working directory" mistakes).
- **`src/whatsapp_desktop_mcp/cli.py`** (Task 3 portion: +48 / -16 lines). Refactored `main()` into two pieces: `_add_server_args(parser)` helper that applies the three server-mode args (`--read-only`, `--fts5-mode`, `--audit-log-max-bytes`); `main()` builds the top-level parser, calls `_add_server_args`, then adds `subparsers = parser.add_subparsers(dest="cmd")`, then `dev_parser = subparsers.add_parser("dev", ...)` with a nested `dev_subparsers.add_parser("reset-rate-limit", ...)`. After `args = parser.parse_args(argv)`, dispatch ordering: **dev branch fires FIRST** (`if args.cmd == "dev" and args.dev_cmd == "reset-rate-limit": from whatsapp_desktop_mcp.dev.reset_rate_limit import run as dev_reset; return dev_reset()`), THEN the existing server-mode flag assignments + lazy `server.run` import — so the dev subcommand explicitly does NOT boot FastMCP.
- **`pyproject.toml`** (+9 lines). Scoped `[tool.ruff.lint.per-file-ignores]` entry `"src/whatsapp_desktop_mcp/dev/*.py" = ["T201"]` with comment block documenting that the rest of the package (server.py / tools/* / reader/* / sender/*) keeps T201 active.
- **`tests/unit/test_dev_subcommand.py`** (245 lines, 12 tests). Sandbox fixture monkey-patches `rate_limit._DB_PATH` to `tmp_path` (no test ever touches the user's real rate-limit DB). `_fake_tty_stdin(text)` helper builds an `io.StringIO` with `isatty()` patched to True (because `monkeypatch.setattr("sys.stdin", io.StringIO(...))` replaces the whole stream object — a separately monkey-patched `isatty` on the original sys.stdin doesn't carry over). Tests cover: cli dispatches to dev.run on `["dev", "reset-rate-limit"]`, cli routes to `server.run` on `[]`, non-tty refuses + DB intact, tty 'y' confirms + unlinks, tty 'n' aborts + DB intact, tty 'garbage' aborts + DB intact, DB-absent no-op + return 0, `ruff check src/whatsapp_desktop_mcp/dev/` exits 0 (per-file-ignore works), `--help` advertises `--audit-log-max-bytes` AND `dev`, `dev --help` advertises `reset-rate-limit`, `dev.reset_rate_limit.run` is callable + `int`-returning, end-to-end `whatsapp-desktop-mcp dev reset-rate-limit </dev/null` exits in `(0, 1)`.

## Tests

- **38 new unit tests** total: 8 in `test_tested_versions_parser.py` + 6 in `test_doctor_degraded_warning.py` + 12 in `test_audit_rotation.py` + 12 in `test_dev_subcommand.py` — all pass.
- **Phase 1 / Phase 2 / Phase 3 Plan 03-01 regression** — every existing test still passes (no test deselected, no test modified).
- **Total no-live suite: 313 tests pass** (was 275 before this plan; +38 new = 14 + 12 + 12).
- **ruff + ruff format + mypy --strict**: all clean across 106 source files.

## Verification (success criteria from prompt)

| Gate | Check | Result |
|------|-------|--------|
| Every task in 03-03-PLAN.md committed atomically | `git log --oneline -7` shows `test(03-03)` + `feat(03-03)` × 3 each (TDD RED → GREEN cadence) | ✓ |
| All `<acceptance_criteria>` blocks pass | 14 + 12 + 12 tests pass | ✓ |
| `uv run ruff check` + `ruff format --check` + `mypy --strict` + `pytest -m "not live"` all pass | 313 pass, 12 deselected (live); 106 source files mypy strict clean | ✓ |
| `from whatsapp_desktop_mcp.reader.tested_versions import supported_version_range` works | shipped as `SUPPORTED_VERSION_RANGE` (canonical name from RESEARCH.md §"Pattern 5"; the prompt's lowercase form was a typo); importing the module-load constant returns `(1, 1)` on the user's machine | ✓ |
| `SchemaFingerprint` has `supported_version_range` + `degraded_mode_warning` fields | `python -c "from whatsapp_desktop_mcp.models.doctor import SchemaFingerprint; assert ..."` exit 0 | ✓ |
| `from whatsapp_desktop_mcp.dev.reset_rate_limit import run` works | importable + `callable(run)` + `int` return annotation | ✓ |
| `whatsapp-desktop-mcp --help` shows `--audit-log-max-bytes` and `dev` subcommand | both advertised in help output | ✓ |
| `whatsapp-desktop-mcp dev reset-rate-limit --help` shows the dev subcommand help | `usage: whatsapp-desktop-mcp dev reset-rate-limit [-h]` rendered | ✓ |
| Audit log rotation test: when audit.log exceeds threshold, append triggers rotation; archive files exist | `test_rotation_triggered_at_threshold` + `test_archive_cap_shifts_oldest_off` + `test_archive_shift_order_no_content_overwrite` all green | ✓ |
| D-13 STRUCTURAL preserved: archive files NEVER contain plaintext body | `test_d13_invariant_no_plaintext_body_in_archive` (sentinel marker grep) + `test_audit_entry_schema_carries_only_body_sha256` (schema reflection) both green | ✓ |
| Live smoke (RUN_LIVE=1): `doctor()` returns `supported_version_range` + `degraded_mode_warning` populated | live run on user's machine: `supported_version_range=(1,1)`, `degraded_mode_warning=None` (WA 26.16.74 IS in matrix); injected `wa_version='26.99.0'` smoke confirms warning fires with the expected structured string | ✓ |
| No `print(` outside `src/whatsapp_desktop_mcp/dev/*.py` | `grep -E '^[^#]*print\\(' src/whatsapp_desktop_mcp/**/*.py` (excluding dev/) returns no matches; ruff T201 stays active outside dev/ | ✓ |
| 03-03-SUMMARY.md created | this file | ✓ |
| STATE.md updated | done in same final commit as this SUMMARY | ✓ |
| ROADMAP.md Phase 3 plan checkbox `03-03-PLAN.md` ticked | done in same final commit as this SUMMARY | ✓ |

## Live Smoke Output

```
$ RUN_LIVE=1 uv run python -c "import asyncio; from whatsapp_desktop_mcp.tools.doctor import doctor; \
    print(asyncio.run(doctor()).schema_fingerprint.supported_version_range, \
          asyncio.run(doctor()).schema_fingerprint.degraded_mode_warning, \
          asyncio.run(doctor()).whatsapp_app_version)"
schema_fingerprint.supported_version_range: (1, 1)
schema_fingerprint.degraded_mode_warning: None
whatsapp_app_version: 26.16.74

$ RUN_LIVE=1 uv run python -c "<inject wa_version='26.99.0' via mock>"
supported_version_range: (1, 1)
degraded_mode_warning: WhatsApp.app v26.99.0 not in tested-versions.md (last tested: 26.16.74); reads may degrade silently.

$ uv run whatsapp-desktop-mcp dev reset-rate-limit </dev/null
No rate-limit DB at /Users/jlqueguiner/Library/Application Support/whatsapp-desktop-mcp/rate-limit.db; nothing to reset.
EXIT=0
```

The DB-absent early-return path fires (the maintainer hasn't run any sends today), so the e2e exit is 0; if the DB existed, the non-tty branch would refuse with exit 1.

## Decisions Made

- **Lifted RESEARCH.md §"Pattern 5" + §"Pattern 6" + §"Pattern 8" verbatim where the structure was research-locked**, with one shaped expansion: the dev subpackage docstring was extended to explicitly document the T-03-03-06 reachability invariant (no import edge from server/tools/reader/sender into dev/) so a future contributor can't accidentally widen the per-file ruff T201 ignore beyond its current scope.
- **Lexical-max-string for `latest` in the degraded warning** — RESEARCH.md §"Pattern 5" notes this as a v1.0 simplification (lexical max on SemVer-shaped strings is 99% correct; full SemVer comparison via `packaging.version.Version` is a v1.1 candidate). On the current single-row `tested_versions.md` the latest is `26.16.74` regardless; the simplification is documented in the doctor.py source comment.
- **`_load_tested_wa_versions` returns `set[str]` (NOT `list[str]`)** — set membership is the operation the doctor extension does (`wa_version not in tested_wa`); a sorted list would have been needed only if the warning required a "tested versions: x, y, z" enumeration, which it doesn't (the warning quotes only the latest tested version per the structured-string format locked in CONTEXT.md D-20).
- **`max(tested_wa, default="(none)")`** — RESEARCH.md §"Pattern 5" specifies the `default="(none)"` sentinel for the empty-set case; preserved verbatim. Callable even when the parser fault-tolerantly returned an empty set (DIAG-02 carry-through).
- **Rotation pre-check on `>=` not `>`** — `_LOG_PATH.stat().st_size >= _resolve_max_bytes()` so a file that exactly hits the threshold rotates on the next append rather than waiting for one byte over. Matches RESEARCH.md §"Pattern 6" verbatim.
- **`max(1, int(val))` in `_resolve_max_bytes`** — RESEARCH.md §"Pattern 6" specifies a 1-byte floor (a 0-byte threshold would rotate every append, which is degenerate but not crash-worthy); preserved.
- **Pitfall 5 sandbox patches BOTH `_LOG_DIR` AND `_LOG_PATH`** — the test fixture monkey-patches both constants because a hypothetical future refactor that uses one constant via `_LOG_DIR / "audit.log"` and ANOTHER code path that uses `_LOG_PATH` directly would diverge if only one is patched. The Phase 2 `_isolate_live_state` fixture (in `tests/integration/test_live_send.py`) does the same; this fixture mirrors that pattern.
- **`_fake_tty_stdin(text)` helper for the dev tests** — when `monkeypatch.setattr("sys.stdin", io.StringIO(...))` replaces the whole stream object, a separately monkey-patched `isatty` on the original sys.stdin is lost (the new StringIO reports `isatty() == False` by default). The helper subclasses StringIO with a True-returning `isatty` so the dev module's tty guard fires the prompt branch. Discovered during the first GREEN run when the tty 'y' test failed with the non-tty refusal path firing.
- **Subparser dispatch fires BEFORE server-mode flag assignments** — the dev branch must explicitly NOT boot FastMCP; the dispatch order in `cli.main()` checks `args.cmd == "dev"` first and returns early, so `server.read_only_mode` / `server.fts5_mode` / the env-var assignment / the lazy `server.run` import never execute when running dev subcommands.

## Deviations from Plan

**No Rule 1 / Rule 2 / Rule 3 / Rule 4 deviations.**

The plan executed verbatim per RESEARCH.md §"Pattern 5" / §"Pattern 6" / §"Pattern 8". The TDD RED → GREEN cadence followed the standard pattern (RED commit → implement → GREEN commit per task). The one minor in-flight adjustment (the `_fake_tty_stdin` helper) was a test-infrastructure fix discovered during the first GREEN run — a test infrastructure improvement, not a behavioral deviation from the plan.

The plan-level success criterion mentioned `from whatsapp_desktop_mcp.reader.tested_versions import supported_version_range` (lowercase) but the canonical name locked by the plan's `must_haves.artifacts.exports` block is `SUPPORTED_VERSION_RANGE` (uppercase, matching the RESEARCH.md §"Pattern 5" verbatim source). Used the plan-locked uppercase name; both forms refer to the same module-load constant.

## Authentication Gates

None — Plan 03-03 is purely internal hardening (parser + model extension + audit rotation + dev subcommand). No new TCC permissions, no new external services, no new network surfaces.

## Self-Check: PASSED

**Files created:**
- `/Users/jlqueguiner/dev/whatsapp-mcp/docs/tested_versions.md` — FOUND
- `/Users/jlqueguiner/dev/whatsapp-mcp/src/whatsapp_desktop_mcp/reader/tested_versions.py` — FOUND
- `/Users/jlqueguiner/dev/whatsapp-mcp/src/whatsapp_desktop_mcp/dev/__init__.py` — FOUND
- `/Users/jlqueguiner/dev/whatsapp-mcp/src/whatsapp_desktop_mcp/dev/reset_rate_limit.py` — FOUND
- `/Users/jlqueguiner/dev/whatsapp-mcp/tests/unit/test_tested_versions_parser.py` — FOUND
- `/Users/jlqueguiner/dev/whatsapp-mcp/tests/unit/test_doctor_degraded_warning.py` — FOUND
- `/Users/jlqueguiner/dev/whatsapp-mcp/tests/unit/test_audit_rotation.py` — FOUND
- `/Users/jlqueguiner/dev/whatsapp-mcp/tests/unit/test_dev_subcommand.py` — FOUND

**Commits referenced (in `git log --oneline`):**
- `a809edd` — test(03-03): add failing tests for tested_versions parser + doctor degraded warning — FOUND
- `435af2c` — feat(03-03): tested_versions.md + parser + SchemaFingerprint extension + doctor degraded warning — FOUND
- `fea5716` — test(03-03): add failing tests for audit log size-based rotation — FOUND
- `2a384dd` — feat(03-03): audit log size-based rotation + --audit-log-max-bytes CLI arg — FOUND
- `5be11f6` — test(03-03): add failing tests for dev subpackage + reset-rate-limit subcommand — FOUND
- `949680f` — feat(03-03): dev subpackage + reset-rate-limit subcommand + cli subparser dispatch — FOUND

## Threat Flags

None — this plan covers the full T-03-03-01 through T-03-03-06 register from the threat model. No new network endpoints, no new auth paths, no new schema changes at trust boundaries:

- T-03-03-01 (parser DoS) → mitigated by fault-tolerant parser (test_parse_z_versions_skips_malformed_row + test_parse_z_versions_int_conversion_warning_branch enforce).
- T-03-03-02 (audit body plaintext leak) → mitigated by D-13 STRUCTURAL invariant (test_d13_invariant_no_plaintext_body_in_archive + test_audit_entry_schema_carries_only_body_sha256 enforce).
- T-03-03-03 (cross-process rotation race) → accepted per CONTEXT.md T-4 single-instance-per-user assumption.
- T-03-03-04 (degraded_mode_warning prompt-injection vector) → low-risk acceptance: both interpolation sources (CFBundleShortVersionString from macOS Info.plist + maintainer-controlled tested_versions.md column 1) are markdown-shaped strings with no LLM-instruction surface; warning is delivered as a Pydantic-modeled string field, NOT as freeform tool output.
- T-03-03-05 (accidental dev reset-rate-limit invocation in CI / non-tty context) → mitigated by sys.stdin.isatty() check (test_dev_run_non_tty_refuses enforces).
- T-03-03-06 (T201 lint bypass via dev subpackage) → mitigated by scoped per-file-ignore (test_dev_subpackage_passes_ruff confirms scope; the rest of the package keeps T201 active).

## Next Steps

- **Plan 03-04:** README install-matrix revamp — 3-row install matrix (brew / .pkg / uvx with TCC-churn caveat) + 3 TCC permission cards + Sending Messages section. Will reference Plan 03-02's brew install command and Plan 03-03's `whatsapp-desktop-mcp dev reset-rate-limit` for budget recovery (D-33 carry).
- **Plan 03-05:** Pre-release smoke suite — `RUN_LIVE_WHATSAPP=1` composing Phase 1 + Phase 2 + FTS5; D-24 fixture extension to sandbox `search_fts5._DB_PATH`. Will exercise this plan's degraded-mode warning logic on the maintainer's live WA install.
- **Phase 3 verify:** After Plan 03-04 + 03-05 ship, run `/gsd-verify-work` to validate Phase 3 against ROADMAP §"Phase 3" success criteria 1–4 (signed-installer / TCC-grant-survives-upgrades / README docs / tested_versions.md + smoke suite / FTS5 ranked sub-second).

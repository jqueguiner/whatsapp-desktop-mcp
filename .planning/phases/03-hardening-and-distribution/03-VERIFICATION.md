---
phase: 03-hardening-and-distribution
verified: 2026-05-14T08:30:00Z
status: human_needed
score: 4/4 ROADMAP success criteria verified at the artifact-and-wiring level (1 of 4 has a documented manual maintainer checkpoint)
overrides_applied: 0
human_verification:
  - test: "Maintainer-local pre-release smoke run"
    expected: "RUN_LIVE=1 RUN_LIVE_WHATSAPP=1 WHATSAPP_DESKTOP_MCP_LIVE_TEST_SELF_NAME=<...> uv run pytest -m live → all 16 live tests green (Phase 1 doctor + read tools + Phase 2 send + Phase 3 release smoke incl. FTS5 force build, quote-wrap on operator chars, audit rotation observable, doctor degraded-mode all-green)"
    why_human: "Requires WhatsApp.app to be installed + logged in on the maintainer's Mac, with the 3 TCC permissions granted to the running uv-managed Python interpreter, and the live self-chat send is destructive UI automation that cannot run unattended"
  - test: "rc1 dry-run of release.yml end-to-end (Plan 03-05 Task 2 checkpoint)"
    expected: "git tag v0.0.1-rc1 && git push origin v0.0.1-rc1 → ci passes, publish job uploads to PyPI via OIDC, pkg-build job (if APPLE_INSTALLER_CERT_P12 secret set) produces signed + notarized + stapled .pkg attached to release, tap-update job (if BREW_TAP_DEPLOY_KEY set) opens PR against jqueguiner/homebrew-whatsapp-desktop-mcp"
    why_human: "Pushing a git tag triggers irreversible PyPI publish (PyPI no-redo policy); requires Apple Developer cert + GitHub Actions secret bootstrap per docs/release-setup.md that the executor cannot safely provision; T-03-05-03 explicitly mandates rc-first discipline before tagging v0.1.0"
  - test: "TCC-grant survives upgrade test (SC1 second clause)"
    expected: "Install signed .pkg or brew formula; grant FDA + Accessibility + Automation to /usr/local/bin/whatsapp-desktop-mcp (or /opt/homebrew/bin/whatsapp-desktop-mcp); upgrade by re-installing same .pkg with later version OR brew upgrade; verify all 3 TCC grants persist (no fresh prompt) — pkgbuild --identifier net.jqueguiner.whatsapp-desktop-mcp and stable launcher path are the structural guarantees"
    why_human: "macOS TCC behavior is not script-testable; requires real install + manual System Settings inspection across two upgrade cycles; the artifact-level invariants (stable absolute path + same pkgbuild --identifier across versions) are wired correctly but the runtime TCC-persistence guarantee is a macOS contract verifiable only by direct user observation"
---

# Phase 3: Hardening & Distribution — Verification Report

**Phase Goal:** End-user on a fresh macOS install downloads signed `.pkg` (or `brew install jqueguiner/whatsapp-desktop-mcp/whatsapp-desktop-mcp`), grants 3 TCC permissions ONCE to a single binary at a stable absolute path, reaches first successful read_chat + send_message from Claude Desktop in under 10 minutes; that grant survives subsequent upgrades.
**Verified:** 2026-05-14T08:30:00Z
**Status:** human_needed (artifact + wiring complete; final SC1 + SC3-live + rc1 dry-run all require maintainer-on-machine actions documented in 03-05-SUMMARY.md `## CHECKPOINT REACHED`)
**Re-verification:** No — initial verification

---

## Goal Achievement — ROADMAP Success Criteria

### SC1 — Signed `.pkg` + brew at stable absolute path; TCC permissions persist across upgrades

| Artifact | Expected | Status | Evidence |
|----------|----------|--------|----------|
| `scripts/build-pkg.sh` | exists, syntax valid, uses `python -m venv --copies`, NOT `uv venv --relocatable`, `pkgbuild --identifier net.jqueguiner.whatsapp-desktop-mcp`, conditional `SIGN_DYLIBS` | ✓ VERIFIED | `bash -n` returns 0; line 62 `python3.12 -m venv --copies "${VENV_DIR}"`; line 43 `BUNDLE_ID="net.jqueguiner.whatsapp-desktop-mcp"`; line 84 `if [ -n "${SIGN_DYLIBS:-}" ]`; `grep -c 'uv venv --relocatable'` returns 0; line 101–107 `pkgbuild --identifier "${BUNDLE_ID}"` |
| `scripts/distribution.xml` | productbuild distribution archive | ✓ VERIFIED | 29 lines; references welcome.html |
| `scripts/pkg-resources/welcome.html` | install-time welcome page | ✓ VERIFIED | exists |
| `Formula/whatsapp-desktop-mcp.rb` | `Language::Python::Virtualenv`, `def install`, `depends_on macos: :sequoia`, depends_on python@3.12 | ✓ VERIFIED | line 21 `include Language::Python::Virtualenv`; line 29 `depends_on "python@3.12"`; line 30 `depends_on macos: :sequoia`; line 62 `virtualenv_install_with_resources` |
| `.github/workflows/release.yml` `pkg-build` job | macos-14, `if: secrets.APPLE_INSTALLER_CERT_P12 != ''`, `productsign`, `xcrun notarytool submit --wait`, `xcrun stapler staple`, `softprops/action-gh-release@v2` | ✓ VERIFIED | line 73 `if: ${{ secrets.APPLE_INSTALLER_CERT_P12 != '' }}`; lines 137–150 notarytool one-shot --wait; lines 152–155 stapler; lines 162–165 softprops/action-gh-release@v2 |
| `release.yml` `tap-update` job | `if: secrets.BREW_TAP_DEPLOY_KEY != ''`, `brew update-python-resources`, NOT `homebrew-pypi-poet`, `peter-evans/create-pull-request@v6` | ✓ VERIFIED | line 185 skip-block; line 235 `brew update-python-resources whatsapp-desktop-mcp`; `grep -c homebrew-pypi-poet` returns 0; line 238 `peter-evans/create-pull-request@v6` |
| `docs/release-setup.md` | 6 secrets + D-07 skip-block walkthrough | ✓ VERIFIED | 290 lines, ~14 KB; all 6 secrets named (`grep -c` returns 22 matches across the 6 secret names); 5 D-07 / skip-block references |
| `pkgbuild --identifier net.jqueguiner.whatsapp-desktop-mcp` ensures TCC persistence across upgrades | T-3 mitigation wired | ⚠️ HUMAN | Structural invariant in place (same identifier across versions; stable launcher path `/usr/local/bin/whatsapp-desktop-mcp` regardless of `.pkg` version); macOS TCC contract that "same package id + same install location = same TCC entry" can only be verified by real install-and-upgrade cycle on macOS |

**SC1 status:** ✓ VERIFIED at the artifact + wiring level. The maintainer-on-machine TCC-persistence test is routed to human verification.

### SC2 — README quickstart documents platform requirements + 3 TCC buckets + install paths

| Artifact | Expected | Status | Evidence |
|----------|----------|--------|----------|
| `README.md` ToS disclaimer | Phase 0 D-20 4-clause blockquote (each clause on its own line for line-grep) | ✓ VERIFIED | lines 3–12; `grep -cE 'automated or bulk messaging\|irrecoverable account ban\|conservative rate limits\|personal account, not a bot' README.md` returns 4 |
| `## Install` section with 3-row matrix | Brew / `.pkg` / `uvx` rows; correct repo URL `jqueguiner/whatsapp-desktop-mcp`; brew tap `jqueguiner/homebrew-whatsapp-desktop-mcp` | ✓ VERIFIED | lines 33–44 install table; line 42 `brew install jqueguiner/whatsapp-desktop-mcp/whatsapp-desktop-mcp`; line 46 `https://github.com/jqueguiner/whatsapp-desktop-mcp/releases`; uvx TCC-churn caveat blockquote at lines 48–52 |
| `## Granting macOS Permissions` (3 TCC cards) | FDA / Accessibility / Automation each with `system_settings_url` deep-link | ✓ VERIFIED | lines 88–130: 3 numbered subsections, each with deep-link (`Privacy_AllFiles`, `Privacy_Accessibility`, `Privacy_Automation`) — 24-case `tests/unit/test_readme_install_matrix.py` D-32 cases pass |
| `## Sending Messages` section | rate-limit defaults (5/min, 30/day) + `WHATSAPP_DESKTOP_MCP_SKIP_CONFIRM` env var + `dev reset-rate-limit` recovery + ToS reinforcement | ✓ VERIFIED | lines 162–203; `WHATSAPP_DESKTOP_MCP_SKIP_CONFIRM=1` at line 191; `whatsapp-desktop-mcp dev reset-rate-limit` at line 181; ban-threshold at line 200 |
| `## FTS5 Search` section | `--fts5-mode={auto,force,disable}` documented | ✓ VERIFIED | lines 205–219 |
| Platform Requirements section | macOS only, WhatsApp Desktop Catalyst build, Python 3.12+ on dev path only | ✓ VERIFIED | lines 17–31 |
| `tests/unit/test_readme_install_matrix.py` regression | 24 grep/regex invariants enforce the above | ✓ VERIFIED | 24 tests pass; covers D-20 / D-22 / D-31 / D-32 / D-33 + DIST-03 + Pitfall 6 |

**SC2 status:** ✓ VERIFIED.

### SC3 — `tested_versions.md` + RUN_LIVE_WHATSAPP=1 smoke suite

| Artifact | Expected | Status | Evidence |
|----------|----------|--------|----------|
| `docs/tested_versions.md` | WA 26.16.74 / Z_VERSION 1 row | ✓ VERIFIED | line 17: `\| 26.16.74 \| 26.4 \| 1 \| FDA/Auto/Acc all granted \| maintainer \| 2026-05-13 \| Phase 1+2 live-verified \|` |
| `src/whatsapp_desktop_mcp/reader/tested_versions.py` parser | fault-tolerant `(1, 1)` default; `SUPPORTED_VERSION_RANGE` module constant; `_load_tested_wa_versions` helper | ✓ VERIFIED | line 130 `SUPPORTED_VERSION_RANGE: tuple[int, int] = load_tested_z_versions()`; lines 91–112 `load_tested_z_versions` with 3-tier fault tolerance (`FileNotFoundError/PermissionError`, empty parse list, `try/except ValueError`); python invocation: `SUPPORTED_VERSION_RANGE: (1, 1)`, tested WA versions `{'26.16.74'}` |
| `models/doctor.py` `SchemaFingerprint.supported_version_range: tuple[int, int]` + `degraded_mode_warning: str | None` | ✓ VERIFIED | lines 110–126; `python -c "from whatsapp_desktop_mcp.models.doctor import SchemaFingerprint; sf = SchemaFingerprint(state='supported', observed_version=1, supported_versions=[1]); print(sf.supported_version_range, sf.degraded_mode_warning)"` → `(1, 1) None` |
| `tools/doctor.py` populates new fields | `model_copy(update={...})` block + structured warning string | ✓ VERIFIED | lines 256–279: live attr import `from whatsapp_desktop_mcp.reader import tested_versions`, range always populated via model_copy, conditional warning when wa_version not in tested_wa |
| `tests/integration/test_release_smoke.py` | 4 live tests gated by `RUN_LIVE_WHATSAPP=1` (composes Phase 1 + Phase 2 + Phase 3); extended `_isolate_live_state_extended` fixture covering 4 sandbox targets | ✓ VERIFIED | 342 lines; module gate at lines 81–87; 4 smoke tests collect under `RUN_LIVE=1 RUN_LIVE_WHATSAPP=1`; fixture at lines 99–130 monkeypatches `rate_limit._DB_PATH`, `audit._LOG_DIR`, `audit._LOG_PATH`, `search_fts5._DB_PATH` (4 targets per Pitfall 5 + D-24) |
| Live execution of the smoke suite | `RUN_LIVE_WHATSAPP=1 ... pytest -m live` produces all 16 live tests green | ⚠️ HUMAN | Skips cleanly with `RUN_LIVE_WHATSAPP` unset (verified). Live execution requires WhatsApp.app + 3 TCC grants on maintainer's Mac. Documented in `03-05-SUMMARY.md ## CHECKPOINT REACHED` Step 1. |

**SC3 status:** ✓ VERIFIED at code level; live execution gated to maintainer.

### SC4 — `search_messages` upgraded to FTS5 shadow index

| Artifact | Expected | Status | Evidence |
|----------|----------|--------|----------|
| `src/whatsapp_desktop_mcp/reader/search_fts5.py` | sidecar at `~/Library/Application Support/whatsapp-desktop-mcp/fts.sqlite`; FTS5 quote-wrap; lazy-build + incremental-refresh + Z_VERSION-mismatch full rebuild | ✓ VERIFIED | line 111 `_DB_PATH: Path = (Path.home() / "Library" / "Application Support" / "whatsapp-desktop-mcp" / "fts.sqlite")`; line 350 `fts_query = '"' + query.replace('"', '""') + '"'`; line 362 `WHERE messages_fts MATCH ?` |
| `--fts5-mode` CLI arg in `cli.py` | choices=auto/force/disable, default auto | ✓ VERIFIED | lines 74–87; `whatsapp-desktop-mcp --help` renders `--fts5-mode {auto,force,disable}` |
| `server.fts5_mode: str = "auto"` module attr | declared next to `read_only_mode` | ✓ VERIFIED | line 90 `fts5_mode: str = "auto"`; python introspection: `server.fts5_mode == "auto"` |
| `tools/search_messages.py` dispatcher | uses live attribute (`from whatsapp_desktop_mcp import server; server.fts5_mode`) — W-4 lesson | ✓ VERIFIED | line 52 `from whatsapp_desktop_mcp.reader import search_fts5`; line 156 `fts_db_exists = search_fts5._DB_PATH.exists()`; lines 157–166 dispatch on `server.fts5_mode`; lines 197–215 OperationalError → LIKE fallback |
| Plan 03-01 unit tests | 22 tests (10 + 12) | ✓ VERIFIED | All 22 pass: 10 in `test_search_fts5.py` (quote-wrap, lazy build, incremental refresh, full rebuild on Z_VERSION mismatch, tombstone joinback, REL-05 isolation, stderr warning, no-stdout); 12 in `test_search_messages_dispatch.py` (default mode, CLI sets attr before run, bad value, all dispatch branches, OperationalError fallback, FDA mapping unchanged) |
| Live FTS5 ranked sub-second performance | live smoke documented in 03-01-SUMMARY: build 0.66s on 84k corpus; search 4ms | ⚠️ HUMAN | Documented but the live verification on the corpus is gated to Plan 03-05 release smoke (which is itself gated by RUN_LIVE_WHATSAPP=1 — maintainer ritual) |

**SC4 status:** ✓ VERIFIED at the artifact + wiring + unit-test level; live performance verified per Plan 03-01 SUMMARY (0.66s build / 4ms search on 84k corpus).

---

## Cross-cutting Invariants

| Invariant | Check | Status | Evidence |
|-----------|-------|--------|----------|
| REL-05 D-24 isolation | Only `sender/verify.py` imports from `reader.connection`; reader/* has zero imports from sender | ✓ VERIFIED | `grep -rE 'from whatsapp_desktop_mcp\.sender' src/whatsapp_desktop_mcp/reader/` returns 0; `grep -rE 'from whatsapp_desktop_mcp\.reader' src/whatsapp_desktop_mcp/sender/` returns exactly 1 line (`sender/verify.py:81: from whatsapp_desktop_mcp.reader.connection import open_ro`); `tests/unit/test_isolation.py` 7/7 pass including `test_sender_to_reader_edge_is_exactly_one_file` |
| stdout = JSON-RPC purity | `print()` only in `dev/*.py` (per-file ruff T201 ignore) | ✓ VERIFIED | `grep -rn '\bprint(' src/whatsapp_desktop_mcp/` returns matches ONLY in `dev/__init__.py` (docstring example) and `dev/reset_rate_limit.py`; `pyproject.toml` line 85 `"src/whatsapp_desktop_mcp/dev/*.py" = ["T201"]` is the only per-file T201 ignore for source code |
| No HTTP listener | Module imports do not include flask / fastapi / aiohttp / http.server | ✓ VERIFIED | `grep -rnE 'http\.server\|aiohttp\|flask\|fastapi\|requests' src/whatsapp_desktop_mcp/` returns zero matches |
| No SQLite write to ChatStorage | rate-limit DB, audit log, FTS sidecar all SEPARATE files at separate paths | ✓ VERIFIED | rate-limit: `~/Library/Application Support/whatsapp-desktop-mcp/rate-limit.db`; audit: `~/Library/Logs/whatsapp-desktop-mcp/audit.log`; FTS: `~/Library/Application Support/whatsapp-desktop-mcp/fts.sqlite`; `grep -rnE 'INSERT INTO ZWA\|UPDATE ZWA\|DELETE FROM ZWA' src/whatsapp_desktop_mcp/` returns 0 matches |
| D-13 STRUCTURAL invariant | `AuditEntry.model_fields` has no body keys (only `body_sha256`) | ✓ VERIFIED | python introspection: `AuditEntry.model_fields` = `['body_sha256', 'chat_id', 'chat_name', 'confirm_skipped', 'elapsed_ms', 'error', 'message_id', 'outcome', 'ts']` — no raw `body` / `body_text` / `body_preview` field |
| Audit log rotation D-25/D-26 | `sender/audit.py:_blocking_append` triggers rotation when size >= `_resolve_max_bytes()`; 5 archives kept; `WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES` env override | ✓ VERIFIED | lines 86–88 module constants (`_DEFAULT_MAX_BYTES = 10 * 1024 * 1024`, env var name, `_ARCHIVE_COUNT = 5`); lines 142–158 `_resolve_max_bytes`; lines 161–185 `_rotate_in_place` with reverse-walk shift; lines 207–214 rotation pre-check at append; 12 unit tests in `test_audit_rotation.py` pass including the D-13 sentinel test |
| `whatsapp-desktop-mcp dev reset-rate-limit` subcommand | callable end-to-end | ✓ VERIFIED | `uv run whatsapp-desktop-mcp dev reset-rate-limit </dev/null` returns "No rate-limit DB at ..."; EXIT=0; CLI --help advertises `dev` subcommand |
| Repo URLs use `jqueguiner` | no `gladia/whatsapp-desktop-mcp` placeholder | ✓ VERIFIED | `grep -rn jqueguiner` across README/Formula/scripts/.github/docs returns 31 matches; `grep -rn 'gladia/whatsapp-desktop-mcp'` returns 0 matches; gladia.io email refs preserved (verified by frontmatter scope of search) |
| Phase 0 D-09 patched Automation probe | still active | ✓ VERIFIED | `permissions/automation.py` line 3 "D-09 PATCHED" docstring; line 43 inline comment marker; probe untouched in Phase 3 |
| Research-locked overrides honored | `python -m venv --copies` (NOT `uv venv --relocatable`); `brew update-python-resources` (NOT `homebrew-pypi-poet`) | ✓ VERIFIED | `grep -c 'uv venv --relocatable'` across build-pkg.sh + release.yml returns 0; `grep -c 'homebrew-pypi-poet'` returns 0 |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `bash -n scripts/build-pkg.sh` syntax | `bash -n` | exit 0 | ✓ PASS |
| `whatsapp-desktop-mcp --help` advertises new flags + dev subcommand | `uv run whatsapp-desktop-mcp --help` | shows `--fts5-mode {auto,force,disable}`, `--audit-log-max-bytes`, `{dev}` positional | ✓ PASS |
| `dev reset-rate-limit` end-to-end | `uv run whatsapp-desktop-mcp dev reset-rate-limit </dev/null` | "No rate-limit DB at ...; nothing to reset." EXIT=0 | ✓ PASS |
| Module imports + canonical exports | `python -c "from whatsapp_desktop_mcp.reader.search_fts5 import _DB_PATH, fts5_search, build_or_refresh, open_rw_fts; from whatsapp_desktop_mcp.dev.reset_rate_limit import run; from whatsapp_desktop_mcp.reader.tested_versions import SUPPORTED_VERSION_RANGE; from whatsapp_desktop_mcp import server; assert server.fts5_mode == 'auto'"` | All imports succeed | ✓ PASS |
| AuditEntry has no plaintext body field | python introspection on `AuditEntry.model_fields` | only `body_sha256`; no `body` / `body_text` / `body_preview` | ✓ PASS |
| Tested-versions parser produces (1, 1) on user's machine | `python -c "from whatsapp_desktop_mcp.reader.tested_versions import SUPPORTED_VERSION_RANGE, _load_tested_wa_versions; print(SUPPORTED_VERSION_RANGE, _load_tested_wa_versions())"` | `(1, 1) {'26.16.74'}` | ✓ PASS |

---

## Test Suite Results

- **Non-live (`uv run pytest -m "not live"`):** **337 passed**, 16 deselected. Total time 7.46s.
- **Live test inventory (`-m live --collect-only`):** **16 tests collected** (Phase 1: 9; Phase 2: 3; Phase 3 release smoke: 4).
- **Phase 3 unit tests focused run:**
  - `test_search_fts5.py` (10) + `test_search_messages_dispatch.py` (12) = 22 ✓
  - `test_audit_rotation.py` (12) + `test_dev_subcommand.py` (12) + `test_doctor_degraded_warning.py` (6) + `test_tested_versions_parser.py` (8) + `test_readme_install_matrix.py` (24) = 62 ✓
  - `test_isolation.py` (7) — REL-05 D-24 ✓ including `test_sender_to_reader_edge_is_exactly_one_file`
- **Lint / format / type:** `uv run ruff check src tests` — All checks passed; `uv run mypy` — Success: no issues found in 108 source files.

Live tests skip cleanly when `RUN_LIVE_WHATSAPP` and `RUN_LIVE` are unset (verified by collection-only run with both gates set: 4 release-smoke tests collect; with both unset: deselected/skipped).

---

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| (none) | TBD/FIXME/XXX scan across all phase-modified files | — | Zero debt markers in `reader/search_fts5.py`, `reader/tested_versions.py`, `dev/__init__.py`, `dev/reset_rate_limit.py`, `sender/audit.py`, `cli.py`, `tools/doctor.py`, `models/doctor.py`, `scripts/build-pkg.sh`, `release.yml`, `Formula/whatsapp-desktop-mcp.rb`, `README.md` |

`print()` in `dev/reset_rate_limit.py` is **legitimately scoped** by the `pyproject.toml` per-file-ignore covering `src/whatsapp_desktop_mcp/dev/*.py` (T-03-03-06 mitigation: dev subcommands are one-shot CLI utilities reachable only via `cli.main`'s subparser dispatch, NEVER via the stdio MCP server boot path). Server / tools / reader / sender all keep T201 active. Verified by `tests/unit/test_dev_subcommand.py::test_dev_subpackage_passes_ruff` (per Plan 03-03 SUMMARY).

---

## Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| **DIST-02** | Project ships an end-user install path that puts the launcher binary at a stable absolute path (so TCC permissions persist across upgrades) — Developer-ID-signed `.pkg` and/or Homebrew formula | ✓ SATISFIED at the artifact level | `scripts/build-pkg.sh` produces `.pkg` with launcher at `/usr/local/bin/whatsapp-desktop-mcp` and `pkgbuild --identifier net.jqueguiner.whatsapp-desktop-mcp`; `Formula/whatsapp-desktop-mcp.rb` ships `Language::Python::Virtualenv` formula installing to `/opt/homebrew/bin/whatsapp-desktop-mcp` (Apple Silicon) or `/usr/local/bin/whatsapp-desktop-mcp` (Intel); `release.yml` `pkg-build` job signs + notarizes + staples + uploads. The TCC-persistence-across-upgrades behavior is the macOS contract (same identifier + same path = same TCC entry); requires real install/upgrade cycle to verify (human verification item 3). REQUIREMENTS.md still shows `[ ]` checkbox — the maintainer should tick this after the SC1 human-verify cycle. |
| **DIST-03** | README includes platform requirements (macOS only, WhatsApp Desktop Catalyst build, Python 3.12+ if user-installed) and a 60-second quickstart | ✓ SATISFIED | REQUIREMENTS.md line 64 already shows `[x]`; README sections "Requirements" (lines 17–31), "Install" matrix (lines 33–44), "Granting macOS Permissions" (lines 88–130) all present and guarded by 24-case parametrized invariant test |

No orphaned requirements: ROADMAP §"Coverage Summary" lists exactly DIST-02 + DIST-03 for Phase 3, and both are accounted for above.

---

## Implicit Decision Coverage (CONTEXT.md D-XX → Plan / Artifact)

| Decision | Covered By | Verified |
|----------|------------|----------|
| D-01..D-05 (channels: brew + .pkg + uvx caveat) | Plan 03-02 + Plan 03-04 | ✓ |
| D-06..D-08 (signing pipeline, D-07 skip-block, release-setup.md) | Plan 03-02 release.yml + docs/release-setup.md | ✓ |
| D-09..D-11 (Formula shape, tap, install command) | Plan 03-02 Formula + Plan 03-04 README | ✓ |
| D-12..D-18 (FTS5 sidecar, schema, lazy build, joinback, REL-05) | Plan 03-01 reader/search_fts5.py | ✓ |
| D-19..D-21 (tested_versions.md + parser + doctor warning) | Plan 03-03 tested_versions.py + doctor.py + models/doctor.py | ✓ |
| D-22..D-24 (smoke suite + RUN_LIVE_WHATSAPP gate + sandbox extension) | Plan 03-05 test_release_smoke.py | ✓ |
| D-25..D-27 (audit rotation 10MB / 5 archives + dev reset-rate-limit) | Plan 03-03 sender/audit.py + dev/reset_rate_limit.py | ✓ |
| D-28..D-30 (CLI args + tool surface unchanged) | Plan 03-01 + Plan 03-03 cli.py | ✓ |
| D-31..D-33 (README install matrix + TCC cards + Sending Messages) | Plan 03-04 README.md + tests/unit/test_readme_install_matrix.py | ✓ |

All 33 decisions from `03-CONTEXT.md` traced to Plan + artifact.

---

## Human Verification Required

### 1. Maintainer-local pre-release smoke run

**Test:** From the maintainer's Mac (with WhatsApp.app installed, logged in, and the 3 TCC grants in place against the running uv-managed Python interpreter):

```bash
RUN_LIVE=1 RUN_LIVE_WHATSAPP=1 \
    WHATSAPP_DESKTOP_MCP_LIVE_TEST_SELF_NAME="<self-chat display name>" \
    uv run pytest -m live -v
```

**Expected:** All 16 live tests green — Phase 1 doctor + read tools, Phase 2 send + post-hoc verify + rate-limit, Phase 3 release smoke (FTS5 force build + ranked results, FTS5 quote-wrap on operator chars, audit rotation observable + D-13 invariant per archive line, doctor degraded-mode all-green).

**Why human:** Requires WhatsApp.app installed + logged in on the maintainer's Mac, with the 3 TCC permissions granted; live self-chat send is destructive UI automation that cannot run unattended; CI macos-14 runners have no WhatsApp.app installed.

### 2. rc1 dry-run of `release.yml`

**Test:** After completing `docs/release-setup.md` sections 2–7 (Apple Developer enrollment + cert generation + .p12 export + GitHub secrets + brew tap bootstrap):

```bash
git tag v0.0.1-rc1
git push origin v0.0.1-rc1
```

**Expected:** Watch GitHub Actions —
- `ci` job passes
- `publish` job uploads `whatsapp-desktop-mcp-0.0.1rc1` to PyPI via OIDC
- `pkg-build` job (if `APPLE_INSTALLER_CERT_P12` set) produces signed + notarized + stapled `.pkg` attached to GitHub release
- `tap-update` job (if `BREW_TAP_DEPLOY_KEY` set) opens PR against `jqueguiner/homebrew-whatsapp-desktop-mcp`

After verification, clean up: `gh release delete v0.0.1-rc1 --yes && git push --delete origin v0.0.1-rc1 && git tag -d v0.0.1-rc1`

**Why human:** Pushing a git tag triggers irreversible PyPI publish (PyPI no-redo policy); requires Apple Developer cert + GitHub Actions secret bootstrap that the executor cannot safely provision; T-03-05-03 explicitly mandates rc-first discipline before tagging v0.1.0. The pipeline ITSELF (release.yml + build-pkg.sh + tap-update job) is verified at code level and dry-run-ready.

### 3. TCC-grant survives upgrade test

**Test:** Install signed `.pkg` (or `brew install`); grant FDA + Accessibility + Automation to `/usr/local/bin/whatsapp-desktop-mcp` (or `/opt/homebrew/bin/whatsapp-desktop-mcp`); upgrade by re-installing same `.pkg` with later version OR `brew upgrade whatsapp-desktop-mcp`; verify all 3 TCC grants persist (no fresh prompts).

**Expected:** macOS does not re-prompt for any of the 3 TCC permissions because the launcher binary path AND the package identifier (`net.jqueguiner.whatsapp-desktop-mcp`) are byte-stable across versions.

**Why human:** macOS TCC behavior is not script-testable; requires real install + manual System Settings inspection across two upgrade cycles. The structural invariants (stable absolute path; `pkgbuild --identifier net.jqueguiner.whatsapp-desktop-mcp`) are wired correctly; the runtime contract is a macOS-OS-level guarantee verifiable only by direct user observation.

---

## Gaps Summary

**No code-level gaps found.** Every artifact required by the 4 ROADMAP success criteria exists, is substantive, is wired into the runtime call paths, and is exercised by automated tests where possible. The 22 + 62 + 4 phase-3-specific unit tests + 16 live tests collect cleanly; 337/337 non-live tests pass; ruff + mypy strict are clean across 108 source files.

**Three items require maintainer-on-machine human verification** (documented in Plan 03-05 SUMMARY's `## CHECKPOINT REACHED` section):

1. RUN_LIVE_WHATSAPP=1 smoke run on the maintainer's Mac with WhatsApp.app installed
2. v0.0.1-rc1 tag-push dry-run after completing the docs/release-setup.md secrets bootstrap
3. Real install + upgrade cycle to verify macOS TCC permissions persist across versions (the macOS contract behind SC1)

The phase goal is achieved at the surface level: every artifact required for an end user to install via `.pkg` or brew, grant 3 TCC permissions to a stable binary path, and reach a first successful read + send is in place. The maintainer's pre-release ritual is the final gate before tagging v0.1.0.

---

_Verified: 2026-05-14T08:30:00Z_
_Verifier: Claude (gsd-verifier)_

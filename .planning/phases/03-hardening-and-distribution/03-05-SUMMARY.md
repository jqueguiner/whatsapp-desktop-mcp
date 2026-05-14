---
phase: 03-hardening-and-distribution
plan: 05
subsystem: testing
tags: [pytest, live-integration, smoke, fts5, audit-rotation, sandbox, release-gate]

# Dependency graph
requires:
  - phase: 01-read-mvp-read-only
    provides: tests/integration/test_live_doctor.py + test_live_reader.py (Phase 1 live read tools — composed by smoke discovery)
  - phase: 02-send-ui-automation-guardrails
    provides: tests/integration/test_live_send.py + B-2 _isolate_live_state autouse fixture pattern (rate_limit + audit sandbox)
  - phase: 03-hardening-and-distribution
    provides: Plan 03-01 FTS5 sidecar (search_fts5._DB_PATH + dispatcher); Plan 03-03 doctor degraded_mode_warning + audit rotation; Plan 03-04 README install matrix
provides:
  - "tests/integration/test_release_smoke.py: 4 live-marked smoke tests gated by RUN_LIVE_WHATSAPP=1 (in addition to per-module RUN_LIVE=1) — composes Phase 1+2+3 surfaces under one release-gate ritual"
  - "_isolate_live_state_extended autouse fixture: D-24 sandbox extension covering all 4 production-state targets (rate_limit._DB_PATH, audit._LOG_DIR, audit._LOG_PATH, search_fts5._DB_PATH); Phase 2's _isolate_live_state in test_live_send.py stays BYTE-STABLE"
  - "Documented maintainer pre-release ritual in module docstring: RUN_LIVE=1 RUN_LIVE_WHATSAPP=1 uv run pytest -m live → green → git tag v0.x.0 → git push --tags"
affects: [Phase 3 verification gate; all future v0.x.0 release tags; Plan 03-02 release.yml dry-run via v0.0.1-rc1]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RUN_LIVE_WHATSAPP=1 release-gate env var (composed AFTER per-module RUN_LIVE=1 — two env vars together for maintainer ritual; keeps CI quick suite fully gated)"
    - "Module-scoped autouse fixture override extends an outer-scope fixture's monkey-patch set without modifying the source-of-truth fixture (D-24 single-source-of-truth structural sandbox preserved)"
    - "Pre-release smoke as composition over re-implementation — pytest discovery picks up Phase 1 + Phase 2 live test modules automatically; new module adds only Phase 3-specific assertions"

key-files:
  created:
    - "tests/integration/test_release_smoke.py — 342 lines, 4 live tests + autouse FTS-extended sandbox fixture"
  modified:
    - ".planning/STATE.md — Phase 3 transitions to 5/5 plans complete; pending verification"
    - ".planning/ROADMAP.md — 03-05 plan checkbox ticked; Phase 3 row updated to Pending verification"

key-decisions:
  - "D-24 fixture extension lives ONLY in test_release_smoke.py via _isolate_live_state_extended; Phase 2's _isolate_live_state in test_live_send.py is BYTE-STABLE (verified zero diff). Phase 2 send tests don't fire FTS5 codepaths so the narrower Phase 2 fixture remains correct for that scope."
  - "RUN_LIVE_WHATSAPP env var composes ON TOP of (not replaces) per-module RUN_LIVE: maintainer runs RUN_LIVE=1 RUN_LIVE_WHATSAPP=1 uv run pytest -m live; CI's pytest -m \"not live\" continues to skip everything live-marked unchanged."
  - "Audit-rotation smoke test does NOT require RUN_LIVE_WHATSAPP itself (pure audit-module exercise — no WhatsApp send), but lives in test_release_smoke.py per CONTEXT.md D-22 composition spirit. The module-level skipif still applies, keeping the suite cleanly gated."
  - "Task 2 (rc1 dry-run) is documented as a manual maintainer gate rather than auto-executed — pushing a git tag triggers irreversible PyPI publish (PyPI no-redo policy); requires Apple Developer cert + GitHub Actions secret bootstrap that the executor cannot provide."

patterns-established:
  - "Pattern 1: Compose-don't-rewrite live test gating — new module adds Phase 3 assertions; Phase 1 + Phase 2 live modules carried in via pytest discovery rather than imported."
  - "Pattern 2: Module-scoped autouse fixture extends outer-scope fixture — _isolate_live_state_extended adds the FTS sidecar target on top of the Phase 2 sandbox without editing the Phase 2 fixture body."
  - "Pattern 3: Two-env-var composition (RUN_LIVE + RUN_LIVE_WHATSAPP) — phase-specific gates compose via AND-of-skips; the maintainer ritual sets both."

requirements-completed: []  # Plan 03-05 frontmatter declares no requirements; closes ROADMAP §"Phase 3" Success Criterion 3 (smoke suite) operationally.

# Metrics
duration: 3 min 13 s
completed: 2026-05-14
---

# Phase 3 Plan 05: Pre-release smoke suite Summary

**RUN_LIVE_WHATSAPP=1-gated live smoke suite composing Phase 1 + Phase 2 + Phase 3 surfaces with D-24 FTS-extended sandbox; Phase 2 _isolate_live_state stays byte-stable.**

## Performance

- **Duration:** 3 min 13 s
- **Started:** 2026-05-14T06:23:59Z
- **Completed:** 2026-05-14T06:27:12Z
- **Tasks:** 1 of 2 executed (Task 2 documented as manual maintainer checkpoint — see below)
- **Files created:** 1 (`tests/integration/test_release_smoke.py`, 342 lines)
- **Files modified for the plan itself:** 0 (Phase 2's `test_live_send.py` is byte-stable per D-24 single-source-of-truth)

## Accomplishments

- New `tests/integration/test_release_smoke.py` (342 lines, 4 tests, all live + RUN_LIVE_WHATSAPP=1 gated):
  - `test_release_smoke_doctor_all_green` — composes Phase 1 DIAG-01 + Plan 03-03 D-20 surface: asserts `all_granted=True`, `schema_fingerprint.state=='supported'`, `degraded_mode_warning is None`, `whatsapp_app_version` semver-shaped, `last_message_ts` within 30 days.
  - `test_release_smoke_fts5_path` — composes Plan 03-01 surface: `server.fts5_mode='force'` lazy-builds the sandboxed FTS sidecar + returns ranked results; finally-block resets `fts5_mode` to `auto`.
  - `test_release_smoke_fts5_quote_wrap_smoke` — composes Pitfall 1 / T-03-01-02 mitigation: `search_messages(query="meeting (test)")` under `fts5_mode='force'` MUST NOT raise `sqlite3.OperationalError`.
  - `test_release_smoke_audit_rotation_observable` — composes Plan 03-03 D-25 surface: 8 audit appends with `WHATSAPP_DESKTOP_MCP_AUDIT_LOG_MAX_BYTES=512` produce `audit.log.1`; D-13 STRUCTURAL invariant verified on each rotated archive line (`body_sha256` present, raw `body` / `body_text` / `body_preview` absent).
- D-24 sandbox extension via `_isolate_live_state_extended` autouse fixture: monkey-patches all 4 production-state targets to `tmp_path` — `rate_limit._DB_PATH`, `audit._LOG_DIR` AND `audit._LOG_PATH` (Pitfall 5: BOTH required), and the new `reader.search_fts5._DB_PATH`.
- Phase 2's `tests/integration/test_live_send.py::_isolate_live_state` is **byte-stable** (zero git diff) — D-24 single-source-of-truth structural sandbox preserved by scoping the extension to the new module only.
- 337 non-live tests stay green; ruff + ruff-format + mypy --strict clean across 108 source files.
- Module docstring documents the maintainer pre-release ritual end-to-end (env vars, expected timing, failure-mode interpretation).

## Task Commits

1. **Task 1: tests/integration/test_release_smoke.py + extended sandbox** — `adf8fdd` (test)

**Plan metadata:** (this commit) `docs(03-05): complete pre-release smoke suite plan`

## Files Created/Modified

- `tests/integration/test_release_smoke.py` (NEW, 342 lines) — 4 live smoke tests + `_isolate_live_state_extended` autouse fixture; module docstring composes Phase 1+2+3 ritual; module-level `pytestmark` declares `pytest.mark.live` + `RUN_LIVE_WHATSAPP=1` skipif.

## Decisions Made

- **Phase 2 fixture stays byte-stable.** Investigated whether Phase 2's send tests fire any FTS5 codepath — they do not (the send tool path is search-free). Therefore the FTS sandbox extension lives ONLY in the smoke module's own autouse fixture. D-24 lock honored exactly as written: "single-source-of-truth structural sandbox" + "leave UNCHANGED if a tiny extension is required" — no edit was required.
- **Audit-rotation smoke included** (Plan 03-05 acknowledges this as optional). Rationale: rotation correctness is part of the v1.0 release contract per Plan 03-03 D-25, and verifying it end-to-end via the rotated archive's D-13 invariant fits naturally inside the smoke suite without firing any WhatsApp UI.
- **`server.fts5_mode` reset doubled-up in the finally blocks** (`= "auto"` then `= prior_mode`) — defensive against a future test injecting a non-default value before this test; no functional difference today (`prior_mode == "auto"` always in v0.1) but byte-stable against future edits.
- **Plan 03-05 grep gates passed with comfortable margin** (counts 2-7, all gates expected `>=1`). No fudging required.

## Deviations from Plan

None — plan executed exactly as written, including the tighter D-24 lock that explicitly preferred no edit to `test_live_send.py` if the fixture extension could live in `test_release_smoke.py` alone (it could; verified).

## Issues Encountered

None.

## Self-Check: PASSED

- File `tests/integration/test_release_smoke.py` exists (342 lines).
- Commit `adf8fdd` exists in `git log`.
- 4 live tests collect under `pytest --collect-only`.
- All 4 tests skip cleanly with `RUN_LIVE_WHATSAPP` unset (exit 0).
- All 8 grep gates from `<verify>` pass with counts ≥ expected.
- 337 non-live tests stay green (was 337; smoke tests are live-only and don't add to non-live count).
- Ruff + ruff-format + project-wide mypy --strict all clean.

---

## CHECKPOINT REACHED

**Type:** human-verify
**Plan:** 03-05
**Progress:** 1/2 tasks executed; Task 2 deferred to maintainer

### Why the executor stopped here

Task 2 of the plan is a `type="checkpoint:human-verify"` gate that exercises the full release pipeline end-to-end. It requires actions the executor cannot safely perform automatically:

1. **Real `git tag v0.0.1-rc1 && git push origin v0.0.1-rc1`** — pushing a tag triggers `.github/workflows/release.yml` (Plan 03-02), which runs the **publish job** (PyPI upload via OIDC). PyPI does NOT allow re-uploading a version after deletion; an accidental push burns the version forever. CONTEXT.md threat model T-03-05-03 explicitly flags this as the rationale for the rc1 dry-run discipline. The executor's deviation rules forbid pushing git tags from this plan.
2. **Apple Developer Installer cert + GitHub secrets** — the `pkg-build` job needs `APPLE_INSTALLER_CERT_P12`, `APPLE_INSTALLER_CERT_PASSWORD`, `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_SPECIFIC_PASSWORD` set per `docs/release-setup.md`. The executor cannot provision these.
3. **Live WhatsApp UI verification on the maintainer's Mac** — Phase 1 + Phase 2 + Phase 3 live tests are gated on `WHATSAPP_DESKTOP_MCP_LIVE_TEST_SELF_NAME` and run real WhatsApp sends; the maintainer must opt in.

The smoke suite code itself (Task 1) is shipped and the gate is now ready for the maintainer to run.

### What the maintainer needs to do (5 sequential steps)

**Step 1 — Run the smoke suite locally** (maintainer's Mac, WhatsApp.app installed, all 3 TCC grants in place):

```bash
RUN_LIVE=1 RUN_LIVE_WHATSAPP=1 \
    WHATSAPP_DESKTOP_MCP_LIVE_TEST_SELF_NAME="<your self-chat display name>" \
    uv run pytest -m live -v
```

Expected: every test passes. Specifically:
- `test_release_smoke_doctor_all_green` reports `all_granted=True`, `schema_fingerprint.state=='supported'`, `degraded_mode_warning is None`, `whatsapp_app_version` matches `/Applications/WhatsApp.app/Contents/Info.plist`'s `CFBundleShortVersionString`, `last_message_ts` is recent.
- `test_release_smoke_fts5_path` lazy-builds the sidecar (10-30 s on a ~100k corpus per RESEARCH §A4; sub-second on smaller corpora) and returns ranked results.
- `test_release_smoke_fts5_quote_wrap_smoke` returns 0+ results without `sqlite3.OperationalError` (Pitfall 1 mitigation verified live).
- `test_release_smoke_audit_rotation_observable` produces `audit.log.1` and verifies the D-13 invariant on every rotated line.
- Phase 1's `test_live_doctor.py` + `test_live_reader.py`: every read tool succeeds.
- Phase 2's `test_live_send.py`: send tools succeed (rate-limit-burning test fires only if `RUN_LIVE_BURN_BUDGET=1` is also set; otherwise it skips).

**Step 2 — Verify the maintainer's Mac is left in clean state** (Pitfall 5 sandbox correctness):

```bash
ls -la ~/Library/Logs/whatsapp-desktop-mcp/ 2>/dev/null
ls -la ~/Library/Application\ Support/whatsapp-desktop-mcp/ 2>/dev/null
```

Expected: only pre-existing production files. No `audit.log.1` from the smoke run; no `fts.sqlite` mtime change from the smoke run.

**Step 3 — Spot-check the dev reset-rate-limit subcommand** (Plan 03-03 Task 3 surface):

```bash
whatsapp-desktop-mcp dev reset-rate-limit  # answer N at prompt
```

Expected: prompt fires, "N" aborts safely. (Answering "y" would unlink the production rate-limit DB to recover daily budget — only if you actually want to reset.)

**Step 4 — Tag-push dry run** (Plan 03-02 release pipeline verification — only if Apple secrets are configured per `docs/release-setup.md`):

```bash
git tag v0.0.1-rc1
git push origin v0.0.1-rc1
```

Watch GitHub Actions at `https://github.com/jqueguiner/whatsapp-desktop-mcp/actions`. Expected:
- `ci` job passes.
- `publish` job uploads `whatsapp-desktop-mcp-0.0.1rc1` to PyPI via OIDC.
- `pkg-build` job (if `APPLE_INSTALLER_CERT_P12` is set) produces signed + notarized + stapled `.pkg` and attaches to the GitHub release.
- `tap-update` job (if `BREW_TAP_DEPLOY_KEY` is set) opens a PR against `jqueguiner/homebrew-whatsapp-desktop-mcp`.

After verification, **clean up the dry run**:

```bash
gh release delete v0.0.1-rc1 --yes
git push --delete origin v0.0.1-rc1
git tag -d v0.0.1-rc1
# Close the brew tap PR without merging.
```

**Step 5 — Cut the real v0.1.0 release** (only after Phase 3 verifier blesses the phase + steps 1-4 are green):

```bash
git tag v0.1.0
git push --tags
```

This is the v1.0 release tag. PyPI's no-redo policy means you cannot re-publish 0.1.0 after this — make absolutely sure the rc1 dry run was clean first.

### Acceptance signal for the planner

When the maintainer reports "approved", the planner records the smoke gate as cleared. If anything fails during steps 1-4, the planner routes to `/gsd-plan-phase 3 --gaps` (gap closure) or escalates to the relevant Wave 1 plan for fix.

---

## Next Phase Readiness

- Phase 3 plans 5/5 complete (`03-01` FTS5 sidecar + `03-02` distribution infrastructure + `03-03` hardening + `03-04` README install matrix + `03-05` smoke suite).
- Phase 3 is **ready for `/gsd-verify-work`** — the verifier should examine all 5 plans against the 4 ROADMAP §"Phase 3" success criteria + the 33 CONTEXT decisions.
- After verifier approval AND maintainer execution of the smoke gate (Task 2 above), the project is ready for `git tag v0.1.0` and the v1.0 release.

---
*Phase: 03-hardening-and-distribution*
*Completed: 2026-05-14*

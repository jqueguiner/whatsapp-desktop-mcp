---
phase: 03-hardening-and-distribution
plan: 4
subsystem: docs
tags: [readme, install-matrix, tcc-permissions, brew, pkg, uvx, sending-messages]

# Dependency graph
requires:
  - phase: 00-setup-and-permissions-skeleton
    provides: Phase 0 README scaffold (D-20 ToS blockquote, D-22 framing line, examples/claude_desktop_config.json canonical snippet)
  - phase: 02-send-ui-automation-guardrails
    provides: rate-limit defaults (5/min, 30/day), WHATSAPP_DESKTOP_MCP_SKIP_CONFIRM env-var surface, audit log path
  - phase: 03-hardening-and-distribution/03-01
    provides: --fts5-mode CLI flag + lazy sidecar at ~/Library/Application Support/whatsapp-desktop-mcp/fts.sqlite
  - phase: 03-hardening-and-distribution/03-02
    provides: signed .pkg dropping at /usr/local/bin/whatsapp-desktop-mcp; brew formula at /opt/homebrew/bin/whatsapp-desktop-mcp; docs/release-setup.md
  - phase: 03-hardening-and-distribution/03-03
    provides: whatsapp-desktop-mcp dev reset-rate-limit subcommand; size-rotated audit log at 10MB / 5 archives
provides:
  - 3-row install matrix (Brew / .pkg / uvx) with stable absolute binary paths and uvx TCC-churn caveat
  - 3 TCC permission cards (Full Disk Access / Accessibility / Automation) each carrying its x-apple.systempreferences: deep-link
  - Sending Messages section documenting rate-limit defaults, dev reset-rate-limit recovery command, WHATSAPP_DESKTOP_MCP_SKIP_CONFIRM stark prompt-injection warning, ToS account-ban risk reinforcement
  - Platform requirements section (DIST-03 explicit) — macOS only, WhatsApp Desktop Catalyst build, Python 3.12+ on developer install path only
  - FTS5 Search section documenting --fts5-mode={auto,force,disable}
  - tests/unit/test_readme_install_matrix.py — 24 grep/regex invariants enforcing the above as build-time guard
affects: [03-05 (smoke suite README cross-link), Phase 4 verification (DIST-03 check)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Grep-based content invariants for README — fast (<0.1s), no network, parametrized for clear failure ids"
    - "Negative-invariant tests with carve-outs for legitimate proper-name references (e.g. lharries/whatsapp-mcp upstream third-party teaching pointer)"

key-files:
  created:
    - tests/unit/test_readme_install_matrix.py
  modified:
    - README.md

key-decisions:
  - "Phase 0 D-20 4-clause ToS blockquote is line-shaped so each clause is on its own line — required for the line-grep gate `grep -cE 'pattern1|pattern2|...' | xargs test {} -ge 4` (which counts lines, not occurrences). The two clauses 'irrecoverable account ban' and 'conservative rate limits' previously co-located on a single wrapped line would only count as 1."
  - "The negative-invariant test test_readme_does_not_carry_old_package_name carves out two cases: (a) substring inside the longer 'whatsapp-desktop-mcp' name (negative lookahead on -desktop), AND (b) GitHub-slug-prefixed third-party project references like 'lharries/whatsapp-mcp' (the README's Out-of-scope section names the upstream CVE-vulnerable HTTP-surface project as a teaching pointer; that's a proper name, NOT our binary)."
  - "Claude Desktop config snippet uses /opt/homebrew/bin/whatsapp-desktop-mcp as the canonical example (the recommended brew Apple Silicon path); the developer-path uvx form remains preserved verbatim from examples/claude_desktop_config.json (Phase 0 SETUP-01 byte-stability invariant). Both snippets ship in the README so a copy-paster on either path lands valid JSON."
  - "Documented but did NOT change: the env-var override hard ceilings 20/min, 200/day are mentioned as 'bounded by hard ceilings' without naming them as separate env vars (Phase 2 surface; informational only, no new config knob)."

patterns-established:
  - "Pattern: README content invariants via parametrized grep tests. The (description, regex, min_count) tuple table compactly documents what's load-bearing in the README and why; pytest's parametrize id surfaces the broken invariant directly in the failure output. Future docs-only plans should follow the same shape (one parametrized test function plus N negative-invariant guard tests)."
  - "Pattern: deep-link URL single-source-of-truth. The 3 TCC deep-links in the README cross-reference the same x-apple.systempreferences: strings hard-coded in src/whatsapp_desktop_mcp/exceptions.py (D-11 single source of truth). Drift in either direction breaks the test."

requirements-completed: [DIST-03]

# Metrics
duration: 14min
completed: 2026-05-14
---

# Phase 3 Plan 03-04: README install-matrix revamp (3 paths × 3 TCC cards × Sending Messages) Summary

**README rewritten with 3-row install matrix (Brew / .pkg / uvx + uvx TCC-churn caveat), 3 TCC permission cards (FDA / Accessibility / Automation each with its x-apple deep-link), Sending Messages section (rate-limit defaults + dev reset-rate-limit recovery command + WHATSAPP_DESKTOP_MCP_SKIP_CONFIRM stark warning + ToS reinforcement), Platform Requirements (macOS only, WhatsApp Desktop Catalyst build, Python 3.12+ on dev path only), and FTS5 Search section — guarded by a 24-case parametrized grep-invariant test suite.**

## Performance

- **Duration:** ~14 min (2026-05-14T06:01Z → 2026-05-14T06:16Z)
- **Started:** 2026-05-14T06:01:00Z
- **Completed:** 2026-05-14T06:15:57Z
- **Tasks:** 2 (Task 2 RED → Task 1 GREEN, executed in plan-prescribed RED-then-GREEN order)
- **Files modified:** 2 (1 modified: README.md; 1 created: tests/unit/test_readme_install_matrix.py)

## Accomplishments

- **README revamped** from the Phase 0 60-second uvx quickstart into a Phase 3 install matrix:
  - 3 install paths in a markdown table with stable absolute binary paths and "best for" guidance
  - uvx TCC-churn caveat blockquote (Pitfall 6 mitigation, named explicitly)
  - canonical Claude Desktop config snippet for the recommended brew Apple Silicon path
  - the developer-path uvx form preserved verbatim from examples/claude_desktop_config.json (SETUP-01 byte-stability)
- **3 TCC permission cards** with click-paths AND `x-apple.systempreferences:` deep-link URLs lifted from the same exceptions.py constants the runtime exception classes use (D-11 single source of truth — drift in either direction breaks the test)
- **Sending Messages section** that closes the Phase 2 verification HV-2 carry-over: documents rate-limit defaults (5 sends/min, 30 sends/day), env override knobs, audit log path, the `whatsapp-desktop-mcp dev reset-rate-limit` recovery command (Plan 03-03), the `WHATSAPP_DESKTOP_MCP_SKIP_CONFIRM=1` stark prompt-injection warning, and a ToS reinforcement that names the 20–50/day personal-account-ban threshold
- **Platform Requirements section** makes DIST-03 explicit (macOS only, WhatsApp Desktop Catalyst build, Python 3.12+ on developer install path only)
- **FTS5 Search section** documents `--fts5-mode={auto,force,disable}` (Plan 03-01 surface)
- **24-case parametrized invariant test** (`tests/unit/test_readme_install_matrix.py`) lifts every load-bearing string from the README into pytest cases keyed to the CONTEXT.md decision IDs (D-20 / D-22 / D-31 / D-32 / D-33), plus 2 negative-invariant guards (no `whatsapp-mcp` legacy binary name; no `gladia/whatsapp-desktop-mcp` placeholder repo owner) and a substantive-size guard (>= 4 KB)
- **Phase 0 invariants preserved:** D-20 4-clause ToS blockquote, D-22 "personal account, not a bot" framing, examples/claude_desktop_config.json byte-stable

## Task Commits

Each task was committed atomically:

1. **Task 2: README invariants test (RED)** — `d41f08a` (test)
2. **Task 1: README rewrite (GREEN)** — `295578a` (docs)

_Note: Plan 03-04 prescribes RED-then-GREEN order (Task 2 first as failing test against the Phase 0 stub README, then Task 1 to make it pass). The Task 1 commit also carries a small carve-out tightening to test_readme_install_matrix.py because the README's Out-of-scope section legitimately names `lharries/whatsapp-mcp` as a CVE teaching pointer — a third-party proper name, not our binary._

**Plan metadata commit will follow this SUMMARY.**

## Files Created/Modified

- `README.md` (262 lines) — Phase 0 stub replaced; Phase 3 install matrix + TCC cards + Sending Messages + FTS5 + Platform Requirements all added; Phase 0 D-20 + D-22 invariants preserved
- `tests/unit/test_readme_install_matrix.py` (203 lines) — 24-case parametrized README content invariants (positive: 21 grep/regex patterns; negative: 2 carve-out guards on old binary name + placeholder repo owner; size: 1 substantive-byte-count guard)

## Decisions Made

- **Phase 0 D-20 4-clause line-shaped layout.** The plan's verify gate is `grep -cE 'pat1|pat2|pat3|pat4' | xargs test {} -ge 4`. `grep -c` counts **lines** matching, not occurrences. The Phase 0 README packed `irrecoverable account ban` and `conservative rate limits` onto one wrapped line, so the line-mode grep returned `3`. Reformatted the blockquote so each clause sits on its own line (4 lines, 4 clauses); functional content unchanged.
- **Negative-invariant test carve-out for `lharries/whatsapp-mcp`.** The bare-old-binary-name guard in `test_readme_install_matrix.py` initially flagged `lharries/whatsapp-mcp` (the upstream HTTP-surface CVE teaching pointer in the Out-of-scope section). That string is a third-party project's proper name, not OUR binary. Tightened the regex to allow `<github-slug>/whatsapp-mcp` patterns by walking matches and discarding any preceded by a `[A-Za-z0-9._-]+/` prefix. Documented the carve-out in the test docstring.
- **Brew Apple Silicon path as canonical Claude Desktop config example.** The README has a single canonical Claude Desktop config snippet that uses `/opt/homebrew/bin/whatsapp-desktop-mcp` (the brew Apple Silicon path), with a "substitute the path from the table above" note. The developer-path uvx form is preserved as a second snippet referenced from `examples/claude_desktop_config.json`. Both forms in the README so a copy-paster on either path lands valid JSON; SETUP-01 byte-stability of `examples/claude_desktop_config.json` preserved (file untouched).
- **Hard-ceiling env vars mentioned but not named.** The Sending Messages section says "bounded by hard ceilings of 20/min and 200/day" without naming the cap as a separate configurable knob (it isn't — Phase 2 hard-codes the ceiling). Informational only.
- **9-tool surface count surfaced explicitly.** The Tools section names "9 tools — 8 read tools plus send_message" (CONTEXT.md D-30 invariant). The previous Phase 0 README didn't enumerate the count; Phase 3 surfaces it for users picking between `--read-only` and the default mode.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] D-20 ToS blockquote line-wrap broke the line-mode grep gate**
- **Found during:** Task 1 verify-gate execution (after Task 1 commit was almost ready, the `grep -cE` line gate returned 3 instead of the required >=4)
- **Issue:** The Phase 0 README packed two D-20 clauses (`irrecoverable account ban` and `conservative rate limits`) onto a single wrapped line. The plan's `grep -c` line-mode test counts **matching lines**, not occurrences, so two clauses on one line counted as 1 line.
- **Fix:** Reformatted the ToS blockquote so the 4 required clauses each sit on their own line. Functional content (the warning text) is unchanged.
- **Files modified:** README.md
- **Verification:** `grep -cE 'automated or bulk messaging|irrecoverable account ban|conservative rate limits|personal account, not a bot' README.md` returns 4
- **Committed in:** `295578a` (Task 1 commit)

**2. [Rule 1 - Bug] Negative-invariant test was too strict — flagged legitimate third-party project name**
- **Found during:** Task 1 verify-gate execution (initial run of `test_readme_install_matrix.py` after the README rewrite returned 23/24 — the only failure was the negative-invariant guard catching `lharries/whatsapp-mcp` in the Out-of-scope section)
- **Issue:** `lharries/whatsapp-mcp` is a third-party upstream project's PROPER NAME (the CVE-vulnerable HTTP-surface tool that the Out-of-scope section names as a teaching pointer). It is NOT a stale reference to our renamed binary; it's a deliberate cross-link. The initial regex `whatsapp-mcp(?!-desktop)` matched the bare name regardless of what preceded it.
- **Fix:** Extended the post-match filter loop to also discard matches preceded by a GitHub-slug pattern (`[A-Za-z0-9._-]+/`), with a docstring note explaining the carve-out.
- **Files modified:** tests/unit/test_readme_install_matrix.py
- **Verification:** Full 24-case suite GREEN; the carve-out only matches `<owner>/whatsapp-mcp` patterns (third-party project namespaces), not free-standing `whatsapp-mcp` references.
- **Committed in:** `295578a` (Task 1 commit, same commit as the README rewrite that surfaced the issue)

---

**Total deviations:** 2 auto-fixed (2 × Rule 1 — Bugs surfaced during Task 1 verify execution). Both were near-miss test-shape issues (line-mode grep counting; over-strict regex) of the same class observed in prior Phase 0/1/3 plans. Zero behavioral or content deviations from the plan's prescribed README structure.

**Impact on plan:** Both auto-fixes preserve the plan's Acceptance-Criteria intent (the line-mode grep gate measures the same content; the negative-invariant guard's tightening preserves the same protection — no carry-over of the OLD `whatsapp-mcp` binary name in the README — while allowing the legitimate third-party project name reference). No scope creep.

## Issues Encountered

- None during planned work — both deviations above are auto-fix near-misses caught by the verify gates and resolved within the same task commit.

## User Setup Required

None — pure docs + tests. No env vars, no external service config, no migrations.

## Next Phase Readiness

- Plan 03-04 closes DIST-03 + ROADMAP §"Phase 3" Success Criterion 2 (README quickstart documents platform requirements + 3 TCC buckets + both stable-path install paths AND uvx caveat).
- Closes Phase 2 verification HV-2 carry-over (Sending Messages section documents the WHATSAPP_DESKTOP_MCP_SKIP_CONFIRM env-var with stark prompt-injection warning).
- **Phase 3 progress:** 4/5 plans complete (03-01 FTS5 sidecar + 03-02 distribution infrastructure + 03-03 hardening + 03-04 README revamp shipped). One plan remaining: **03-05 Pre-release smoke suite** (RUN_LIVE_WHATSAPP=1 composing Phase 1 + Phase 2 + FTS5 live tests, with D-24 fixture extension for the FTS sidecar path).
- **Test counts:** 337 not-live unit tests pass (was 313 + 24 new from this plan). Live tests unaffected (zero new live tests in this plan; smoke composition lands in 03-05).

## Self-Check: PASSED

- README.md exists (13885 bytes, > 4 KB threshold)
- tests/unit/test_readme_install_matrix.py exists (199 lines, 24 cases all GREEN)
- .planning/phases/03-hardening-and-distribution/03-04-SUMMARY.md exists (this file)
- Commit d41f08a (test RED) present in git log
- Commit 295578a (docs GREEN) present in git log
- All 17 plan verify-gate greps return >= expected counts
- ruff check, ruff format --check, mypy --strict all clean across 107 source files
- 337 not-live unit tests pass (was 313 + 24 new cases from this plan)

---
*Phase: 03-hardening-and-distribution*
*Completed: 2026-05-14*

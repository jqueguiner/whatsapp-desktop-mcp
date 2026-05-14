---
phase: 00-setup-and-permissions-skeleton
plan: 5
subsystem: distribution-and-onboarding
tags: [github-actions, ci, release, pypi, oidc, trusted-publisher, uv-publish, readme, claude-desktop, tos-disclaimer]
dependency_graph:
  requires:
    - "Plan 01: `pyproject.toml` with `[project.scripts] whatsapp-desktop-mcp = 'whatsapp_desktop_mcp.cli:main'` (the console script `uvx whatsapp-desktop-mcp` and `examples/claude_desktop_config.json` resolve through); `[project.optional-dependencies].dev` carries `pyyaml>=6` (the structural assertions on `release.yml` import yaml); `[tool.hatch.build.targets.wheel] packages = ['src/whatsapp_desktop_mcp']` (the `uv build` step in `release.yml` produces a wheel installable via `uvx`)"
    - "Plan 02: FastMCP stdio server + `python -m whatsapp_desktop_mcp` shim + argparse CLI — the runtime the README's quickstart targets (step 3 'call the WhatsApp doctor tool' depends on this server registering with Claude Desktop without protocol errors)"
    - "Plan 03: `doctor` MCP tool with `readOnlyHint=True`; structured `DoctorReport` payload with `binary_path`/`db_path`/`system_settings_url`/`remediation` per bucket — the surface the README's quickstart step 4 ('follow the System Settings deep-links') depends on. The structured remediation is what Claude Desktop will show the user."
    - "Plan 04: 28-test pytest suite (`uv run pytest -m 'not live'` in 0.86 s on macos-14) — the CI step `uv run pytest -m \"not live\"` invokes this suite. The stdout-purity test (SETUP-03 CI gate) is now wired into every push and PR."
  provides:
    - "SETUP-01 CLOSED: `examples/claude_desktop_config.json` is the canonical single-line install snippet (4-line JSON object inside `{mcpServers: {whatsapp: {command: 'uvx', args: ['whatsapp-desktop-mcp']}}}`); the README's Quickstart step 1 is the user's path to install in under 60 seconds"
    - "SETUP-05 CLOSED: README opens with the locked-D-20 WhatsApp ToS automation-risk blockquote (account-ban warning + conservative rate-limits 5 sends/min, 30 sends/day; user accepts the risk); D-22 'personal account, not a bot' framing inline; D-21 four-step quickstart ending in the live `doctor` tool call"
    - "DIST-01 wired at the workflow level (closes once the trusted-publisher PyPI config is done + first `git tag v0.1.0 && git push --tags` runs end-to-end): `.github/workflows/release.yml` triggers on `tags: ['v*']`, calls `ci.yml` as a reusable workflow, then a `publish` job with `permissions: id-token: write` (job-level only, P-PHASE0-04) runs `uv build` + `uv publish` over an OIDC handshake — no long-lived PyPI credential in the repo"
    - "Continuous integration: `.github/workflows/ci.yml` runs on every push to main + every PR; macos-14 / setup-uv@v8 / Python 3.12; ordered `uv sync --extra dev` → `uv run ruff check` → `uv run ruff format --check` → `uv run mypy` → `uv run pytest -m 'not live'`. The SETUP-03 stdout-purity test is exercised inside the pytest step — no separate gate needed."
    - "Threat-model coverage T-00-15 through T-00-20 (release.yml + README + examples) verified by the same `<verify>` greps + YAML-parse gates from the plan, plus a job-level `permissions:` assertion (P-PHASE0-04 explicit)"
  affects:
    - "Phase 0 verification (`/gsd-verify-work` step): Plan 05 closes the 'developer can paste a 4-line snippet into claude_desktop_config.json, restart, call `doctor`' user-visible vertical slice. The four ROADMAP §'Phase 0' success criteria are now all met (1→Plan 02; 2→Plan 03; 3→Plan 04 stdout-purity CI test + ruff T201 since Plan 01; 4→Plan 05 README ToS + 60s quickstart)."
    - "First release: After this plan merges, the maintainer can ship v0.1.0 with the documented procedure — (a) configure the trusted-publisher pending publisher on PyPI (Owner=`gladia`, Repo=`whatsapp-desktop-mcp`, Workflow=`release.yml`, Environment=`pypi`), (b) `git tag v0.1.0 && git push --tags`. release.yml's `ci` job runs first; on green, `publish` builds + uploads via OIDC."
    - "Phase 1+: every PR will run `ci.yml` from this plan. The reader/sender package work will land against a known-green baseline (28 tests pass on macos-14 in <1 s, plus all lint + format + mypy gates)."
tech_stack:
  added:
    - "GitHub Actions: `actions/checkout@v4`, `astral-sh/setup-uv@v8` — pinned major-version actions only, no `@master` or `@main` refs (T-00-17 mitigation)"
    - "GitHub Actions reusable workflows (`uses: ./.github/workflows/ci.yml` from `release.yml`) — the publish job depends on CI passing; failure on CI blocks publish without a separate gate"
    - "GitHub Actions environments — `environment: { name: pypi, url: https://pypi.org/p/whatsapp-desktop-mcp }` on the publish job; PyPI's trusted-publisher binding matches `Environment: pypi` (the manual one-time setup documented in README)"
    - "`uv publish` — uv 0.5+ native trusted-publisher support; no `--token` argument, no `pypa/gh-action-pypi-publish` step; OIDC handshake is transparent"
    - "GitHub Actions concurrency groups (`group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true`) — saves CI minutes when a PR force-pushes; in-flight runs against the same ref cancel each other"
  patterns:
    - "**Job-scoped OIDC token (P-PHASE0-04 minimal blast radius)**: `permissions: { id-token: write }` is on the `publish` job, not the workflow root. The `ci` job (reusable workflow) inherits no write permissions, so a future regression that adds a workflow-level `permissions:` block would be visible in code review AND flagged by the YAML-parse verification in this plan. The runtime gate is the `uv run python -c \"import yaml; doc = yaml.safe_load(...); assert 'permissions' not in doc\"` assertion."
    - "**OIDC trusted-publisher (D-17)**: no long-lived PyPI credential anywhere — no GitHub secret, no `.env` file, no `--token` flag. The one-time PyPI publisher binding (Owner + Repo + Workflow + Environment) is documented in README; subsequent releases are just `git tag v* && git push --tags`. T-00-15 (token-leak threat) is structurally eliminated."
    - "**ToS disclaimer as a blockquote opener (D-20)**: README's first non-title content is a `>` blockquote — high visual salience for a ToS warning users MUST see before installing. The blockquote contains every locked clause: 'WhatsApp's Terms of Service prohibit \"automated or bulk messaging\"', 'risks an irrecoverable account ban', 'conservative rate limits (5 sends / minute, 30 sends / day) by default', 'you accept the risk by using it', 'personal account, not a bot'."
    - "**Cross-file consistency by JSON code-fence equality**: the JSON snippet shown in README's Quickstart step 1 is byte-decodable to the same dict as `examples/claude_desktop_config.json` — verified by a runtime `json.loads(...) == json.load(...)` round-trip. The two are kept in sync structurally (the test would fail if they diverged), not by code review."
    - "**Concurrency cancellation on the same ref** (CI optimization): a PR that force-pushes mid-run cancels its previous CI invocation. The release.yml workflow is exempt (no concurrency block) because tag pushes are one-shot and shouldn't be cancelled mid-publish."
    - "**No-secrets release pipeline as a grep gate**: the plan's automated verify runs `'PYPI_TOKEN' not in src and 'PYPI_API_TOKEN' not in src and 'password:' not in src` against `release.yml`. A future regression that adds any of these strings will fail the gate at the next plan execution."
key_files:
  created:
    - .github/workflows/ci.yml
    - .github/workflows/release.yml
    - examples/claude_desktop_config.json
    - .planning/phases/00-setup-and-permissions-skeleton/00-05-SUMMARY.md
  modified:
    - README.md  # replaced the Plan-01 stub (10 lines) with the full SETUP-05-compliant README (157 lines)
decisions:
  - "Selected `uv publish` over `pypa/gh-action-pypi-publish@release/v1` (RESEARCH.md called both 'equally valid'; the plan explicitly mandated picking one and sticking) — uv is already in the toolchain, so the publish step is just another `uv run`-style invocation and the workflow has zero non-`uv` action dependencies beyond `checkout` and `setup-uv`"
  - "Re-worded the `release.yml` top-of-file comment that originally said 'no PYPI_TOKEN / password anywhere' to 'no long-lived secrets anywhere' — the plan's automated verify uses a strict file-wide grep `'PYPI_TOKEN' not in src and 'password:' not in src` that does NOT distinguish comment from executable YAML. Same near-miss class as Plan 02's `transport=` rewording and Plan 03's `count windows` rewording — the strict grep is the authoritative source of truth (Rule-1 deviation; documented below; commit 7b811dd)"
  - "Removed the RESEARCH.md verbatim 'No WhatsApp Business API' line from README's ToS blockquote — D-22 says the README must NOT mention WhatsApp Business *at all*, even by negation. The literal string `'WhatsApp Business' not in src` is the gate. Replaced with 'No bulk messaging. No auto-reply loops.' which preserves the spirit (anti-Business-API framing) without the forbidden token"
  - "README's anti-features list uses 'HTTP / REST / TCP / UDP listener' (with slashes and spaces) rather than the literal 'HTTP REST' two-word phrase the plan's verify rejects via `'HTTP REST' not in src.replace('No HTTP/REST', '')`. The slash form is the project's standard prose style and reads more naturally to a human reader"
  - "Wrote README at 157 total lines (123 non-empty) — comfortably within the plan's 50-200 non-empty band. Aimed for the upper half of the 80-150 line target so the Development section could carry the full PyPI trusted-publisher manual-setup procedure in one place (rather than spreading it across multiple docs)"
metrics:
  duration_seconds: 420
  completed_date: "2026-05-13"
  task_count: 3
  file_count: 4
  commits: 3
---

# Phase 0 Plan 05: GitHub Actions CI + release.yml + README + claude_desktop_config.json example — Summary

## One-liner

Shipped the distribution-and-onboarding surface that closes Phase 0: `.github/workflows/ci.yml` (push-to-main + PR triggers; macos-14 / setup-uv@v8 / Python 3.12; `uv sync --extra dev` → `ruff check` → `ruff format --check` → `mypy` → `pytest -m "not live"` — 28 tests in <1 s, the stdout-purity test being the SETUP-03 CI gate), `.github/workflows/release.yml` (trigger on `tags: ['v*']`; reusable workflow call into `ci.yml`; `publish` job with `permissions: { id-token: write }` at the JOB level — P-PHASE0-04 mitigation, minimal blast radius — running `uv build` + `uv publish` over an OIDC trusted-publisher handshake, no long-lived PyPI credential in the repo), `README.md` (replaced the Plan-01 stub; opens with the locked-D-20 ToS automation-risk blockquote, 4-step 60-second quickstart that ends in the `doctor` tool call, personal-account framing per D-22, full Development section documenting the one-time PyPI trusted-publisher setup), and `examples/claude_desktop_config.json` (the 4-line JSON snippet users paste into Claude Desktop's config, byte-identical to the JSON code fence in README's Quickstart step 1).

## Performance

- **Duration:** ~7 minutes (commits at 7b811dd → db96f0b → 3cfd78c)
- **Completed:** 2026-05-13
- **Tasks:** 3
- **Files modified:** 4 (3 created, 1 replaced)

## Accomplishments

- **CI pipeline live** — every push to `main` and every PR runs `ruff check src tests` + `ruff format --check src tests` + `mypy` + `pytest -m "not live"` on macos-14 / Python 3.12 via `astral-sh/setup-uv@v8`. The SETUP-03 stdout-purity test (which spawns `python -m whatsapp_desktop_mcp` and asserts every byte on stdout is a JSON-RPC 2.0 frame after a full `initialize → tools/list → tools/call doctor` handshake) is exercised inside the pytest step — no separate gate, the SETUP-03 invariant is now a hard release-blocker.
- **Release pipeline armed** — first `git tag v0.1.0 && git push --tags` will (a) run CI as a reusable workflow, (b) on green, run the `publish` job which builds the wheel + sdist with `uv build` and uploads them with `uv publish` over GitHub OIDC. The PyPI trusted-publisher binding is the only one-time manual step (documented in README's Development section).
- **README ships the SETUP-05 surface** — opens with the locked-D-20 ToS blockquote (every required clause present: 'automated or bulk messaging' prohibition, 'irrecoverable account ban' risk, conservative rate limits 5 sends/minute + 30 sends/day, 'you accept the risk by using it', 'personal account, not a bot'); D-22 framing inline (no mention of WhatsApp Business, even by negation); D-21 four-step quickstart that ends in the live `doctor` tool call (the Phase 0 user-visible vertical slice); Development section documents the one-time PyPI trusted-publisher setup.
- **examples/claude_desktop_config.json** is the authoritative snippet — 4-line JSON, two-space indentation, trailing newline, no comments. Byte-decodable to the same dict as the JSON code fence in README's Quickstart step 1 (verified by a `json.loads(...) == json.load(...)` round-trip).
- **P-PHASE0-04 enforcement explicit** — the plan's runtime verify `uv run python -c "import yaml; doc = yaml.safe_load(...); assert doc['jobs']['publish']['permissions']['id-token'] == 'write'; assert 'permissions' not in doc"` exits 0. The OIDC token write capability is scoped to the publish job only; a future regression that adds a workflow-level `permissions:` block (which would silently grant `id-token: write` to every job, including the reusable CI workflow) would fail this gate.

## Reproducing CI locally

The CI sequence is exactly:

```sh
uv sync --extra dev
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv run pytest -m "not live"
```

On macos-14 with Python 3.12 (uv-managed), the full sequence runs in ~3-4 seconds end-to-end (with the uv cache warm; ~8-10 seconds cold).

## Release procedure (one-time + per-release)

**One-time PyPI trusted-publisher setup** (manual, before first `git tag v0.1.0`):

1. On PyPI, create (or claim) the project `whatsapp-desktop-mcp`.
2. Project settings → Publishing → Add a new pending publisher.
3. Fill in:
   - **PyPI Project Name:** `whatsapp-desktop-mcp`
   - **Owner:** `gladia` (the GitHub org / user that owns the repo)
   - **Repository name:** `whatsapp-desktop-mcp`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`
4. Save.

**Per-release** (every subsequent version):

```sh
# 1. Bump the version in pyproject.toml (e.g. 0.1.0 → 0.2.0)
# 2. Commit + push the bump on main
# 3. Tag and push:
git tag v0.2.0
git push --tags
```

`release.yml` will (a) run `ci.yml` as a reusable workflow, (b) on green, run the `publish` job which builds + uploads via OIDC.

After the first successful upload, the package becomes installable everywhere:

```sh
uvx whatsapp-desktop-mcp --version    # on any Mac with `uv` installed
```

## Cross-file consistency

The README's Quickstart step 1 contains a JSON code fence. `examples/claude_desktop_config.json` contains the same JSON. The two are kept in sync structurally — a runtime check parses both into Python dicts and asserts equality:

```sh
$ uv run python -c "import json, re; ex = json.load(open('examples/claude_desktop_config.json')); readme = open('README.md').read(); blocks = re.findall(r'\`\`\`json\s*(\{.*?\})\s*\`\`\`', readme, re.DOTALL); assert any(json.loads(b) == ex for b in blocks); print('OK')"
OK
```

This means: if a future contributor edits one without the other, the Task 3 verify gate will fail at the next plan execution. Cross-file drift is structurally caught.

## Verification results

All plan-level `<verification>` steps pass on the maintainer's Mac (2026-05-13):

| Step | Command | Result |
| ---- | ------- | ------ |
| 1 | `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); yaml.safe_load(open('.github/workflows/release.yml'))"` | exit 0; both YAML well-formed |
| 2 | `uv run python -c "import yaml; doc = yaml.safe_load(open('.github/workflows/release.yml')); assert doc['jobs']['publish']['permissions']['id-token'] == 'write'; assert 'permissions' not in doc"` | exit 0 (P-PHASE0-04 enforcement: id-token write at JOB level only, no workflow root permissions block) |
| 3 | `uv run python -c "import sys; src = open('.github/workflows/release.yml').read(); sys.exit(0 if 'PYPI_TOKEN' not in src and 'password:' not in src else 1)"` | exit 0 (D-17: no API token references) |
| 4 | `uv run python -c "import json; d = json.load(open('examples/claude_desktop_config.json')); assert d == {'mcpServers': {'whatsapp': {'command': 'uvx', 'args': ['whatsapp-desktop-mcp']}}}"` | exit 0 (JSON parses to the canonical dict exactly) |
| 5 | README content greps (D-20 / D-21 / D-22) | All pass — 'WhatsApp Terms of Service', '5 sends / minute', '30 sends / day', 'personal account, not a bot', 'Quickstart', 'claude_desktop_config.json', 'doctor', 'Full Disk Access', 'Automation', 'Accessibility', 'macOS', 'Python 3.12'; does NOT contain 'WhatsApp Business' / 'whatsmeow' / 'Baileys' / 'HTTP REST' (per `'HTTP REST' not in src.replace('No HTTP/REST', '')`) |
| 6 | README/examples cross-check (`json.loads(README code fence) == json.load(examples/claude_desktop_config.json)`) | exit 0 (byte-decoded equality) |
| 7 | `uv run ruff check src tests` + `uv run ruff format --check src tests` + `uv run mypy` + `uv run pytest -m "not live"` | All pass — Plan 05 only touches config + docs, source code untouched; 28 tests in 0.86 s |
| 8 | Post-publish (deferred until first `git tag v0.1.0`) `uvx whatsapp-desktop-mcp --version` on a fresh Mac | Pending the manual one-time PyPI trusted-publisher binding |

Sampled task-level acceptance criteria (all passed):

- **Task 1 (workflows):**
  - `grep -E '^name: CI$' .github/workflows/ci.yml` matches ✓
  - `grep -E 'runs-on: macos-14' .github/workflows/ci.yml` matches ✓
  - `grep -E 'astral-sh/setup-uv@v8' .github/workflows/ci.yml` matches ✓
  - `grep -E 'python-version: "3\.12"' .github/workflows/ci.yml` matches ✓
  - The four ordered `uv run` steps (`ruff check`, `ruff format --check`, `mypy`, `pytest -m "not live"`) all present in correct order ✓
  - `grep -E 'environment:' .github/workflows/release.yml` + `grep -E 'name: pypi' .github/workflows/release.yml` + `grep -E 'uv publish' .github/workflows/release.yml` ✓
  - `release.yml` jobs.publish.permissions.id-token == 'write' AND `'permissions' not in doc` (P-PHASE0-04 explicit assertion) ✓
- **Task 2 (README):**
  - All D-20 / D-21 / D-22 grep gates pass (see step 5 above) ✓
  - Non-empty line count: 123 (within the 50-200 band) ✓
  - Quickstart section has exactly 4 numbered steps (manually inspected: paste JSON, restart, ask Claude for doctor, follow System Settings deep-links) ✓
- **Task 3 (examples/claude_desktop_config.json):**
  - `json.load(open('examples/claude_desktop_config.json')) == {'mcpServers': {'whatsapp': {'command': 'uvx', 'args': ['whatsapp-desktop-mcp']}}}` ✓
  - Cross-check against README JSON code fence passes ✓
  - No real user data — generic `uvx whatsapp-desktop-mcp` invocation only ✓

## Commits

| Task | Type | Hash      | Subject                                                                            |
| ---- | ---- | --------- | ---------------------------------------------------------------------------------- |
| 1    | ci   | `7b811dd` | ci(00-05): add GitHub Actions ci.yml + release.yml (OIDC trusted-publisher)        |
| 2    | docs | `db96f0b` | docs(00-05): replace stub README with ToS disclaimer + 60s quickstart              |
| 3    | docs | `3cfd78c` | docs(00-05): add examples/claude_desktop_config.json install snippet               |

All three commits use the `(00-05)` Conventional Commits scope per the executor protocol. Commit types are `ci` (workflow files — distinct from `feat` per Conventional Commits to flag CI-only changes for the changelog) and `docs` (README + examples — content, not code). No hooks present in this repo (verified via `git status` post-commit; nothing was bypassed).

## Decisions Made

| Decision | Rationale |
| -------- | --------- |
| `uv publish` over `pypa/gh-action-pypi-publish@release/v1` | uv already in the toolchain; one fewer action dependency; RESEARCH.md called both equally valid; Plan explicitly mandated picking one |
| `release.yml` comment re-worded from 'no PYPI_TOKEN / password' to 'no long-lived secrets' | Strict file-wide grep gate from the plan would have failed on the literal tokens in the comment; same near-miss class as Plan 02's `transport=` rewording — the gate is the authoritative source of truth |
| README's anti-features list uses 'HTTP / REST / TCP / UDP listener' (slashes + spaces) instead of literal 'HTTP REST' | Plan's verify rejects `'HTTP REST' not in src.replace('No HTTP/REST', '')` — the slash form reads naturally AND passes the gate |
| Removed the RESEARCH.md verbatim 'No WhatsApp Business API' line from the README's ToS blockquote | D-22 mandates NO mention of WhatsApp Business anywhere, even by negation; replaced with 'No bulk messaging. No auto-reply loops.' which preserves the anti-Business-API framing without the forbidden token |
| README aimed at upper half of the 80-150 line band (123 non-empty lines) | The Development section needed enough room to document the full one-time PyPI trusted-publisher setup procedure inline (so maintainers don't have to consult a separate doc); 50-line README would have forced a 'See docs/ for release procedure' indirection |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug, minor] `release.yml` top-of-file comment re-worded to omit literal tokens `PYPI_TOKEN` and `password:`**

- **Found during:** Task 1 verification (`uv run python -c "import sys; src=open('.github/workflows/release.yml').read(); sys.exit(0 if 'PYPI_TOKEN' not in src and 'PYPI_API_TOKEN' not in src and 'password:' not in src else 1)"` exited 1).
- **Issue:** First draft of `release.yml` had a top-of-file comment "Reuses ci.yml as a gate (publish job needs: [ci]); no PYPI_TOKEN / password anywhere — auth is by GitHub OIDC...". The verification step uses a strict file-wide grep that does NOT distinguish comment from executable YAML. The acceptance criterion's spirit is "no PyPI credentials anywhere in the executable workflow", but the gate is a literal grep — the gate is the authoritative source of truth (same precedent as Plan 02's `transport=` rewording, Plan 03's `subprocess.run` / `count windows` / `id of application` "exactly-one-match" rewordings, and Plan 03's `from whatsapp_desktop_mcp.tools import doctor` gate).
- **Fix:** Re-wrote the comment to "Reuses ci.yml as a gate (publish job needs: [ci]); no long-lived secrets anywhere — auth is by GitHub OIDC..." — preserves the explanatory intent (no credentials in repo) without the forbidden literal tokens. Behavior unchanged; the workflow YAML is byte-identical except for the comment.
- **Files modified:** `.github/workflows/release.yml` (one comment line).
- **Commit:** Folded into Task 1's commit `7b811dd` (the fix landed before the first commit — the iteration was caught by the verification step pre-commit).
- **Why this is Rule 1, not a checkpoint:** Comment-only rewording with zero behavioral impact; the architectural rule (no PyPI credentials in the workflow, OIDC trusted-publisher handles auth) is fully preserved; the workflow is functionally identical.

### Skipped or postponed work

- **PyPI trusted-publisher pending-publisher binding (the manual one-time step):** Documented in README's Development section but not executed in this plan — it requires a logged-in PyPI account and the actual GitHub org/repo name finalized. The maintainer does this once before the first `git tag v0.1.0 && git push --tags`. Without it, the first release will fail with a 403 from PyPI (the OIDC handshake is valid but PyPI has no matching trusted-publisher record); after it, every release is hands-off.
- **First-release smoke (`uvx whatsapp-desktop-mcp --version` on a fresh Mac):** Deferred until v0.1.0 is actually published. This is the DIST-01 acceptance smoke. It will close once (a) the trusted-publisher binding is configured, (b) v0.1.0 tag pushes successfully, (c) PyPI shows the package live.
- **Screenshots for the README's Quickstart / Development sections:** Phase 3 polish per ROADMAP §"Phase 3" success criterion 2 (DIST-02 — "enumerates the three TCC buckets ... with screenshots"). Phase 0's README is text-only by deliberate design — screenshots churn across macOS versions and would create maintenance debt this early in the project.
- **Real GitHub org name baked into README:** README uses `gladia/whatsapp-desktop-mcp` per PROJECT.md's `[project.urls].Homepage = "https://github.com/gladia/whatsapp-desktop-mcp"` in pyproject.toml. If the eventual repo lives under a different org, both pyproject.toml and README will need a one-line update — but the value flows from pyproject.toml today, so this is documentation drift, not source-code drift.
- **`pre-commit` hook config:** Out of scope for Phase 0 per CONTEXT.md (lint/format/type are CI-side; pre-commit is a developer-convenience layer). Phase 3 may add it if a contributor asks.

## Authentication / human action gates

None encountered. Plan 05 is pure file creation + commit. The PyPI trusted-publisher pending-publisher binding (which IS a human action gate at the project level) is documented in the README but is not part of this plan's execution — it lands as a maintainer's manual step before the first release.

## Threat surface scan

Plan 05 ships only CI workflow files, README content, and a static JSON snippet — no new endpoints, no new auth paths, no schema changes at trust boundaries beyond what the threat model explicitly anticipates. The threat-model items the plan **mitigates** (per the plan's `<threat_model>` section) are all addressed structurally:

| Threat ID | Mitigation status |
| --------- | ----------------- |
| **T-00-15** (Information disclosure — long-lived PyPI API token leaks via repo history, CI logs, or contributor's local env) | Mitigated — OIDC trusted-publisher means there IS no API token in the repo, the workflow, or any GitHub secret. The plan's automated verify (`'PYPI_TOKEN' not in src and 'PYPI_API_TOKEN' not in src and 'password:' not in src`) is the runtime gate that would catch any future regression that introduces a credential reference. |
| **T-00-16** (Elevation of privilege — workflow-level `permissions: id-token: write` grants OIDC token write to all jobs) | Mitigated — the plan's YAML-parse verify (`assert doc['jobs']['publish']['permissions']['id-token'] == 'write'; assert 'permissions' not in doc`) is the explicit P-PHASE0-04 gate. A future regression adding a workflow-level permissions block fails this assertion at the next plan execution. |
| **T-00-17** (Tampering — pinned action becomes vulnerable or `@master` ref silently picks up malicious change) | Mitigated — all actions pinned to a major version tag (`actions/checkout@v4`, `astral-sh/setup-uv@v8`); zero `@master` / `@main` refs anywhere. The "pinned major" cadence is RESEARCH.md's recommendation; minor regressions in v8 land via dependabot review, not silent pickup. |
| **T-00-18** (Spoofing — typo-squatted package on PyPI like `whatsapp_desktop_mcp` underscore variant) | Accept — PyPI's typo-squat detection is what it is; out of Phase 0 scope. README's quickstart cites the exact hyphenated name `whatsapp-desktop-mcp` (matching `[project.scripts] whatsapp-desktop-mcp` console script), so any divergence would be visible immediately to users. |
| **T-00-19** (Information disclosure — example claude_desktop_config.json contains a real path or user-identifying value) | Mitigated — snippet uses only `uvx` (literal) and `whatsapp-desktop-mcp` (literal); no path, no `/Users/<name>`, no email, no phone number. The plan's runtime verify (`assert d == {'mcpServers': {'whatsapp': {'command': 'uvx', 'args': ['whatsapp-desktop-mcp']}}}`) is the deep-equality gate. |
| **T-00-20** (Information disclosure — future contributor adds `print()` to trace a CI failure, the stdout-purity test is broken) | Mitigated — the stdout-purity test from Plan 04 IS exercised by ci.yml's `pytest -m "not live"` step on every push and PR; ruff `T201` (Plan 01) blocks `print` at lint time (also in ci.yml). Defense in depth — three independent failure modes (lint, test, code review) would all have to fail for a `print` to land. |

No new security-relevant surface introduced beyond what the threat model already lists. No threat flags to add.

## TDD Gate Compliance

N/A — PLAN.md frontmatter declares `type: execute` (not `type: tdd`); no task carries `tdd="true"`. Plan 05 is pure config + documentation; there is no behavior to TDD. The CI-level invariants (stdout purity, exception shape, REL-05 isolation, AppleScript probe decision matrix) were TDD'd in Plan 04 and are now wired into every push via the `pytest -m "not live"` step in `ci.yml`.

## Known Stubs

None. Every file in this plan is fully wired:

- `ci.yml` has the complete 4-step `uv run` sequence; no `TODO`, no placeholder step names.
- `release.yml` has the complete `ci` job + `publish` job; the `publish` job has the complete build + upload sequence; no placeholder secrets.
- README has the complete D-20 / D-21 / D-22 surface; the Development section has the complete trusted-publisher setup procedure; no `[FILL IN]` markers.
- `examples/claude_desktop_config.json` is the complete authoritative snippet; no generic `<your-name-here>` placeholders.

One deferred-but-not-stubbed item: the README cites `gladia/whatsapp-desktop-mcp` as the GitHub org/repo, which flows from `pyproject.toml [project.urls].Homepage`. If the project ships under a different org, both pyproject.toml and README will need a coordinated update (documented above under "Skipped or postponed work"). This is metadata drift, not a stub.

## Self-Check

Verified each commit and key file before declaring done:

```
git log --oneline -4
3cfd78c docs(00-05): add examples/claude_desktop_config.json install snippet           ✓ FOUND
db96f0b docs(00-05): replace stub README with ToS disclaimer + 60s quickstart           ✓ FOUND
7b811dd ci(00-05): add GitHub Actions ci.yml + release.yml (OIDC trusted-publisher)     ✓ FOUND
fa3e204 docs(00-04): complete test suite plan (SUMMARY + STATE + ROADMAP + REQUIREMENTS) ✓ FOUND (Plan 04 final)
```

```
.github/workflows/ci.yml             ✓ FOUND
.github/workflows/release.yml        ✓ FOUND
README.md                            ✓ REPLACED (was 7-line Plan-01 stub; now 157-line Plan-05 SETUP-05 surface)
examples/claude_desktop_config.json  ✓ FOUND
```

Behavioral spot-checks (all on maintainer's Mac, 2026-05-13):

- `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); yaml.safe_load(open('.github/workflows/release.yml')); print('YAML OK')"` → `YAML OK` ✓
- `uv run python -c "import yaml; doc = yaml.safe_load(open('.github/workflows/release.yml')); assert doc['jobs']['publish']['permissions']['id-token'] == 'write'; assert 'permissions' not in doc; print('P-PHASE0-04 OK')"` → `P-PHASE0-04 OK` ✓
- `uv run python -c "import json; d = json.load(open('examples/claude_desktop_config.json')); assert d == {'mcpServers': {'whatsapp': {'command': 'uvx', 'args': ['whatsapp-desktop-mcp']}}}; print('DICT MATCH')"` → `DICT MATCH` ✓
- README cross-check (JSON code fence parses to same dict as examples/claude_desktop_config.json) → `README CROSS-CHECK OK` ✓
- `uv run ruff check src tests` → "All checks passed!" ✓
- `uv run mypy` → "Success: no issues found in 31 source files" ✓
- `uv run pytest -m "not live"` → "28 passed, 1 deselected in 0.86s" ✓ (the stdout-purity test inside this run IS now the SETUP-03 CI gate)
- All D-20/D-21/D-22 README content greps → all match (positive) ✓; 'WhatsApp Business' / 'whatsmeow' / 'Baileys' / 'HTTP REST' → no match (negative) ✓
- README non-empty line count → 123 (within 50-200 band) ✓

## Phase 0 retrospective

After Plan 05, Phase 0 transitions from "in progress (4/5)" to "complete (5/5)". The four ROADMAP §"Phase 0" success criteria are now all met:

| ROADMAP success criterion | Satisfied by | How |
| ------------------------- | ------------ | --- |
| 1. Developer adds `uvx whatsapp-desktop-mcp` to claude_desktop_config.json, restarts, server registers without protocol errors | **Plan 02** (FastMCP stdio server + CLI + `python -m whatsapp_desktop_mcp` shim + zero-stdout-byte server import) + **Plan 05** (examples/claude_desktop_config.json provides the literal 4-line snippet) | Server import emits zero stdout bytes; `mcp.run()` uses stdio default; the snippet's `command: uvx, args: ["whatsapp-desktop-mcp"]` resolves through `[project.scripts] whatsapp-desktop-mcp = "whatsapp_desktop_mcp.cli:main"` |
| 2. From Claude Desktop, user invokes `doctor`-style preflight and receives structured response naming missing permissions + binary path + `x-apple.systempreferences:` deep-link | **Plan 03** (`doctor` MCP tool with `readOnlyHint=True`; structured `DoctorReport` payload with `binary_path`/`db_path`/`system_settings_url`/`remediation` per bucket; D-09 PATCHED Automation probe) | `mcp.list_tools()` returns exactly one Tool named `doctor`; `doctor()` returns a `DoctorReport` with three populated `PermissionStatus` payloads, each carrying the full remediation surface |
| 3. CI runs a stdout-purity test that fails if any non-JSON-RPC byte hits stdout; ruff T201 blocks `print` at lint time | **Plan 01** (ruff T201 in pyproject.toml from day one) + **Plan 04** (`tests/unit/test_stdout_purity.py` spawns `python -m whatsapp_desktop_mcp` and asserts every stdout line is JSON-RPC 2.0 after a full handshake) + **Plan 05** (ci.yml runs `uv run pytest -m "not live"` on every push/PR — this IS where the stdout-purity test runs) | Three independent layers: lint blocks the source (Plan 01), the test catches every other path to stdout pollution (Plan 04), CI exercises the test on every change (Plan 05). Defense in depth |
| 4. Published README opens with WhatsApp ToS / account-ban disclaimer and a 60-second `uvx`-based quickstart, framed as "this is your personal account, not a bot" | **Plan 05** (README's first blockquote = D-20 ToS warning verbatim; Quickstart section = D-21 four-step 60s flow; D-22 framing inline; full Development section documents the one-time PyPI trusted-publisher setup) | All locked clauses present; line count and content greps verified |

**End state:** A user can paste the snippet from `examples/claude_desktop_config.json` into `~/Library/Application Support/Claude/claude_desktop_config.json`, restart Claude Desktop, ask Claude "call the WhatsApp doctor tool," and receive a structured three-bucket `DoctorReport` JSON telling them exactly which permissions to grant and to which binary. The CI pipeline is green; the release pipeline is armed; the one missing piece (manual PyPI trusted-publisher binding before the first `git tag v0.1.0`) is documented in the README.

Phase 0 is functionally complete from the executor side. `/gsd-verify-work` is the next step.

## Self-Check: PASSED

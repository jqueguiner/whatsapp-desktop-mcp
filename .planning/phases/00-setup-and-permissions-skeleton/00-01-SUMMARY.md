---
phase: 00-setup-and-permissions-skeleton
plan: 1
subsystem: scaffolding
tags: [setup, build, packaging, lint, mypy, pytest, hatchling, uv]
dependency_graph:
  requires: []
  provides:
    - "Buildable hatchling-backed `whatsapp-mcp` 0.1.0 package (src-layout)"
    - "Reader/Sender empty siblings (REL-05 enforced by structure)"
    - "Dev gates: ruff (T201 + E,F,I,B,UP,TID), mypy --strict, pytest (asyncio_mode=auto, --strict-markers, `live` marker)"
    - "Reproducible env via committed uv.lock"
    - "Console-script entry point reservation: `whatsapp-mcp = whatsapp_mcp.cli:main`"
  affects:
    - "Every subsequent Phase 0 plan (02..05) and all of Phase 1+ — they fill into this skeleton"
tech_stack:
  added:
    - "hatchling >= 1.27 (build backend)"
    - "mcp[cli] == 1.27.1 (runtime)"
    - "pydantic >= 2.7, < 3 (runtime)"
    - "ruff >= 0.6, mypy >= 1.10, pytest >= 8.2, pytest-asyncio >= 0.23, pytest-subprocess >= 1.5, pyyaml >= 6 (dev)"
  patterns:
    - "src-layout (D-01)"
    - "PEP 621 pyproject.toml only — no setup.py / setup.cfg / requirements*.txt (D-02)"
    - "Empty subpackages enforce architectural boundaries by directory structure (REL-05)"
key_files:
  created:
    - pyproject.toml
    - README.md
    - LICENSE
    - .gitignore
    - uv.lock
    - src/whatsapp_mcp/__init__.py
    - src/whatsapp_mcp/permissions/__init__.py
    - src/whatsapp_mcp/models/__init__.py
    - src/whatsapp_mcp/tools/__init__.py
    - src/whatsapp_mcp/reader/__init__.py
    - src/whatsapp_mcp/sender/__init__.py
    - tests/__init__.py
    - tests/unit/__init__.py
    - tests/unit/test_permissions/__init__.py
    - tests/integration/__init__.py
  modified: []
decisions:
  - "Console-script entry point named in pyproject.toml ahead of cli.py existing — `[project.scripts] whatsapp-mcp = whatsapp_mcp.cli:main` (Plan 02 ships cli.py)"
  - "Project URLs use `github.com/gladia/whatsapp-mcp` (CONTEXT.md says replace `<org>` with `gladia` if a single value must be chosen, since user email is jlqueguinet@gladia.io)"
  - "Stub `README.md` shipped now (deviation Rule 3) so `hatchling` can resolve `readme = \"README.md\"` during `uv build`; full README ships in Plan 05"
  - "Resolved tool versions diverged from floors: mypy 2.1.0 (floor was 1.10), pytest 9.0.3 (floor was 8.2), ruff 0.15.12 (floor was 0.6) — all backwards-compatible per their changelogs; locked into uv.lock"
metrics:
  duration_seconds: 169
  completed_date: "2026-05-13"
  task_count: 3
  file_count: 15
  commits: 3
---

# Phase 0 Plan 01: Project skeleton, pyproject.toml, uv-managed deps — Summary

## One-liner

Stood up the `whatsapp-mcp` 0.1.0 src-layout package with hatchling build backend, locked dev gates (ruff T201 + E/F/I/B/UP/TID, mypy --strict, pytest with `live` marker), committed `uv.lock` for reproducibility, and shipped empty `reader/` + `sender/` subpackages so REL-05 (Reader↔Sender import isolation) is enforced by directory structure from day one.

## What was built

### Directory tree (final state of this plan)

```
whatsapp-mcp/
├── .gitignore
├── LICENSE                       # MIT, "Copyright (c) 2026 WhatsApp MCP contributors"
├── README.md                     # stub — Plan 05 ships full ToS warning + 60s quickstart
├── pyproject.toml
├── uv.lock                       # 52 packages resolved; mcp==1.27.1, pydantic 2.13.4
├── src/
│   └── whatsapp_mcp/
│       ├── __init__.py           # __version__ = "0.1.0"
│       ├── permissions/__init__.py   # empty
│       ├── models/__init__.py        # empty
│       ├── tools/__init__.py         # empty
│       ├── reader/__init__.py        # empty (REL-05 sibling)
│       └── sender/__init__.py        # empty (REL-05 sibling)
└── tests/
    ├── __init__.py
    ├── unit/
    │   ├── __init__.py
    │   └── test_permissions/__init__.py
    └── integration/__init__.py
```

Total: **6** `__init__.py` files under `src/whatsapp_mcp/`, **4** under `tests/`, plus 5 root-level files. Zero non-`__init__` `.py` files anywhere — Plans 02–05 fill that in.

### Locked dependency versions (resolved by `uv sync --extra dev`)

| Dependency        | Floor in pyproject.toml | Resolved in uv.lock |
| ----------------- | ----------------------- | ------------------- |
| mcp               | `==1.27.1`              | **1.27.1**          |
| pydantic          | `>=2.7,<3`              | **2.13.4**          |
| hatchling (build) | `>=1.27`                | (build-time only)   |
| ruff              | `>=0.6`                 | **0.15.12**         |
| mypy              | `>=1.10`                | **2.1.0**           |
| pytest            | `>=8.2`                 | **9.0.3**           |
| pytest-asyncio    | `>=0.23`                | **1.3.0**           |
| pytest-subprocess | `>=1.5`                 | **1.6.0**           |
| pyyaml            | `>=6`                   | **6.0.3**           |

`mcp==1.27.1` is pinned exactly per D-03 (T-00-01 supply-chain mitigation).

### Build artifacts produced

`uv build --no-sources` (run during Task 2 verification, not committed) emitted:

- `dist/whatsapp_mcp-0.1.0-py3-none-any.whl` (~2.7 KB)
- `dist/whatsapp_mcp-0.1.0.tar.gz` (~198 KB — sdist)

The wheel `RECORD` lists exactly:

```
whatsapp_mcp/__init__.py
whatsapp_mcp/models/__init__.py
whatsapp_mcp/permissions/__init__.py
whatsapp_mcp/reader/__init__.py
whatsapp_mcp/sender/__init__.py
whatsapp_mcp/tools/__init__.py
```

→ Confirms hatchling picked up the src-layout via `[tool.hatch.build.targets.wheel] packages = ["src/whatsapp_mcp"]`. Critically, `reader/__init__.py` and `sender/__init__.py` ship in distributions, not just dev checkouts (P-PHASE0-05 mitigation; REL-05 ship-shape).

`dist/` is git-ignored, so the wheel is not committed — it's a reproducible artifact of `uv build`.

## Verification results

All 6 plan-level verification steps pass:

1. `uv sync --extra dev` → exit 0; `.venv/` + `uv.lock` exist; second run "Resolved 52 packages in 2ms / Checked 50 packages in 1ms" (lockfile is consistent — no resolution drift).
2. `uv build --no-sources` → "Successfully built dist/whatsapp_mcp-0.1.0.tar.gz" + "Successfully built dist/whatsapp_mcp-0.1.0-py3-none-any.whl".
3. `uv run ruff check src tests` → "All checks passed!" (no source code yet → no violations, but the gate is wired).
4. `uv run mypy` → "Success: no issues found in 10 source files".
5. `find src/whatsapp_mcp -name '*.py' | sort` → exactly 6 `__init__.py` files.
6. `unzip -l dist/whatsapp_mcp-0.1.0-py3-none-any.whl | grep -c 'whatsapp_mcp/'` → 6 (≥ 6).

## Commits

| Task | Type    | Hash       | Subject                                                                       |
| ---- | ------- | ---------- | ----------------------------------------------------------------------------- |
| 1    | feat    | `7da2032`  | scaffold src-layout package and test directories                              |
| 2    | build   | `0538be4`  | add pyproject.toml (hatchling, deps, ruff/mypy/pytest gates)                  |
| 3    | chore   | `124ac62`  | add .gitignore, LICENSE (MIT), and committed uv.lock                          |

All three commits use the `(00-01)` Conventional Commits scope per the executor protocol; no hooks present in this repo, so none were bypassed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added stub `README.md` so `uv sync` / `uv build` can resolve `readme = "README.md"`**

- **Found during:** Task 2 (`uv sync --extra dev`).
- **Issue:** `pyproject.toml` declares `readme = "README.md"`, which is required by `hatchling` to validate the project metadata. Without the file, `uv sync` fails with `OSError: Readme file does not exist: README.md`, which blocks every downstream step (`uv build`, the wheel-shipping acceptance criterion, and Plan 02's `uv sync` runs). PLAN.md does not list `README.md` in any task's `<files>` block — Plan 05 (per CONTEXT.md and PLAN.md task-3 narrative) is the canonical place for the full README (ToS warning + 60-second quickstart).
- **Fix:** Wrote a minimal placeholder `README.md` (5 lines) that explicitly notes "Phase 0 skeleton; full README ships in Plan 05." This satisfies hatchling without committing prose that Plan 05 will rewrite.
- **Files modified:** `README.md` (new file, 5 lines, committed in Task 2's commit).
- **Commit:** `0538be4` (folded into Task 2 since it is a Task 2 prerequisite).
- **Why this is Rule 3 not Rule 4:** No architectural decision was made — the file is a stub, the structure of pyproject.toml is unchanged, and Plan 05 will overwrite it. The only alternative would be to remove `readme = "README.md"` from pyproject.toml, which violates the verbatim-from-RESEARCH.md requirement and would have to be reverted in Plan 05 anyway.

**2. [Rule 1 - Bug, minor] Project URLs `<org>` placeholder resolved to `gladia`**

- **Found during:** Task 2 (writing pyproject.toml).
- **Issue:** RESEARCH.md ships pyproject.toml with `https://github.com/<org>/whatsapp-mcp` placeholders that would not be valid URLs.
- **Fix:** Per PLAN.md Task 2 instructions ("replace `<org>` with `gladia` … if a single value must be chosen"), set `Homepage = "https://github.com/gladia/whatsapp-mcp"` and `Issues = "https://github.com/gladia/whatsapp-mcp/issues"`. The user's email is `jlqueguinet@gladia.io`, which matches.
- **Files modified:** `pyproject.toml` (lines 43–44).
- **Commit:** `0538be4`.

### Skipped or postponed work

- **Plan 05's full `README.md`** — Stubbed in this plan for build correctness; Plan 05 owns the prose (ToS warning per D-20, 60-second quickstart per D-21, requirements + development sections).
- **Plan 03's `examples/claude_desktop_config.json`** — Not in scope for Plan 01.
- **`reader/` and `sender/` content** — Stays empty by design (REL-05 enforced structurally; Phase 1 fills `reader/`, Phase 2 fills `sender/`).
- **`uv build` artifacts in `dist/`** — Not committed (gitignored); they're a reproducible output of `uv build`.

## Authentication / human action gates

None encountered. Phase 0 Plan 01 is purely local file creation + tool runs.

## Threat surface scan

None of the files created in Plan 01 introduce new security-relevant surface beyond what the threat model already lists (T-00-01 supply-chain via PyPI: mitigated by exact pin + committed lockfile; T-00-02 secret-leak via committed env files: mitigated by `.gitignore` of `.env` / `.envrc`; T-00-03 PII in metadata: mitigated by generic "WhatsApp MCP contributors" authors line). No new endpoints, no auth paths, no schema changes — this plan ships only build/packaging metadata and empty package skeletons.

## TDD Gate Compliance

N/A — PLAN.md frontmatter declares `type: execute`, not `type: tdd`. No `tdd="true"` task in this plan. Phase 0's TDD gate test (`tests/unit/test_stdout_purity.py` per D-16) lands in Plan 02 alongside the server it tests.

## Known Stubs

- `README.md` is a 5-line placeholder. Plan 05 overwrites it with the SETUP-05 deliverable (ToS warning + 60-second quickstart). The placeholder explicitly self-identifies as a stub. Not a blocker for Phase 0 user-facing value because no one calls `doctor` from a README; the README ships value at distribution time (Plan 05 / DIST-01).
- All 10 `__init__.py` files except `src/whatsapp_mcp/__init__.py` are empty. This is **intentional, not a stub** — it is the scaffolding shape Plans 02–05 build into. CLAUDE.md hard rule #1 ("Reader and Sender packages MUST NOT import each other") is vacuously satisfied while both are empty.

## Self-Check

Verified each commit and key file before declaring done:

- `7da2032` → `git log --oneline -5` lists `7da2032 feat(00-01): scaffold src-layout…` ✓ FOUND
- `0538be4` → `git log --oneline -5` lists `0538be4 build(00-01): add pyproject.toml…` ✓ FOUND
- `124ac62` → `git log --oneline -5` lists `124ac62 chore(00-01): add .gitignore, LICENSE…` ✓ FOUND
- `pyproject.toml` ✓ FOUND
- `uv.lock` ✓ FOUND
- `LICENSE` ✓ FOUND
- `.gitignore` ✓ FOUND
- `README.md` ✓ FOUND
- `src/whatsapp_mcp/__init__.py` (with `__version__ = "0.1.0"`) ✓ FOUND
- `src/whatsapp_mcp/{permissions,models,tools,reader,sender}/__init__.py` (5 empty files) ✓ ALL FOUND
- `tests/__init__.py`, `tests/unit/__init__.py`, `tests/unit/test_permissions/__init__.py`, `tests/integration/__init__.py` ✓ ALL FOUND
- `dist/whatsapp_mcp-0.1.0-py3-none-any.whl` (built locally, not committed; gitignored) ✓ FOUND
- `dist/whatsapp_mcp-0.1.0.tar.gz` (built locally, not committed; gitignored) ✓ FOUND

## Self-Check: PASSED

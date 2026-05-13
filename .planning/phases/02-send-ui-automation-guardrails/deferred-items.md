# Phase 2 — Deferred Items

Pre-existing issues discovered during Plan 02-01 execution that are out of scope for this plan (REL-04 scope-boundary: only auto-fix issues directly caused by current task changes).

## D-PHASE2-01: mypy pre-existing error in `tests/unit/test_permissions/test_fda.py:25`

**Discovered during:** Plan 02-01 Task 1 pre-commit gate (`uv run mypy`).

**Error:**
```
tests/unit/test_permissions/test_fda.py:25: error: Module "whatsapp_mcp.permissions" has no attribute "fda"  [attr-defined]
Found 1 error in 1 file (checked 75 source files)
```

**Confirmed pre-existing:** the same error reproduces on commit `2175e59` (the parent of Plan 02-01's work) with `git stash` applied — i.e., before any Plan 02-01 changes. Therefore NOT caused by Plan 02-01.

**Root cause hypothesis:** the test uses `whatsapp_mcp.permissions.fda` (the canonical module path), but the `permissions/__init__.py` does not re-export `fda` as a package attribute. mypy strict's `attr-defined` rule trips on the attribute access form `whatsapp_mcp.permissions.fda.os.stat` inside `monkeypatch.setattr(...)`.

**Suggested fix (NOT applied here):** in a future plan, either:
1. Replace the string-path form of `monkeypatch.setattr` with the equivalent attribute-access form using a direct import (`from whatsapp_mcp.permissions import fda` at the top of the test), OR
2. Add `from . import fda, accessibility, automation` to `src/whatsapp_mcp/permissions/__init__.py` so mypy sees the submodules as package attributes.

**Why deferred from Plan 02-01:** this plan touches `pyproject.toml`, `exceptions.py`, and three new `sender/*.py` files. The mypy error is in `tests/unit/test_permissions/` and is unrelated to any of those. Per REL-04 scope-boundary, only fixes directly caused by Plan 02-01 changes ship in Plan 02-01 commits.

**Workaround during Plan 02-01:** the local pre-commit gate is run as `uv run mypy src/whatsapp_mcp/exceptions.py src/whatsapp_mcp/sender/` (scoped to this plan's files), which passes clean. The full-tree `uv run mypy` baseline error count is held at 1 (pre-existing), not increased.

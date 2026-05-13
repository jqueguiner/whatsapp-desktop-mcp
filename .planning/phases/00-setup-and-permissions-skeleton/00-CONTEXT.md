# Phase 0: Setup & Permissions Skeleton - Context

**Gathered:** 2026-05-13
**Status:** Ready for planning
**Mode:** auto (decisions selected via recommended-default; review before /gsd-plan-phase)

<domain>
## Phase Boundary

Deliver a runnable, installable MCP stdio server for the WhatsApp MCP project that exposes exactly one tool (`doctor`) — a permission preflight that detects and structurally reports missing macOS Full Disk Access, Accessibility, and Automation grants, with a `x-apple.systempreferences:` deep-link and the exact binary path the user must whitelist.

The phase ships nothing that touches `ChatStorage.sqlite` rows, nothing that drives WhatsApp's UI, and nothing that sends messages. It locks the scaffolding (project layout, MCP framework usage, lint/type/test gates, CI, release-to-PyPI workflow, README disclaimer + quickstart) so every later phase plugs into a known-clean baseline.

User-visible value: "I added one line to `claude_desktop_config.json`, restarted Claude Desktop, called `doctor`, and got a structured report telling me exactly which macOS permissions to grant and how."

In scope: SETUP-01, SETUP-02, SETUP-03, SETUP-04, SETUP-05, DIST-01.
Out of scope (this phase): every read tool, every send tool, schema parsing, FTS5 index, signed `.pkg` (Phase 3), `--read-only` flag mechanics (Phase 1).

</domain>

<decisions>
## Implementation Decisions

### Project Layout
- **D-01:** `src/`-layout Python package named `whatsapp_mcp` (PyPI name `whatsapp-mcp`). Reserve `whatsapp_mcp/reader/`, `whatsapp_mcp/sender/`, `whatsapp_mcp/tools/`, `whatsapp_mcp/server.py`, `whatsapp_mcp/cli.py` as empty/stub siblings now so REL-05 (Reader↔Sender isolation) is enforced from day one by structure, not by convention.
- **D-02:** Pyproject manages everything (`build-backend = hatchling.build`); no `setup.py`, no `setup.cfg`. Console script entry point `whatsapp-mcp = whatsapp_mcp.cli:main` so `uvx whatsapp-mcp` works.

### MCP Framework
- **D-03:** Use `mcp[cli]==1.27.1` with FastMCP decorators (`@mcp.tool()`); register the `doctor` tool with `readOnlyHint=true`. Do not drop down to the lower-level `Server` class.
- **D-04:** Transport is stdio only. No HTTP/SSE listener (encoded as an anti-feature in REQUIREMENTS.md — `lharries/whatsapp-mcp` was hit by HTTP path-traversal CVEs).
- **D-05:** Server entry point sets `logging.basicConfig(stream=sys.stderr, level=...)` BEFORE importing anything that might log on import. Wrap any noisy third-party import in `contextlib.redirect_stdout(sys.stderr)` defensively.

### `doctor` Tool Scope (this phase)
- **D-06:** `doctor` returns a `DoctorReport` with three permission checks only:
  - `full_disk_access`: `granted | denied`, plus `binary_path`, `db_path`, `system_settings_url`
  - `automation_whatsapp`: `granted | denied | whatsapp_not_installed`, plus same fields
  - `accessibility`: `granted | denied`, plus same fields
- **D-07:** `doctor` does NOT probe the SQLite schema, the WhatsApp.app version, or the `coverage` window — those land in Phase 1's DIAG-01 expansion. (Architecture explicitly partitions "verify the cement set" from "verify the engine runs.")
- **D-08:** `doctor` is the only `tools/list` entry in Phase 0. A no-op `ping` tool is intentionally NOT shipped — `doctor` itself is the smoke test.

### Permission Probe Technique
- **D-09:** Probes are **try-and-catch on small real actions**, not pyobjc TCC API calls and not `tccutil`/TCC.db reads.
  - **FDA**: `os.stat(db_path)` → `PermissionError` (errno EACCES / EPERM) → `denied`. `FileNotFoundError` → `whatsapp_not_installed`.
  - **Automation (WhatsApp)**: `subprocess.run(["osascript","-e",'id of application "WhatsApp"'], capture_output=True, timeout=3)`. Map: exit 0 → `granted`; stderr trailing `(-1743)` → `denied`; stderr trailing `(-1728)` / `(-600)` → `whatsapp_not_installed`; stderr trailing `(-1708)` → `granted` (event not handled by WA but Apple Events succeeded, which is what we're really probing). **Empirical override of an earlier draft** that used `tell application "WhatsApp" to count windows` — WA Catalyst returns `-1708` even when Automation is granted, which would mis-classify. Verified on the user's Mac 2026-05-13 (see 00-RESEARCH.md).
  - **Accessibility**: `osascript -e 'tell application "System Events" to count processes'` with timeout 3. Map: exit 0 → `granted`; stderr trailing `(-1719)` / `(-25211)` → `denied`. Match the trailing `(-NNNN)` numeric error code only — AppleScript stderr is locale-localized (the user's machine emits French prose), so prose regex breaks.
- **D-10:** Each probe runs in `asyncio.to_thread` / `asyncio.create_subprocess_exec` with a 3-second wait_for, so the stdio loop never blocks on a stalled `osascript`.
- **D-11:** Every `denied` response includes:
  - `binary_path`: `sys.executable` (when running under `uvx`, this is the resolved interpreter path the user must add to the corresponding TCC list)
  - `db_path`: result of the path-resolver helper (`~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite`)
  - `system_settings_url`: the right `x-apple.systempreferences:` URL per bucket (`com.apple.preference.security?Privacy_AllFiles`, `…?Privacy_Automation`, `…?Privacy_Accessibility`)
  - `remediation`: one-line human instruction
- **D-12:** Phase 0 also surfaces a structured exception class hierarchy (`PermissionRequired` → `FullDiskAccessRequired` / `AutomationPermissionRequired` / `AccessibilityPermissionRequired`) for use by future tools that fail on a missing permission. Phase 0 itself does not raise these — `doctor` reports them — but the classes ship now so Phase 1's tools can import them.

### Lint / Type / Test Gates
- **D-13:** `ruff>=0.6` configured in `pyproject.toml` with `T201` (no `print`) enabled at `error` severity from day one. Also enable `E`, `F`, `I`, `B`, `UP`, `TID`. Format width 100.
- **D-14:** `mypy>=1.10` strict on the package; `--strict --warn-unreachable`. No `Any` in tool return signatures.
- **D-15:** `pytest>=8.2` + `pytest-asyncio` for the async server, `pytest-subprocess>=1.5` for the `osascript` boundary. Coverage threshold not enforced in Phase 0 (too early), but the test directory layout (`tests/unit/`, `tests/integration/`) is established.
- **D-16:** A `tests/unit/test_stdout_purity.py` test spawns the MCP server as a subprocess, writes a valid `initialize` + `tools/list` + `tools/call doctor` JSON-RPC sequence to its stdin, reads stdout line-by-line, and **asserts every line parses as JSON-RPC**. Anything else (including a stray `print`, a third-party deprecation warning hitting stdout) fails the test. This test is the gate for SETUP-03 and is required to pass in CI.

### Distribution & CI
- **D-17:** Publish to PyPI as `whatsapp-mcp`. Use `uv build` + `uv publish` (trusted publisher via PyPI's GitHub OIDC — no secret API token in repo). DIST-01 acceptance is "`uvx whatsapp-mcp doctor` works on a fresh Mac with Python 3.12+ available via uv."
- **D-18:** GitHub Actions, two workflows:
  - `.github/workflows/ci.yml`: triggers on push + PR, runs `ruff check`, `ruff format --check`, `mypy`, `pytest -m "not live"`. Single job on `macos-14` (Apple Silicon — matches user environment). Python matrix [3.12]. Caches via `actions/setup-python` + `uv`.
  - `.github/workflows/release.yml`: triggers on `tags: ['v*']`, runs CI then `uv build` + `uv publish` via OIDC trusted-publisher.
- **D-19:** `pyproject.toml` `requires-python = ">=3.12"`. No support for 3.10/3.11 in Phase 0 — minimum can be lowered later if any user complains, but starting strict makes type hints simpler.

### README & Disclaimers (SETUP-05)
- **D-20:** README opens with a one-paragraph **WhatsApp ToS warning**: this MCP automates the user's personal WhatsApp account; WhatsApp prohibits "automated or bulk messaging"; running the send tools at scale risks an irrecoverable account ban; the project ships conservative rate limits but the user accepts the risk.
- **D-21:** README's quickstart is exactly four commands: install Claude Desktop config snippet, restart Claude Desktop, call `doctor` from the chat, follow the structured remediation. Total < 60 seconds for someone who already has WhatsApp Desktop logged in.
- **D-22:** README explicitly names the project as **personal-account, single-user, single-Mac**. No mention of WhatsApp Business API.

### Claude's Discretion
- **Logger naming, exception message wording, exact ruff rule subset:** Claude picks reasonable defaults during planning/execution.
- **Whether to ship a `--version` and `--help` flag in Phase 0:** Claude's call (probably yes; trivial via the FastMCP CLI).
- **Whether to ship a tiny `examples/` directory with the `claude_desktop_config.json` snippet** — Claude's call (probably yes for SETUP-01 ergonomics).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project decisions
- `.planning/PROJECT.md` — core value, constraints, key decisions
- `.planning/REQUIREMENTS.md` — Phase 0 owns SETUP-01..05 + DIST-01
- `.planning/ROADMAP.md` §"Phase 0" — goal + 4 success criteria

### Live-verified domain facts (do NOT re-research)
- `.planning/research/SUMMARY.md` §"TL;DR", §"Recommended Stack", §"Verified Facts About the Target Environment"
- `.planning/research/STACK.md` — Python 3.12 + `mcp[cli]==1.27.1` + FastMCP + stdlib `sqlite3` + `subprocess`+`osascript` (versions pinned)
- `.planning/research/ARCHITECTURE.md` §"Recommended Project Structure", §"Component Decomposition" (reader/sender isolation rule applies even though those modules are empty in Phase 0)
- `.planning/research/PITFALLS.md` P4, P7, P13, P14, P15 (Phase 0 mitigates these)

### External
- MCP spec — https://modelcontextprotocol.io/docs (2025-06-18 revision)
- MCP Python SDK README — https://github.com/modelcontextprotocol/python-sdk (FastMCP usage)
- macOS TCC URLs — `x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles` / `?Privacy_Automation` / `?Privacy_Accessibility`
- AppleScript error codes — `-1743` (osaErrorAuthDenied / Automation denied), `-1719` (errAEAccessibilityNotEnabled), `-1728` (errAENoSuchObject)
- PyPI trusted-publishing for GitHub Actions — https://docs.pypi.org/trusted-publishers/
- Project guide: `CLAUDE.md` (root) — hard architectural rules

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None. This is the first phase of a greenfield repo. Nothing exists in `whatsapp_mcp/` yet.

### Established Patterns
- `.planning/research/ARCHITECTURE.md` §"Recommended Project Structure" prescribes a `src/whatsapp_mcp/{server,cli,tools,reader,sender,models}.py` layout with the reader/sender isolation rule. Phase 0 must instantiate this layout (mostly as empty `__init__.py` placeholders) so Phase 1+ can fill it in without restructuring.
- Lint/type/test config style: standard 2026 Python project — `pyproject.toml` for everything; no `setup.cfg`; no `requirements*.txt` (use `uv lock`).

### Integration Points
- The only external integration this phase touches is the user's local macOS environment (TCC permissions and an installed WhatsApp.app, both probed via `osascript`/`os.stat` only — no SQLite reads in Phase 0).
- The MCP integration point is Claude Desktop's `claude_desktop_config.json`, which gets a single `whatsapp-mcp` entry (the README ships the exact JSON snippet).

</code_context>

<specifics>
## Specific Ideas

- The 3-permission `doctor` design intentionally mirrors `anipotts/imessage-mcp`'s preflight pattern (cited in research/FEATURES.md) — every iMessage MCP that didn't ship a `doctor` regretted it.
- The structured `*Required` exception classes ship in Phase 0 even though Phase 0 doesn't raise them — Phase 1's tools will import these classes from `whatsapp_mcp.exceptions`, so freezing the names + fields now avoids a Phase 1 refactor.
- "60-second quickstart" in README is a literal target — the four commands are: edit `claude_desktop_config.json`, restart Claude Desktop, ask Claude "call the WhatsApp doctor tool," follow the linked System Settings URLs.

</specifics>

<deferred>
## Deferred Ideas

- **`ping` tool / heartbeat** — `doctor` is the smoke test; no separate `ping` needed in Phase 0. Re-evaluate in Phase 1 if MCP clients want a cheap liveness check.
- **`--version` flag and `--help`** — trivial; Claude ships them in Phase 0 if it makes sense, but no decision required here.
- **Brew formula** — Phase 3 (DIST-02). Phase 0 stays `uvx`-only.
- **Signed `.pkg` installer** — Phase 3 (DIST-02). The TCC churn problem (`uvx`'s Python path changes between upgrades, breaking FDA grants) is the explicit reason `.pkg` is in the roadmap; Phase 0 documents the caveat in the README but does not solve it.
- **Schema fingerprint, WhatsApp.app version detection, `coverage` window** — Phase 1 (DIAG-01). Phase 0's `doctor` deliberately stops at the 3 permission probes.
- **Auto-injection of the `claude_desktop_config.json` snippet** (some MCPs ship a `whatsapp-mcp install --client claude-desktop` subcommand) — nice-to-have, defer.

</deferred>

---

*Phase: 0-Setup & Permissions Skeleton*
*Context gathered: 2026-05-13*

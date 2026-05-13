# Stack Research — WhatsApp MCP (macOS Desktop control)

**Domain:** Local MCP server driving the macOS WhatsApp Desktop app (Catalyst) for an LLM client (Claude Desktop / Claude Code).
**Researched:** 2026-05-13
**Overall confidence:** HIGH on language/SDK/SQLite/distribution choices. MEDIUM on the AppleScript-only "send" path (the WhatsApp Catalyst app does not publish a scripting dictionary, so sends rely on `System Events` keystroke injection — see Pitfalls). MEDIUM on the exact ChatStorage.sqlite schema stability across WhatsApp Desktop releases.

---

## TL;DR — Recommended Stack

**Primary:** Python 3.12 + `mcp[cli]` (FastMCP) + stdlib `sqlite3` (read-only URI mode) + `subprocess.run(["osascript", ...])` for sends, distributed as a `uvx`-installable PyPI package.

**Fallback:** TypeScript + `@modelcontextprotocol/sdk` + `better-sqlite3` + the `applescript` npm package, distributed via `npx`. Pick this only if the implementer is much more comfortable in TS — Python wins on every other axis for this use case.

**Explicitly do NOT pick:** Go + `whatsmeow` (different protocol, requires its own QR auth, defeats the "ride the existing Desktop session" requirement — this is what `lharries/whatsapp-mcp` does and it is *not* what this project is).

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended (vs alternatives) |
|------------|---------|---------|-----------------------------------|
| **Python** | 3.12.x | Runtime | 3.12 is the stable sweet spot for MCP / `uv` / PyPI wheel coverage in 2026. 3.10 is the floor required by `mcp`; 3.13 is bleeding-edge for some pyobjc wheels. Pick 3.12. **Confidence: HIGH.** |
| **mcp** (Python SDK) | `mcp[cli]==1.27.1` (May 2026) | MCP protocol over stdio | Official Anthropic SDK, ships FastMCP decorator API, supports stdio (default for Claude Desktop) and Streamable HTTP. TypeScript SDK works but Python wins because the macOS automation surface (pyobjc, osascript, sqlite3) is all stdlib-or-Apple-blessed. **Confidence: HIGH.** |
| **stdlib `sqlite3`** | bundled with Python 3.12 | Read `ChatStorage.sqlite` | Zero deps. WhatsApp's DB is read-only from our perspective; no async needed because each MCP tool call is a short-lived synchronous query. Open with `sqlite3.connect("file:...?mode=ro&immutable=1", uri=True)` so we never risk a write or compete with the WhatsApp app's WAL writer. **Confidence: HIGH.** |
| **`subprocess` + `osascript`** | stdlib | Send messages by driving WhatsApp via AppleScript / System Events | The WhatsApp Catalyst app does not expose an AppleScript scripting dictionary, so the only viable send path is `tell application "System Events" to keystroke ...` — which is what every public solution does. `subprocess.run(["osascript", "-e", script])` is the simplest, most debuggable, most portable option. PyObjC + NSAppleScript is nominally faster (no fork) but adds a heavy dep for a path that runs once per `send_message` call. **Confidence: HIGH for the technique; MEDIUM for long-term reliability — see Pitfalls.** |
| **`uv` / `uvx`** | `uv >= 0.5` | Distribution + isolated execution | 2025 stats: 38% of MCP servers are Python and the canonical install line in `claude_desktop_config.json` is `"command": "uvx", "args": ["whatsapp-mcp"]`. `uvx` resolves and runs the package in an ephemeral venv on every Claude Desktop start — no global pollution, no `pip install` step for the user. Beats `pipx` on speed and is what the MCP docs now recommend. **Confidence: HIGH.** |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **pyobjc-core** + **pyobjc-framework-Cocoa** | 12.1 (Apr 2026) | Optional: read clipboard, query frontmost app, future Accessibility (`AXUIElement`) work | Only pull in if/when we need to *read* the WhatsApp window state (e.g. confirm a chat is selected before keystroking). Do not pull in just to run AppleScript — `osascript` subprocess is simpler. **Confidence: MEDIUM** (likely needed in v1.1 for "send confirmation"). |
| **pydantic** | `>=2.7,<3` | Tool input/output schemas | Already a transitive dep of `mcp`. Use it explicitly for `Message`, `Chat`, `Contact` dataclasses returned by tools — gives us free JSON schema for the MCP tool contract. **Confidence: HIGH.** |
| **anyio** | `>=4.4` | Async primitives if any tool ever needs concurrency | Transitive dep of `mcp`. Don't add directly unless we end up scheduling background polling (out of scope for v1). |
| **structlog** | `>=24.1` | Structured logging to stderr (stdout is the MCP transport!) | Critical operational gotcha: an MCP stdio server **must not** print anything to stdout that isn't a JSON-RPC frame. Configure `structlog` → stderr only. Plain `logging.basicConfig(stream=sys.stderr)` works too — only add `structlog` if we want JSON logs. **Confidence: HIGH.** |
| **platformdirs** | `>=4.2` | Locate user dirs (cache for chat-name → JID lookup) | Use only if we add a small cache file. Otherwise skip. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **uv** | Project + dep + venv manager | `uv init`, `uv add mcp[cli]`, `uv run`. Replaces pip + virtualenv + pip-tools. |
| **ruff** `>=0.6` | Lint + format | Replaces black + isort + flake8 in one binary. |
| **mypy** `>=1.10` (or `pyright`) | Type checking | Strict mode on the public tool surface — MCP clients see the types. |
| **pytest** `>=8.2` + **pytest-subprocess** `>=1.5` | Test runner + osascript mocking | `pytest-subprocess` lets us assert that the right `osascript -e ...` script was assembled without actually opening WhatsApp. The send path is genuinely hard to unit-test otherwise. |
| **pytest-asyncio** `>=0.23` | If/when async tools are added | Optional. |

### Configuration / Secrets

**Secrets:** None. The whole point of this project is that it piggybacks on the user's already-authenticated WhatsApp Desktop session. There is no API key, no QR code, no token to store. **Flag in docs: this means anyone who can run our MCP server can read the user's WhatsApp.** Document that, but do not invent an auth layer for it (the MCP transport is stdio = local process = same trust boundary as the user shell).

**Config:** A single optional env var or CLI flag for the SQLite path override, in case the user has a non-default Group Container location. Default: `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite`. Fail loudly with a permissions hint if the path exists but isn't readable (Full Disk Access not granted).

---

## Installation

```bash
# For end users — single line in claude_desktop_config.json:
# {
#   "mcpServers": {
#     "whatsapp": {
#       "command": "uvx",
#       "args": ["whatsapp-mcp"]
#     }
#   }
# }

# For developers:
curl -LsSf https://astral.sh/uv/install.sh | sh
uv init whatsapp-mcp && cd whatsapp-mcp
uv add "mcp[cli]==1.27.1" "pydantic>=2.7,<3" "structlog>=24.1"
uv add --dev "ruff>=0.6" "mypy>=1.10" "pytest>=8.2" "pytest-subprocess>=1.5"
# Optional, only when accessibility readback is needed:
# uv add "pyobjc-core==12.1" "pyobjc-framework-Cocoa==12.1"
```

---

## Per-Component Rationale

### Why Python over TypeScript over Go

| Criterion | Python (recommended) | TypeScript | Go |
|-----------|---------------------|------------|-----|
| MCP SDK maturity | `mcp` 1.27.1, FastMCP decorators, official | `@modelcontextprotocol/sdk` 1.29.0, official, also mature | Community (`mark3labs/mcp-go`), no first-party SDK |
| macOS automation | stdlib `subprocess`+`osascript`; pyobjc native if needed | Workable via `applescript` / `node-osascript` npm wrappers; less first-class | Possible via `os/exec` + osascript; least Mac-native ecosystem |
| SQLite (read-only) | stdlib `sqlite3`, zero deps | Needs `better-sqlite3` (native build) | `mattn/go-sqlite3` (cgo) |
| Distribution to Claude Desktop | `uvx whatsapp-mcp` — single line, no Node runtime needed | `npx whatsapp-mcp` — works but requires Node and npm registry publish | Built binary per arch — heaviest user setup |
| Apple-signed binary path (matters for TCC/FDA) | `/usr/bin/python3` is Apple-signed; user-installed Pythons are not — TCC propagation from Claude.app **only** works for Apple-signed children. Mitigation: instruct users to grant Full Disk Access **directly to the Python binary `uv` selects** (or Terminal/Claude.app for the launching parent). | Same problem (Node is not Apple-signed). | Same problem. |
| Type safety | mypy/pyright (gradual) | Native | Native |
| Verdict | **Pick this.** Smallest dep tree, native osascript story, minimal distribution friction, matches `mcp[cli]` design. | Fallback if team is TS-only. | Avoid for this project — its strength (`whatsmeow`) is *not* what we're building. |

**Confidence: HIGH.**

### Why stdlib `sqlite3` over aiosqlite / SQLAlchemy / better-sqlite3

- The DB is **read-only** for us. We are a passenger on WhatsApp's writer.
- Each MCP tool call is short-lived and synchronous from the LLM's perspective; there is no benefit to async I/O for a single 50ms query.
- WAL mode (which WhatsApp uses) supports many concurrent readers as long as we open with `?mode=ro&immutable=1` — no risk of corrupting WhatsApp's writer.
- `aiosqlite` adds an unnecessary thread-per-connection and a dep, with no perf gain for our access pattern (the [aiosqlite issue #97 confirms it is *slower* than stdlib sqlite3 in many cases](https://github.com/omnilib/aiosqlite/issues/97)).
- SQLAlchemy is overkill: we have ~5 tables, hand-rolled SQL is shorter and more grep-able than ORM models for a CoreData-style schema we don't own.
- TS equivalent (`better-sqlite3`) is excellent in its ecosystem but requires a native build step that `uvx` users will never see. Not relevant to the recommended stack.

**Confidence: HIGH.**

### Why `subprocess + osascript` over PyObjC NSAppleScript over UI scripting libraries

- The WhatsApp Catalyst app **does not publish an AppleScript scripting dictionary**, so we cannot do `tell application "WhatsApp" to send message "x"`. Confirmed by absence in every search result and matched by every public WhatsApp-on-Mac automation that resorts to keystroke injection or web-based DOM manipulation in Chrome.
- The only viable send path is: `tell application "WhatsApp" to activate` → `tell application "System Events" to keystroke ...`. This requires the user to grant **Accessibility** permission (System Settings → Privacy & Security → Accessibility) to the launching process (Claude Desktop, Terminal, or the Python binary).
- `subprocess.run(["osascript", "-e", script], check=True, timeout=10)` is the most maintainable form: AppleScript stays as readable strings, easy to log, easy to test with `pytest-subprocess`, no PyObjC NSAppleScript glue.
- PyObjC NSAppleScript would skip the fork+exec but it adds 30+MB of pyobjc wheels and complicates the Apple-signing/TCC story — not worth it for a path called once per send.
- `pywhatkit`, `selenium`, `pyautogui` are explicitly out of scope: they require WhatsApp Web in a browser, which we are *not* using.

**Confidence: HIGH on technique. MEDIUM on durability — see PITFALLS.md for the System Events keystroke fragility (focus stealing, IME, non-ASCII chars, send button location).**

### Why `uvx` over `pipx` over packaged binary

- `uvx` is what the official MCP docs and the broader 2026 MCP ecosystem standardise on (mirroring the Node side's `npx`).
- Resolves and runs the package in an isolated ephemeral venv on every Claude Desktop launch — no stale installs, no `~/.local/pipx` directory the user has to know about.
- 10-100x faster than `pipx` per-invocation (Rust resolver + content-addressed cache).
- Single-line config in `claude_desktop_config.json` — the lowest-friction install we can ship.
- Built binary (PyInstaller / shiv) is the heaviest option and complicates Apple notarization; reject unless we hit a hard TCC blocker that signing solves.

**Confidence: HIGH.**

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Python + `mcp` | TypeScript + `@modelcontextprotocol/sdk` 1.29.0 + `better-sqlite3` + `applescript` npm | Team is TS-only, OR a future v2 wants to share types with a web UI. |
| stdlib `sqlite3` | `aiosqlite` 0.20+ | Only if we add a streaming endpoint that yields thousands of rows over MCP — not in scope for v1. |
| stdlib `sqlite3` | `peewee` / `sqlglot` for query building | If the schema bites us with version drift and we want safer query construction. Reach for this in v1.1, not v1. |
| `subprocess` + `osascript` | `py-applescript` (PyObjC NSAppleScript wrapper) | If we measure unacceptable latency from `osascript` cold-start (unlikely — ~50ms) or need to call the same compiled script repeatedly within one tool invocation. |
| `subprocess` + `osascript` | Hammerspoon / Lua bridge | Never for v1 — adds a whole separate runtime the user must install. |
| `uvx` | `pipx` | If a corporate user has `uv` blocked but `pipx` allowed. |
| `uvx` | Built binary (PyInstaller) | Only if TCC/FDA propagation forces us to ship an Apple-notarized signed binary. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **`whatsmeow` (Go) / Baileys (TS) / `lharries/whatsapp-mcp` architecture** | These connect via the WhatsApp Web multidevice protocol with their own QR-pairing — that is a *different product*. The user explicitly rejected it in PROJECT.md ("ride the already-running Desktop session"). It also burns one of WhatsApp's 4 paired-device slots. | Read `ChatStorage.sqlite` directly; send via osascript. |
| **WhatsApp Cloud / Business API** | Requires Meta business onboarding, phone number provisioning, and is for business accounts. Explicitly out of scope. | Same — local DB + osascript. |
| **Selenium / `pywhatkit` / `pyautogui` driving WhatsApp Web in Chrome** | Requires keeping a browser tab open, fragile DOM, defeats "drive the Desktop app." | osascript against the native Catalyst app. |
| **Electron-era assumptions about WhatsApp's storage** | WhatsApp deprecated the Electron Mac app in Sept 2024 and the current Catalyst app stores data at `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/` with iOS-style CoreData tables (`ZWAMESSAGE`, `ZWACHATSESSION`, `ZWAMEDIAITEM`). Old tutorials referencing `~/Library/Application Support/WhatsApp/Databases/Databases.db` are stale — that file has no chat content. | Always probe `ChatStorage.sqlite` in the Group Container. |
| **`aiosqlite` for our query pattern** | Slower than stdlib `sqlite3` for short queries (per upstream issue #97), adds a dep, no benefit for read-only short-lived tool calls. | stdlib `sqlite3` with `?mode=ro&immutable=1`. |
| **PyObjC just to run AppleScript** | 30MB of wheels, TCC/Apple-signing complications, no win over `osascript` subprocess for single-shot sends. | `subprocess.run(["osascript", "-e", ...])`. |
| **Writing to `ChatStorage.sqlite`** | The WhatsApp app holds the writer lock and a fake message would be discarded (or worse, corrupt the DB). The "creating a fake WhatsApp message via SQLite" article confirms the manipulation is detectable and gets overwritten on next sync. | All writes go through the GUI via osascript. |
| **`stdout` for logs** | MCP stdio transport uses stdout for JSON-RPC frames. A single stray `print()` corrupts the protocol and Claude Desktop drops the connection. | All logging to `stderr`. |
| **Bundling our own Python with PyInstaller for v1** | Adds notarization, code signing, ~80MB binaries. Not needed when `uvx` works. | `uvx whatsapp-mcp`. |

---

## macOS Permissions — Part of the Stack Story

This is non-negotiable runtime context the install docs MUST cover:

1. **Full Disk Access (FDA) — required to read `ChatStorage.sqlite`.**
   The Group Container is sandboxed; only the WhatsApp process itself reads it without FDA. Our process needs FDA granted to:
   - The launching parent (Claude Desktop / Terminal / Claude Code), AND/OR
   - The actual Python binary `uv` resolves (which lives under `~/.local/share/uv/python/...` — surprising for users).

   Known landmine: TCC silently denies non-Apple-signed children. Apple-signed `/usr/bin/python3` inherits TCC from a granted parent; a Homebrew/`uv`-managed Python may not. Document the "drag the binary into the FDA list" workaround.

2. **Accessibility — required for `System Events` keystroke injection (the send path).**
   Granted to whichever process invokes `osascript`. Same propagation caveat as FDA.

3. **Automation — required for `tell application "WhatsApp" to activate` to succeed.**
   First invocation triggers a permission prompt; if the user dismisses it the send silently fails. Document `tccutil reset AppleEvents` as a recovery step.

4. **No keychain, no network, no secrets storage.** This MCP server must never make outbound network calls — the entire trust story is "local, piggybacks on Desktop session."

**Confidence: HIGH on the requirements; MEDIUM on the exact UX of the prompts (Apple changes them per major macOS release).**

---

## Testing Approach (code that touches a live macOS app)

Three layers, in order of preference:

1. **Pure-function unit tests (most coverage).** Extract everything possible into pure functions: SQL row → `Message` dataclass, search filter parsing, AppleScript template rendering. Test these with plain `pytest` against fixture rows. **Aim for 80%+ of code here.**

2. **`pytest-subprocess` for the osascript boundary.** Register expected `osascript -e <script>` invocations and assert the assembled script string is correct without actually keystroking anything. This is the right unit-test boundary for the send path.
   ```python
   def test_send_message_assembles_script(fp):
       fp.register(["osascript", "-e", fp.any()], stdout=b"")
       send_message("Family", "hi")
       assert b'tell application "WhatsApp"' in fp.calls[0][2].encode()
   ```

3. **Hand-driven integration tests (smoke).** A small `tests/integration/` suite gated by `RUN_LIVE_WHATSAPP=1` env var that actually opens WhatsApp and sends to a designated test chat. Run manually before each release; never in CI. Document the test chat setup.

**Avoid:** trying to mock `pyobjc` or set up a headless Catalyst app. Both are dead ends. The `pytest-subprocess` boundary is where the seam belongs.

**Confidence: HIGH.**

---

## Stack Patterns by Variant

**If WhatsApp ships a future schema change that breaks our reader:**
- Isolate ALL schema knowledge in one `chatstorage_schema.py` module with versioned query strings and a runtime `PRAGMA user_version` check.
- Fail loudly with the detected schema version and a "supported up to vN" message — do not return wrong data.

**If the AppleScript send path proves too unreliable in the wild:**
- Fallback A: drop down to PyObjC + `AXUIElement` to programmatically locate the message text field and `setValue:` it directly (more robust than keystroke, but requires Accessibility API).
- Fallback B: send via `web.whatsapp.com` automation as a *secondary* path — only as a v1.1 escape hatch, never as v1 default (it contradicts the project's design intent).

**If a Windows/Linux user shows up demanding support:**
- Deferred. v1 is macOS-only. The send path would need to be rewritten per-OS (PowerShell + UI Automation on Windows, dbus on Linux). The reader path may or may not transfer (Windows WhatsApp uses a UWP storage layer; Linux has no native WhatsApp app).

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `mcp==1.27.1` | Python 3.10+, Claude Desktop using MCP 2025-11 spec | Use `mcp[cli]` extra for the `mcp` CLI (helpful for `mcp dev`). |
| `pyobjc-framework-Cocoa==12.1` | Python 3.10–3.14 | Pin pyobjc-core and pyobjc-framework-Cocoa to the same major version. |
| `pytest-subprocess>=1.5` | pytest 8.x | Last verified May 2026. |
| macOS | 13 Ventura minimum, 14 Sonoma / 15 Sequoia / 26 Tahoe verified | Catalyst WhatsApp requires macOS 11+; we target current OS releases. |
| WhatsApp Desktop | Catalyst app (Sept 2024+) | The Electron app is deprecated; do not test against it. |

---

## Open Questions

1. **Exact stability of `ZWAMESSAGE` / `ZWACHATSESSION` columns across WhatsApp Catalyst minor versions.** Forensics articles describe an iOS-style schema, but the macOS Catalyst app may add/rename columns. **Mitigation:** dump schema in CI and snapshot-test against a known-good copy. Flag as needing phase-specific verification.
2. **Whether reading `ChatStorage.sqlite` while WhatsApp is the writer ever returns torn rows under WAL.** Theoretically `?mode=ro&immutable=1` with `?nolock=1` is safe, but worth measuring under load. Add to phase 1 spike.
3. **Whether keystroke injection handles emoji and non-BMP Unicode reliably for sends.** AppleScript `keystroke` historically truncates surrogate pairs. May need Pasteboard-based injection (write to clipboard, ⌘V, restore clipboard) as a fallback.
4. **Apple's TCC behaviour for `uvx`-managed Python binaries on macOS 26 Tahoe.** Active issue (see anthropics/claude-code#36832, #50735). May force us to recommend `pipx --system-site-packages` or even document a manual Python install path.
5. **Whether WhatsApp's media files (ZWAMEDIAITEM paths) are accessible without additional sandbox extensions** — they live under the same Group Container but may have stricter ACLs.

---

## Sources

- [MCP Python SDK on PyPI (`mcp` 1.27.1, May 2026)](https://pypi.org/project/mcp/) — version + Python 3.10 floor, HIGH
- [modelcontextprotocol/python-sdk GitHub](https://github.com/modelcontextprotocol/python-sdk) — FastMCP API, stdio transport, HIGH
- [`@modelcontextprotocol/sdk` 1.29.0 on npm](https://www.npmjs.com/package/@modelcontextprotocol/sdk) — TS SDK fallback version, HIGH
- [Group-IB: WhatsApp forensic artifacts](https://www.group-ib.com/blog/whatsapp-forensic-artifacts/) — confirms `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite` and `ZWAMESSAGE`/`ZWACHATSESSION` schema, MEDIUM (forensics-focused, not Catalyst-specific dating)
- [WhatsApp deprecates Electron Mac app for Catalyst (WABetaInfo, idownloadblog)](https://www.idownloadblog.com/2023/01/26/whatsapp-mac-app-native-beta-catalyst/) — confirms the app is Catalyst-based as of 2024+, HIGH
- [Michael Tsai: SQLite Databases in App Group Containers](https://mjtsai.com/blog/2025/05/15/sqlite-databases-in-app-group-containers-dont/) — confirms WhatsApp uses the Group Container pattern, MEDIUM
- [aiosqlite issue #97: slower than sqlite3](https://github.com/omnilib/aiosqlite/issues/97) — basis for the "stdlib sqlite3 is fine" call, HIGH
- [bswen: Using uvx to Run MCP Servers in Claude Desktop](https://docs.bswen.com/blog/2026-03-05-using-uvx-with-mcp-servers/) — `uvx` install pattern, HIGH
- [Build to Launch: How to Install Any MCP Servers](https://buildtolaunch.substack.com/p/mcp-server-types-installation-guide-claude-cursor) — 55% JS / 38% Python ecosystem split, MEDIUM
- [GitHub: lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) — confirms what we are *not* building (whatsmeow + Go bridge), HIGH
- [GitHub: victor-torres/whatsapp-applescript](https://github.com/victor-torres/whatsapp-applescript) — proves the keystroke-injection technique, MEDIUM (targets WhatsApp Web in Chrome, not the Catalyst app — but the System Events approach generalises)
- [Srool the Knife: Automating WhatsApp Using AppleScript (2024)](https://www.srooltheknife.com/2024/02/automating-whatsapp-using-applescript.html) — current WhatsApp + AppleScript techniques, MEDIUM
- [PyObjC framework Cocoa 12.1 on PyPI](https://pypi.org/project/pyobjc-framework-Cocoa/) — version pin if/when needed, HIGH
- [HackTricks: macOS TCC](https://angelica.gitbook.io/hacktricks/macos-hardening/macos-security-and-privilege-escalation/macos-security-protections/macos-tcc) — TCC database + propagation rules, MEDIUM
- [anthropics/claude-code#36832 — TCC permission prompt every launch on macOS](https://github.com/anthropics/claude-code/issues/36832) — open TCC propagation issue affecting MCP servers, HIGH (active bug)
- [Simon Willison: Mocking subprocess with pytest-subprocess](https://til.simonwillison.net/pytest/pytest-subprocess) — testing approach for osascript boundary, HIGH
- [PyObjC ScriptingBridge API Notes](https://pyobjc.readthedocs.io/en/latest/apinotes/ScriptingBridge.html) — confirms ScriptingBridge is "flawed" per upstream and PyObjC NSAppleScript is the recommended bridge if we ever need it, HIGH

---
*Stack research for: macOS WhatsApp Desktop MCP server*
*Researched: 2026-05-13*

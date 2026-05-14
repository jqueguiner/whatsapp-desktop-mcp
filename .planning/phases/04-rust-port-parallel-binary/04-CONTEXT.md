# Phase 4: Rust port (parallel binary, additive) - Context

**Gathered:** 2026-05-14
**Status:** Ready for planning
**Mode:** auto (decisions selected via recommended-default; review before /gsd-plan-phase)

<domain>
## Phase Boundary

Spike a Rust MCP server as a SECOND binary `whatsapp-desktop-mcp-rs` shipped alongside the existing Python `whatsapp-desktop-mcp` (PyPI 0.0.1rc1, live). Python implementation stays load-bearing for v1.0; Rust is an experimental additive second-track. The MVP scope of Phase 4 is the SMALLEST validation slice — `doctor` tool only — that proves the architecture works end-to-end (Cargo workspace, MCP Rust SDK, AX-API via objc2, osascript subprocess, AppleScript probe parsing, structured permission report). Promotion to full parity (8 read tools + send_message) is Phase 4.x or Phase 5; v0 ships ONLY the doctor tool.

Hard user constraint: **don't override existing Python code.** Rust lives under a new top-level `rs/` Cargo workspace. Zero shared source files. Python source files byte-stable. CI Python gates unchanged.

User-visible value (v0): a Rust developer can `cargo install --git github.com/jqueguiner/whatsapp-desktop-mcp.git --root /usr/local rs/whatsapp-desktop-mcp-rs`, point Claude Desktop at `/usr/local/bin/whatsapp-desktop-mcp-rs`, call `doctor`, and get the same 3-permission preflight report shape as the Python implementation.

Success-criterion mapping (per ROADMAP §"Phase 4"):
- SC1 (no shared source files; cargo build doesn't touch Python; Python tests don't require Rust toolchain) — Phase 4 v0
- SC2 (cargo build → stdio MCP server with doctor tool returning 3-permission preflight + DB path + WA version) — Phase 4 v0
- SC3 (cross-binary parity test, RUN_LIVE_RUST=1) — Phase 4 v0 (doctor parity only)
- SC4 (README "Rust port (experimental)" subsection) — Phase 4 v0
- SC5 (no PyPI publish change; Rust artifact attached to GitHub release via separate cargo-build job) — Phase 4 v0

In scope (v0): rs/ Cargo workspace; doctor tool with 3 probes; FDA/Automation/Accessibility probes; bidi-blind error code parsing; structured `DoctorReport` model; MCP stdio handshake; cross-binary parity test.

Out of scope (this phase, deferred to Phase 4.x or Phase 5): read tools (list_chats, read_chat, extract_recent, search_messages, search_contacts, get_chat_metadata, get_message_context); send_message tool + sender package; cross-chat-quote heuristic; rate limiter; audit log; FTS5 sidecar; brew formula bottle for Rust; Rust release.yml PyPI-equivalent publish.

</domain>

<decisions>
## Implementation Decisions

### Cargo Workspace Shape
- **D-01:** **Top-level `rs/` directory contains a Cargo workspace.** Workspace root: `rs/Cargo.toml` declaring `[workspace] members = [...]`. Sibling to `src/whatsapp_desktop_mcp/` (Python). Building Rust does NOT touch Python; running Python `pytest` does NOT require `cargo`.
- **D-02:** **Workspace member layout (mirrors Python package structure for cross-language maintainability):**
  - `rs/whatsapp-desktop-mcp-rs/` — binary crate (the MCP server entry point)
  - `rs/crates/wamcp-models/` — lib crate (Pydantic-equivalent: serde-serializable types — `DoctorReport`, `PermissionCheck`, `PermissionState`, `Coverage`, `Jid`, `Chat`, `Message`, `Contact`, `MediaRef`)
  - `rs/crates/wamcp-permissions/` — lib crate (3 permission probes; D-09 patched Automation; bidi-blind error parsing)
  - `rs/crates/wamcp-paths/` — lib crate (path resolvers + system_settings_url; mirrors Python paths.py)
  - `rs/crates/wamcp-tools/` — lib crate (MCP tool registrations; v0 = doctor only)
  - `rs/crates/wamcp-reader/` — lib crate (empty in v0; reserved for Phase 4.x parity work; REL-05-equivalent rule applies)
  - `rs/crates/wamcp-sender/` — lib crate (empty in v0; reserved for Phase 4.x; REL-05-equivalent rule)
- **D-03:** **REL-05 D-24 evolution mirrored in Cargo:** `wamcp-reader` MUST NOT have `wamcp-sender` in its `[dependencies]`. `wamcp-sender` MAY ONLY depend on `wamcp-reader-connection` (a future thin sub-crate to be carved out when parity work begins) — NOT on `wamcp-reader` proper. Phase 4 v0 ships both crates EMPTY (`lib.rs` with `// Phase 4.x: reserved` placeholder), so the rule is enforced structurally from day one. A `rs/tests/isolation.rs` integration test parses the `Cargo.lock` graph and asserts the rule.
- **D-04:** **Workspace `[workspace.package]` shared metadata:** `version = "0.0.0"` (semver pre-1.0; Rust port not yet shipped to any registry); `edition = "2021"` (stable, well-supported); `rust-version = "1.75"` (MSRV — pinned for reproducibility; bump only when a dep requires it); `license = "MIT"`; `repository = "https://github.com/jqueguiner/whatsapp-desktop-mcp"`; `homepage` same.

### MCP Rust SDK
- **D-05:** **`rmcp` (modelcontextprotocol/rust-sdk).** Official Anthropic-maintained Rust SDK. Pin via `rmcp = { version = "<latest-stable>", features = ["transport-stdio", "macros"] }`. `transport-stdio` feature enables the JSON-RPC stdio loop; `macros` feature provides `#[tool]` derive for ergonomic registration mirroring Python FastMCP `@mcp.tool` decorator.
- **D-06:** **Tool registration pattern:** `#[derive(Tool)] struct DoctorTool;` with `#[tool(name = "doctor", description = "...")] async fn doctor(&self, ctx: Context) -> Result<DoctorReport>`. Mirrors Python's `@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True), meta={"anthropic/maxResultSizeChars": 60000})` — translate annotations + meta to rmcp's equivalent attribute syntax (researcher locks exact form; if rmcp doesn't support `meta` annotations natively, set via `ToolBuilder::meta()` programmatic API).
- **D-07:** **Server entry point** in `rs/whatsapp-desktop-mcp-rs/src/main.rs`. Sets up tracing-subscriber to stderr (NEVER stdout — equivalent to Python D-05 stdout-purity rule). Constructs `rmcp::Server::builder().add_tool(DoctorTool)` and `server.serve(StdioTransport).await`.
- **D-08:** **Stdout-purity equivalent:** all logging via `tracing` crate writing to stderr (`fmt().with_writer(io::stderr).init()`). Lint-blocked at workspace level: `[workspace.lints.rust] unused_must_use = "deny"` plus a `clippy::print_stdout = "deny"` lint to catch any `println!` (Rust's equivalent of Python's `print`). CI test in Phase 4 mirrors Python's `tests/unit/test_stdout_purity.py` — spawns the Rust binary, asserts stdout pure JSON-RPC.

### AX-API + AppleScript
- **D-09:** **PyObjC-equivalent crates:** `objc2 = "0.5"` (modern, Send+Sync, actively maintained 2025-2026), `objc2-foundation = "0.2"` (NSString/NSArray bindings), `objc2-application-services = "0.2"` (the AX-API surface — `AXUIElementCopyAttributeValue`, `AXUIElementCreateApplication`, `kAXFocusedWindowAttribute`, `kAXTitleAttribute` constants). Older `cocoa` crate explicitly REJECTED (maintenance-only; not Send+Sync; pre-2024 API).
- **D-10:** **AX state assertion in v0 Rust scope:** NOT shipped. AX-API integration is reserved for Phase 4.x (when send_message lands and needs the load-bearing P5 mitigation). v0 doctor tool does NOT call AX; it only does the 3 permission probes via osascript subprocess + `os::stat()` for FDA. Crate dep `objc2-application-services` is added to workspace Cargo.toml v0 but only USED in `wamcp-permissions/src/accessibility.rs`'s permission probe (which spawns `osascript` — same as Python's D-09 patched probe).
- **D-11:** **AppleScript invocation:** `std::process::Command::new("osascript")` mirroring Python `subprocess.run(["osascript", ...])`. Locale-blind error parsing via `regex = "1"` crate with the same regex Python uses: `\((-?\d+)\)\s*\Z`. Error code mapping verbatim from D-09 patched probe: `0` → granted; `-1708` → granted (event-not-handled by WA but Apple Events succeeded); `-1743` → denied; `-1728`/`-600` → whatsapp_not_installed; `-1719`/`-25211` → accessibility denied. Bidi-strip helper: `_strip_bidi(s: &str) -> String` removes U+200E (LRM), U+2068 (FSI), U+2069 (PDI) codepoints — same as Python `_strip_bidi`.
- **D-12:** **3 permission probes (mirrors Python `wamcp-permissions/src/{fda,automation,accessibility}.rs`):**
  - `fda.rs` — `std::fs::metadata(db_path)` → `ErrorKind::PermissionDenied` → `denied`; `ErrorKind::NotFound` → `whatsapp_not_installed`; OK → `granted`. Wrapped in `tokio::task::spawn_blocking` (mirrors Python `asyncio.to_thread`).
  - `automation.rs` — D-09 patched probe `id of application "WhatsApp"` via osascript subprocess. Map: exit 0 → `granted`; trailing `(-1743)` → `denied`; `(-1728)`/`(-600)` → `whatsapp_not_installed`; `(-1708)` → `granted` (load-bearing patch — verbatim from Python).
  - `accessibility.rs` — `tell application "System Events" to count processes` via osascript. Map: exit 0 → `granted`; `(-1719)`/`(-25211)` → `denied`.

### Doctor Tool (v0 scope)
- **D-13:** **`DoctorReport` shape mirrors Python's:** `full_disk_access: PermissionCheck`, `automation_whatsapp: PermissionCheck`, `accessibility: PermissionCheck`, `db_path: Option<String>`, `schema_fingerprint: Option<SchemaFingerprint>`, `whatsapp_app_version: Option<String>`, `last_message_ts: Option<i64>`, `coverage_summary: Option<Coverage>`. v0 Rust populates the 3 permission probes + `db_path` + `whatsapp_app_version` (parsed from `Info.plist` via `plist` crate). Other fields = `None` in v0 (schema fingerprint, last-message ts, coverage are reader-tier work — deferred to Phase 4.x parity).
- **D-14:** **`PermissionCheck` shape:** `state: PermissionState`, `bucket: String`, `binary_path: String`, `db_path: Option<String>`, `system_settings_url: String`, `remediation: String`. Same as Python.
- **D-15:** **`PermissionState` enum:** `Granted | Denied | WhatsappNotInstalled | Unknown`. Serde-serialized as snake_case strings to match Python output verbatim.
- **D-16:** **`binary_path` value:** `std::env::current_exe()?.to_string_lossy().into_owned()` — the actual running Rust binary path (analogous to Python's `sys.executable`). For `cargo install`-ed binaries: `~/.cargo/bin/whatsapp-desktop-mcp-rs`. For `cargo build --release` local: `<workspace>/rs/target/release/whatsapp-desktop-mcp-rs`.

### SQLite (deferred but crate added v0)
- **D-17:** **`rusqlite = { version = "0.31", features = ["bundled"] }` in workspace Cargo.toml.** Feature `bundled` ships SQLite 3.x statically linked — eliminates system SQLite version variance. v0 doctor tool does NOT open the DB (no schema fingerprint probe in v0); the dep is added so Phase 4.x reader work can immediately consume it.
- **D-18:** **RO-WAL connection pattern (Phase 4.x reservation, locked here for consistency):** `Connection::open_with_flags(uri_path, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_URI | OpenFlags::SQLITE_OPEN_NO_MUTEX)`. URI form: `format!("file:{}?mode=ro", db_path.display())`. Set `PRAGMA busy_timeout = 5000` post-open. Wrap in `spawn_blocking`.

### Distribution
- **D-19:** **GitHub release artifact only for v0.** `release.yml` adds a `rust-build` job (downstream of `publish` PyPI job; runs only on tag push, no skip-block needed since cargo is always available on macOS-14 runners). Steps: `cargo build --release --locked`, strip, `softprops/action-gh-release@v2` attaches `whatsapp-desktop-mcp-rs-{version}-{arch}.tar.gz` to the same GitHub release. Apple-Silicon-only for v0 (`runs-on: macos-14`); Intel cross-compile deferred.
- **D-20:** **No PyPI publish for Rust binary.** v1.0 release.yml's PyPI publish job stays Python-only. Rust v0 ships exclusively as GitHub release asset.
- **D-21:** **No brew formula bottle for Rust v0.** Brew tap stays Python-only. `cargo install --git https://github.com/jqueguiner/whatsapp-desktop-mcp --root /usr/local rs/whatsapp-desktop-mcp-rs` documented as the dev install path.
- **D-22:** **Rust binary version:** `0.0.0` for first Phase 4 ship (separate from Python's 0.0.1rc1 / 0.1.0 sequence). Rust versioning is independent of Python's. v0 ships as v0.0.0; first user-facing release as v0.1.0-rust1 (post-doctor-parity); promoted to 1.0.0 only after full parity.

### Cross-Binary Parity Test
- **D-23:** **`tests/integration/test_rust_python_parity.py`** (lives in Python test suite for ease — Python test runs both binaries via subprocess and compares JSON outputs). Gated by `RUN_LIVE_RUST=1` env var (separate from RUN_LIVE_WHATSAPP — user opts in to Rust binary execution explicitly). Steps:
  1. Locate Rust binary at `rs/target/release/whatsapp-desktop-mcp-rs` (skip test if not built — standard pytest skip with informative message).
  2. Spawn each binary as MCP stdio server, send `initialize` + `tools/list` + `tools/call doctor` JSON-RPC sequence to each.
  3. Parse `doctor` responses from both.
  4. Assert: `set(rust_report.keys()) == set(python_report.keys())` (top-level field shape parity).
  5. Assert: each PermissionCheck's `state` matches across binaries (granted vs denied parity — the actual TCC state must be equivalent because both binaries are checking the SAME machine; if Rust says `granted` and Python says `denied` for the same probe, the architecture is broken).
  6. Assert: `binary_path` values DIFFER (sanity check that the test actually ran two binaries) but `db_path` + `system_settings_url` MATCH (both probe the same WhatsApp install).
- **D-24:** **Sandbox carry:** the parity test reuses Phase 2 B-2 `_isolate_live_state` autouse fixture extended in Phase 3 D-24 — but only the rate-limit + audit + FTS sandbox parts apply (Rust v0 doesn't have those subsystems). Document this as a known v0 limitation.

### CI Integration
- **D-25:** **`.github/workflows/ci.yml` extension:** add a `rust-lint-test` job that runs in PARALLEL to existing `lint-type-test` job (which is Python). Steps: `actions-rust-lang/setup-rust-toolchain@v1` (pin version), `cd rs && cargo fmt --check && cargo clippy -- -D warnings && cargo test --workspace`. Job's failure does NOT block existing Python job (separate matrix entries). `runs-on: macos-14` (objc2 builds need macOS).
- **D-26:** **Cargo.lock committed.** Reproducible builds across maintainers + CI. `.gitignore` adds `rs/target/` (build artifacts; large, regeneratable). Lockfile lives at `rs/Cargo.lock` (workspace root).
- **D-27:** **`rs/rustfmt.toml`** with sane defaults: `edition = "2021"`, `max_width = 100` (matches Python's ruff line-length=100), `imports_granularity = "Module"`, `group_imports = "StdExternalCrate"`. Single source of truth for Rust formatting.
- **D-28:** **`rs/clippy.toml`** with `msrv = "1.75"` and warn-level pedantic lints scoped to relevant categories (no blanket `clippy::pedantic = "warn"` — too noisy; pick `clippy::correctness = "deny"`, `clippy::suspicious = "deny"`, `clippy::style = "warn"`, `clippy::print_stdout = "deny"` per D-08).

### README + Docs
- **D-29:** **README adds a "Rust port (experimental)" subsection under `## Install`** (Phase 3 D-31 3-row matrix). The new row is the FOURTH option, marked `experimental` with a stark "v0 ships only doctor tool; not yet parity with Python; for early adopters" callout. Install command: `cargo install --git https://github.com/jqueguiner/whatsapp-desktop-mcp --root /usr/local rs/whatsapp-desktop-mcp-rs`. claude_desktop_config.json snippet: `{"command": "/usr/local/bin/whatsapp-desktop-mcp-rs"}`.
- **D-30:** **`rs/README.md`** — Rust-specific README inside the Cargo workspace. Build instructions (`cargo build --release --locked`), test instructions (`cargo test --workspace`), parity-test instructions (`RUN_LIVE_RUST=1 uv run pytest tests/integration/test_rust_python_parity.py`). Cross-references the project README for context.

### Threat Model (high-level — planner expands per-task)
- **T-1 (Rust binary supply chain):** `cargo install --git` pulls source + builds locally — no signed-binary attack surface. Future bottle distribution (Phase 4.x) requires re-evaluation.
- **T-2 (TCC churn under cargo install):** `cargo install --root /usr/local` puts binary at `/usr/local/bin/whatsapp-desktop-mcp-rs` — STABLE path, satisfies P15 mitigation same way Python `.pkg`/brew does. Re-installs preserve TCC grants.
- **T-3 (objc2 unsafe-FFI risk):** `objc2`'s `extern_class!` + `msg_send_id!` macros encapsulate unsafe FFI in well-tested abstractions; no hand-rolled unsafe blocks in Phase 4 v0 source.
- **T-4 (osascript subprocess):** same as Python — locale-blind regex parsing, exit-code mapping, no shell injection (use `Command::new` + `arg()` form, never shell-out via string).
- **T-5 (parity test false-positive):** parity test mocks nothing — both binaries run live against the same WhatsApp Desktop install. False-positive risk: machine state changes between rust-binary call and python-binary call (e.g., user toggles a TCC permission). Mitigation: run both binaries in tight sequence (< 1s apart) and document the race.

### Claude's Discretion
- Exact rmcp version pin (latest stable at execution time)
- Exact objc2 / objc2-foundation / objc2-application-services version pins
- Whether to ship a `rs/.cargo/config.toml` with build settings (probably yes — `[target.aarch64-apple-darwin] rustflags = ["-C", "target-cpu=apple-m1"]` for native perf)
- Whether to use `cargo-deny` for dep auditing (probably yes for Phase 4 v0 hygiene; trivial)
- Whether to ship a `Justfile` or `make` wrapper for common cargo commands (Claude's call; small repo, probably skip)
- Exact CI matrix shape (Python existing + Rust new — sequential or parallel jobs)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project decisions
- `.planning/PROJECT.md` — core value, hard constraint: macOS-only v1
- `.planning/ROADMAP.md` §"Phase 4" — 5 success criteria + scope locks
- `.planning/STATE.md` — Roadmap Evolution note for Phase 4

### Live-verified domain facts (do NOT re-research)
- `.planning/research/SUMMARY.md` — DB path, Z_VERSION, send-path constraints (same for Rust as Python)
- `.planning/phases/00-setup-and-permissions-skeleton/00-CONTEXT.md` D-09 patched Automation probe (`id of application "WhatsApp"`, -1708 = granted) — Rust uses verbatim
- `.planning/phases/00-setup-and-permissions-skeleton/00-RESEARCH.md` — bidi-invisibles list; AppleScript error code table
- `.planning/phases/02-send-ui-automation-guardrails/02-RESEARCH.md` §"AX-API" + §"PyObjC patterns" — translate to objc2

### Python source to MIRROR (do NOT modify; Rust ports the design):
- `src/whatsapp_desktop_mcp/cli.py` — argparse → Rust clap
- `src/whatsapp_desktop_mcp/server.py` — FastMCP → rmcp Server
- `src/whatsapp_desktop_mcp/tools/doctor.py` — `@mcp.tool` → `#[tool]`
- `src/whatsapp_desktop_mcp/permissions/{osascript,fda,automation,accessibility}.py` — D-09 patched probe; locale-blind regex; bidi strip
- `src/whatsapp_desktop_mcp/models/doctor.py` — Pydantic → serde Serialize/Deserialize
- `src/whatsapp_desktop_mcp/paths.py` — path resolvers + system_settings_url
- `src/whatsapp_desktop_mcp/exceptions.py` — frozen exception hierarchy → Rust thiserror enums

### External crates (verify versions at execution time)
- `rmcp` (modelcontextprotocol/rust-sdk) — MCP server SDK
- `objc2` family (objc2, objc2-foundation, objc2-application-services) — AX-API
- `rusqlite` with `bundled` feature — SQLite (deferred read use to Phase 4.x but added v0)
- `tokio` — async runtime
- `serde` + `serde_json` — JSON serialization
- `tracing` + `tracing-subscriber` — stderr logging (stdout-purity)
- `regex` — locale-blind error parsing
- `plist` — WhatsApp.app Info.plist version probe
- `clap` — CLI argument parsing (cli.py equivalent)
- `thiserror` — exception enums
- `anyhow` — error glue (top-level main)

### Project guide
- `CLAUDE.md` — REL-05 D-24 evolution, stdout=JSON-RPC, no HTTP, no SQLite write — apply same rules to Rust port

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (Python — port designs, do NOT import)
- D-09 patched Automation probe (`whatsapp_desktop_mcp/permissions/automation.py`) — Rust ports verbatim
- locale-blind regex `\((-?\d+)\)\s*\Z` (`whatsapp_desktop_mcp/permissions/osascript.py`) — Rust uses same pattern via `regex` crate
- Bidi-invisibles strip (U+200E/U+2068/U+2069) — same data, different language
- system_settings_url helpers (`whatsapp_desktop_mcp/paths.py`) — same URLs, ported to Rust constants
- `DoctorReport` Pydantic model shape (`whatsapp_desktop_mcp/models/doctor.py`) — port to serde

### Established Patterns (apply to Rust)
- stdio-only transport; never bind HTTP listener
- stdout = JSON-RPC; logging to stderr
- Short-lived per-call DB connections (when reader lands in Phase 4.x)
- Per-tool timeouts (when more tools land in Phase 4.x)
- REL-05 D-24 narrow edge (sender→reader.connection only) — enforced via Cargo dep graph

### Integration Points
- WhatsApp Desktop on macOS — same target environment
- macOS TCC (Full Disk Access, Accessibility, Automation) — same 3 buckets
- WhatsApp.app `Info.plist` at `/Applications/WhatsApp.app/Contents/Info.plist` — same version source

</code_context>

<specifics>
## Specific Ideas

- **v0 acceptance demo:** maintainer runs `cargo build --release --locked` + adds `{"command": "/Users/.../rs/target/release/whatsapp-desktop-mcp-rs"}` to a SEPARATE Claude Desktop MCP server entry (alongside the Python `whatsapp` entry — both registered under different names, e.g. `whatsapp` Python + `whatsapp-rs` Rust), restarts Claude Desktop, asks Claude to call `whatsapp-rs:doctor`, and gets the same 3-permission JSON shape as `whatsapp:doctor`.
- **First parity assertion that fires:** if user's Mac has WhatsApp installed + 3 TCC perms granted, both `python doctor()` and `rust doctor()` should return all 3 buckets `state=granted`. If they disagree, the Rust probe logic has a bug.
- **Cargo workspace size estimate:** ~15 source files Rust v0 (server entry + 3 probes + doctor tool + models + paths + 5-6 lib crate stubs). Cargo.lock will be ~500-1000 lines (rmcp + objc2 + tokio + serde + ... transitive closure).
- **Build time first-pass estimate:** ~3-5 min on macOS-14 cold cache (mostly compiling tokio, serde, objc2 family). Subsequent builds cached < 30s.

</specifics>

<deferred>
## Deferred Ideas

- **Read tool parity** (8 read tools: list_chats, read_chat, extract_recent, search_messages, search_contacts, get_chat_metadata, get_message_context, doctor expansion) — Phase 4.x or Phase 5
- **Send tool parity** (send_message + sender package + cross-chat-quote + rate limiter + audit log) — Phase 4.x or Phase 5
- **FTS5 sidecar in Rust** — Phase 4.x
- **Brew formula bottle for Rust binary** — Phase 4.x
- **Rust release.yml signed-binary publish** — Phase 4.x
- **Intel cross-compile** — Phase 4.x (Apple Silicon only for v0)
- **Performance benchmark vs Python** (cold-start time, memory footprint) — Phase 4.x
- **Promotion of Rust → primary** (deprecate Python implementation) — far future, only after FULL parity verified across all v1.0 tools + cross-machine smoke pass + 6-month stability window

</deferred>

---

*Phase: 4-Rust port (parallel binary, additive)*
*Context gathered: 2026-05-14*

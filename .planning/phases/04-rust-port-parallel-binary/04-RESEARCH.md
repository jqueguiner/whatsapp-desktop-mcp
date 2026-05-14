# Phase 4: Rust port (parallel binary, additive) — Research

**Researched:** 2026-05-14
**Domain:** Rust MCP server (rmcp 1.x), macOS TCC permission probing via osascript subprocess + objc2 family, Cargo workspace ergonomics, cross-binary parity testing
**Confidence:** HIGH (rmcp + objc2 + plist + clap versions verified live against crates.io 2026-05-14; rmcp-macros source for `#[tool]` attribute syntax inspected from the 1.7.0 published crate)

## Summary

Phase 4 v0 ports ONLY the `doctor` tool to Rust as a parallel binary `whatsapp-desktop-mcp-rs` shipped under a top-level `rs/` Cargo workspace. The 30 locked decisions in CONTEXT.md set the architecture (workspace shape, MSRV, REL-05-equivalent rule, cross-binary parity test, no PyPI publish for Rust v0). Research scope is the tactical implementation specifics that the planner needs to write task actions: exact crate versions, exact dependency stanzas, the `rmcp` 1.7.0 `#[tool]` macro syntax, the `objc2-application-services` 0.3.2 AX-API surface (deferred to Phase 4.x but added to Cargo.toml v0), and a pragmatic 3-plan split that mirrors Phase 0's 5-plan structure.

The single highest-risk finding is that **CONTEXT.md D-04 locks MSRV at `1.75`**, but several modern dependencies have moved past that floor. The verified live data:

- `rmcp` 1.7.0 — no published MSRV (works on 1.75 in practice; transitively pulls `tokio` 1.52 which is MSRV 1.71)
- `objc2` 0.6.4 — MSRV 1.71 ✓
- `objc2-foundation` 0.3.2 — MSRV 1.71 ✓
- `objc2-application-services` 0.3.2 — MSRV 1.71 ✓
- `tokio` 1.52.3 — MSRV 1.71 ✓
- `rusqlite` 0.39 — MSRV unspecified; latest known to work on 1.75
- `plist` 1.7.4 — MSRV 1.68 ✓ (NOT 1.9.0 which is MSRV 1.88 — too new for our 1.75 floor)
- `clap` 4.5.61 — MSRV 1.74 ✓ (NOT 4.6.x which is MSRV 1.85 — too new)
- `tracing`, `tracing-subscriber`, `serde`, `serde_json`, `regex`, `thiserror`, `anyhow` — all comfortably below 1.75

CONTEXT.md D-09 also names stale objc2 family versions (`0.5` / `0.2`); the verified current major lines are `0.6` / `0.3`. The planner MUST use the verified versions below, not the CONTEXT.md examples.

The second high-impact finding: rmcp's `#[tool]` macro DOES support arbitrary `meta = <expr>` annotations natively, so the Python `@mcp.tool(meta={"anthropic/maxResultSizeChars": 60000})` annotation translates verbatim to Rust as `#[tool(meta = serde_json::json!({"anthropic/maxResultSizeChars": 60000}))]`. No programmatic `ToolBuilder::meta()` fallback needed.

**Primary recommendation:** Use rmcp 1.7.0 with default features (which already enable `macros` + `server`) plus `transport-io`. Use `#[tool_router(server_handler)]` on the impl block and `#[tool(name=..., description=..., annotations(read_only_hint = true), meta = serde_json::json!({...}))]` on the doctor function. Pin `clap = "4.5"` and `plist = "1.7"` to honor MSRV 1.75; OR bump MSRV to 1.85 (Claude's discretion — see Open Questions). Split Phase 4 into 3 plans (skeleton / doctor + probes / CI + parity).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| MCP stdio JSON-RPC handshake | Rust binary (`whatsapp-desktop-mcp-rs`) | — | Single MCP server process; equivalent to Python's `server.py` + FastMCP `mcp.run()`. |
| Tool routing & dispatch | `rs/crates/wamcp-tools/` lib crate | rmcp `#[tool_router]` macro | Same separation Python uses (`tools/doctor.py`); macro generates the dispatch wiring. |
| 3 permission probes | `rs/crates/wamcp-permissions/` lib crate | OS subprocess (`/usr/bin/osascript`) + filesystem (`std::fs::metadata`) | Probes are pure functions of OS state; isolated for unit-testability and reuse by Phase 4.x sender (P5 mitigation). |
| Path resolution | `rs/crates/wamcp-paths/` lib crate | — | Pure path arithmetic (mirrors Python `paths.py`); zero I/O. |
| Permission report serde | `rs/crates/wamcp-models/` lib crate | serde + serde_json | Pydantic-equivalent typed boundary; serializable to JSON-RPC payloads. |
| WhatsApp.app version probe | `rs/crates/wamcp-tools/` (in doctor body) | `plist` crate | Reading `/Applications/WhatsApp.app/Contents/Info.plist` is a public-bundle resource; no FDA gate; trivially re-uses Python's logic. |
| Reader (deferred) | `rs/crates/wamcp-reader/` (empty stub) | `rusqlite` (added to deps for Phase 4.x continuity) | REL-05 D-24 isolation enforced from day one via empty crate + Cargo dep-graph test. |
| Sender (deferred) | `rs/crates/wamcp-sender/` (empty stub) | `objc2-application-services` for AX-API + `osascript` for AppleScript | Same REL-05 reservation as reader. |
| Process logging | Rust binary `main.rs` | `tracing` + `tracing-subscriber` to stderr | Equivalent to Python's `logging.basicConfig(stream=sys.stderr, ...)`; lint-blocked from stdout via `clippy::print_stdout = "deny"`. |
| Cross-binary parity | Python test (`tests/integration/test_rust_python_parity.py`) | `subprocess.Popen` driving both binaries | Lives in Python suite per CONTEXT D-23; the Rust toolchain stays optional for Python developers. |

## User Constraints (from CONTEXT.md)

> 30 decisions are locked. The planner MUST honor them verbatim. This research investigates tactical implementation details under those constraints — it does NOT relitigate the locked choices.

### Locked Decisions (verbatim summary — full text in `04-CONTEXT.md`)

| ID | Lock |
|----|------|
| D-01 | Top-level `rs/` directory contains a Cargo workspace; building Rust does NOT touch Python; running Python tests does NOT require cargo. |
| D-02 | Workspace members: `whatsapp-desktop-mcp-rs` (binary), `wamcp-{models,permissions,paths,tools,reader,sender}` (libs). Reader+sender empty in v0. |
| D-03 | REL-05 D-24 evolution: `wamcp-reader` MUST NOT depend on `wamcp-sender`. Enforced structurally by empty stubs in v0 and a `rs/tests/isolation.rs` parsing the Cargo dep graph. |
| D-04 | `[workspace.package]`: `version = "0.0.0"`, `edition = "2021"`, `rust-version = "1.75"`, `license = "MIT"`. |
| D-05 | Use `rmcp` (modelcontextprotocol/rust-sdk). Pin to latest stable. Need `transport-stdio`-equivalent + `macros` features. |
| D-06 | Tool registration via `#[tool]` derive macro mirroring Python's `@mcp.tool` annotations + meta. |
| D-07 | Server entry in `rs/whatsapp-desktop-mcp-rs/src/main.rs`. Tracing to stderr. |
| D-08 | Stdout-purity: all logs to stderr; `clippy::print_stdout = "deny"`; CI parity test mirrors Python's `tests/unit/test_stdout_purity.py`. |
| D-09 | objc2 family for PyObjC equivalent. AX-API in `objc2-application-services`. Reject older `cocoa` crate. |
| D-10 | AX-API integration NOT shipped in v0; reserved for Phase 4.x. v0 doctor uses osascript only. Crate dep added to workspace v0 for continuity. |
| D-11 | AppleScript via `std::process::Command::new("osascript")`. Locale-blind regex `\((-?\d+)\)\s*\Z`. Error code mapping verbatim from D-09 patched probe. Bidi-strip helper. |
| D-12 | 3 probes: `fda.rs` (`std::fs::metadata`), `automation.rs` (osascript `id of application "WhatsApp"`), `accessibility.rs` (osascript `tell application "System Events" to count processes`). All wrapped in `tokio::task::spawn_blocking`. |
| D-13 | `DoctorReport` mirrors Python: 3 PermissionCheck fields + db_path + schema_fingerprint + whatsapp_app_version + last_message_ts + coverage_summary. v0 populates 3 probes + db_path + whatsapp_app_version; the rest = `None`. |
| D-14 | `PermissionCheck`: state, bucket, binary_path, db_path, system_settings_url, remediation. |
| D-15 | `PermissionState`: `Granted | Denied | WhatsappNotInstalled | Unknown`, serialized snake_case. |
| D-16 | `binary_path = std::env::current_exe()?.to_string_lossy().into_owned()`. |
| D-17 | `rusqlite = { version = "0.31", features = ["bundled"] }` added v0; not USED in v0 (deferred). |
| D-18 | RO-WAL connection pattern locked for Phase 4.x consistency. |
| D-19 | Distribution: GitHub release artifact via release.yml `rust-build` job; macos-14; tarball attached via `softprops/action-gh-release@v2`. |
| D-20 | NO PyPI publish for Rust binary. |
| D-21 | NO brew formula bottle for Rust v0. `cargo install --git ...` documented. |
| D-22 | Rust binary version `0.0.0` for first ship; independent of Python's 0.0.1rc1 / 0.1.0 sequence. |
| D-23 | `tests/integration/test_rust_python_parity.py` lives in Python suite. Gated by `RUN_LIVE_RUST=1`. Asserts: top-level keys parity; per-bucket state parity; `binary_path` differs; `db_path` + `system_settings_url` match. |
| D-24 | Sandbox carry from Phase 2/3 D-24 fixture; only rate-limit + audit + FTS sandbox parts apply (Rust v0 has none). |
| D-25 | CI: `rust-lint-test` job in PARALLEL to existing `lint-type-test` (Python). `actions-rust-lang/setup-rust-toolchain@v1`. macOS-14. Steps: fmt --check, clippy -- -D warnings, test --workspace. |
| D-26 | `Cargo.lock` committed at `rs/Cargo.lock`. `.gitignore` adds `rs/target/`. |
| D-27 | `rs/rustfmt.toml`: edition=2021, max_width=100, imports_granularity=Module, group_imports=StdExternalCrate. |
| D-28 | `rs/clippy.toml`: msrv="1.75"; warn-level lints scoped (correctness=deny, suspicious=deny, style=warn, print_stdout=deny). |
| D-29 | README adds 4th install row: "Rust port (experimental)". |
| D-30 | `rs/README.md` Rust-specific README inside the workspace. |

### Claude's Discretion (from CONTEXT.md)

- Exact `rmcp` version pin (latest stable at execution time)
- Exact `objc2` / `objc2-foundation` / `objc2-application-services` version pins
- Whether to ship `rs/.cargo/config.toml` with build settings (e.g. `target-cpu=apple-m1`)
- Whether to use `cargo-deny` for dep auditing
- Whether to ship a `Justfile` or `make` wrapper (probably skip — small repo)
- Exact CI matrix shape (sequential vs parallel jobs)

This research provides RECOMMENDATIONS for each — see `## Standard Stack` and `## Architecture Patterns`.

### Deferred Ideas (OUT OF SCOPE — do NOT plan)

- Read tool parity (8 read tools) — Phase 4.x or Phase 5
- Send tool parity (send_message + sender + cross-chat-quote + rate limiter + audit log) — Phase 4.x or Phase 5
- FTS5 sidecar in Rust — Phase 4.x
- Brew formula bottle for Rust binary — Phase 4.x
- Rust release.yml signed-binary publish — Phase 4.x
- Intel cross-compile (Apple Silicon only for v0)
- Performance benchmark vs Python — Phase 4.x
- Promotion of Rust → primary — far future, only after FULL parity

## Phase Requirements

**No new v1 REQ-IDs.** Phase 4 v0 is exploratory per ROADMAP §"Phase 4". Implicit non-functional requirements (from CONTEXT.md):

| Implicit ID | Description | Research Support |
|-------------|-------------|------------------|
| RUST-NOREGRESS | Rust port MUST NOT regress any Python-side functionality | Cargo workspace under `rs/`; zero shared source files; CI Python `lint-type-test` job unchanged |
| RUST-NOOVERRIDE | Rust port MUST NOT replace any Python source file | All Python files in `src/whatsapp_desktop_mcp/` byte-stable; Rust under `rs/` exclusively |
| RUST-NOPATHCHANGE | Rust port MUST NOT change install paths for existing Python binary | release.yml `rust-build` job is additive; PyPI publish + pkg-build + tap-update jobs untouched |
| RUST-DOCTOR-PARITY | Rust `doctor` must return same shape as Python `doctor` | DoctorReport serde model mirrors Python Pydantic verbatim (D-13/14/15); cross-binary parity test asserts shape (D-23) |
| RUST-STDOUT-PURE | Rust binary stdout must be JSON-RPC only | `tracing` to stderr; `clippy::print_stdout = "deny"` (D-08); CI test mirrors Python's `test_stdout_purity.py` |

## Standard Stack

### Core (verified live against crates.io 2026-05-14)

| Crate | Pinned Version | Features | Purpose | MSRV |
|-------|---------------|----------|---------|------|
| `rmcp` | `1.7.0` | `["server", "macros", "transport-io"]` (server+macros are default; `transport-io` adds the `transport::stdio()` function) | Official MCP Rust SDK from `modelcontextprotocol/rust-sdk` | unspecified (works on 1.75) |
| `tokio` | `1` (resolves to 1.52.x) | `["macros", "rt-multi-thread", "io-std", "process"]` | Async runtime; `rt-multi-thread` for `#[tokio::main]`; `io-std` for `tokio::io::{stdin, stdout}`; `process` for `tokio::process::Command` | 1.71 ✓ |
| `serde` | `1` | `["derive"]` | Pydantic-equivalent typed surfaces | low |
| `serde_json` | `1` | — | JSON-RPC payloads + meta annotation expressions | low |
| `schemars` | `1` (transitively via `rmcp[server]`) | — | JSON Schema generation for tool input schemas | low |
| `anyhow` | `1` | — | Top-level `main() -> anyhow::Result<()>` glue (CONTEXT D-15: never `.unwrap()` in main paths) | low |
| `thiserror` | `2` | — | Typed exception enums (Python `exceptions.py` equivalent) | low |
| `tracing` | `0.1` | — | Structured logging to stderr | low |
| `tracing-subscriber` | `0.3` | `["fmt"]` | Subscriber writing to `io::stderr` (D-08 stdout-purity invariant) | low |
| `regex` | `1` | — | Locale-blind error code regex `\((-?\d+)\)\s*\Z` (D-11) | low |
| `clap` | `4.5` (NOT 4.6.x — MSRV 1.85 conflicts with D-04) | `["derive"]` | argparse equivalent; `--version` / `--help` for CLI parity | 1.74 ✓ |
| `plist` | `1.7` (NOT 1.9.x — MSRV 1.88 conflicts with D-04) | — | Read `/Applications/WhatsApp.app/Contents/Info.plist` for `CFBundleShortVersionString` | 1.68 ✓ |

### macOS-specific (verified)

| Crate | Pinned Version | Features | Purpose | MSRV |
|-------|---------------|----------|---------|------|
| `objc2` | `0.6` (current 0.6.4) — **D-09 names "0.5", which is stale** | — | Objective-C runtime + Send+Sync `extern_class!` macros | 1.71 ✓ |
| `objc2-foundation` | `0.3` (current 0.3.2) — **D-09 names "0.2", stale** | `["std"]` | NSString/NSArray bindings | 1.71 ✓ |
| `objc2-application-services` | `0.3` (current 0.3.2) — **D-09 names "0.2", stale** | `["std", "AXUIElement", "AXAttributeConstants", "AXError"]` (selective AX feature gating) | AX-API surface for Phase 4.x; ADDED to workspace deps v0 (CONTEXT D-10) but only USED in 4.x | 1.71 ✓ |

### Deferred (added to workspace deps v0 per CONTEXT, USED in Phase 4.x)

| Crate | Pinned Version | Features | Purpose |
|-------|---------------|----------|---------|
| `rusqlite` | `0.31` (CONTEXT D-17) — note current is 0.39; D-17 explicitly locks 0.31 for Phase 4.x continuity | `["bundled"]` | RO-WAL SQLite reader for Phase 4.x parity work |

### Alternatives Considered (and rejected)

| Instead of | Could Use | Tradeoff / Why Rejected |
|------------|-----------|-------------------------|
| `rmcp` | Hand-rolled JSON-RPC stdio loop | Rejected: rmcp 1.x is official Anthropic SDK, 9.7M downloads, actively released (1.7.0 published yesterday). No reason to hand-roll. |
| `rmcp` | Community `mcp-server` / `mcp-rust-sdk` crates | Rejected: rmcp is the official one — `[VERIFIED: docs.rs/rmcp + GitHub modelcontextprotocol/rust-sdk]`. Community crates lag spec. |
| `objc2` family | Older `cocoa` + `core_foundation` crates | Rejected by CONTEXT D-09: not Send+Sync, not actively maintained, pre-2024 API. |
| `plist 1.9` | `plist 1.7.4` | 1.9 requires MSRV 1.88; D-04 locks 1.75. 1.7.4 is the latest 1.7.x line and works. |
| `clap 4.6` | `clap 4.5` | Same reason: 4.6 requires MSRV 1.85; 4.5.61 (latest 4.5.x) requires 1.74 and works. |
| Sync `std::process::Command` | `tokio::process::Command` | tokio variant integrates with the rmcp async runtime; the Python equivalent uses `asyncio.create_subprocess_exec` so this is verbatim parity. |

### Concrete `[workspace.dependencies]` block (recommendation)

```toml
[workspace.dependencies]
# MCP SDK
rmcp = { version = "1.7", features = ["server", "macros", "transport-io"] }

# Async runtime
tokio = { version = "1", features = ["macros", "rt-multi-thread", "io-std", "process"] }

# Serialization
serde = { version = "1", features = ["derive"] }
serde_json = "1"

# Error handling
anyhow = "1"
thiserror = "2"

# Logging (stderr only — D-08 stdout purity)
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["fmt"] }

# Regex (locale-blind error parsing — D-11)
regex = "1"

# CLI (--version / --help)
clap = { version = "4.5", features = ["derive"] }

# WhatsApp.app Info.plist version probe
plist = "1.7"

# macOS Objective-C runtime + AX-API (AX usage deferred to Phase 4.x — D-10)
objc2 = "0.6"
objc2-foundation = { version = "0.3", features = ["std"] }
objc2-application-services = { version = "0.3", features = ["std"] }

# SQLite (deferred read use to Phase 4.x — D-17)
rusqlite = { version = "0.31", features = ["bundled"] }
```

### Version verification commands (run before committing Cargo.toml)

```bash
# Verify each crate at execution time (versions may have moved further)
cargo search rmcp --limit 1
cargo search objc2 --limit 1
cargo search objc2-application-services --limit 1
cargo search plist --limit 1
cargo search clap --limit 1
```

## Architecture Patterns

### System Architecture Diagram (v0 doctor-only)

```
                Claude Desktop / Claude Code (MCP client)
                              │
                              │ JSON-RPC over stdio
                              │ (stdin / stdout)
                              ▼
              ┌───────────────────────────────────┐
              │  whatsapp-desktop-mcp-rs (binary) │
              │   rs/whatsapp-desktop-mcp-rs/main │
              │                                   │
              │  ┌──────────────────────────────┐ │
              │  │ rmcp Server                  │ │
              │  │   tracing → stderr           │ │
              │  │   transport::stdio()         │ │
              │  └──────────────┬───────────────┘ │
              │                 │ dispatch         │
              │                 ▼                  │
              │  ┌──────────────────────────────┐ │
              │  │ wamcp-tools::doctor          │ │
              │  │   #[tool(name="doctor", …)]  │ │
              │  └──────┬───────────────────────┘ │
              │         │                          │
              │         ├───────────────┬─────────┐│
              │         ▼               ▼         ▼│
              │  ┌────────────┐  ┌────────────┐  ┌────────────┐
              │  │ wamcp-     │  │ wamcp-     │  │ wamcp-     │
              │  │ permissions│  │ permissions│  │ permissions│
              │  │  ::fda     │  │  ::auto    │  │  ::access  │
              │  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
              │        │               │               │       │
              │        ▼               ▼               ▼       │
              │ spawn_blocking   tokio::process   tokio::process│
              │ std::fs::metadata  Command         Command      │
              │ (db_path)         (osascript)    (osascript)   │
              └─────────────────────────────────────────────────┘
                       │               │               │
                       ▼               ▼               ▼
              filesystem stat   /usr/bin/osascript  /usr/bin/osascript
              (~/Library/...    "id of application  "tell System Events
              ChatStorage.sqlite) WhatsApp"          to count processes"
```

Data flow: Claude Desktop sends `tools/call doctor` → rmcp dispatcher → `doctor` async fn → 3 probes run sequentially (Phase 0 ordering preserved per CONTEXT D-13) → each probe returns `PermissionCheck` → assembled into `DoctorReport` → serde-serialized to JSON-RPC response → rmcp writes frame to stdout. Throughout, `tracing` events go to stderr (NEVER stdout — D-08 invariant).

WhatsApp.app Info.plist read happens in parallel (no FDA gate — public bundle resource per Phase 1's existing logic).

### Recommended Project Structure

```
rs/
├── Cargo.toml                      # workspace root: [workspace] members + [workspace.package] + [workspace.dependencies] + [workspace.lints]
├── Cargo.lock                      # COMMITTED (D-26)
├── rustfmt.toml                    # D-27: edition=2021, max_width=100
├── clippy.toml                     # D-28: msrv="1.75", lint scoping
├── README.md                       # D-30: Rust-specific build/test/parity instructions
├── .cargo/
│   └── config.toml                 # OPTIONAL (Claude discretion): [target.aarch64-apple-darwin] rustflags = ["-C", "target-cpu=apple-m1"]
├── deny.toml                       # OPTIONAL (Claude discretion): cargo-deny advisory + license + bans config
├── tests/
│   └── isolation.rs                # D-03: parses Cargo.lock graph; asserts wamcp-reader → wamcp-sender NOT a path
├── whatsapp-desktop-mcp-rs/        # binary crate (the MCP server entry point)
│   ├── Cargo.toml                  # [package] name, [[bin]] name = "whatsapp-desktop-mcp-rs"
│   └── src/
│       └── main.rs                 # ~50 lines: tracing init → DoctorTool::new → server.serve(stdio()).await
└── crates/
    ├── wamcp-models/               # serde structs (DoctorReport, PermissionCheck, PermissionState, ...)
    │   ├── Cargo.toml
    │   └── src/
    │       └── lib.rs
    ├── wamcp-permissions/          # 3 probes (fda, automation, accessibility) + osascript helper + bidi strip
    │   ├── Cargo.toml
    │   └── src/
    │       ├── lib.rs              # pub mod fda; pub mod automation; pub mod accessibility; pub mod osascript;
    │       ├── fda.rs              # std::fs::metadata wrapped in spawn_blocking
    │       ├── automation.rs       # D-09 patched probe via osascript
    │       ├── accessibility.rs    # System Events count via osascript
    │       ├── osascript.rs        # OsascriptResult, run_osascript, _strip_bidi, error regex (OnceLock)
    │       └── url.rs              # x-apple.systempreferences URL constants
    ├── wamcp-paths/                # path resolvers (mirrors Python paths.py)
    │   ├── Cargo.toml
    │   └── src/
    │       └── lib.rs              # resolve_chatstorage_path, resolve_lid_path, ... (v0 only needs chatstorage)
    ├── wamcp-tools/                # MCP tool registrations (v0 = doctor only)
    │   ├── Cargo.toml
    │   └── src/
    │       ├── lib.rs              # pub use doctor::DoctorTool;
    │       └── doctor.rs           # #[tool_router(server_handler)] impl DoctorTool { #[tool(...)] async fn doctor(...) }
    ├── wamcp-reader/               # PHASE 4.X RESERVATION — empty in v0
    │   ├── Cargo.toml              # MUST NOT have wamcp-sender in [dependencies] (D-03)
    │   └── src/
    │       └── lib.rs              # // Phase 4.x: reserved (intentionally empty)
    └── wamcp-sender/               # PHASE 4.X RESERVATION — empty in v0
        ├── Cargo.toml              # MAY ONLY depend on wamcp-reader-connection (future); NOT wamcp-reader (D-03)
        └── src/
            └── lib.rs              # // Phase 4.x: reserved (intentionally empty)
```

### Pattern 1: Workspace root `Cargo.toml` (complete file recommendation)

```toml
[workspace]
resolver = "2"
members = [
    "whatsapp-desktop-mcp-rs",
    "crates/wamcp-models",
    "crates/wamcp-permissions",
    "crates/wamcp-paths",
    "crates/wamcp-tools",
    "crates/wamcp-reader",
    "crates/wamcp-sender",
]

[workspace.package]
version = "0.0.0"                                                 # D-04
edition = "2021"                                                  # D-04
rust-version = "1.75"                                             # D-04 (NOTE: see Open Questions #1 — clap/plist constraints)
license = "MIT"                                                   # D-04
repository = "https://github.com/jqueguiner/whatsapp-desktop-mcp" # D-04
homepage = "https://github.com/jqueguiner/whatsapp-desktop-mcp"   # D-04

[workspace.dependencies]
# (full block from "Standard Stack" above)

[workspace.lints.rust]
unsafe_op_in_unsafe_fn = "deny"  # objc2 unsafe blocks must be explicit
unused_must_use = "deny"

[workspace.lints.clippy]
print_stdout = "deny"            # D-08: stdout is JSON-RPC only
print_stderr = "warn"            # tracing should be used instead, but stderr is allowed
correctness = { level = "deny", priority = -1 }
suspicious = { level = "deny", priority = -1 }
style = { level = "warn", priority = -1 }
# pedantic = { level = "warn", priority = -1 }   # NOT enabled per D-28 (too noisy)
unwrap_used = "warn"             # D-15-anti-pattern: use ? + anyhow::Result
expect_used = "warn"

[profile.release]
strip = true                     # smaller binaries; complements release.yml `strip` step
lto = "thin"                     # link-time optimization for cold-start size+speed
codegen-units = 1                # max optimization at expense of build time
```
**Source:** rmcp 1.7.0 verified from `gh api repos/modelcontextprotocol/rust-sdk/contents/crates/rmcp/Cargo.toml`. Workspace lints syntax is stable since Rust 1.74.

### Pattern 2: Binary crate `Cargo.toml`

`rs/whatsapp-desktop-mcp-rs/Cargo.toml`:

```toml
[package]
name = "whatsapp-desktop-mcp-rs"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
repository.workspace = true
homepage.workspace = true
description = "Rust port of the macOS WhatsApp Desktop MCP server (experimental)"

[[bin]]
name = "whatsapp-desktop-mcp-rs"
path = "src/main.rs"

[dependencies]
rmcp = { workspace = true }
tokio = { workspace = true }
anyhow = { workspace = true }
tracing = { workspace = true }
tracing-subscriber = { workspace = true }
clap = { workspace = true }
wamcp-tools = { path = "../crates/wamcp-tools" }
```

### Pattern 3: `main.rs` skeleton (~50 lines)

```rust
//! Stdio MCP server entry point — Rust port (Phase 4 v0).
//!
//! Mirrors Python's `whatsapp_desktop_mcp.server` + `whatsapp_desktop_mcp.cli`:
//!   - tracing-subscriber writes to stderr BEFORE any tool registration
//!   - rmcp Server hosts ONE tool (doctor) via the wamcp-tools crate
//!   - serve(stdio()) runs the JSON-RPC loop on stdin/stdout
//!
//! Hard rules (CLAUDE.md + CONTEXT.md D-08):
//!   - NEVER println! — use tracing macros (clippy::print_stdout = "deny" enforces)
//!   - NEVER bind HTTP listener — stdio only
//!   - main returns anyhow::Result<()> so the ? operator is used at every fallible call

use anyhow::Result;
use clap::Parser;
use rmcp::{transport::stdio, ServiceExt};
use tracing_subscriber::EnvFilter;
use wamcp_tools::DoctorTool;

#[derive(Parser, Debug)]
#[command(name = "whatsapp-desktop-mcp-rs", version)]
struct Cli {
    // v0 has no flags; --version / --help are auto-provided by clap derive.
    // Phase 4.x will add --read-only / --fts5-mode mirroring Python.
}

#[tokio::main]
async fn main() -> Result<()> {
    let _cli = Cli::parse();

    // CRITICAL: subscriber writes to stderr — stdout is the JSON-RPC channel (D-08).
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .with_writer(std::io::stderr)
        .with_ansi(false)            // no ANSI escapes in log output
        .init();

    tracing::info!(
        version = env!("CARGO_PKG_VERSION"),
        "whatsapp-desktop-mcp-rs starting"
    );

    let service = DoctorTool::new()
        .serve(stdio())
        .await?;

    let quit_reason = service.waiting().await?;
    tracing::info!(?quit_reason, "MCP server shut down");
    Ok(())
}
```

**Source provenance:**
- `serve(stdio()).await` pattern: `[VERIFIED: gh api modelcontextprotocol/rust-sdk/README.md @ rmcp-1.7.0]` (calculator example, lines 130–155 of README.md)
- `transport::stdio` function: `[VERIFIED: docs.rs/rmcp/1.7.0/rmcp/transport/index.html]` — gated by `transport-io` feature
- `tracing_subscriber::fmt().with_writer(std::io::stderr)`: `[CITED: docs.rs/tracing-subscriber 0.3]` standard idiom

### Pattern 4: `wamcp-tools::doctor` (the actual tool registration)

`rs/crates/wamcp-tools/src/doctor.rs`:

```rust
//! The doctor MCP tool — preflight permission report (Phase 4 v0).
//!
//! Mirrors Python `whatsapp_desktop_mcp.tools.doctor` byte-for-byte at the
//! JSON wire shape (CONTEXT D-13 + cross-binary parity test D-23).

use rmcp::{tool, tool_router, ServerHandler};
use serde_json::json;
use wamcp_models::DoctorReport;
use wamcp_paths::resolve_chatstorage_path;
use wamcp_permissions::{accessibility, automation, fda};

#[derive(Clone)]
pub struct DoctorTool;

impl DoctorTool {
    pub fn new() -> Self {
        Self
    }
}

impl Default for DoctorTool {
    fn default() -> Self {
        Self::new()
    }
}

#[tool_router(server_handler)]
impl DoctorTool {
    #[tool(
        name = "doctor",
        description = "Reports whether the three macOS permissions the WhatsApp MCP needs \
                       (Full Disk Access, Apple Events / Automation for WhatsApp, Accessibility) \
                       are granted to the current process; additionally reports the resolved \
                       ChatStorage.sqlite path and the installed WhatsApp.app version.",
        annotations(
            title = "Doctor — preflight permission check",
            read_only_hint = true,
            destructive_hint = false,
            idempotent_hint = true,
            open_world_hint = false,
        ),
        meta = json!({"anthropic/maxResultSizeChars": 60000})
    )]
    async fn doctor(&self) -> Result<DoctorReport, String> {
        // Phase 0 probes (sequential — preserves Python ordering per CONTEXT D-13)
        let fda_status = fda::check().await.map_err(|e| e.to_string())?;
        let automation_status = automation::check_whatsapp().await.map_err(|e| e.to_string())?;
        let accessibility_status = accessibility::check().await.map_err(|e| e.to_string())?;

        let db_path = resolve_chatstorage_path();
        let whatsapp_app_version = probe_whatsapp_version().await;

        // v0 fields not yet populated (deferred to Phase 4.x): schema_fingerprint,
        // last_message_ts, coverage_summary — all None.
        Ok(DoctorReport {
            full_disk_access: fda_status,
            automation_whatsapp: automation_status,
            accessibility: accessibility_status,
            db_path: Some(db_path),
            schema_fingerprint: None,
            whatsapp_app_version,
            last_message_ts: None,
            coverage_summary: None,
        })
    }
}

const WHATSAPP_INFO_PLIST_PATH: &str = "/Applications/WhatsApp.app/Contents/Info.plist";

async fn probe_whatsapp_version() -> Option<String> {
    tokio::task::spawn_blocking(|| {
        let value: plist::Value = plist::from_file(WHATSAPP_INFO_PLIST_PATH).ok()?;
        value
            .as_dictionary()?
            .get("CFBundleShortVersionString")?
            .as_string()
            .map(|s| s.to_owned())
    })
    .await
    .ok()
    .flatten()
}
```

**Source provenance:**
- `#[tool(name=..., description=..., annotations(...), meta = ...)]` syntax: `[VERIFIED: rmcp-macros 1.7.0 src/tool.rs]` lines 83–171 (downloaded crate, inspected). Field names: `title`, `read_only_hint`, `destructive_hint`, `idempotent_hint`, `open_world_hint` — `[VERIFIED: docs.rs/rmcp/1.7.0/rmcp/model/struct.ToolAnnotations.html]`.
- `#[tool_router(server_handler)]` for tools-only servers: `[VERIFIED: gh api rust-sdk README.md]` lines 110–135.
- `meta = json!({...})` — the macro accepts an arbitrary `Expr` and forwards as `.with_meta(<expr>)`: `[VERIFIED: rmcp-macros 1.7.0 src/tool.rs:155]`.

### Pattern 5: Permission probes — verbatim Rust ports

`rs/crates/wamcp-permissions/src/osascript.rs`:

```rust
//! Async osascript runner with a hard wall-clock timeout.
//! Verbatim port of Python `whatsapp_desktop_mcp/permissions/osascript.py`.

use std::sync::OnceLock;
use std::time::Duration;
use tokio::process::Command;
use tokio::time::timeout;

/// Match the trailing parenthesised signed integer regardless of locale.
/// Same regex Python uses (CONTEXT D-11).
fn err_re() -> &'static regex::Regex {
    static RE: OnceLock<regex::Regex> = OnceLock::new();
    RE.get_or_init(|| regex::Regex::new(r"\((-?\d+)\)\s*\z").expect("err regex"))
}

/// Strip macOS bidi-invisibles (U+200E LRM, U+2068 FSI, U+2069 PDI) — same
/// codepoint set as Python's `_strip_bidi`. CONTEXT D-11.
pub fn strip_bidi(s: &str) -> String {
    s.chars()
        .filter(|c| !matches!(*c as u32, 0x200E | 0x2068 | 0x2069))
        .collect()
}

#[derive(Debug, Clone)]
pub struct OsascriptResult {
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
    pub error_code: Option<i64>,
}

pub async fn run_osascript(script: &str, timeout_secs: u64) -> OsascriptResult {
    // Use Command::new + arg to avoid shell injection — never shell-out via string.
    let fut = Command::new("/usr/bin/osascript")
        .arg("-e")
        .arg(script)
        .output();

    let output = match timeout(Duration::from_secs(timeout_secs), fut).await {
        Ok(Ok(o)) => o,
        Ok(Err(e)) => {
            // FileNotFoundError equivalent (osascript missing — non-mac runner)
            if e.kind() == std::io::ErrorKind::NotFound {
                return OsascriptResult {
                    exit_code: -1,
                    stdout: String::new(),
                    stderr: "osascript-missing".into(),
                    error_code: None,
                };
            }
            tracing::error!(?e, "osascript spawn failed");
            return OsascriptResult {
                exit_code: -1,
                stdout: String::new(),
                stderr: format!("spawn-error: {e}"),
                error_code: None,
            };
        }
        Err(_) => {
            tracing::warn!(timeout_secs, "osascript timed out");
            return OsascriptResult {
                exit_code: -1,
                stdout: String::new(),
                stderr: "timeout".into(),
                error_code: None,
            };
        }
    };

    let stdout = String::from_utf8_lossy(&output.stdout).into_owned();
    let stderr = String::from_utf8_lossy(&output.stderr).into_owned();
    let exit_code = output.status.code().unwrap_or(-1);

    let error_code = if exit_code != 0 {
        err_re()
            .captures(&strip_bidi(&stderr))
            .and_then(|c| c.get(1))
            .and_then(|m| m.as_str().parse::<i64>().ok())
    } else {
        None
    };

    OsascriptResult { exit_code, stdout, stderr, error_code }
}
```

`rs/crates/wamcp-permissions/src/automation.rs`:

```rust
//! Apple Events / Automation probe — D-09 patched probe (CONTEXT D-12 verbatim).
//! Mirrors Python `whatsapp_desktop_mcp/permissions/automation.py`.

use crate::osascript::run_osascript;
use crate::url::AUTOMATION_URL;
use wamcp_models::{PermissionCheck, PermissionState};

const PROBE: &str = r#"id of application "WhatsApp""#;

pub async fn check_whatsapp() -> Result<PermissionCheck, std::io::Error> {
    let result = run_osascript(PROBE, 3).await;
    let binary_path = std::env::current_exe()
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|_| "<unknown>".into());

    // Granted: clean exit OR app handled the event OR app installed but not running.
    if result.exit_code == 0
        || result.error_code == Some(-1708)
        || result.error_code == Some(-600)
    {
        return Ok(PermissionCheck {
            bucket: "automation".into(),
            state: PermissionState::Granted,
            binary_path,
            db_path: None,
            system_settings_url: AUTOMATION_URL.into(),
            remediation: String::new(),
        });
    }
    // Denied
    if result.error_code == Some(-1743) {
        return Ok(PermissionCheck {
            bucket: "automation".into(),
            state: PermissionState::Denied,
            binary_path: binary_path.clone(),
            db_path: None,
            system_settings_url: AUTOMATION_URL.into(),
            remediation: format!(
                "Grant Automation permission for WhatsApp to: {binary_path}\n\
                 Open System Settings -> Privacy & Security -> Automation, \
                 find the row for the binary above, and tick the WhatsApp checkbox. \
                 If the row does not exist, run `tccutil reset AppleEvents` and re-run doctor."
            ),
        });
    }
    // Not installed
    if result.error_code == Some(-1728) {
        return Ok(PermissionCheck {
            bucket: "automation".into(),
            state: PermissionState::WhatsappNotInstalled,
            binary_path,
            db_path: None,
            system_settings_url: AUTOMATION_URL.into(),
            remediation: "WhatsApp Desktop is not installed. Install it from the App Store.".into(),
        });
    }
    // Unknown — log + surface as denied with diagnostic remediation.
    tracing::warn!(
        exit_code = result.exit_code,
        error_code = ?result.error_code,
        stderr = %result.stderr,
        "automation probe unexpected"
    );
    Ok(PermissionCheck {
        bucket: "automation".into(),
        state: PermissionState::Denied,
        binary_path,
        db_path: None,
        system_settings_url: AUTOMATION_URL.into(),
        remediation: format!(
            "osascript probe returned an unexpected result \
             (exit={}, error_code={:?}). Try restarting WhatsApp and re-running doctor. \
             If the problem persists, open an issue with the doctor output.",
            result.exit_code, result.error_code
        ),
    })
}
```

`rs/crates/wamcp-permissions/src/fda.rs`:

```rust
//! Full Disk Access probe — std::fs::metadata against ChatStorage.sqlite.
//! Mirrors Python `whatsapp_desktop_mcp/permissions/fda.py`.

use crate::url::FDA_URL;
use wamcp_models::{PermissionCheck, PermissionState};
use wamcp_paths::resolve_chatstorage_path;

pub async fn check() -> Result<PermissionCheck, std::io::Error> {
    let db_path = resolve_chatstorage_path();
    let db_path_clone = db_path.clone();

    // Wrap the blocking stat in spawn_blocking — equivalent to Python's
    // asyncio.to_thread (CONTEXT D-12).
    let result = tokio::task::spawn_blocking(move || std::fs::metadata(&db_path_clone))
        .await
        .map_err(std::io::Error::other)?;

    let binary_path = std::env::current_exe()
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|_| "<unknown>".into());

    match result {
        Ok(_) => Ok(PermissionCheck {
            bucket: "fda".into(),
            state: PermissionState::Granted,
            binary_path,
            db_path: Some(db_path),
            system_settings_url: FDA_URL.into(),
            remediation: String::new(),
        }),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(PermissionCheck {
            bucket: "fda".into(),
            state: PermissionState::WhatsappNotInstalled,
            binary_path,
            db_path: Some(db_path),
            system_settings_url: FDA_URL.into(),
            remediation: "WhatsApp Desktop is not installed at the expected path. \
                          Install WhatsApp from the App Store and run `doctor` again.".into(),
        }),
        Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => Ok(PermissionCheck {
            bucket: "fda".into(),
            state: PermissionState::Denied,
            binary_path: binary_path.clone(),
            db_path: Some(db_path),
            system_settings_url: FDA_URL.into(),
            remediation: format!(
                "Grant Full Disk Access to: {binary_path}\n\
                 Open System Settings -> Privacy & Security -> Full Disk Access, \
                 click '+', and add the path above."
            ),
        }),
        Err(e) => {
            tracing::warn!(?e, "fda probe unexpected error");
            Ok(PermissionCheck {
                bucket: "fda".into(),
                state: PermissionState::Denied,
                binary_path,
                db_path: Some(db_path),
                system_settings_url: FDA_URL.into(),
                remediation: format!("Unexpected filesystem error ({e}); see logs."),
            })
        }
    }
}
```

`rs/crates/wamcp-permissions/src/accessibility.rs`:

```rust
//! Accessibility probe — System Events count via osascript.
//! Mirrors Python `whatsapp_desktop_mcp/permissions/accessibility.py`.

use crate::osascript::run_osascript;
use crate::url::ACCESSIBILITY_URL;
use wamcp_models::{PermissionCheck, PermissionState};

const PROBE: &str = r#"tell application "System Events" to count processes"#;

pub async fn check() -> Result<PermissionCheck, std::io::Error> {
    let result = run_osascript(PROBE, 3).await;
    let binary_path = std::env::current_exe()
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|_| "<unknown>".into());

    if result.exit_code == 0 {
        return Ok(PermissionCheck {
            bucket: "accessibility".into(),
            state: PermissionState::Granted,
            binary_path,
            db_path: None,
            system_settings_url: ACCESSIBILITY_URL.into(),
            remediation: String::new(),
        });
    }
    if matches!(result.error_code, Some(-1719) | Some(-25211)) {
        return Ok(PermissionCheck {
            bucket: "accessibility".into(),
            state: PermissionState::Denied,
            binary_path: binary_path.clone(),
            db_path: None,
            system_settings_url: ACCESSIBILITY_URL.into(),
            remediation: format!(
                "Grant Accessibility permission to: {binary_path}\n\
                 Open System Settings -> Privacy & Security -> Accessibility, \
                 click '+', add the binary above, and tick its checkbox."
            ),
        });
    }
    tracing::warn!(
        exit_code = result.exit_code,
        error_code = ?result.error_code,
        stderr = %result.stderr,
        "accessibility probe unexpected"
    );
    Ok(PermissionCheck {
        bucket: "accessibility".into(),
        state: PermissionState::Denied,
        binary_path,
        db_path: None,
        system_settings_url: ACCESSIBILITY_URL.into(),
        remediation: format!(
            "osascript probe returned an unexpected result (exit={}, error_code={:?}). See logs.",
            result.exit_code, result.error_code
        ),
    })
}
```

### Pattern 6: `wamcp-models` — serde structs (verbatim Python parity)

`rs/crates/wamcp-models/src/lib.rs`:

```rust
//! Pydantic-equivalent typed surface for the doctor MCP tool.
//! JSON wire shape MUST match `whatsapp_desktop_mcp.models.doctor.DoctorReport`
//! (CONTEXT D-13 / D-14 / D-15). Cross-binary parity test (D-23) asserts shape.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PermissionState {
    Granted,
    Denied,
    WhatsappNotInstalled,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PermissionCheck {
    /// One of "fda" | "automation" | "accessibility" — same string Python emits.
    pub bucket: String,
    pub state: PermissionState,
    /// Absolute path of the binary that needs the permission. Equivalent to
    /// Python's sys.executable (D-16).
    pub binary_path: String,
    /// Resolved path to ChatStorage.sqlite — only set for the FDA bucket.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub db_path: Option<String>,
    /// x-apple.systempreferences: URL that opens the right TCC panel.
    pub system_settings_url: String,
    /// One-line human instruction for fixing a denied state.
    #[serde(default)]
    pub remediation: String,
}

/// v0 placeholder for Phase 4.x — kept here so the DoctorReport shape is
/// stable from day one. v0 doctor always returns `None` for this field.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SchemaFingerprint {
    pub state: String,            // "supported" | "unsupported" | "unreachable"
    pub observed_version: Option<i32>,
    pub supported_versions: Vec<i32>,
    #[serde(default)]
    pub remediation: String,
}

/// v0 placeholder for Phase 4.x.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Coverage {
    pub from_ts: Option<i64>,
    pub to_ts: Option<i64>,
    pub asked_window_seconds: Option<i64>,
    pub have_window_seconds: Option<i64>,
    pub is_full: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DoctorReport {
    pub full_disk_access: PermissionCheck,
    pub automation_whatsapp: PermissionCheck,
    pub accessibility: PermissionCheck,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub db_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub schema_fingerprint: Option<SchemaFingerprint>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub whatsapp_app_version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_message_ts: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub coverage_summary: Option<Coverage>,
}
```

**Naming parity check:** Python `PermissionStatus` model uses `Literal["granted", "denied", "whatsapp_not_installed"]` strings. Rust serializes the enum variants as `"granted" | "denied" | "whatsapp_not_installed" | "unknown"` thanks to `#[serde(rename_all = "snake_case")]`. The `unknown` variant is new in Rust (not present in Python's Literal); it's only ever produced by the bidi-blind regex when the error code can't be parsed. The parity test (D-23) asserts the 3 known buckets match — `unknown` is treated as a parity violation if it appears.

### Anti-Patterns to Avoid (from CONTEXT and CLAUDE.md)

- **`println!` / `eprintln!` in source** → use `tracing::info!` / `tracing::warn!` to stderr. `clippy::print_stdout = "deny"` enforces (D-08). `print_stderr = "warn"` directs developers to tracing.
- **Modifying any Python source file** → CLAUDE.md hard rule + user request. Rust under `rs/` only.
- **Python tests requiring Rust toolchain** → parity test must `pytest.skip()` cleanly when `rs/target/release/whatsapp-desktop-mcp-rs` is absent.
- **Rust build requiring Python venv** → `cargo build` must work in a fresh checkout with no Python installed. Workspace test: rename `src/` to `src.bak/`, run `cargo build --workspace` from `rs/`, restore.
- **Sharing source files across `rs/` and `src/whatsapp_desktop_mcp/`** → CONTEXT D-01. Zero shared files.
- **INSERT/UPDATE/DELETE on ChatStorage.sqlite from Rust** → same CLAUDE.md rule as Python. v0 doesn't open the DB at all (deferred); when it does in Phase 4.x, the connection MUST be `OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_URI` per D-18.
- **Binding HTTP / TCP / UDP listener** → CLAUDE.md hard rule #5. Stdio only. The `transport-streamable-http-*` rmcp features must NOT be enabled.
- **Raw FFI for AX-API** → CONTEXT D-09 mandates `objc2-application-services`. Never write `extern "C" { fn AXUIElementCreateApplication(...) }` blocks.
- **`.unwrap()` in main paths** → use `?` + `anyhow::Result<()>` from `main`. `clippy::unwrap_used = "warn"` enforces. Tests may unwrap freely (`#[allow(clippy::unwrap_used)]` per test fn).
- **Shell-out via string** → always `Command::new("/usr/bin/osascript").arg("-e").arg(script)`. Never `.arg(format!("-e {script}"))`.
- **`std::process::Command` (sync)** in async paths — use `tokio::process::Command` so it doesn't block the runtime. Wrap `std::fs::metadata` (no async equivalent) in `tokio::task::spawn_blocking`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MCP JSON-RPC stdio loop | Custom newline-delimited JSON parser | `rmcp::transport::stdio()` | rmcp handles framing, initialize/handshake, capability negotiation, error types — getting this wrong means Claude Desktop silently drops the connection (P-PHASE0-01). |
| Tool registration | Manual `serde_json::json!({"tools": [...]})` for `tools/list` | `#[tool]` + `#[tool_router]` macros | Macros auto-generate input_schema from `Parameters<T>`, output_schema from return type, and the dispatch table. Hand-rolled tables drift from struct types. |
| AppleScript error code parsing | Substring matching on English error prose | `regex::Regex::new(r"\((-?\d+)\)\s*\z")` (locale-blind) | Python had this exact bug (P-PHASE0-02): French / Japanese stderr has different prose; only the trailing `(-NNNN)` is locale-stable (CONTEXT D-11). |
| Bidi-invisible string handling | Generic Unicode normalization (NFC/NFD/NFKD) | Codepoint filter on `[U+200E, U+2068, U+2069]` | Apple emits these in error messages and chat headers; full normalization changes other content. CONTEXT D-11. |
| Apple `Info.plist` parsing | `serde_json` (plists are XML or binary, not JSON) + handwritten parser | `plist = "1.7"` crate | Apple uses BOTH XML and binary plist formats; `plist::from_file` auto-detects. Python uses stdlib `plistlib`; Rust has no stdlib equivalent. |
| TCC permission detection via TCC.db | Open `~/Library/Application Support/com.apple.TCC/TCC.db` directly | osascript probes + `std::fs::metadata` | Reading TCC.db itself requires Full Disk Access — circular dependency. Python solved this with the try-and-do-the-action pattern (CONTEXT D-09); Rust uses the same. |
| AX-API FFI | Raw `extern "C"` blocks calling `AXUIElementCreateApplication` etc. | `objc2-application-services` | `objc2`'s `extern_class!` macros encapsulate Send+Sync invariants and CFRetained lifetime management. CONTEXT D-09 explicitly rejects the older `cocoa` crate. |
| Cargo dep-graph isolation check | Hand-grep `Cargo.toml` files for forbidden imports | Parse `Cargo.lock` with `cargo_lock` crate, OR `cargo metadata` JSON | More robust than text-grepping; Python's REL-05 unit test pattern (Phase 1 D-19) translates by parsing `cargo metadata` JSON and walking the dependency graph. |

**Key insight:** every problem above had a Python equivalent that was solved with the same "use the official thing" answer. The Rust port does NOT get to relitigate those decisions — it ports them.

## Runtime State Inventory

> Phase 4 is a NEW build (not a rename/refactor). Most categories are N/A.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — Rust binary writes nothing in v0 (no DB access, no sidecar files, no rate-limit DB, no audit log). | None. Phase 4.x will introduce sidecar files for parity with Phase 2/3 — to be researched then. |
| Live service config | The Claude Desktop `claude_desktop_config.json` may be edited by users to register a SECOND entry pointing at the Rust binary (e.g., `whatsapp-rs` alongside `whatsapp` Python). This is user-managed; the Rust binary doesn't write the config. | None — document the snippet in `rs/README.md` (D-30) and project README (D-29). |
| OS-registered state | macOS TCC database. The Rust binary at `~/.cargo/bin/whatsapp-desktop-mcp-rs` (cargo install) or `<workspace>/rs/target/release/whatsapp-desktop-mcp-rs` (local build) is a NEW binary path that must be granted FDA + Accessibility + Automation independently. The Python binary's grants do NOT inherit. | Document in README + `rs/README.md`: each binary needs separate TCC grants. The doctor tool surfaces this (`binary_path` field). |
| Secrets / env vars | `RUN_LIVE_RUST=1` — new env var introduced in CONTEXT D-23 to gate the parity test. No secret material. | Document in `rs/README.md` parity-test section. |
| Build artifacts | `rs/target/` (Cargo build outputs — large, regeneratable). `rs/Cargo.lock` is COMMITTED (D-26). The release.yml `rust-build` job produces `whatsapp-desktop-mcp-rs-{version}-aarch64-apple-darwin.tar.gz` attached to GitHub release. | Add `rs/target/` to `.gitignore` (D-26). Verify `rs/Cargo.lock` is NOT in `.gitignore`. |

**TCC churn warning (P15 carry-over):** the Phase 3 P15 problem — pipx/uvx installations creating new venv paths that orphan TCC grants — applies analogously to `cargo install --git`. Each `cargo install` to a NEW git revision DOES rebuild the binary at the same path (`~/.cargo/bin/whatsapp-desktop-mcp-rs`), so grants persist. But if the user changes `--root`, the binary moves and grants are orphaned. Document in `rs/README.md`: stick to one `--root` (recommend `/usr/local`) for stability.

## Common Pitfalls

### Pitfall 1: rmcp version pin drift between README and crates.io
**What goes wrong:** The rust-sdk README on `main` branch shows `rmcp = { version = "0.16.0", features = ["server"] }`. crates.io reports the latest as 1.7.0 (released 2026-05-13). Copying the README's "0.16.0" into Cargo.toml resolves to a stale pre-1.x version with different APIs.
**Why it happens:** The README appears to lag the published crate. The repo has a "Migrating to 1.x" pinned discussion (#716) confirming 1.x is the current major.
**How to avoid:** ALWAYS verify against `cargo search rmcp` or the crates.io API — never trust a README literal version. Use `version = "1.7"` or `version = "1"` for caret-bounded pin to the current major.
**Warning signs:** Compile errors mentioning `IntoTransport not implemented for stdio()`, `tool_router macro not found`, or `transport-stdio not a valid feature` — all symptoms of resolving to a 0.x version.

### Pitfall 2: MSRV drift between locked floor and dependency reality
**What goes wrong:** CONTEXT D-04 locks MSRV at 1.75. `clap` 4.6 (released April 2026) requires MSRV 1.85. `plist` 1.9 requires MSRV 1.88. Naively pinning `clap = "4"` resolves to 4.6 and breaks the build on 1.75 toolchains.
**Why it happens:** Rust ecosystem advances MSRV per-crate without coordination. CONTEXT was written with knowledge available at decision time.
**How to avoid:** Pin MAJOR.MINOR (`clap = "4.5"`, `plist = "1.7"`) for any dep where MSRV matters. CI runs on the pinned 1.75 toolchain — `actions-rust-lang/setup-rust-toolchain@v1` reads `rust-version` from `Cargo.toml`.
**Warning signs:** `rustc 1.75 cannot compile package X (requires rustc Y or later)` errors at `cargo build`. The fix is to bump the dep to a compatible older minor — NOT to bump MSRV silently.
**Alternative:** if the planner / user prefers latest deps, BUMP MSRV to 1.85 in D-04 (renegotiate with user; planner should flag in PLAN-CHECK).

### Pitfall 3: Stdout pollution by panic / debug print
**What goes wrong:** A `println!("debug")` slips into source, OR an unhandled panic prints to stdout via the default panic hook. Either pollutes the JSON-RPC channel and Claude Desktop drops the connection (same P-PHASE0-01 class as Python).
**Why it happens:** Rust's default panic hook writes to stderr (correct), but:
  - `println!` / `dbg!` are tempting during development
  - Some libraries print warnings via `eprintln!` (acceptable — stderr) or `println!` (BAD)
  - `tracing-subscriber` defaults to stdout if `with_writer` not specified
**How to avoid:**
  - `clippy::print_stdout = "deny"` (D-28) catches `println!` at lint time
  - `tracing_subscriber::fmt().with_writer(std::io::stderr).init()` — explicit stderr
  - CI test mirrors Python's `tests/unit/test_stdout_purity.py`: spawns the binary, sends `initialize` + `tools/list` + `tools/call doctor`, asserts every byte on stdout deserializes as JSON-RPC
  - Set custom panic hook that forces stderr: `std::panic::set_hook(Box::new(|info| eprintln!("{info}")))`
**Warning signs:** Any `cargo clippy` warning containing "print_stdout"; intermittent Claude Desktop disconnects; CI failure in the stdout-purity test.

### Pitfall 4: tokio runtime mismatch between rmcp and tokio::process
**What goes wrong:** `tokio::process::Command::output()` requires the `process` feature on tokio. Without it, the call compiles but panics at runtime ("runtime not initialized").
**Why it happens:** tokio's feature flags gate runtime capabilities. rmcp pulls in tokio with features `["sync", "macros", "rt", "time"]` — NOT `process`, NOT `io-std` (verified from rmcp 1.7.0 Cargo.toml).
**How to avoid:** the binary crate's `[dependencies]` must explicitly enable the features the binary uses, even if rmcp also depends on tokio. Use `tokio = { version = "1", features = ["macros", "rt-multi-thread", "io-std", "process"] }`.
**Warning signs:** Runtime panics like `there is no reactor running, must be called from the context of a Tokio 1.x runtime` or `the `process` feature must be enabled`.

### Pitfall 5: Cross-binary parity test races on TCC state changes
**What goes wrong:** The user toggles a TCC permission between the Python doctor call and the Rust doctor call. Test asserts state parity — fails.
**Why it happens:** TCC state is global mutable OS state. The two binaries are separate processes; their probes run at different wall-clock times.
**How to avoid (from CONTEXT T-5):** run both binaries in tight sequence (< 1s apart). Use Python `subprocess.Popen` + a single tool call per binary, then compare. Document in test docstring + `rs/README.md`: "if the test fails intermittently, ensure no TCC toggles during the test window."
**Warning signs:** Sporadic CI flakes only on the `RUN_LIVE_RUST=1` test. NOT a code bug — a test design quirk.

### Pitfall 6: objc2 family version skew across crates
**What goes wrong:** Pinning `objc2 = "0.6"` and `objc2-application-services = "0.2"` (the CONTEXT-named version) resolves to incompatible `objc2` API surface usage inside the application-services crate. Compile fails with cryptic trait errors.
**Why it happens:** `objc2-application-services` 0.2 was built against `objc2` 0.5; 0.3 was built against 0.6. The crates' versions track each other in lockstep.
**How to avoid:** pin all `objc2-*` family crates to the SAME compatible major line. Verified compatible: `objc2 = "0.6"` + `objc2-foundation = "0.3"` + `objc2-application-services = "0.3"`. CONTEXT D-09's example versions (0.5 / 0.2) are stale — use the verified line above.
**Warning signs:** Trait-bound errors mentioning `Encode`, `RefEncode`, or `extern_class!` macro expansion failures.

### Pitfall 7: `#[tool]` macro `meta` attribute requires `serde_json::json!` import
**What goes wrong:** Writing `#[tool(meta = {"anthropic/maxResultSizeChars": 60000})]` — this is JS object syntax, not Rust. Compile fails.
**Why it happens:** The macro accepts an arbitrary Rust expression for `meta` (verified from rmcp-macros 1.7.0 source: `pub meta: Option<Expr>`). The expression must evaluate to something convertible to `serde_json::Value`.
**How to avoid:** use `serde_json::json!` macro: `meta = json!({"anthropic/maxResultSizeChars": 60000})`. Add `use serde_json::json;` at top of file. The `json!` macro accepts JSON-like syntax inside Rust.
**Warning signs:** `expected expression, found '{'` or `cannot find macro json! in this scope`.

### Pitfall 8: `cargo install --git` resolves to wrong workspace member
**What goes wrong:** `cargo install --git https://github.com/jqueguiner/whatsapp-desktop-mcp.git rs/whatsapp-desktop-mcp-rs` fails or installs the wrong binary — `cargo install` doesn't accept arbitrary paths after the URL.
**Why it happens:** `cargo install --git <URL>` expects a package name (or `--bin` flag), not a workspace path.
**How to avoid:** the correct invocation is `cargo install --git https://github.com/jqueguiner/whatsapp-desktop-mcp.git --root /usr/local whatsapp-desktop-mcp-rs` — the workspace member NAME (not path) is the positional arg. The README install snippet must use this form.
**Warning signs:** `error: package id specification 'rs/whatsapp-desktop-mcp-rs' did not match any packages` at install time.

### Pitfall 9: Workspace `[workspace.lints]` requires resolver = "2" + Rust 1.74+
**What goes wrong:** Setting `[workspace.lints]` on the workspace root with `resolver = "1"` (the default for `edition = "2015"` workspaces) is silently ignored. Lints don't propagate to member crates.
**Why it happens:** `[workspace.lints]` is a 2024-era feature that requires the v2 feature resolver.
**How to avoid:** explicit `[workspace] resolver = "2"` at the top of `rs/Cargo.toml`. Each member's `Cargo.toml` should have `[lints] workspace = true` to inherit the workspace lints. Rust 1.75 supports this (resolver 2 stabilized in 1.51; workspace lints stabilized in 1.74).
**Warning signs:** Clippy lints firing on workspace root code but NOT on member crates; `print_stdout = "deny"` not catching `println!` in `wamcp-permissions/`.

## Code Examples

All examples in `## Architecture Patterns` (Patterns 1–6) are verified Rust code. Additional examples below cover the remaining tactical concerns.

### Cross-binary parity test (`tests/integration/test_rust_python_parity.py`)

```python
"""Cross-binary parity test for the doctor MCP tool (CONTEXT D-23).

Spawns BOTH binaries (Python + Rust) as MCP stdio servers, sends identical
JSON-RPC sequences, parses the doctor responses, and asserts shape parity.

Gated by RUN_LIVE_RUST=1 (separate from RUN_LIVE_WHATSAPP — the user opts in
to executing the Rust binary explicitly). Skips cleanly when the Rust binary
is not built (informative pytest.skip message).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Repo root is two levels up from this test file.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUST_BIN = _REPO_ROOT / "rs" / "target" / "release" / "whatsapp-desktop-mcp-rs"
_PYTHON_INVOCATION = [sys.executable, "-m", "whatsapp_desktop_mcp"]


def _send_jsonrpc_sequence(cmd: list[str | os.PathLike]) -> dict:
    """Spawn `cmd` as MCP stdio server, send initialize + tools/call doctor,
    return the parsed doctor result dict.
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # 1. initialize
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "parity-test", "version": "0.0.0"},
            },
        }) + "\n")
        proc.stdin.flush()
        _ = proc.stdout.readline()  # initialize response

        # 2. initialized notification (no response expected)
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }) + "\n")
        proc.stdin.flush()

        # 3. tools/call doctor
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "doctor", "arguments": {}},
        }) + "\n")
        proc.stdin.flush()
        result_line = proc.stdout.readline()

        result = json.loads(result_line)
        # The doctor tool returns its DoctorReport as the structuredContent.
        # rmcp + FastMCP both wrap typed results into result.structuredContent
        # (or result.content[0].text JSON for older protocol versions).
        return result["result"]
    finally:
        proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_RUST") != "1",
    reason="Rust parity test gated by RUN_LIVE_RUST=1 (opt-in)",
)
@pytest.mark.skipif(
    not _RUST_BIN.exists(),
    reason=(
        f"Rust binary not built at {_RUST_BIN}; "
        "run `cd rs && cargo build --release --locked` first."
    ),
)
def test_rust_python_doctor_parity() -> None:
    """Both binaries' doctor output must agree on shape and TCC state."""
    rust_result = _send_jsonrpc_sequence([str(_RUST_BIN)])
    # Run Python second, in tight sequence (< 1s apart) per CONTEXT T-5.
    time.sleep(0.1)
    python_result = _send_jsonrpc_sequence(_PYTHON_INVOCATION)

    # Extract the structured doctor reports from both responses.
    rust_doctor = rust_result.get("structuredContent") or json.loads(
        rust_result["content"][0]["text"]
    )
    python_doctor = python_result.get("structuredContent") or json.loads(
        python_result["content"][0]["text"]
    )

    # Top-level field shape parity (CONTEXT D-23 step 4).
    expected_keys = {
        "full_disk_access", "automation_whatsapp", "accessibility",
        "db_path", "schema_fingerprint", "whatsapp_app_version",
        "last_message_ts", "coverage_summary",
    }
    rust_keys = {k for k, v in rust_doctor.items() if v is not None}
    python_keys = {k for k, v in python_doctor.items() if v is not None}
    # Rust v0 doesn't populate schema_fingerprint / last_message_ts /
    # coverage_summary — those are Phase 4.x. Compare only the v0-populated set.
    rust_v0_set = {"full_disk_access", "automation_whatsapp", "accessibility",
                   "db_path", "whatsapp_app_version"}
    assert rust_v0_set.issubset(rust_keys), f"Rust missing v0 keys: {rust_v0_set - rust_keys}"
    assert rust_v0_set.issubset(python_keys), "Python missing v0 keys (parity broken)"

    # Per-bucket state parity (CONTEXT D-23 step 5).
    for bucket in ("full_disk_access", "automation_whatsapp", "accessibility"):
        rust_state = rust_doctor[bucket]["state"]
        python_state = python_doctor[bucket]["state"]
        assert rust_state == python_state, (
            f"{bucket}: rust={rust_state!r} python={python_state!r} — "
            "TCC state divergence indicates broken probe logic in one binary"
        )

    # binary_path differs (sanity check both binaries actually ran)
    rust_bp = rust_doctor["full_disk_access"]["binary_path"]
    python_bp = python_doctor["full_disk_access"]["binary_path"]
    assert rust_bp != python_bp, "binary_path identical — test didn't run two binaries"

    # db_path + system_settings_url match (both probe the same WhatsApp install)
    assert rust_doctor["db_path"] == python_doctor["db_path"]
    assert (
        rust_doctor["full_disk_access"]["system_settings_url"]
        == python_doctor["full_disk_access"]["system_settings_url"]
    )
```

### CI integration (`.github/workflows/ci.yml` extension)

Append a new `rust-lint-test` job (parallel to existing `lint-type-test` per CONTEXT D-25):

```yaml
  rust-lint-test:
    runs-on: macos-14    # objc2 builds need macOS (D-25)
    steps:
      - uses: actions/checkout@v4

      - name: Install Rust toolchain (reads rust-version from rs/Cargo.toml)
        uses: actions-rust-lang/setup-rust-toolchain@v1.16.1   # latest stable as of 2026-05-08
        with:
          toolchain: "1.75"          # honors CONTEXT D-04 MSRV pin
          components: rustfmt,clippy
          # cache: enabled by default for the workspace at the working dir we set

      - name: cargo fmt --check
        working-directory: rs
        run: cargo fmt --all -- --check

      - name: cargo clippy (workspace, deny warnings)
        working-directory: rs
        run: cargo clippy --workspace --all-targets --locked -- -D warnings

      - name: cargo test (workspace)
        working-directory: rs
        run: cargo test --workspace --locked

      - name: stdout-purity smoke (mirrors Python tests/unit/test_stdout_purity.py)
        working-directory: rs
        run: |
          cargo build --release --locked
          # Send initialize + tools/list + tools/call doctor; assert every stdout line is JSON.
          ./target/release/whatsapp-desktop-mcp-rs <<'EOF' | python3 -c '
          import sys, json
          for line in sys.stdin:
              line = line.strip()
              if not line:
                  continue
              json.loads(line)  # raises if not valid JSON
          '
          {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"ci","version":"0"}}}
          {"jsonrpc":"2.0","method":"notifications/initialized"}
          {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
          {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"doctor","arguments":{}}}
          EOF
```

**Notes on the YAML:**
- Job name `rust-lint-test` mirrors Python's `lint-type-test` naming (D-25).
- `actions-rust-lang/setup-rust-toolchain@v1.16.1` — pinned to a verified version (released 2026-05-08). Use major-line `@v1` for floating, OR pin like `@v1.16.1` for reproducibility. CONTEXT D-25 says "pin version" — recommend `@v1.16.1` exact pin.
- `toolchain: "1.75"` honors D-04 MSRV. The action ALSO honors `rust-version` from `Cargo.toml` if `toolchain:` is omitted; explicit pin is more transparent.
- `--locked` flag fails if `Cargo.lock` would change — guard against silent drift (D-26).
- Stdout-purity smoke is inline; can be lifted into a `tests/integration/test_stdout_purity.rs` Cargo integration test in Phase 4.x for cleaner separation.

### Release.yml `rust-build` job

Append after `tap-update` (independent of pkg-build / tap-update — D-19 says it's downstream of `publish` only):

```yaml
  # ---------------------------------------------------------------------
  # rust-build (Phase 4 v0)
  # ---------------------------------------------------------------------
  # Builds the Rust port binary on tag push and attaches it to the same
  # GitHub release as the Python .pkg.
  #
  # Decisions: D-19 (GitHub release artifact only), D-22 (independent
  # versioning — Rust starts at 0.0.0 regardless of Python's version).
  # Apple-Silicon-only for v0 (D-19); Intel cross-compile deferred to
  # Phase 4.x.
  rust-build:
    needs: [publish]
    runs-on: macos-14    # Apple Silicon
    permissions:
      contents: write    # required for softprops/action-gh-release@v2 release upload
    steps:
      - uses: actions/checkout@v4

      - name: Install Rust toolchain
        uses: actions-rust-lang/setup-rust-toolchain@v1.16.1
        with:
          toolchain: "1.75"   # D-04 MSRV

      - name: Build release binary
        working-directory: rs
        run: cargo build --release --locked

      - name: Strip symbols
        working-directory: rs
        run: strip target/release/whatsapp-desktop-mcp-rs

      - name: Compute Rust binary version
        id: rust_version
        working-directory: rs
        run: |
          # D-22: Rust binary version is independent of git tag.
          # Read it from rs/Cargo.toml (which sources from [workspace.package].version).
          RUST_VERSION=$(grep -m1 -E '^version\s*=' Cargo.toml | head -1 | awk -F'"' '{print $2}')
          # If the workspace version is the placeholder "0.0.0", fall back to git tag.
          if [ "$RUST_VERSION" = "0.0.0" ]; then
            RUST_VERSION="${GITHUB_REF#refs/tags/v}-rust0"
          fi
          echo "version=$RUST_VERSION" >> "$GITHUB_OUTPUT"

      - name: Tarball
        run: |
          ARCH=$(uname -m)   # arm64 on macos-14
          TARBALL="whatsapp-desktop-mcp-rs-${{ steps.rust_version.outputs.version }}-${ARCH}-apple-darwin.tar.gz"
          tar -czf "$TARBALL" -C rs/target/release whatsapp-desktop-mcp-rs
          echo "TARBALL=$TARBALL" >> "$GITHUB_ENV"

      - name: Attach to GitHub release
        uses: softprops/action-gh-release@v2
        with:
          files: ${{ env.TARBALL }}
```

**Notes:**
- Independent of pkg-build / tap-update — Rust artifact attaches even if Python pkg/tap jobs fail or skip (D-19 / D-20).
- Apple Silicon only for v0 (D-19). The tarball name encodes `arm64-apple-darwin` (the result of `uname -m` on macos-14).
- Versioning quirk: D-22 says first ship is `0.0.0`. The placeholder logic above keeps the file name informative even when workspace version is the placeholder — it falls back to the git tag suffixed with `-rust0`.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `mcp-rust-sdk` community crate | `rmcp` (modelcontextprotocol/rust-sdk) | Anthropic published official SDK in 2025 | Use rmcp; community crates lag spec. |
| `cocoa` crate for Cocoa bindings | `objc2` family | objc2 0.5+ in 2024 introduced Send+Sync types | CONTEXT D-09 explicitly mandates objc2; cocoa is maintenance-only. |
| Hand-rolled extern "C" AX-API blocks | `objc2-application-services` | 0.3.x (Q4 2025) added comprehensive AX feature gating | No need for raw FFI; extern_class! macros encapsulate unsafe. |
| `pyo3` for Python interop | N/A — Rust is a SEPARATE binary, not a Python extension | Phase 4 design choice (CONTEXT D-01) | Zero Python interop surface. The two binaries communicate ONLY via the same WhatsApp Desktop install. |
| Cargo per-crate `[dependencies]` duplication | `[workspace.dependencies]` + `<dep>.workspace = true` | Stable since Rust 1.64 (2022) | Use workspace deps for single-source-of-truth pinning. |
| Per-crate `[lints]` duplication | `[workspace.lints]` + `[lints] workspace = true` | Stable since Rust 1.74 (Nov 2023) | One source of truth for clippy/rustc lints; D-28 enforced workspace-wide. |
| `tracing` 0.2 (never released) | `tracing` 0.1 (still current) | n/a | 0.1 is the actual current line. |

**Deprecated/outdated:**
- `cocoa` crate — last meaningful release 2022. Use `objc2-foundation` + `objc2-app-kit`.
- `mcp-rust-sdk` (community) — superseded by official `rmcp`.
- `pretty_env_logger` / `env_logger` — `tracing-subscriber` is the modern choice for structured logging.

## Plan Structure Recommendation

Phase 4 v0 is small (~15 source files) but multi-faceted (Cargo workspace setup + 3 probes + tool registration + CI integration + parity test + docs). Splitting into 3 plans mirrors Phase 0's structure (5 plans) and keeps each plan to a coherent unit of work:

### Plan 04-01: Workspace skeleton (no behavior, structure only)

**Goal:** `cd rs && cargo build --workspace --locked` succeeds against a workspace with 6 lib crate stubs + 1 binary crate that does nothing.

**Deliverables:**
- `rs/Cargo.toml` (workspace root: members + [workspace.package] + [workspace.dependencies] + [workspace.lints])
- `rs/Cargo.lock` (committed — D-26)
- `rs/rustfmt.toml` (D-27)
- `rs/clippy.toml` (D-28)
- `rs/.gitignore` additions (`target/`)
- `rs/whatsapp-desktop-mcp-rs/Cargo.toml` + `src/main.rs` (just `tracing::info!("hello"); Ok(())`, no rmcp yet)
- `rs/crates/wamcp-{models,permissions,paths,tools,reader,sender}/Cargo.toml` + `src/lib.rs` stubs (each with `// Phase 4 v0: stub` or `// Phase 4.x: reserved`)
- `rs/.cargo/config.toml` with `[target.aarch64-apple-darwin] rustflags = ["-C", "target-cpu=apple-m1"]` (Claude discretion — recommend yes for native perf)
- `rs/deny.toml` (Claude discretion — recommend yes for hygiene; trivial)
- `rs/tests/isolation.rs` integration test asserting wamcp-reader does NOT depend on wamcp-sender (parses `cargo metadata` JSON)
- `rs/README.md` build instructions (D-30)

**Acceptance:** `cd rs && cargo build --workspace --locked && cargo test --workspace --locked` green.

### Plan 04-02: Doctor tool + 3 probes + WhatsApp.app version

**Goal:** the binary built in Plan 04-01 actually serves the doctor tool over MCP stdio, returning a real DoctorReport.

**Deliverables:**
- `wamcp-models/src/lib.rs` (PermissionState enum, PermissionCheck, SchemaFingerprint stub, Coverage stub, DoctorReport)
- `wamcp-paths/src/lib.rs` (resolve_chatstorage_path; mirror Python paths.py)
- `wamcp-permissions/src/{osascript,fda,automation,accessibility,url}.rs`
- `wamcp-tools/src/{lib,doctor}.rs` (DoctorTool with #[tool_router(server_handler)] + #[tool] doctor function + plist-based version probe)
- `whatsapp-desktop-mcp-rs/src/main.rs` (full ~50-line server entry point with rmcp + tracing-stderr)
- Unit tests in each crate: probe state mapping for each error code; bidi-strip; regex; serde round-trip on DoctorReport

**Acceptance:**
- `cargo test --workspace --locked` green (unit tests).
- Manual smoke: `./rs/target/release/whatsapp-desktop-mcp-rs <<<` <JSON-RPC initialize + tools/call doctor> returns valid DoctorReport JSON on stdout.

### Plan 04-03: CI + cross-binary parity + docs

**Goal:** the new binary is buildable from CI on every PR, the parity test runs against both binaries on demand, and users can find the install instructions in the README.

**Deliverables:**
- `.github/workflows/ci.yml` — append `rust-lint-test` job (D-25)
- `.github/workflows/release.yml` — append `rust-build` job (D-19)
- `tests/integration/test_rust_python_parity.py` (CONTEXT D-23 verbatim implementation)
- `README.md` — append "Rust port (experimental)" subsection as 4th install row (D-29)
- `rs/README.md` — full Rust-specific build/test/parity-test instructions (D-30)

**Acceptance:**
- CI on a PR runs both `lint-type-test` (Python, unchanged) AND `rust-lint-test` (new) in parallel; both green.
- `RUN_LIVE_RUST=1 uv run pytest tests/integration/test_rust_python_parity.py -v` passes on a Mac with WhatsApp installed + 3 TCC perms granted (manual maintainer verification — flag in plan that this is a smoke test, not CI).
- Tag push triggers `rust-build` job and attaches `whatsapp-desktop-mcp-rs-*-arm64-apple-darwin.tar.gz` to the GitHub release.

### Why 3 plans and not 1 or 5?

- **Not 1:** the v0 work is 15 source files + CI + docs. A single plan has too many discrete acceptance criteria; planner-checker will flag it.
- **Not 5 (Phase 0 mirror):** Phase 0 split was 5 because each piece was a Python phase prerequisite (skeleton / FastMCP / probes / tests / CI). Phase 4 has fewer moving parts because it's porting an EXISTING design.
- **3 is the sweet spot:** structure (skeleton) → behavior (probes + tool) → integration (CI + parity + docs). Each plan is independently testable; a regression in one doesn't block the others.

### Plan dependency order

```
04-01-skeleton   (no deps)
      │
      ▼
04-02-doctor     (depends on 04-01: workspace must exist)
      │
      ▼
04-03-ci-parity  (depends on 04-02: needs a real doctor to test)
```

Plans 04-01 and 04-02 cannot run in parallel (04-02's lib crate sources need the workspace skeleton). Plans 04-02 and 04-03 cannot run in parallel either (parity test invokes the actual built binary).

**Parallelization recommendation:** within each plan, plan tasks may run in parallel where their files don't overlap (e.g., in Plan 04-02 the 3 probe files + the models file have zero overlap). The orchestrator's `parallelization: true` config setting in `.planning/config.json` already enables this.

## Project Constraints (from CLAUDE.md)

These directives have the same authority as locked decisions. The planner MUST verify each is honored.

| Source | Directive | Phase 4 v0 Honor Path |
|--------|-----------|----------------------|
| CLAUDE.md "Stack (locked)" | Anti-stack list (do NOT introduce: whatsmeow, Baileys, WhatsApp Cloud API, aiosqlite, SQLAlchemy, pywhatkit, Selenium, any HTTP REST surface) | Rust port introduces NONE of these. `rusqlite` is locally-bundled SQLite (D-17), not an HTTP DB. No HTTP listener. |
| CLAUDE.md hard rule #1 | Reader and Sender MUST NOT import each other | Cargo enforces structurally: `wamcp-reader` MUST NOT have `wamcp-sender` in `[dependencies]` (D-03). Empty stubs in v0 enforce this from day one. `rs/tests/isolation.rs` parses `cargo metadata` and asserts. |
| CLAUDE.md hard rule #2 | stdout is the JSON-RPC channel | `clippy::print_stdout = "deny"` (D-08); `tracing` to stderr; CI stdout-purity smoke test. |
| CLAUDE.md hard rule #3 | Never write to ChatStorage.sqlite | v0 doesn't open the DB at all. Phase 4.x: `OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_URI` (D-18). |
| CLAUDE.md hard rule #4 | Never inline media bytes in tool responses | v0 tool returns DoctorReport — no media. Phase 4.x reader will mirror Python's MediaRef pattern. |
| CLAUDE.md hard rule #5 | No HTTP / TCP / UDP listener — stdio only | `rmcp` features explicitly enable ONLY `transport-io` (stdio); the HTTP transport features (`transport-streamable-http-*`) are NOT enabled. |
| CLAUDE.md hard rule #6 | Never compare JID strings directly | v0 doesn't touch JIDs. Phase 4.x reader will mirror the `Jid` type pattern from Python. |
| CLAUDE.md hard rule #7 | Send is destructiveHint:true and gated by elicitation | v0 has no send tool. Phase 4.x will mirror Python's elicitation + rate limit + audit log. |
| CLAUDE.md hard rule #8 | Every read tool returns a `coverage` field | v0 has no read tools. DoctorReport carries `coverage_summary` (set to `None` in v0; populated in Phase 4.x). |
| CLAUDE.md "GSD workflow" | Atomic commits — every plan ships as own commit | Planner produces 3 separate plans; executor commits each independently per `commit_docs: true`. |
| CLAUDE.md "Working preferences" | YOLO mode on, granularity coarse | The 3-plan split honors coarse granularity; `auto_advance: true` flows through. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | rmcp 1.7.0 stdio transport works correctly with `tokio::io::stdin()` + `tokio::io::stdout()` and the `transport-io` feature (no additional config needed). | Standard Stack / Pattern 3 | LOW — verified from docs.rs/rmcp/1.7.0/rmcp/transport/index.html that `serve((stdin, stdout))` is the canonical idiom. If wrong, the binary fails fast at handshake (test catches it). |
| A2 | rmcp's `#[tool]` macro `meta = <expr>` accepts `serde_json::json!({...})` and forwards to the tool advertisement's `_meta` field on `tools/list`. | Pattern 4 / Pitfall 7 | LOW — verified from rmcp-macros 1.7.0 source (`pub meta: Option<Expr>` + `quote! { .with_meta(#m) }`). The `_meta` field is part of MCP spec 2025-11-25; rmcp's serialization should comply. |
| A3 | The cross-binary parity test's JSON-RPC sequence (`initialize` → `notifications/initialized` → `tools/call doctor`) works against BOTH FastMCP (Python) and rmcp (Rust) without protocol-version mismatch. | Code Examples / Parity Test | MEDIUM — Python FastMCP `mcp[cli]==1.27.1` and rmcp 1.7.0 may negotiate different protocol versions (`2025-11-25` vs an older one). The test should accept whichever protocol version each server advertises in its `initialize` response. Mitigation: the example code parses both `result.structuredContent` and `result.content[0].text` JSON forms to handle wire-shape variation. |
| A4 | `actions-rust-lang/setup-rust-toolchain@v1.16.1` honors a `toolchain:` parameter and installs Rust 1.75 (not the latest stable). | CI Pattern | HIGH-confidence — verified from action README; standard parameter. If wrong, MSRV regression caught by `cargo build --locked` failures on the runner. |
| A5 | The `[workspace.lints]` section propagates to member crates only when each member's Cargo.toml has `[lints] workspace = true`. | Pitfall 9 | HIGH-confidence — verified from rustdoc / Cargo book. If skipped, lints silently don't fire and clippy passes despite `print_stdout` calls in member crates. Mitigation: planner adds `[lints] workspace = true` to EVERY member Cargo.toml stanza. |
| A6 | The `softprops/action-gh-release@v2` action attaches files to an EXISTING release created by the `publish` job's tag push (vs. creating a new release). | Release.yml Pattern | LOW — already used by Phase 3 pkg-build job (line 200–203 of release.yml). Same usage pattern; will work. |
| A7 | Rust 1.75 toolchain is still installable via `actions-rust-lang/setup-rust-toolchain@v1.16.1` in 2026. | CI Pattern | HIGH-confidence — Rust 1.75 was released Dec 2023; toolchain registry retains old versions indefinitely. |
| A8 | The `cargo install --git <URL> --root /usr/local <package-name>` form works for installing a workspace member by name. | Distribution / Pitfall 8 | HIGH-confidence — standard Cargo behavior since 1.0. The `<package-name>` (workspace member name, not path) is the positional arg per `cargo install --help`. |

## Open Questions

1. **MSRV bump or strict floor?**
   - What we know: CONTEXT D-04 locks MSRV at 1.75. `clap 4.6` (released April 2026) requires MSRV 1.85; `plist 1.9` requires MSRV 1.88. Pinning the older minor lines (`clap = "4.5"`, `plist = "1.7"`) preserves D-04 but commits us to bug-fix-only releases on those crates.
   - What's unclear: does the user want strict MSRV preservation (pin old minors), or modern dep latitude (bump MSRV to 1.85 in D-04)?
   - Recommendation: **pin the old minors** — D-04 is locked, and 1.75 is well within active support. Bumping MSRV in v0 sets a precedent that drifts every quarter. Document in plan + flag for future re-evaluation if a security advisory drops on `clap 4.5.x` / `plist 1.7.x`.

2. **`cargo-deny` config — include or skip?**
   - What we know: CONTEXT calls this "Claude's discretion". Adding `rs/deny.toml` is trivial; running `cargo deny check` in CI catches advisory + license issues.
   - What's unclear: maintainer appetite for adding another CI check.
   - Recommendation: **include it**. The cost is one config file (~30 lines) and one CI step (5s). The benefit is early detection of yanked crates and license incompatibilities. Default config (`cargo deny init`) is good enough; no custom rules needed.

3. **`rs/.cargo/config.toml` with `target-cpu=apple-m1`?**
   - What we know: CONTEXT calls this "Claude's discretion". Setting `rustflags = ["-C", "target-cpu=apple-m1"]` for `aarch64-apple-darwin` produces binaries that won't run on Intel Macs (irrelevant — D-19 is Apple Silicon only) but use M1-specific instructions for ~5–15% perf wins on async + JSON paths.
   - What's unclear: whether Phase 4.x will want to ship Intel binaries (would require removing this setting).
   - Recommendation: **include it**, scoped to `[target.aarch64-apple-darwin]` only. Phase 4.x cross-compile work would add an `[target.x86_64-apple-darwin]` block without conflict.

4. **Does the rmcp `#[tool]` macro's `description` field accept multi-line strings cleanly?**
   - What we know: rmcp-macros source treats it as a string literal. Python multi-line descriptions pass cleanly.
   - What's unclear: whether Rust raw strings (`r#"..."#`) are accepted by the macro parser.
   - Recommendation: use ordinary `\` line-continuation in the `description = "..."` argument (as in Pattern 4). Smoke-test in Plan 04-02 by `cargo expand` to verify the macro expansion.

5. **Rust tarball naming convention.**
   - What we know: D-19 says `whatsapp-desktop-mcp-rs-{version}-{arch}.tar.gz`. Apple Silicon = `arm64` (uname -m) or `aarch64` (Rust target triple).
   - What's unclear: which arch identifier to use.
   - Recommendation: use `aarch64-apple-darwin` (Rust target triple) — it's the canonical Cargo identifier and survives cross-compile expansion. Pattern: `whatsapp-desktop-mcp-rs-0.0.0-aarch64-apple-darwin.tar.gz`.

## Environment Availability

| Dependency | Required By | Available on dev mac | Version | Fallback |
|------------|------------|---------------------|---------|----------|
| Rust toolchain | Plans 04-01..04-03 | Unknown — must verify | — | rustup install command in `rs/README.md` |
| Cargo | Plans 04-01..04-03 | Bundled with Rust | — | Same |
| `/usr/bin/osascript` | Plan 04-02 (osascript probes) | YES (macOS bundles it; same as Python uses) | macOS native | Probe falls back to `osascript-missing` synthetic result (mirrors Python) |
| `/Applications/WhatsApp.app/Contents/Info.plist` | Plan 04-02 (version probe) | Conditional — depends on whether WhatsApp Desktop is installed | 26.16.74 verified live 2026-05-13 | `whatsapp_app_version: None` (mirrors Python `_probe_whatsapp_version_blocking` returning None) |
| `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite` | Plan 04-02 (FDA probe) + parity test | Conditional — present iff WhatsApp installed AND launched at least once | ~89 MB live | `WhatsappNotInstalled` state (mirrors Python) |
| Python 3.12 + uv + `whatsapp-desktop-mcp` | Plan 04-03 parity test | YES (verified by Phase 0–3 completing) | 3.12.x | N/A — parity test requires both binaries to compare |
| GitHub Actions macOS-14 runner | Plans 04-03 (CI + release) | N/A (cloud) | macOS 14.x with Xcode CLT preinstalled | None — CONTEXT D-25 mandates macos-14 |
| `actions-rust-lang/setup-rust-toolchain@v1.16.1` | Plan 04-03 | Available from GitHub Marketplace | v1.16.1 (verified 2026-05-08) | Could fall back to `rustup-init` install in workflow, but the action handles caching too |

**Missing dependencies with no fallback:** None for v0 (cargo install works on any Mac with Xcode CLT; rustup is the universal install path).

**Missing dependencies with fallback:** WhatsApp.app being uninstalled or never-launched is gracefully handled by the doctor tool returning `whatsapp_not_installed` — same behavior as Python.

**Pre-execution check command (to run BEFORE Plan 04-01):**

```bash
# Verify Rust toolchain available
command -v cargo >/dev/null 2>&1 && cargo --version
command -v rustc >/dev/null 2>&1 && rustc --version
# Expected: rustc 1.75.0 or later
```

## Security Domain

> Phase 4 v0 is a parallel implementation of EXISTING Python functionality. The threat model carries from Phases 0–3 with adjustments for Rust-specific surfaces.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | NO | No auth — single-user local MCP server. |
| V3 Session Management | NO | Stdio is point-to-point per-process; no session state. |
| V4 Access Control | YES (transitively via TCC) | macOS TCC enforces FDA / Accessibility / Automation. The doctor tool reports state but does NOT bypass. |
| V5 Input Validation | YES | `serde` deserialization on tool inputs; `Parameters<T>` types in rmcp enforce schema. v0 doctor takes no inputs. |
| V6 Cryptography | NO | No crypto in Rust v0. WhatsApp's E2EE is upstream of our reads. |
| V7 Error Handling & Logging | YES | `tracing` to stderr; structured errors; never expose internal paths in messages beyond what's already public (binary path is intentionally exposed for remediation). |
| V12 Files and Resources | YES | `std::fs::metadata` on a known absolute path; no path traversal surface in v0. |
| V13 API + Web Service | NO | Stdio only — no HTTP/REST surface. |

### Known Threat Patterns for `(Rust + macOS + osascript subprocess + AX-API future)`

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| AppleScript injection via tool input | Tampering | v0 doctor takes ZERO user input. Phase 4.x send_message will require quote-escaping per Phase 2 patterns — all hand-rolled string interpolation into AppleScript REJECTED; use `Command::new + arg` with literal scripts only. |
| Locale-blind error code spoofing | Spoofing | The error regex extracts trailing `(-NNNN)` from stderr. A malicious app cannot easily forge stderr from `osascript` (we control the subprocess). Mitigation = treat unknown error codes as `Denied` (defense in depth — CONTEXT D-12). |
| Stdout pollution → MCP framing break | Repudiation (loss of audit trail) | `clippy::print_stdout = "deny"` + tracing-to-stderr + CI stdout-purity smoke. |
| TCC bypass attempt | Elevation of Privilege | The Rust binary CANNOT elevate beyond what TCC has granted to its own path. Each cargo install creates a new path; user must grant explicitly. doctor tool reports the actual binary path so user knows what to grant. |
| Path traversal on Info.plist read | Information Disclosure | Hard-coded absolute path `/Applications/WhatsApp.app/Contents/Info.plist`. No user-controlled component. |
| Cargo supply chain | Tampering | `Cargo.lock` committed (D-26) ensures reproducible builds. `cargo deny` (recommended in Open Question 2) catches yanked crates and known advisories. `cargo install --git` builds from source — no pre-built binary attack surface. |
| Unsafe FFI in objc2 | Tampering | All AX-API calls use `objc2`'s `extern_class!` + safe wrapper macros. Direct `extern "C"` blocks are FORBIDDEN (Anti-Patterns). v0 has zero AX usage; Phase 4.x will use the same objc2 patterns. |

### Audit considerations
- `tracing` events on stderr are NOT cryptographically protected (same as Python's logging). Treated as best-effort observability, not security audit.
- v0 has no audit log (no send tool). Phase 4.x will mirror Python's `~/Library/Logs/whatsapp-desktop-mcp/audit.log` mode 0600 pattern.

## Sources

### Primary (HIGH confidence — VERIFIED 2026-05-14)
- `rmcp` 1.7.0 published crate inspected via `gh api modelcontextprotocol/rust-sdk` + crate download from crates.io
  - `rmcp-macros/1.7.0/src/tool.rs` — full attribute parser source (lines 83–171, 391+)
  - `rmcp/Cargo.toml` (rmcp-1.7.0 ref) — features list (lines 90+: default = ["base64", "macros", "server"])
  - `rust-sdk/README.md` (main branch) — canonical stdio server example (calculator, lines 130–155)
- `https://crates.io/api/v1/crates/rmcp` — version 1.7.0 (released May 13, 2026), 9.7M total downloads
- `https://crates.io/api/v1/crates/objc2` — version 0.6.4 (released Feb 26, 2026), MSRV 1.71
- `https://crates.io/api/v1/crates/objc2-foundation` — version 0.3.2, MSRV 1.71
- `https://crates.io/api/v1/crates/objc2-application-services` — version 0.3.2, MSRV 1.71, full AX feature flag list
- `https://docs.rs/objc2-application-services/latest/objc2_application_services/struct.AXUIElement.html` — `new_application(pid)` and `new_system_wide()` methods verified
- `https://docs.rs/rmcp/1.7.0/rmcp/transport/index.html` — `stdio()` function under `transport-io` feature
- `https://docs.rs/rmcp/1.7.0/rmcp/model/struct.ToolAnnotations.html` — full ToolAnnotations field list and builder API
- `https://crates.io/api/v1/crates/clap/versions` — full MSRV history confirming 4.5.61 = MSRV 1.74, 4.6.x = MSRV 1.85
- `https://crates.io/api/v1/crates/plist/versions` — full MSRV history confirming 1.7.4 = MSRV 1.68, 1.9.0 = MSRV 1.88
- `https://crates.io/api/v1/crates/tokio` — version 1.52.3, MSRV 1.71
- `https://crates.io/api/v1/crates/rusqlite` — version 0.39.0 (CONTEXT D-17 explicitly locks 0.31)
- `https://github.com/actions-rust-lang/setup-rust-toolchain/releases` — v1.16.1 latest (May 8, 2026)

### Secondary (MEDIUM confidence — repo source code referenced)
- `src/whatsapp_desktop_mcp/permissions/{osascript,fda,automation,accessibility}.py` — Python implementations being mirrored
- `src/whatsapp_desktop_mcp/tools/doctor.py` — Python tool registration pattern being mirrored
- `src/whatsapp_desktop_mcp/models/doctor.py` — Pydantic models being ported to serde
- `src/whatsapp_desktop_mcp/paths.py` — path resolver being ported
- `src/whatsapp_desktop_mcp/server.py` — FastMCP setup pattern (incl. logging-to-stderr-before-imports)
- `.github/workflows/ci.yml` + `release.yml` — existing job patterns for the new rust-lint-test + rust-build jobs

### Tertiary (LOW confidence — to validate during planning)
- A3 (Assumptions Log) — protocol version negotiation between FastMCP `1.27.1` and rmcp `1.7.0`; both should agree on 2025-11-25 but may differ.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every crate version verified live against crates.io 2026-05-14; MSRV constraints cross-checked.
- Architecture: HIGH — patterns ported verbatim from Python source code with type-system equivalents; tool registration syntax verified from rmcp-macros 1.7.0 source.
- Pitfalls: HIGH — Pitfalls 1, 2, 6, 9 are verified live (version drift, MSRV, objc2 family skew, workspace lints); Pitfalls 3, 4, 5, 7, 8 are standard known issues with verified workarounds.
- Plan structure: HIGH — mirrors Phase 0's 5-plan split with the 3-plan reduction explained.

**Research date:** 2026-05-14
**Valid until:** 2026-06-14 (30 days for stable Rust ecosystem; rmcp publishes monthly so check for >1 minor version drift before then)

---

## RESEARCH COMPLETE

**Phase:** 4 — Rust port (parallel binary, additive)
**Confidence:** HIGH

### Key Findings
- `rmcp` 1.7.0 is the verified current version (NOT the README's stale "0.16.0"); use `features = ["server", "macros", "transport-io"]` (server+macros are default)
- `objc2` family canonical line is `0.6` / `0.3` / `0.3` (CONTEXT D-09's `0.5` / `0.2` examples are stale — must update during planning)
- MSRV 1.75 (D-04) IS achievable but requires pinning `clap = "4.5"` and `plist = "1.7"` (NOT 4.6 / 1.9 which require 1.85 / 1.88) — flagged as Open Question 1 for user confirmation
- `#[tool]` macro DOES support `meta = serde_json::json!({...})` natively — no programmatic ToolBuilder fallback needed; verified from rmcp-macros 1.7.0 source
- `transport::stdio()` returns a `(stdin, stdout)` transport — full `serve(stdio()).await` pattern works as `Calculator.serve(stdio()).await?`
- Recommend 3-plan split: 04-01-skeleton (workspace + stubs), 04-02-doctor (probes + tool + version probe), 04-03-ci-parity (CI + release.yml + parity test + docs)
- All 3 permission probes port verbatim from Python — same osascript invocations, same error code matrix, same bidi-strip codepoints, same `spawn_blocking` pattern (Python's `to_thread` equivalent)
- Cross-binary parity test runs both binaries via subprocess.Popen, sends initialize+tools/call doctor JSON-RPC sequence, asserts top-level keys + per-bucket state parity + binary_path divergence
- 3 Claude-discretion items resolved with recommendations: include `rs/.cargo/config.toml` (target-cpu=apple-m1), include `cargo-deny` (trivial), skip Justfile/make wrapper (small repo)
- Workspace `[lints]` propagation requires `[lints] workspace = true` in EVERY member Cargo.toml — Pitfall 9 must land in plan-checker's verification list

### File Created
`/Users/jlqueguiner/dev/whatsapp-mcp/.planning/phases/04-rust-port-parallel-binary/04-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | All versions verified live against crates.io 2026-05-14; MSRV constraints cross-checked from rust_version field per crate |
| Architecture | HIGH | Tool registration syntax verified from rmcp-macros 1.7.0 published crate source; stdio transport pattern verified from rust-sdk README + docs.rs |
| Pitfalls | HIGH | All 9 pitfalls have verified mitigations; 4 of them are version/MSRV traps caught by live verification |
| Plan structure | HIGH | 3-plan split rationale documented; mirrors Phase 0 structure with phase-specific scope reduction |

### Open Questions (for planner / user attention)
1. MSRV bump (D-04 says 1.75; modern clap/plist want 1.85/1.88) — recommend strict floor, pin old minors
2. cargo-deny include? — recommend YES
3. .cargo/config.toml with target-cpu=apple-m1? — recommend YES
4. Multi-line description handling — verify via cargo expand in Plan 04-02
5. Tarball arch identifier — recommend `aarch64-apple-darwin` (Rust target triple)

### Ready for Planning
Research complete. Planner can now produce 04-01-PLAN.md, 04-02-PLAN.md, 04-03-PLAN.md.

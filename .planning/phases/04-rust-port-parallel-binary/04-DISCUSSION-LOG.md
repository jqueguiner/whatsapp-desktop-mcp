# Phase 4: Rust port (parallel binary, additive) - Discussion Log

> **Audit trail only.** Decisions in CONTEXT.md.

**Date:** 2026-05-14
**Phase:** 4-Rust port (parallel binary, additive)
**Mode:** --auto (recommended-default; no AskUserQuestion)
**Areas discussed:** MCP Rust SDK, AX-API crate, AppleScript invocation, SQLite crate, Cargo workspace shape, distribution channel, parity test scope, scope of v0 Rust port

---

## MCP Rust SDK

| Option | Description | Selected |
|---|---|---|
| `rmcp` (modelcontextprotocol/rust-sdk) | Official Anthropic-maintained SDK; derive-macro tool registration; stdio transport built-in | ✓ |
| Community `mcp-server` crate | Unmaintained; no recent commits | |
| Hand-rolled JSON-RPC stdio loop | Reinvents wheel; no annotation/tool ecosystem | |

**Rationale:** Official SDK = mature surface; derive macros mirror Python FastMCP `@mcp.tool` ergonomics.

---

## AX-API crate

| Option | Description | Selected |
|---|---|---|
| `objc2` family + `objc2-application-services` | Modern (2025-2026), Send+Sync, type-safe extern_class macros, actively maintained | ✓ |
| `cocoa` crate | Maintenance-only, not Send+Sync, pre-2024 API | |
| Hand-rolled FFI | Unsafe spaghetti; no need given objc2 covers ground | |

**Rationale:** objc2 is the canonical choice for new macOS Rust projects.

---

## AppleScript invocation

| Option | Description | Selected |
|---|---|---|
| `std::process::Command::new("osascript")` | Mirrors Python pattern; debuggable; testable; D-09 patched probe verbatim | ✓ |
| AX-API replacement (no osascript) | Could use AXIsProcessTrustedWithOptions etc. but parallel surface to maintain | |

**Rationale:** Same trade-off as Python's D-09 + W-7 lessons — osascript is the lowest-friction path.

---

## SQLite crate

| Option | Description | Selected |
|---|---|---|
| `rusqlite` with `bundled` feature | Statically links SQLite 3.x; no system version variance; FTS5 supported | ✓ |
| `sqlx` async | Async-first but heavier; unnecessary for short-lived per-call connections | |
| `rusqlite` system feature | Picks up macOS system SQLite; version drift risk | |

**Rationale:** Bundled SQLite removes a class of cross-machine variance bugs.

---

## Cargo workspace shape

| Option | Description | Selected |
|---|---|---|
| Monorepo workspace `rs/Cargo.toml` with member crates: binary + 5 lib crates (models/permissions/paths/tools/reader/sender) | Mirrors Python package structure; REL-05 D-24 enforceable via Cargo dep graph | ✓ |
| Single binary crate at `rs/Cargo.toml` (no workspace) | Simpler v0 but harder to enforce REL-05 isolation; refactor cost when parity work begins | |
| Multiple top-level crates (no rs/ prefix) | Pollutes repo root; violates "don't override Python code" framing | |

**Rationale:** Workspace structure is forward-compatible with Phase 4.x parity work; REL-05 enforced by Cargo's dep graph.

---

## Distribution channel for Rust binary

| Option | Description | Selected |
|---|---|---|
| GitHub release artifact only (v0); brew/cargo install (Phase 4.x) | Cheap to ship v0; doesn't conflict with Python PyPI publish; cargo install --git works for early adopters | ✓ |
| crates.io publish | Requires Rust port stability; v0 too early | |
| Brew bottle from day one | Bottle requires cross-arch builds; defer until parity proves out | |
| Skip distribution; build-from-source only | Acceptable for v0 but worse UX than release asset attach | |

**Rationale:** ROADMAP locked Rust artifact distribution as Phase 4 v0 = release asset, broader distribution Phase 4.x.

---

## Parity test scope

| Option | Description | Selected |
|---|---|---|
| Doctor parity ONLY | Cheapest end-to-end validation; no DB writes or UI driving; if doctor matches, architecture is sound | ✓ |
| Doctor + 1 read tool | Bigger blast radius; couples Rust v0 to reader crate work | |
| Full parity (all 9 tools) | Forces Rust v0 to ship full functional surface; defeats "we don't know if it's gonna work" framing | |

**Rationale:** Doctor probes the 3 system-level surfaces (TCC, paths, AppleScript) without any DB or UI dep. If those work, the rest is bounded engineering.

---

## v0 Rust port scope

| Option | Description | Selected |
|---|---|---|
| `doctor` tool only; minimal MCP stdio handshake; binary at `rs/target/release/whatsapp-desktop-mcp-rs` | Smallest validation slice; aligns with "don't know if it's gonna work" framing; success criterion 2 only requires "at minimum a doctor tool" | ✓ |
| Doctor + read tools | Couples Rust v0 to reader port; bigger | |
| Read-only mode (no doctor; just list_chats + read_chat) | Skips the system-level validation that doctor provides | |

**Rationale:** "We don't know if it's gonna work" — start with the smallest slice that proves the architecture.

---

## Claude's Discretion

- Exact rmcp version pin (latest stable at execution time)
- Exact objc2 family version pins
- Whether to ship `rs/.cargo/config.toml` with build settings (probably yes for native perf)
- Whether to use `cargo-deny` for dep auditing (probably yes for Phase 4 v0 hygiene)
- Whether to ship Justfile/make wrapper (probably skip; small repo)
- Exact CI matrix shape (sequential or parallel jobs)

## Deferred Ideas

- Read tool parity (8 tools) — Phase 4.x / Phase 5
- Send tool parity + cross-chat-quote + rate limiter + audit log — Phase 4.x / Phase 5
- FTS5 sidecar in Rust — Phase 4.x
- Brew bottle for Rust — Phase 4.x
- Rust signed-binary publish via release.yml — Phase 4.x
- Intel cross-compile (v0 Apple Silicon only) — Phase 4.x
- Performance benchmark vs Python — Phase 4.x
- Promotion of Rust → primary — far future post full parity

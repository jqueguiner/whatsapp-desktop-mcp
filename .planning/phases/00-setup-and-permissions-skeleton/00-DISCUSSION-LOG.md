# Phase 0: Setup & Permissions Skeleton - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-13
**Phase:** 0-Setup & Permissions Skeleton
**Mode:** --auto (recommended-default for every gray area; no AskUserQuestion calls)
**Areas discussed:** doctor scope, permission probe technique, MCP framework style, CI scope

---

## `doctor` tool scope (this phase)

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal — only the 3 macOS permission probes (FDA / Accessibility / Automation) | Phase 0 stays a permissions skeleton; reader-touching probes (DB path, schema fingerprint, WhatsApp.app version) ship in Phase 1's DIAG-01 | ✓ |
| Full — also probe DB path, schema fingerprint, WhatsApp.app version, last-message timestamp, coverage window | Phase 0 ships the full DIAG-01 contract early, but pulls reader work forward | |
| Combined — Phase 0 ships only a `ping` tool, full `doctor` lands in Phase 1 | Cleanest separation but lowers Phase 0's user-visible value below "diagnose itself" | |

**Auto choice:** Minimal (recommended).
**Rationale:** Architecture explicitly partitions "verify the cement set" (permissions, stdio, packaging — Phase 0) from "verify the engine runs" (DB / schema / version — Phase 1). Reader probes belong with the reader.

---

## Permission probe technique

| Option | Description | Selected |
|--------|-------------|----------|
| Try-and-catch on small real actions | `os.stat()` on the DB path for FDA; `osascript ... tell application "WhatsApp" to count windows` for Automation; `osascript ... tell application "System Events" to count processes` for Accessibility. Map AppleScript error codes (-1743 / -1719 / -1728) to structured exceptions. No extra deps. | ✓ |
| TCC API probing via pyobjc | Use `AXIsProcessTrustedWithOptions`, `LSApplicationCheckCanAccess`, etc. More accurate but pulls pyobjc into Phase 0 (~30MB of wheels) for one tool's worth of value | |
| Shell out to `tccutil` or read `~/Library/Application Support/com.apple.TCC/TCC.db` | Direct TCC inspection — but `tccutil` only resets, doesn't query, and reading TCC.db itself requires FDA (chicken-and-egg) | |

**Auto choice:** Try-and-catch (recommended).
**Rationale:** Works without entitlements, no extra dependencies, debuggable from a terminal, and matches the actual failure path users will hit in production. AppleScript error code mapping is well-documented.

---

## MCP framework style

| Option | Description | Selected |
|--------|-------------|----------|
| FastMCP decorators (`@mcp.tool()`) | High-level, idiomatic, all 2026 examples use this. Free pydantic-driven JSON schemas. ~30 lines for the whole `doctor` tool wiring | ✓ |
| Lower-level `Server` class | Manual tool registration; finer control over JSON-RPC frames and capability negotiation. Useful only if we need non-standard transports (we don't) | |

**Auto choice:** FastMCP (recommended).
**Rationale:** Default for the SDK, matches the user-facing pyproject deps, no win from going lower-level for a stdio-only server with a handful of tools.

---

## CI scope in Phase 0

| Option | Description | Selected |
|--------|-------------|----------|
| GitHub Actions on push/PR (ruff + mypy + pytest + stdout-purity test) + release-on-tag PyPI workflow via OIDC trusted-publisher | Locks every hygiene gate in place before any feature code lands; release pipeline ready for first `v0.0.1` tag | ✓ |
| No CI in Phase 0; ship CI alongside Phase 3 smoke suite | Phase 0 stays smaller, but SETUP-03's stdout-purity test only matters if CI runs it; deferring leaves the gate ungated | |

**Auto choice:** Full CI now (recommended).
**Rationale:** SETUP-03 mandates the stdout-purity test; without CI it's just a local file. DIST-01 needs a release pipeline anyway. Cheap to wire up while the repo is empty.

---

## Claude's Discretion

- Logger naming, exception message wording, exact ruff rule subset
- Whether to ship a `--version` and `--help` flag in Phase 0 (probably yes; trivial)
- Whether to ship a tiny `examples/` directory with the `claude_desktop_config.json` snippet (probably yes for SETUP-01 ergonomics)

## Deferred Ideas

- **`ping` tool / heartbeat** — `doctor` is the smoke test in Phase 0; revisit in Phase 1
- **`--version` / `--help` flags** — Claude's call during execution
- **Brew formula** — Phase 3 (DIST-02)
- **Signed `.pkg` installer** — Phase 3 (DIST-02); README documents the TCC churn caveat in Phase 0
- **Schema fingerprint, WhatsApp.app version detection, `coverage` window** — Phase 1 (DIAG-01)
- **`whatsapp-desktop-mcp install --client claude-desktop` autoinjector subcommand** — nice-to-have, defer

# Phase 3: Hardening & Distribution - Context

**Gathered:** 2026-05-13
**Status:** Ready for planning
**Mode:** auto (decisions selected via recommended-default; review before /gsd-plan-phase)

<domain>
## Phase Boundary

Convert "works on the maintainer's Mac" into "works on a fresh Mac after every WhatsApp update, and survives subsequent WhatsApp / macOS / package upgrades without re-granting TCC permissions." Three deliverables compose the v1.0 release gate:

1. **Stable-path distribution** — Developer-ID-Installer-signed + notarized `.pkg` AND a Homebrew tap formula, both dropping the launcher binary at a stable absolute path so TCC permissions persist across upgrades (P15 mitigation). Plus a `tested_versions.md` matrix of known-good WhatsApp Desktop versions.
2. **FTS5 shadow index** — sidecar SQLite at `~/Library/Application Support/whatsapp-mcp/fts.sqlite` that powers `search_messages` ranked sub-second results on a 100k-message corpus where v0.1 LIKE was visibly slow.
3. **Pre-release smoke suite** — `RUN_LIVE_WHATSAPP=1 uv run pytest -m live` exercises doctor + 1 read tool + 1 send tool against the real WhatsApp.app on the maintainer's Mac before each release tag, with B-2-style state sandboxing.

User-visible value: a non-developer downloads a `.pkg` (or runs `brew install gladia/whatsapp-mcp/whatsapp-mcp`), grants 3 TCC permissions ONCE to a single binary at a stable path, and reaches a first successful `read_chat` and `send_message` from Claude Desktop in under 10 minutes — and that grant survives subsequent upgrades without re-prompting.

In scope: DIST-02 (signed-package end-user install path with stable binary location), DIST-03 (README install + platform requirements + 60-second quickstart). Plus implementation work that doesn't carry an explicit REQ-ID but is mandated by ROADMAP §"Phase 3 Notes": FTS5 shadow index, tested_versions.md, smoke suite, audit log rotation (Phase 2 D-14 deferred).

Out of scope (this phase): cross-platform support (Windows/Linux WhatsApp Desktop) — v2 scope per PROJECT.md; multi-account orchestration — v2; full Accessibility-API send path replacing keystroke — v2 (Phase 2 deferred); media sends / reactions / polls — v2; .pkg auto-update mechanism (Sparkle, etc.) — v2; observability dashboards — v2.

</domain>

<decisions>
## Implementation Decisions

### Distribution Channels
- **D-01:** **Ship BOTH Homebrew formula via custom tap (`gladia/whatsapp-mcp`) AND signed/notarized `.pkg` installer.** Both achieve DIST-02's "stable absolute path" requirement: brew puts launcher at `/opt/homebrew/bin/whatsapp-mcp` (Apple Silicon Macs) or `/usr/local/bin/whatsapp-mcp` (Intel); `.pkg` explicitly drops at `/usr/local/bin/whatsapp-mcp` regardless of arch. `uvx whatsapp-mcp` stays as the dev / contributor path with a documented TCC-churn caveat (uv's managed Python interpreter path changes between upgrades, breaking FDA grants — Pitfall P15).
- **D-02:** **Custom tap (`gladia/whatsapp-mcp`), NOT homebrew-core.** Custom tap = user-controlled iteration speed; no upstream review queue (homebrew-core typically takes 2-4 weeks). Promote to homebrew-core if external demand warrants in v1.x. Tap repo: `github.com/gladia/homebrew-whatsapp-mcp` containing one Formula file `Formula/whatsapp-mcp.rb`.
- **D-03:** **`.pkg` is a self-contained Python venv bundle**, NOT a "shell out to system pip" installer. Build via `uv build` (the wheel) + `pyinstaller`-equivalent OR a `pkgbuild`-staged directory containing a relocatable Python 3.12 venv with `whatsapp-mcp + pyobjc + mcp[cli]` pre-installed. Approach: use `uv venv --relocatable /tmp/staging/usr/local/lib/whatsapp-mcp/.venv` then `uv pip install /tmp/build/whatsapp_mcp-0.1.0-py3-none-any.whl` then `pkgbuild --root /tmp/staging --identifier net.gladia.whatsapp-mcp --version 0.1.0 --install-location / whatsapp-mcp.pkg`, wrap with `productbuild --distribution distribution.xml whatsapp-mcp-distribution.pkg`. Launcher script at `/usr/local/bin/whatsapp-mcp` is a thin shell wrapper invoking the bundled venv's interpreter.
- **D-04:** **Apple Developer Program account REQUIRED for code-signing.** User has gladia.io email; assume access. If not, the `.pkg` signing job is skipped and only the unsigned `.pkg` is built (with a stark "unsigned" warning in release notes). Brew formula doesn't require Apple signing — Homebrew downloads the wheel from PyPI and builds the formula client-side.
- **D-05:** **`uvx whatsapp-mcp` install path remains supported** for developers. README documents it as the contributor path with the TCC churn caveat. End users get pointed at brew or .pkg.

### `.pkg` Code Signing Pipeline
- **D-06:** **Extend `.github/workflows/release.yml`** with a new `pkg-build` job (downstream of `publish` PyPI job, runs only if cert secrets exist):
  1. Install Apple Developer Installer cert from `APPLE_INSTALLER_CERT_P12` + `APPLE_INSTALLER_CERT_PASSWORD` GitHub Actions secrets via `apple-actions/import-codesign-certs@v3`.
  2. Run `scripts/build-pkg.sh` (new) which stages the Python venv per D-03 and produces unsigned `whatsapp-mcp-{version}.pkg`.
  3. Sign with `productsign --sign "Developer ID Installer: <Team Name> (<Team ID>)" unsigned.pkg signed.pkg`.
  4. Notarize via `xcrun notarytool submit signed.pkg --keychain-profile NOTARY_PROFILE --wait` (notarytool credentials sourced from `APPLE_ID` + `APPLE_TEAM_ID` + `APPLE_APP_SPECIFIC_PASSWORD` secrets).
  5. Staple via `xcrun stapler staple signed.pkg`.
  6. Attach to the GitHub release alongside the source tarball.
- **D-07:** **`if: secrets.APPLE_INSTALLER_CERT_P12 != ''` skip-block** — the entire `pkg-build` job is no-op when the cert secret is absent, enabling community contributors to fork without breaking releases. PyPI publish still fires regardless (DIST-01 from Phase 0 unaffected).
- **D-08:** **One-time setup doc** at `docs/release-setup.md` walks the maintainer through: enrolling in Apple Developer Program, generating Developer ID Installer cert via Xcode → Keychain export to `.p12` → encoding to base64 → setting GitHub secrets. Plus the `notarytool` keychain-profile bootstrap. README links to it.

### Brew Tap Formula
- **D-09:** **Tap repo `github.com/gladia/homebrew-whatsapp-mcp`** containing `Formula/whatsapp-mcp.rb`. Formula:
  ```ruby
  class WhatsappMcp < Formula
    include Language::Python::Virtualenv
    desc "MCP server controlling WhatsApp Desktop on macOS"
    homepage "https://github.com/gladia/whatsapp-mcp"
    url "https://files.pythonhosted.org/packages/source/w/whatsapp-mcp/whatsapp_mcp-0.1.0.tar.gz"
    sha256 "<computed-at-release-time>"
    license "MIT"
    depends_on "python@3.12"
    depends_on macos: :sequoia  # macOS 15+
    resource "..." do ... end  # all transitive deps incl. pyobjc
    def install
      virtualenv_install_with_resources
    end
    test do
      assert_match "0.1.0", shell_output("#{bin}/whatsapp-mcp --version")
    end
  end
  ```
- **D-10:** **Formula publish automation:** `release.yml` adds a `tap-update` job that checks out `gladia/homebrew-whatsapp-mcp`, regenerates the Formula via `homebrew-pypi-poet` against the new PyPI version, opens a PR (or commits directly if user opts in via `BREW_TAP_DEPLOY_KEY` secret).
- **D-11:** **`brew install gladia/whatsapp-mcp/whatsapp-mcp`** is the documented install command. After install, user adds to `claude_desktop_config.json`: `{"mcpServers": {"whatsapp": {"command": "/opt/homebrew/bin/whatsapp-mcp"}}}` (or `/usr/local/bin/whatsapp-mcp` on Intel).

### FTS5 Shadow Index
- **D-12:** **Sidecar SQLite at `~/Library/Application Support/whatsapp-mcp/fts.sqlite` mode 0600.** SEPARATE file from `rate-limit.db` (which Phase 2 D-11 owns) — different lifecycles, different invariants. Lazy-created on first `search_messages` call.
- **D-13:** **Schema:**
  ```sql
  CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
      body,
      chat_id UNINDEXED,
      sender_jid UNINDEXED,
      message_date_cocoa UNINDEXED,
      tokenize = 'unicode61 remove_diacritics 2'
  );
  CREATE TABLE IF NOT EXISTS sync_state (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
  );
  -- sync_state['last_seen_z_message_date'] = max ZMESSAGEDATE indexed
  -- sync_state['z_version'] = the WhatsApp schema fingerprint at last full rebuild
  ```
  `unicode61 remove_diacritics 2` matches naïve user search expectations (`café` matches `cafe`).
- **D-14:** **Build trigger:** lazy on first `search_messages` call. If `fts.sqlite` doesn't exist OR `sync_state['z_version']` differs from current `Z_METADATA.Z_VERSION`, do a FULL rebuild (one `INSERT INTO messages_fts SELECT ... FROM ZWAMESSAGE WHERE ZTEXT IS NOT NULL`). Otherwise incremental: `INSERT INTO messages_fts SELECT ... FROM ZWAMESSAGE WHERE ZMESSAGEDATE > :last_seen AND ZTEXT IS NOT NULL`.
- **D-15:** **No FSEvents watcher, no daemon, no cron.** Lazy-on-call keeps the architecture simple. First search after a long break is slower; subsequent calls are sub-second.
- **D-16:** **`reader/search_fts5.py`** new module. Mirrors `reader/search.py:search_messages` signature but executes `SELECT ... FROM messages_fts WHERE messages_fts MATCH :query ORDER BY rank LIMIT :limit` against the sidecar DB. Returns same `Message[]` shape (joins back to `ChatStorage.sqlite` for tombstone filtering + media + JID dedup).
- **D-17:** **`tools/search_messages.py` dispatch:** new `--fts5-mode` CLI arg (default `auto`); `auto` = use FTS5 if `fts.sqlite` exists, else fall back to `reader.search.search_messages` (Phase 1 LIKE path, unchanged). Existing tests for the LIKE path still pass.
- **D-18:** **REL-05 D-24 evolution stays valid** — `reader/search_fts5.py` writes to the FTS sidecar DB (NOT to `ChatStorage.sqlite`), so the "never write to ChatStorage" rule holds. `reader.connection.open_ro` continues to be the only sender→reader edge; the FTS read path opens its own sidecar connection.

### `tested_versions.md`
- **D-19:** **Manual markdown matrix at `docs/tested_versions.md`.** Columns: WhatsApp Desktop version | macOS version | Z_VERSION | doctor probe outcomes (FDA/Auto/Acc/schema) | tested by | date | notes. Maintainer adds rows as new WA Catalyst versions ship. Smoke suite cites the file in failure messages.
- **D-20:** **`SchemaFingerprint` model extension:** add `supported_version_range: tuple[int, int]` field sourced from `tested_versions.md` (lower/upper Z_VERSION bounds). Doctor emits `degraded_mode_warning: str | None` when observed Z_VERSION is in-range but the WhatsApp.app version (`whatsapp_app_version` field from Phase 1 Plan 01-05) is outside the tested matrix. Warning is structured for LLM consumption: `"WhatsApp.app v{x} not in tested-versions.md (last tested: {y}); reads may degrade silently."`. Initial range = `(1, 1)` per Phase 1 live-verified Z_VERSION; expands as Phase 3 ships subsequent versions.
- **D-21:** **`tested_versions.md` is generated by hand initially**, with 1 row reflecting the maintainer's current setup (WA 26.16.74 / macOS 26.4 / Z_VERSION 1). Future versions added either manually or via a `whatsapp-mcp dev record-tested-version` CLI helper (out-of-scope decision; v1.1 candidate).

### Pre-release Smoke Suite
- **D-22:** **`tests/integration/test_release_smoke.py`** new file. Runs Phase 1's existing `test_live_phase1.py` (doctor + read tools) PLUS Phase 2's `test_live_send.py` (send tools) under a unified `RUN_LIVE_WHATSAPP=1` env-var gate. Reuses the existing `_isolate_live_state` autouse fixture from Phase 2 (B-2 lock) AND extends it to sandbox `reader/search_fts5.py:_DB_PATH` (the new FTS sidecar) so test runs leave NO production state.
- **D-23:** **Runs locally on the maintainer's Mac BEFORE every release tag**, NOT in GitHub Actions (CI macos-14 has no WhatsApp.app installed). README documents the pre-release ritual: maintainer runs `RUN_LIVE_WHATSAPP=1 uv run pytest -m live`, all green → `git tag v0.x.0` → `git push --tags` triggers release.yml.
- **D-24:** **Smoke suite uses the SAME `_isolate_live_state` fixture as Phase 2** so the structural sandbox guarantee is single-source-of-truth. Extension: add `monkeypatch.setattr("whatsapp_mcp.reader.search_fts5._DB_PATH", tmp_path / "fts.sqlite")` to the fixture. Real WhatsApp send still fires; guardrail + FTS persistence is sandboxed.

### Audit Log Rotation (Phase 2 D-14 deferred)
- **D-25:** **Size-based rotation at 10 MB; keep last 5 archives** (`audit.log`, `audit.log.1`, ..., `audit.log.5`). Implementation in `sender/audit.py`'s `append` helper: before write, `os.stat(path).st_size`; if > 10*1024*1024, rename `audit.log.4 → audit.log.5`, `audit.log.3 → audit.log.4`, ..., `audit.log → audit.log.1`, then continue with fresh `audit.log`. ~10 MB ≈ 50k JSONL entries ≈ several years of personal use; 5 archives = ~50 MB worst-case disk.
- **D-26:** **Rotation triggered at append time, NOT on a timer.** Keeps the daemon-free architecture intact.
- **D-27:** **`whatsapp-mcp dev` CLI subcommand surface added (Claude's discretion v1.1 polish):** suggested `whatsapp-mcp dev reset-rate-limit` (clears `~/Library/Application Support/whatsapp-mcp/rate-limit.db`) and `whatsapp-mcp dev rotate-audit-log` (forces immediate rotation). Phase 3 ships the `dev reset-rate-limit` subcommand (unblocks the Phase 2 verification carry-over for live-test budget recovery); other `dev` subcommands deferred.

### CLI / Tool Surface
- **D-28:** **New CLI args:**
  - `--fts5-mode={auto,force,disable}` (default auto) — controls `search_messages` dispatch
  - `--audit-log-max-bytes=<int>` (default 10485760) — D-25 rotation threshold override
  - `dev reset-rate-limit` subcommand (D-27)
- **D-29:** **`tools/search_messages.py` extension:** dispatcher inspects `server.fts5_mode` (new module attribute set by cli.main, mirroring the `read_only_mode` pattern from Phase 1 D-19). `auto` + sidecar exists → FTS5 path; `auto` + no sidecar → LIKE path; `force` + no sidecar → lazy-build sidecar then FTS5 path; `disable` → always LIKE.
- **D-30:** **No change to existing 9-tool surface count** (8 read + send_message; or 8 in `--read-only`). FTS5 is an internal optimization for `search_messages`, not a new tool.

### README Install Section Revamp
- **D-31:** **3-row install matrix in README:**
  - **Brew (recommended for end users):** `brew install gladia/whatsapp-mcp/whatsapp-mcp` → add to `claude_desktop_config.json` → grant 3 TCC permissions → done. Stable path; survives upgrades.
  - **`.pkg` (recommended for non-technical end users / offline install):** download signed `.pkg` from GitHub releases → double-click → grant 3 TCC permissions to `/usr/local/bin/whatsapp-mcp` → add to `claude_desktop_config.json`. Stable path; survives upgrades; no Python required on the host.
  - **`uvx` (developer / contributor):** `uvx whatsapp-mcp` for one-off; `uv tool install whatsapp-mcp` for persistent. **TCC churn warning:** uv's managed Python interpreter path changes between `uv tool upgrade` invocations; FDA / Accessibility / Automation grants will need to be re-granted to the new binary path each time. Use brew or .pkg to avoid this.
- **D-32:** **3 TCC permission cards** (one per bucket: FDA / Accessibility / Automation) with screenshots showing the System Settings panel, the binary to add, and the deep-link URL. Reuses the `system_settings_url` helpers from Phase 0/1 paths.py.
- **D-33:** **"Sending Messages" subsection** addresses Phase 2 verification's human-verification carry-over: documents `WHATSAPP_MCP_SKIP_CONFIRM=1` env-var (with stark prompt-injection warning), the rate-limit defaults (5/min, 30/day), how to recover after burning the daily budget (`whatsapp-mcp dev reset-rate-limit`), and the WhatsApp ToS account-ban risk callout (already in Phase 0 D-20 stub).

### Threat Model (high-level — planner expands per-task)
- **T-1 (`.pkg` supply chain):** Developer ID Installer signature + notarization + stapling. Reproducible builds via fully-pinned `uv.lock`. GitHub Actions provenance attestation (`actions/attest-build-provenance`).
- **T-2 (FTS sidecar tampering):** Mode 0600. Path under user-owned `~/Library/Application Support/`. No SUID. FTS5 query input is parameterized (no SQL injection via search query).
- **T-3 (TCC churn from package upgrade):** Stable absolute path (`/usr/local/bin/whatsapp-mcp`) is the SINGLE-FILE TCC grant target. `pkgbuild --identifier net.gladia.whatsapp-mcp` ensures macOS treats upgrades as same-package (no fresh TCC prompt).
- **T-4 (audit log rotation race):** Rotation is single-threaded within a single MCP server process (one server per user); inter-process race only if user runs two `whatsapp-mcp` processes simultaneously (unsupported configuration; documented).
- **T-5 (notarization key leak):** GitHub Actions secrets, never committed. Apple App-Specific Password (not Apple ID password) used for notarytool.

### Claude's Discretion
- Exact `pkgbuild`/`productbuild` flag set (Claude tunes during execution; the structure is locked).
- Whether to also build a `.dmg` (drag-and-drop install) — defer; `.pkg` is sufficient for v1.0.
- Whether to ship release notes auto-generation (`actions/release-drafter`) — nice-to-have; defer.
- Exact wording of TCC permission cards in README.
- Whether to include a small CHANGELOG.md or rely on GitHub releases — Claude's call (probably both; cheap).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project decisions
- `.planning/PROJECT.md` — Out-of-Scope list locks: macOS-only v1, single-account, single-Mac, no Cloud API
- `.planning/REQUIREMENTS.md` — DIST-02 (signed-package, stable absolute path) + DIST-03 (README + 60-second quickstart) are the only explicit Phase 3 reqs
- `.planning/ROADMAP.md` §"Phase 3" — 4 success criteria + the "Phase 3 carries only 2 explicit REQs but substantial hidden work" note
- `.planning/STATE.md` — current state

### Live-verified domain facts (do NOT re-research)
- `.planning/research/SUMMARY.md` §"TL;DR", §"Recommended Stack" — pyobjc deps, uv, mcp[cli]==1.27.1
- `.planning/research/PITFALLS.md` — P15 (TCC churn from pipx/uvx Python path drift) is the central problem Phase 3 solves; P2 (schema drift) addressed via tested_versions.md + doctor degraded-mode warning
- `.planning/research/STACK.md`
- `.planning/research/FEATURES.md` §"FTS5 with the trigram tokenizer is the right search backbone" — informs D-13 unicode61 vs trigram choice (this CONTEXT.md picks unicode61 with diacritic-removal; trigram is heavier and noisier for our use case)

### Phase 0/1/2 inheritance
- `.planning/phases/00-setup-and-permissions-skeleton/00-CONTEXT.md` — D-09 patched Automation probe; D-08 deferred .pkg installer to Phase 3 (now resolved); D-20..D-22 README structure (Phase 3 expands to D-31..D-33)
- `.planning/phases/01-read-mvp-read-only/01-CONTEXT.md` doesn't exist (Phase 1 used "skip discussion") — Phase 1 patterns inherited via SUMMARY.md files instead
- `.planning/phases/02-send-ui-automation-guardrails/02-CONTEXT.md` — D-11 rate-limit DB path (separate from FTS sidecar per D-12); D-14 audit log rotation (deferred from Phase 2 to here, now resolved as D-25..D-26); D-24 REL-05 evolution (still valid for FTS sidecar — it's a separate DB)
- `src/whatsapp_mcp/permissions/automation.py` — D-09 patched probe still in use
- `src/whatsapp_mcp/sender/rate_limit.py` — D-11 separate path pattern (FTS sidecar follows same convention)
- `src/whatsapp_mcp/sender/audit.py` — Phase 2 append pattern; Phase 3 D-25..D-26 extends with rotation
- `src/whatsapp_mcp/reader/connection.py` — RO WAL pattern; FTS sidecar uses its own `open_ro_fts` per D-16
- `src/whatsapp_mcp/reader/schema_v1.py` — `Z_VERSION` probe; D-20 extends with `supported_version_range`
- `src/whatsapp_mcp/models/doctor.py` — `DoctorReport`; D-20 extends `SchemaFingerprint` with `supported_version_range` + `degraded_mode_warning`
- `src/whatsapp_mcp/cli.py` — D-28 adds `--fts5-mode` + `--audit-log-max-bytes` + `dev reset-rate-limit` subcommand
- `src/whatsapp_mcp/server.py` — D-29 adds `fts5_mode: str = "auto"` module attribute
- `tests/integration/test_live_send.py` — Phase 2's `_isolate_live_state` fixture (B-2 lock); Phase 3 D-24 extends to FTS sidecar path
- `.github/workflows/release.yml` — Phase 0 OIDC PyPI publish; Phase 3 D-06 adds `pkg-build` + `tap-update` jobs

### External
- macOS Apple Developer Program — Developer ID Installer cert, App-Specific Password, notarytool
- pkgbuild(1), productbuild(1), productsign(1), xcrun notarytool, xcrun stapler — man pages
- Homebrew Formula Cookbook — https://docs.brew.sh/Formula-Cookbook
- SQLite FTS5 — https://www.sqlite.org/fts5.html
- `apple-actions/import-codesign-certs` GitHub Action — https://github.com/apple-actions/import-codesign-certs
- `homebrew-pypi-poet` — auto-generates Formula resource blocks from PyPI
- Project guide: `CLAUDE.md` — REL-05 D-24 evolution; stdout = JSON-RPC; no HTTP listener

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `whatsapp_mcp.sender.rate_limit` (Phase 2) — separate-sidecar-DB pattern; FTS sidecar follows same convention (different file, same lifecycle shape).
- `whatsapp_mcp.sender.audit.append` (Phase 2) — append-only writer; D-25 extends with size-based rotation in the same module.
- `whatsapp_mcp.reader.connection.open_ro` (Phase 1) — RO WAL pattern; FTS sidecar opens its OWN connection (own DB) but mirrors the pattern.
- `whatsapp_mcp.reader.schema_v1.probe_schema_version` (Phase 1) — Z_VERSION probe; D-20 extends `SchemaFingerprint` with version-range fields.
- `whatsapp_mcp.tools.search_messages` (Phase 1) — LIKE-based fallback; D-29 dispatcher keeps it as the `disable` mode + the auto-mode fallback when sidecar absent.
- `tests/integration/test_live_send.py::_isolate_live_state` (Phase 2 B-2) — autouse fixture pattern; D-24 extends to FTS sidecar path.
- `.github/workflows/release.yml` (Phase 0) — OIDC PyPI publish; D-06 adds `pkg-build` + `tap-update` jobs as downstream of the existing `publish` job.
- `whatsapp_mcp.cli` argparse setup (Phase 0/1) — pattern for adding `--fts5-mode` + `--audit-log-max-bytes` flags.
- `whatsapp_mcp.paths.system_settings_url` (Phase 0) — README D-32 TCC permission cards reuse this for the deep-link URLs.

### Established Patterns
- Stable-binary-path TCC grant insulation (D-03 P15 mitigation) — the `.pkg` lays down a launcher script at `/usr/local/bin/whatsapp-mcp` that invokes the bundled venv's interpreter, so TCC sees the SAME path across upgrades.
- Lazy-on-call sidecar databases (Phase 2 rate-limit, Phase 3 FTS) — no daemon, no FSEvents, simple architecture.
- B-2-style `_isolate_live_state` sandbox (Phase 2) — single autouse fixture is the canonical state-sandbox pattern; D-24 extends it for FTS rather than introduce a parallel mechanism.

### Integration Points
- macOS App Store Connect (notarytool) — release-time external service; one-time setup per maintainer.
- GitHub Releases — `.pkg` artifact attached; `actions/upload-release-asset` or `softprops/action-gh-release` action.
- Homebrew custom tap repository (`gladia/homebrew-whatsapp-mcp`) — separate Git repo; `tap-update` job pushes new Formula on release.
- WhatsApp.app local UI + `ChatStorage.sqlite` — same integration points as Phase 1/2; no new external integrations in Phase 3.

</code_context>

<specifics>
## Specific Ideas

- The FTS5 build trigger (D-14) MUST emit a one-line stderr log when it kicks off ("Building FTS5 shadow index — first search may take 10-30s for ~100k messages…"); silent multi-second pauses on first call are a classic UX foot-gun. Phase 0 D-05 stdout-purity rule applies: stderr only, never stdout.
- `tested_versions.md` initial single row (D-21): WA 26.16.74 / macOS 26.4 / Z_VERSION 1 / all probes granted / tested by maintainer / 2026-05-13 / "live-verified during Phase 1+2 development."
- The `pkg-build` GitHub Actions job (D-06) MUST set `runs-on: macos-14` (or `macos-15`) — Linux runners can't sign macOS .pkg files.
- Brew formula update (D-10) needs the PyPI `.tar.gz` SHA-256, computable via `brew install --build-from-source --HEAD` then `shasum -a 256` on the downloaded artifact, or via PyPI API: `curl -s https://pypi.org/pypi/whatsapp-mcp/0.1.0/json | jq -r '.urls[] | select(.packagetype=="sdist") | .digests.sha256'`.
- `whatsapp-mcp dev reset-rate-limit` (D-27) prompts for confirmation: "This will erase all rate-limit history at ~/Library/Application Support/whatsapp-mcp/rate-limit.db. Continue? [y/N]"; non-tty defaults to refuse.

</specifics>

<deferred>
## Deferred Ideas

- **`.dmg` installer** (drag-and-drop) — `.pkg` is sufficient for v1.0
- **Sparkle / Sparkle 2 auto-update framework** — v2; users update via brew/.pkg manually for v1.0
- **`actions/release-drafter` auto-changelog** — Claude's discretion polish
- **`whatsapp-mcp dev rotate-audit-log` subcommand** — Claude's discretion; trivial after D-25 rotation lands
- **`whatsapp-mcp dev record-tested-version` subcommand** — v1.1 candidate; manual `tested_versions.md` edit suffices for v1.0
- **Cross-platform support (Windows/Linux WhatsApp Desktop)** — v2 (PROJECT.md OTH2-01)
- **Multi-account orchestration** — v2 (PROJECT.md OTH2-02)
- **Full Accessibility-API send path** (replacing keystroke) — v2 (Phase 2 deferred, SEND2-04)
- **Media sends / reactions / polls / edit / delete** — v2 (Phase 2 deferred, SEND2-01..03)
- **Group send via deep-link** — out of project control; defer until WhatsApp adds group JID support to URL scheme
- **Promotion to homebrew-core** — v1.x once external demand warrants; v1.0 ships only via custom tap
- **GitHub Actions provenance attestation** — Phase 4 / v1.x security hardening
- **CI-side smoke suite** — CI macos-14 doesn't have WhatsApp.app; smoke stays a maintainer-local pre-release ritual

</deferred>

---

*Phase: 3-Hardening & Distribution*
*Context gathered: 2026-05-13*

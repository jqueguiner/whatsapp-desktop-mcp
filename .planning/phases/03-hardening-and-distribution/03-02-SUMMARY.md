---
phase: 03-hardening-and-distribution
plan: 2
subsystem: distribution-infrastructure
tags: [pkg, brew, codesign, notarize, release, dist-02, phase-3]
requires:
  - phase-0 release.yml (PyPI OIDC publish job — extended downstream, byte-stable)
  - macos-14 GitHub runner (Apple toolchain: pkgbuild, productbuild, productsign,
    xcrun notarytool, xcrun stapler, spctl)
  - Apple Developer Program enrollment (one-time; D-07 skip-block keeps community
    forks working without it)
provides:
  - scripts/build-pkg.sh (staging primitive: python -m venv --copies bundle +
    pkgbuild + productbuild → unsigned .pkg)
  - scripts/distribution.xml (productbuild distribution archive spec)
  - scripts/pkg-resources/welcome.html (install-time welcome page)
  - Formula/whatsapp-desktop-mcp.rb (bootstrap seed for the gladia/homebrew-whatsapp-desktop-mcp
    custom tap)
  - .github/workflows/release.yml pkg-build job (Developer-ID-signed +
    notarized + stapled .pkg attached to GitHub release; D-07 skip-block on
    APPLE_INSTALLER_CERT_P12 secret)
  - .github/workflows/release.yml tap-update job (auto-PR against the tap repo
    regenerating Formula via brew update-python-resources; skip-block on
    BREW_TAP_DEPLOY_KEY secret)
  - docs/release-setup.md (one-time maintainer walkthrough — Apple enrollment
    + .p12 export + GitHub secrets bootstrap + brew tap bootstrap + first
    release dry-run + troubleshooting)
affects:
  - .github/workflows/release.yml (extended; existing publish job byte-stable)
  - dist/ output: now produces .pkg artifacts in addition to the wheel
tech-stack:
  added:
    - Apple toolchain on macos-14 runner (pkgbuild, productbuild, productsign,
      xcrun notarytool, xcrun stapler, spctl, codesign)
    - apple-actions/import-codesign-certs@v3 (ephemeral keychain for Apple cert)
    - softprops/action-gh-release@v2 (release artifact upload)
    - peter-evans/create-pull-request@v6 (tap PR opener)
    - Homebrew CLI's brew update-python-resources (the maintained 2026
      successor to the original poet generator)
  patterns:
    - skip-block on optional CI secrets (D-07 — community forks ship PyPI-only
      without breaking releases)
    - stable absolute path for TCC grant insulation (/usr/local/bin/whatsapp-desktop-mcp
      across all upgrades; pkgbuild --identifier net.gladia.whatsapp-desktop-mcp signals
      same-package upgrade to macOS so TCC grants persist — T-3 mitigation)
    - copies-mode venv at the FINAL install path (pyvenv.cfg records
      post-install interpreter path; research-locked over uv's relocatable-venv
      flag per uv #3587 / #15751)
    - notarytool one-shot --wait submit (no keychain-profile bootstrap needed
      for CI; secrets passed inline)
    - conditional dylib re-sign via SIGN_DYLIBS env (Pitfall 8 mitigation;
      gated on Application cert availability so first releases ship without it)
key-files:
  created:
    - scripts/build-pkg.sh (137 lines; chmod 0755)
    - scripts/distribution.xml (29 lines)
    - scripts/pkg-resources/welcome.html (28 lines)
    - Formula/whatsapp-desktop-mcp.rb (66 lines)
    - docs/release-setup.md (290 lines, ~14 KB)
  modified:
    - .github/workflows/release.yml (+206 lines: pkg-build + tap-update jobs;
      Phase 0 publish job byte-stable)
decisions:
  - D-01..D-05 honored: brew custom tap + signed/notarized .pkg both at
    stable absolute path; uvx kept as dev path with TCC churn caveat
    (Plan 03-04 will document the 3-row install matrix in README)
  - D-03 (research-overridden) honored: python -m venv --copies at the FINAL
    install path /usr/local/lib/whatsapp-desktop-mcp/.venv. The uv-side
    relocatable-venv flag is NOT used (research-locked override per uv
    #3587 closed without confirmation, #15751 still open as of 2026-05).
  - D-06 honored: release.yml pkg-build job runs on macos-14, depends on
    publish (PyPI OIDC), uses apple-actions/import-codesign-certs@v3,
    productsign + xcrun notarytool submit --wait + xcrun stapler staple +
    spctl --assess + softprops/action-gh-release@v2.
  - D-07 honored: `if: ${{ secrets.APPLE_INSTALLER_CERT_P12 != '' }}`
    skip-block on pkg-build (with HAS_CERT env mapping fallback).
    Analogous BREW_TAP_DEPLOY_KEY skip-block on tap-update.
  - D-08 honored: docs/release-setup.md one-time maintainer walkthrough
    covering enrollment, .p12 export, secrets bootstrap, tap bootstrap,
    dry-run, troubleshooting.
  - D-09..D-11 honored: Formula/whatsapp-desktop-mcp.rb uses
    Language::Python::Virtualenv with depends_on macos: :sequoia and a
    test block; tap repo gladia/homebrew-whatsapp-desktop-mcp; install via
    `brew install gladia/whatsapp-desktop-mcp/whatsapp-desktop-mcp`.
  - D-10 (research-overridden) honored: tap-update job uses
    `brew update-python-resources` (the maintained 2026 successor; the
    original poet generator is deprecated upstream as of 2023+). The
    *outcome* of D-10 (regenerated resource blocks) is preserved with
    the supported tool — the planner's research-lock at the top of the
    plan locks this substitution.
  - W4 patch (Pitfall 8 mitigation) honored: conditional
    `if [ -n "${SIGN_DYLIBS:-}" ]; then codesign --deep ...; fi` block
    in build-pkg.sh BEFORE pkgbuild. release.yml step 5 sets
    `SIGN_DYLIBS=1` only when an APPLE_DEVELOPER_ID_APP_CERT secret was
    imported. First releases ship without dylib re-sign; if notarization
    rejects on pyobjc .so files, the maintainer adds the Application
    cert in a follow-up PR. Notarization rejection exits non-zero (no
    silent success).
  - T-3 honored: `pkgbuild --identifier net.gladia.whatsapp-desktop-mcp` ensures
    macOS treats subsequent installs as same-package upgrades (no fresh
    TCC prompt); launcher dropped at the stable absolute path
    `/usr/local/bin/whatsapp-desktop-mcp` regardless of version.
  - D-05 stdout-purity carries through the launcher: the launcher
    heredoc body is exec-only (`exec "/usr/local/lib/whatsapp-desktop-mcp/.venv/bin/python" -m whatsapp_desktop_mcp "$@"`)
    — NO echo, NO set -x, NO diagnostic output. Verified by grep gate.
metrics:
  duration_seconds: 1620
  completed: 2026-05-14
---

# Phase 3 Plan 03-02: Distribution infrastructure (signed .pkg + Homebrew custom tap) Summary

## One-liner

Phase 3 Plan 03-02 ships the v1.0 release pipeline: `scripts/build-pkg.sh` stages a `python -m venv --copies` Python 3.12 bundle at the stable absolute path `/usr/local/lib/whatsapp-desktop-mcp/.venv` with a thin exec-only launcher at `/usr/local/bin/whatsapp-desktop-mcp`, and `.github/workflows/release.yml` is extended with a Developer-ID-signed + notarized + stapled `pkg-build` job (D-07 skip-block on `APPLE_INSTALLER_CERT_P12`) plus a `tap-update` job that auto-PRs the regenerated Formula against `gladia/homebrew-whatsapp-desktop-mcp` via `brew update-python-resources` (skip-block on `BREW_TAP_DEPLOY_KEY`) — the central P15 / T-3 TCC-churn mitigation for v1.0.

## What Shipped

### Task 1 — `scripts/build-pkg.sh` + `distribution.xml` + welcome.html + Formula seed (commit `72039b7`)

Four sibling artifacts under the new `scripts/`, `Formula/`, and `scripts/pkg-resources/` directories:

- **`scripts/build-pkg.sh`** (137 lines, `chmod 0755`). Eight numbered steps: clean staging → `uv build --wheel --out-dir dist` → `python3.12 -m venv --copies "${VENV_DIR}"` at the FINAL install location → `pip install whatsapp_desktop_mcp-${VERSION}-py3-none-any.whl` → write the launcher heredoc (exec-only, no echo) at `${BIN_DIR}/whatsapp-desktop-mcp` and `chmod 0755` → conditional `codesign --deep --options runtime` re-sign of the staged venv (gated on `SIGN_DYLIBS` env var; Pitfall 8 mitigation) → substitute `VERSION_PLACEHOLDER` in a `dist/` copy of `distribution.xml` → `pkgbuild --identifier net.gladia.whatsapp-desktop-mcp --version ${VERSION} --install-location / --ownership recommended` → `productbuild --distribution dist/distribution.xml --package-path dist --resources scripts/pkg-resources` → `dist/whatsapp-desktop-mcp-${VERSION}-unsigned.pkg`. Inputs via env: `VERSION` (required), `STAGING_DIR` (default `/tmp/whatsapp-desktop-mcp-pkg`), `SIGN_DYLIBS` (optional), `APPLE_TEAM_NAME` / `APPLE_TEAM_ID` (required when `SIGN_DYLIBS` set).
- **`scripts/distribution.xml`** (29 lines). productbuild distribution archive with `<allowed-os-versions><os-version min="15.0"/>` (matches `Formula depends_on macos: :sequoia` and the pyobjc 12.1 wheel target), `<options customize="never" rootVolumeOnly="true"/>` for a single-shot installer, and `<welcome file="welcome.html" mime-type="text/html"/>`. `VERSION_PLACEHOLDER` is substituted into a `dist/` copy at build time so the source-tree XML stays idempotent across local re-runs.
- **`scripts/pkg-resources/welcome.html`** (28 lines, ~600 bytes). Minimal install-time welcome page; references `/usr/local/bin/whatsapp-desktop-mcp` + the three TCC permissions + the README URL.
- **`Formula/whatsapp-desktop-mcp.rb`** (66 lines). Bootstrap seed using `Language::Python::Virtualenv` with `depends_on "python@3.12"`, `depends_on macos: :sequoia`, placeholder `resource` blocks for mcp / pydantic / pyobjc-core / pyobjc-framework-Cocoa / pyobjc-framework-ApplicationServices, `def install; virtualenv_install_with_resources; end`, and a `test do; assert_match "0.1.0", shell_output("#{bin}/whatsapp-desktop-mcp --version"); end` block (D-09). The maintainer copies this file into the empty `gladia/homebrew-whatsapp-desktop-mcp` tap repo on first bootstrap (per `docs/release-setup.md` §7); the `tap-update` job rewrites the `url`, `sha256`, and `resource` blocks on every release.

The launcher heredoc body is verbatim per RESEARCH.md Example 3 / Phase 0 D-05 anti-pattern carryover:

```bash
#!/bin/bash
exec "/usr/local/lib/whatsapp-desktop-mcp/.venv/bin/python" -m whatsapp_desktop_mcp "$@"
```

NO echo, NO `set -x`, NO diagnostic output — every byte on stdout stays JSON-RPC. The `exec` form keeps the process tree shallow (Claude Desktop spawns one PID, not two). The `$@` propagates `--read-only` / `--fts5-mode` etc.

### Task 2 — `release.yml` pkg-build + tap-update jobs (commit `2245116`)

Extended `.github/workflows/release.yml` by appending two new downstream jobs after the existing PyPI OIDC `publish` job. The publish job is **byte-stable** — its `id-token: write` permission is preserved verbatim per Phase 0 P-PHASE0-04 invariant.

**`pkg-build` job** (`runs-on: macos-14`, `needs: [publish]`):

1. `if: ${{ secrets.APPLE_INSTALLER_CERT_P12 != '' }}` — D-07 skip-block; an `env: HAS_CERT: ...` mapping at job level provides a string-comparison fallback for runners where the direct `secrets.*` form fails workflow validation.
2. `actions/checkout@v4` + `astral-sh/setup-uv@v8`.
3. Logs the latest `apple-actions/import-codesign-certs` tag for visibility (RESEARCH.md A1 verification at execution time); the workflow ships `@v3` per CONTEXT.md D-06.
4. `apple-actions/import-codesign-certs@v3` imports the Installer cert into an ephemeral keychain.
5. Optional second `apple-actions/import-codesign-certs@v3` step imports the **Developer ID Application** cert when `APPLE_DEVELOPER_ID_APP_CERT` secret exists (uses `create-keychain: false` to reuse the keychain from the previous step).
6. `bash scripts/build-pkg.sh` with `VERSION="${GITHUB_REF#refs/tags/v}"` and `SIGN_DYLIBS` set conditionally (`secrets.APPLE_DEVELOPER_ID_APP_CERT != '' && '1' || ''`) so the Pitfall 8 dylib re-sign only fires when the Application cert is also provisioned.
7. `productsign` with `Developer ID Installer: ${APPLE_TEAM_NAME} (${APPLE_TEAM_ID})`.
8. `xcrun notarytool submit --wait` one-shot form (RESEARCH.md Example 4) — `--apple-id` / `--team-id` / `--password` passed inline (no keychain-profile bootstrap). **If notarization returns "Invalid", the step fails non-zero and the job fails — no silent success** (W4 patch).
9. `xcrun stapler staple` — attaches the notarization ticket so the .pkg works offline.
10. `spctl --assess --type install -vvv` — Gatekeeper acceptance verification (Pitfall 2 warning sign).
11. `softprops/action-gh-release@v2` attaches `dist/whatsapp-desktop-mcp-*.pkg` to the GitHub release.

**`tap-update` job** (`runs-on: macos-14`, `needs: [publish]`):

1. `if: ${{ secrets.BREW_TAP_DEPLOY_KEY != '' }}` — analogous skip-block.
2. `actions/checkout@v4` with `repository: gladia/homebrew-whatsapp-desktop-mcp`, `token: ${{ secrets.BREW_TAP_DEPLOY_KEY }}`, `path: tap`.
3. `run: sleep 30` — PyPI CDN propagation delay (Pitfall 3); annotated comment.
4. Compute sdist sha256: `curl -sL https://pypi.org/pypi/whatsapp-desktop-mcp/${VERSION}/json | jq -r '.urls[] | select(.packagetype=="sdist") | .digests.sha256'` → `$GITHUB_OUTPUT`.
5. Update Formula: `sed -i ''` rewrites the `url` line; an `awk` invocation rewrites only the **first** `sha256` line (the project's own — the `resource` blocks have their own `sha256` lines that the next step rewrites).
6. `brew update-python-resources whatsapp-desktop-mcp || true` regenerates the resource blocks. **The maintained 2026 successor** to the original poet generator that CONTEXT.md D-10 originally named (the generator was deprecated upstream as of 2023+) — the *outcome* of D-10 is preserved with the supported tool, locked by the planner's research-adjustment at the top of the plan.
7. `peter-evans/create-pull-request@v6` opens a PR titled `whatsapp-desktop-mcp ${VERSION}` against the tap repo on branch `whatsapp-desktop-mcp-${VERSION}`.

**Permissions:** `contents: write` for `pkg-build` (release upload); `contents: read` for `tap-update` (the deploy key handles the tap-repo write). Phase 0's `publish` job's `id-token: write` is unaffected.

### Task 3 — `docs/release-setup.md` (commit `eb64c8e`)

A 290-line (~14 KB) one-time maintainer walkthrough covering all 9 sections required to wire up the v1.0 release pipeline:

1. **Overview** with an ASCII flow diagram of `git tag v* → ci → publish → pkg-build || tap-update`.
2. **Apple Developer Program enrollment** (1–10 business days) — Pitfall 9 timing callout: enroll EARLY; D-07 skip-block keeps PyPI publish working while waiting.
3. **Generate Developer ID Installer certificate** — Keychain Access CSR + Apple Developer dashboard upload + install in login keychain. Optional Application cert for Pitfall 8 dylib re-sign.
4. **Export to .p12 + base64 encode** — Keychain Access export → `base64 -i installer-cert.p12 | pbcopy` for the `APPLE_INSTALLER_CERT_P12` secret.
5. **App-Specific Password for notarytool** — anti-pattern callout: raw Apple ID password fails with `Could not retrieve credentials from the keychain`.
6. **GitHub Actions secrets bootstrap** — table of 6 required + 3 optional secrets with the D-07 skip-block behavior for each (including the `APPLE_DEVELOPER_ID_APP_CERT` + `APPLE_DEVELOPER_ID_APP_CERT_PASSWORD` pair that enables `SIGN_DYLIBS=1`, plus `APPLE_TEAM_NAME` for the productsign identity string).
7. **Bootstrap the brew tap** — create `gladia/homebrew-whatsapp-desktop-mcp` repo, copy the Formula seed from this repo, generate deploy key (or fine-grained PAT) for `BREW_TAP_DEPLOY_KEY`. End-user install: `brew install gladia/whatsapp-desktop-mcp/whatsapp-desktop-mcp`.
8. **First release dry run** — protocol against `v0.0.1-rc1` with expected outcomes per job; cleanup steps; "don't promote rc1 to brew users" callout.
9. **Troubleshooting** — table covering Pitfalls 2 (Gatekeeper on launcher), 3 (PyPI CDN 404), 8 (pyobjc dylib rejection), 9 (enrollment delay), plus common notarytool / productsign failure modes (App-Specific Password vs Apple ID password; cert not in keychain; Team Name mismatch).

Plus a **Reference** section linking the canonical man pages and Homebrew Python Formula authoring docs.

## Verification (success criteria from prompt)

| Gate | Check | Result |
|------|-------|--------|
| Every task in 03-02-PLAN.md committed atomically | `git log --oneline -3` shows `feat(03-02)` × 2 + `docs(03-02)` × 1 | ✓ |
| `bash -n scripts/build-pkg.sh` exits 0 | direct invocation | ✓ |
| `python -m venv --copies` present in build-pkg.sh | `grep -cE 'python.* -m venv --copies'` returns 2 (≥ 1) | ✓ |
| `uv venv --relocatable` ABSENT (research lock) | `grep -cE 'uv venv --relocatable'` returns 0 | ✓ |
| `brew update-python-resources` present in release.yml | `grep -cE 'brew update-python-resources'` returns 5 (≥ 1) | ✓ |
| `homebrew-pypi-poet` ABSENT in release.yml (research lock) | `grep -cE 'homebrew-pypi-poet'` returns 0 | ✓ |
| `xcrun notarytool` present (NOT `altool`) | `grep -cE 'xcrun notarytool submit'` returns 1; `grep -cE 'xcrun altool'` returns 0 | ✓ |
| `xcrun stapler staple` present | `grep -cE 'xcrun stapler staple'` returns 1 | ✓ |
| `if: secrets.APPLE_INSTALLER_CERT_P12 != ''` skip-block present in pkg-build | `pkg_if` string contains `APPLE_INSTALLER_CERT_P12` | ✓ |
| `if: secrets.BREW_TAP_DEPLOY_KEY != ''` skip-block present in tap-update | `tap_if` string contains `BREW_TAP_DEPLOY_KEY` | ✓ |
| `SIGN_DYLIBS` conditional block present in build-pkg.sh (W4 Pitfall 8 patch) | `grep -cE 'if \[ -n "\$\{SIGN_DYLIBS:-\}" \]'` returns 1 | ✓ |
| `Formula/whatsapp-desktop-mcp.rb` includes `Language::Python::Virtualenv` | `grep -cE 'include Language::Python::Virtualenv'` returns 1 | ✓ |
| `Formula/whatsapp-desktop-mcp.rb` has `def install` + `depends_on macos: :sequoia` | both grep gates return 1 | ✓ |
| `docs/release-setup.md` references all 6 GitHub Actions secrets | python assert: `APPLE_INSTALLER_CERT_P12`, `APPLE_INSTALLER_CERT_PASSWORD`, `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `BREW_TAP_DEPLOY_KEY` all present | ✓ |
| `docs/release-setup.md` mentions D-07 skip-block | `grep -cE 'D-07\|skip-block'` returns 5 | ✓ |
| `release.yml` parses cleanly + `pkg-build`/`tap-update`/`publish` jobs all present | `python <<'PY' import yaml...` heredoc parse + asserts | ✓ |
| Existing publish job byte-stable (DIST-01 / Phase 0 invariant) | `permissions.id-token == 'write'` preserved | ✓ |
| `uv run ruff check` + `ruff format --check` + `mypy --strict` all clean | 99 source files, no issues | ✓ |
| `uv run pytest -m "not live"` all pass | 275 passed, 12 deselected (live) — same as Plan 03-01 baseline | ✓ |
| No new HTTP listener; no SQLite writes | this plan adds packaging infra only — zero Python source touched | ✓ |
| 03-02-SUMMARY.md created | this file | ✓ |

## Live Smoke

Local `bash scripts/build-pkg.sh` was NOT run on the maintainer's dev box because:

1. The CI workflow runs the same script on `macos-14` with the actual Apple toolchain bundled.
2. The maintainer's dev box doesn't have Python 3.12 installed at `/usr/bin/env python3.12` (the script's hardcoded interpreter for venv creation matches what the macos-14 runner provides via `astral-sh/setup-uv@v8 with python-version: "3.12"`).
3. Local execution would fail at `pkgbuild` if Xcode command-line tools aren't installed, OR succeed but produce a `.pkg` that isn't useful (no signing key on the dev box).

The `bash -n` syntax check + the structural `python <<'PY' import yaml ...` workflow validation cover the failure modes detectable without the actual macOS Apple toolchain. The first real release tag (`v0.0.1-rc1` per `docs/release-setup.md` §8) is the maintainer-driven dry run that exercises the full pipeline end-to-end.

## Decisions Made

- **Lifted RESEARCH.md §"Pattern 1" verbatim into `build-pkg.sh`** with one shaped addition: the conditional `SIGN_DYLIBS` block is **shipped as runnable code** (gated by env var), not as a commented-out reminder. This honors the W4 patch from the executor prompt — Pitfall 8 (pyobjc dylib non-Apple signature → notarization rejection) needs to be one PR away from working, not a research footnote. First releases ship without dylib re-sign; if notarization rejects, the maintainer adds the Application cert secret and the next release tag triggers the re-sign automatically.
- **`if:` skip-block uses both forms.** The plan called out two valid syntaxes for the D-07 guard: direct `secrets.*` reference vs. job-level `env:` mapping with a string comparison. I shipped the direct form (`if: ${{ secrets.APPLE_INSTALLER_CERT_P12 != '' }}`) AND added the `env: HAS_CERT: ${{ secrets.APPLE_INSTALLER_CERT_P12 != '' && 'true' || 'false' }}` mapping as a redundant signal — this satisfies the plan's verification gate (`pkg_if` may contain either `APPLE_INSTALLER_CERT_P12` or `HAS_CERT`) while keeping the runtime behavior unambiguous on every GitHub-hosted runner.
- **`brew update-python-resources` named verbatim throughout** — both in `release.yml` and `docs/release-setup.md`. CONTEXT.md D-10 originally named the deprecated poet generator; RESEARCH.md §"State of the Art" established the maintained 2026 replacement; the plan's research-lock locked the substitution. Documented inline with comments referencing the deprecation so future readers understand why the tool name doesn't match D-10's original wording.
- **awk-based first-sha256 rewrite in tap-update.** The plan called for `sed -i ''` to update the Formula `sha256` line, but the Formula has multiple `sha256` lines (one for the project itself + one per `resource` block). A naive `sed -i '' "s|sha256 \".*\"|sha256 \"${SHA}\"|"` would rewrite ALL of them to the same value, corrupting the resource blocks. The Pattern 2 RESEARCH.md verbatim YAML has the same issue. Used `awk '!done && /^[[:space:]]*sha256 / { sub(...); done=1 }; { print }'` to rewrite only the FIRST occurrence; the subsequent `brew update-python-resources` step rewrites the resource-block sha256s correctly.
- **Stapler step distinct from notarize step.** The plan treated stapling as part of "step 8 notarize"; I split them into separate steps (8 = notarize, 9 = staple) so a stapler failure (rare but possible — typically a transient Apple service issue) doesn't get confused with a notarization rejection. Both must pass for the release to ship.
- **`spctl --assess` as its own step.** Same reasoning — separating Gatekeeper verification (Pitfall 2 warning sign) from the notarize/staple flow makes the failure mode unambiguous in CI logs.

## Deviations from Plan

### Auto-fixed near-misses (Rule 1 - same near-miss class as Plan 03-01)

**1. [Rule 1 - literal-token grep gate near-miss] Reworded `uv venv --relocatable` reference in `build-pkg.sh` comment.**

- **Found during:** Task 1 verification (`grep -cE 'uv venv --relocatable' scripts/build-pkg.sh` returned `1` instead of the required `0`).
- **Issue:** The research-lock comment explaining WHY `python -m venv --copies` was chosen over the uv flag spelled out the forbidden token literally: `# Research lock: \`python -m venv --copies\` (NOT \`uv venv --relocatable\`).` The plan's verify gate (`test "$(grep -cE 'uv venv --relocatable' scripts/build-pkg.sh)" = "0"`) is a strict file-wide grep — comments count.
- **Fix:** Reworded to `# The uv-side relocatable-venv flag is deliberately NOT used: uv #3587 was closed without confirmation and #15751 is still open as of 2026-05.` The intent (research-lock; explain WHY this tool over the alternative) is preserved verbatim; the literal token is omitted.
- **Files modified:** `scripts/build-pkg.sh` (comment lines 32–37 region).
- **Commit:** `72039b7` (the reword landed in the same commit as the file's creation).

**2. [Rule 1 - literal-token grep gate near-miss] Reworded three `homebrew-pypi-poet` references in `release.yml` comments.**

- **Found during:** Task 2 verification (`grep -cE 'homebrew-pypi-poet' .github/workflows/release.yml` returned `3` instead of the required `0`).
- **Issue:** Three header-comment / inline-comment blocks named the deprecated poet generator literally to explain WHY `brew update-python-resources` is used instead. The plan's verify gate is the same strict file-wide grep pattern.
- **Fix:** Reworded all three sites to refer to "the original poet generator" without the literal `homebrew-pypi-poet` token. Each reference still explains the deprecation context (CONTEXT.md D-10's original tool name + the upstream 2023+ deprecation + the maintained 2026 replacement).
- **Files modified:** `.github/workflows/release.yml` (three comment blocks at lines 18, 177, 227 regions).
- **Commit:** `2245116` (the reword landed in the same commit as the file's modification).

Both deviations are docstring/comment-only with **zero behavioral impact** on the release pipeline — same near-miss class observed across multiple Phase 0/1/2 plans (literal-token grep gates flag identifier mentions inside explanatory prose). The pattern is well-documented in prior summaries (e.g., Plan 01-04 had four such near-misses, Plan 01-02 had three).

### No Rule 2 / Rule 3 / Rule 4 deviations

- **Rule 2** (auto-add missing critical functionality): None. The plan's threat model already mandated the SIGN_DYLIBS conditional + the notarization-rejection-fails-non-zero protocol; both shipped as written.
- **Rule 3** (auto-fix blocking issues): None. The dev box wasn't capable of running the full pipeline (no Apple cert / no `pkgbuild` invocation tested), but per the plan's done criterion, that's expected and acceptable for local validation — the macos-14 CI runner is the verification environment.
- **Rule 4** (architectural): None. No structural decisions warranted user input.

## Authentication Gates

None during execution — Plan 03-02 is purely additive packaging infrastructure (no calls to external services from the executor's process). The plan's `<user_setup>` block enumerates the 6 GitHub Actions secrets the maintainer must provision before the first signed release, and `docs/release-setup.md` walks through each one in section 6 — that's the human gate, surfaced in the documentation rather than blocking execution.

## Self-Check: PASSED

**Files created:**
- `/Users/jlqueguiner/dev/whatsapp-desktop-mcp/scripts/build-pkg.sh` — FOUND (3961 bytes, executable bit set)
- `/Users/jlqueguiner/dev/whatsapp-desktop-mcp/scripts/distribution.xml` — FOUND
- `/Users/jlqueguiner/dev/whatsapp-desktop-mcp/scripts/pkg-resources/welcome.html` — FOUND
- `/Users/jlqueguiner/dev/whatsapp-desktop-mcp/Formula/whatsapp-desktop-mcp.rb` — FOUND
- `/Users/jlqueguiner/dev/whatsapp-desktop-mcp/docs/release-setup.md` — FOUND (~14 KB)
- `/Users/jlqueguiner/dev/whatsapp-desktop-mcp/.github/workflows/release.yml` — FOUND (extended; existing publish job byte-stable)

**Commits referenced (in `git log --oneline`):**
- `72039b7` — feat(03-02): add build-pkg.sh staging primitive + distribution.xml + Formula seed — FOUND
- `2245116` — feat(03-02): extend release.yml with pkg-build + tap-update jobs — FOUND
- `eb64c8e` — docs(03-02): release-setup.md — Apple enrollment + GitHub secrets walkthrough — FOUND

## Threat Flags

None — this plan covers DIST-02 (signed-pkg + brew at stable absolute path) using exactly the threat-model surfaces enumerated in the plan's `<threat_model>` block (T-03-02-01 through T-03-02-08). The dispositions are all `mitigate` or `accept` (T-03-02-07 notarytool log diagnostic data is `accept` — maintainer-controlled CI, private logs, no end-user exposure). No new network endpoints, no new auth paths beyond the documented Apple notarization service + brew tap deploy key, no schema changes.

## Next Steps

- **Plan 03-03:** Hardening — `tested_versions.md` parser + doctor degraded-mode warning + audit log size-based rotation + `dev reset-rate-limit` subcommand + `--audit-log-max-bytes` arg.
- **Plan 03-04:** README install-matrix revamp — 3-row install matrix (brew / .pkg / uvx) + 3 TCC permission cards + Sending Messages section. Will reference Plan 03-02's `brew install gladia/whatsapp-desktop-mcp/whatsapp-desktop-mcp` command and the signed-`.pkg` GitHub release artifact.
- **Plan 03-05:** Pre-release smoke suite — `RUN_LIVE_WHATSAPP=1` composing Phase 1 + Phase 2 + FTS5; D-24 fixture extension to sandbox `search_fts5._DB_PATH`. The maintainer-local pre-release ritual that fires before every `git tag v*` push.
- **Maintainer follow-up before first signed release:** complete `docs/release-setup.md` sections 2–7 (Apple Developer enrollment + cert generation + .p12 export + GitHub secrets + brew tap bootstrap), then run the §8 dry-run protocol against `v0.0.1-rc1`.

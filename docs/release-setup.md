# Release Setup — One-time Maintainer Bootstrap

This document is the one-time maintainer walkthrough for bootstrapping the
WhatsApp MCP release pipeline: Apple Developer Program enrollment, code-signing
certificates, GitHub Actions secrets, and the Homebrew custom tap.

After completing the steps below, every `git tag v* && git push --tags` will:

1. Run CI (lint + type-check + test).
2. Publish to PyPI via OIDC (already wired in Phase 0; no maintainer action
   required after the one-time PyPI trusted-publisher setup).
3. Build a Developer-ID-signed + notarized + stapled `.pkg` and attach it to
   the GitHub release (only when the Apple cert secrets are present — see
   the **Skip-block** note below).
4. Open a PR against `jqueguiner/homebrew-whatsapp-desktop-mcp` with the regenerated
   Formula (only when `BREW_TAP_DEPLOY_KEY` is present).

> **Skip-block (D-07).** If `APPLE_INSTALLER_CERT_P12` is not set, the
> `pkg-build` job is no-op and the release ships PyPI-only with a stark
> "unsigned" warning the maintainer should add to the GitHub release notes.
> If `BREW_TAP_DEPLOY_KEY` is not set, the `tap-update` job is no-op and
> the maintainer can update the tap manually. Community forks without
> either secret ship PyPI-only without breaking the release.

---

## 1. Overview

```
                                  git tag v0.1.0 && git push --tags
                                                |
                                                v
                                          .github/workflows/release.yml
                                          /         |        \
                                         /          |         \
                                  ┌─────v────┐  ┌───v────┐  ┌──v──────┐
                                  │   ci     │  │ publish│  │ pkg-    │
                                  │ (lint +  │  │  (OIDC │  │ build   │
                                  │  tests)  │  │ → PyPI)│  │ (.pkg → │
                                  └──────────┘  └───┬────┘  │  GH rel)│
                                                    │       └──┬──────┘
                                                    │          │
                                                    │       (Apple cert
                                                    │        secrets)
                                                    │
                                              ┌─────v─────┐
                                              │ tap-update│
                                              │  (PR → tap│
                                              │   repo)   │
                                              └───────────┘
                                              (BREW_TAP_DEPLOY_KEY)
```

The maintainer must complete **sections 2 through 7** ONCE, in order, before
the first signed-`.pkg` release. Section 8 is the dry-run gate.

---

## 2. Apple Developer Program enrollment (1–10 business days)

> **Pitfall 9 — start enrollment EARLY.** Apple's identity verification
> takes 5–10 business days for organization accounts; if you wait until
> release day to enroll, the D-07 skip-block keeps PyPI publish working
> but you'll ship the first release unsigned (`.pkg` artifact omitted).

1. Visit <https://developer.apple.com/programs/>.
2. Choose **Organization** enrollment (recommended for `gladia.io`) or
   **Individual** if shipping under a personal Apple ID.
   - **Organization:** requires legal-entity verification (D-U-N-S
     number, articles of incorporation). Apple typically takes 5–10
     business days. This is the right path for `jqueguiner/whatsapp-desktop-mcp`.
   - **Individual:** typically approved within 24 hours.
3. Pay the $99/year membership fee.
4. Wait for the welcome email confirming enrollment.

While waiting, you can complete sections 3–6 below using a placeholder
secret value (set the GitHub Actions secret to any non-empty string to
test that the `if:` skip-block evaluates correctly), then swap to the
real cert once enrollment completes.

---

## 3. Generate the Developer ID Installer certificate

The `pkg-build` job needs a **Developer ID Installer** certificate (NOT
"Mac Installer Distribution" — that one is for the Mac App Store). To
generate it:

1. On your Mac, open **Keychain Access** → **Certificate Assistant** →
   **Request a Certificate from a Certificate Authority…**
2. Enter your Apple ID email; choose **Saved to disk** (NOT "Emailed to
   the CA"). Click Continue and save the `.certSigningRequest` file.
3. Visit the Apple Developer dashboard:
   <https://developer.apple.com/account/resources/certificates/list>
4. Click the `+` to create a new certificate. Choose **Software** →
   **Developer ID Installer**. Click Continue.
5. Upload the `.certSigningRequest` from step 2. Click Continue.
6. Download the issued `.cer` file. Double-click to install it in
   **Keychain Access** under the **login** keychain.

Optionally repeat the steps choosing **Developer ID Application** to
generate a second cert that lets the `pkg-build` job re-sign the pyobjc
dylibs inside the staged venv (Pitfall 8 mitigation). This is optional
on the first release; if notarization rejects pyobjc `.so` files, add
the Application cert in a follow-up PR by setting
`APPLE_DEVELOPER_ID_APP_CERT` (see section 6).

---

## 4. Export the certificate to .p12 + base64 encode

1. Open **Keychain Access** → **login** keychain → **My Certificates**.
2. Find **Developer ID Installer: <Your Team Name> (XXXXXXXXXX)**.
3. Right-click → **Export "Developer ID Installer…"**.
4. Set the file format to **Personal Information Exchange (.p12)**.
5. Set a strong password — this becomes
   `APPLE_INSTALLER_CERT_PASSWORD` in the GitHub secrets.
6. Save the `.p12` file (e.g. to `~/Desktop/installer-cert.p12`).
7. On the command line, base64-encode it:
   ```bash
   base64 -i ~/Desktop/installer-cert.p12 | pbcopy   # macOS — copies to clipboard
   ```
   (On Linux: `base64 -w 0 ~/Desktop/installer-cert.p12`.)
   The clipboard now holds the value for `APPLE_INSTALLER_CERT_P12`.

If you also generated a Developer ID Application cert (section 3,
optional step), repeat the export + base64 encode for it; that gives
you `APPLE_DEVELOPER_ID_APP_CERT` and `APPLE_DEVELOPER_ID_APP_CERT_PASSWORD`.

---

## 5. Generate the App-Specific Password for notarytool

`xcrun notarytool` does NOT accept your raw Apple ID password — it
requires an App-Specific Password generated from the Apple ID web
dashboard.

> **Anti-pattern.** Passing your Apple ID password directly to
> `notarytool` will fail with `Error: Could not retrieve credentials
> from the keychain.` This is one of the most common notarization
> setup mistakes.

1. Visit <https://appleid.apple.com>.
2. Sign in → **Sign-In and Security** → **App-Specific Passwords**.
3. Click **+** to generate a new password. Label it
   `whatsapp-desktop-mcp notarization`.
4. Copy the generated password (4 groups of 4 characters,
   `xxxx-xxxx-xxxx-xxxx`). This becomes `APPLE_APP_SPECIFIC_PASSWORD`.

You'll also need:
- `APPLE_ID` — your Apple Developer account email.
- `APPLE_TEAM_ID` — visible at
  <https://developer.apple.com/account/membership/>; a 10-char
  alphanumeric string like `A1B2C3D4E5`.
- `APPLE_TEAM_NAME` — your team's display name as it appears on
  certs, e.g. `Gladia SAS`. The `productsign` command formats the
  identity as `Developer ID Installer: <APPLE_TEAM_NAME> (<APPLE_TEAM_ID>)`.

---

## 6. GitHub Actions secrets bootstrap

Visit <https://github.com/jqueguiner/whatsapp-desktop-mcp/settings/secrets/actions>
and add the following secrets. The first six are required for signed
`.pkg` builds; the remaining two are optional (Application-cert + brew
tap deploy key).

| Secret name | Required? | Source |
|-------------|-----------|--------|
| `APPLE_INSTALLER_CERT_P12` | required | base64 from section 4 |
| `APPLE_INSTALLER_CERT_PASSWORD` | required | password from section 4 step 5 |
| `APPLE_ID` | required | Apple Developer email |
| `APPLE_TEAM_ID` | required | 10-char Team ID from section 5 |
| `APPLE_TEAM_NAME` | required | Team display name from section 5 |
| `APPLE_APP_SPECIFIC_PASSWORD` | required | from section 5 step 4 |
| `APPLE_DEVELOPER_ID_APP_CERT` | optional | base64 of the Application cert; enables `SIGN_DYLIBS=1` (Pitfall 8) |
| `APPLE_DEVELOPER_ID_APP_CERT_PASSWORD` | conditional | required when `APPLE_DEVELOPER_ID_APP_CERT` is set |
| `BREW_TAP_DEPLOY_KEY` | required for `tap-update` | see section 7 below |

> **D-07 skip-block.** If `APPLE_INSTALLER_CERT_P12` is unset, the
> `pkg-build` job is skipped entirely (community-fork-friendly). The
> `publish` (PyPI OIDC) job and the `tap-update` job both run
> independently. Likewise, if `BREW_TAP_DEPLOY_KEY` is unset, the
> `tap-update` job is skipped — `pkg-build` and `publish` still run.

---

## 7. Bootstrap the brew tap

The Homebrew custom tap lives in a separate repository:
<https://github.com/jqueguiner/homebrew-whatsapp-desktop-mcp>. The `tap-update`
job rewrites `Formula/whatsapp-desktop-mcp.rb` in this repo on every release.

To bootstrap:

1. Create a new GitHub repo `jqueguiner/homebrew-whatsapp-desktop-mcp` (empty;
   the name MUST start with `homebrew-` for `brew tap` to recognize it).
2. Clone it locally:
   ```bash
   git clone git@github.com:jqueguiner/homebrew-whatsapp-desktop-mcp.git
   cd homebrew-whatsapp-desktop-mcp
   mkdir Formula
   ```
3. Copy the seed Formula from this repo into the tap:
   ```bash
   cp /path/to/whatsapp-desktop-mcp/Formula/whatsapp-desktop-mcp.rb Formula/whatsapp-desktop-mcp.rb
   git add Formula/whatsapp-desktop-mcp.rb
   git commit -m "bootstrap: initial Formula"
   git push origin main
   ```
4. Generate a deploy key (or fine-grained PAT with **Contents:Write**
   scoped to ONLY this tap repo):
   - **Deploy key:** in the tap repo on GitHub → Settings → Deploy
     keys → Add deploy key. Generate via `ssh-keygen -t ed25519` and
     paste the public key. Tick **Allow write access**. Save the
     private key — this becomes `BREW_TAP_DEPLOY_KEY` in the
     `jqueguiner/whatsapp-desktop-mcp` repo's secrets.
   - **Fine-grained PAT** (alternative): Generate at
     <https://github.com/settings/personal-access-tokens/new>, scope
     to `jqueguiner/homebrew-whatsapp-desktop-mcp` only, **Contents: Read and
     Write**. Save the token as `BREW_TAP_DEPLOY_KEY`.
5. End users install via:
   ```bash
   brew tap jqueguiner/whatsapp-desktop-mcp        # add the tap
   brew install whatsapp-desktop-mcp           # install the formula
   ```
   (Or the one-shot `brew install jqueguiner/whatsapp-desktop-mcp/whatsapp-desktop-mcp`.)

---

## 8. First release dry run

Before promoting a real release, run the full pipeline against a
release-candidate tag to surface any wiring issues.

```bash
git tag v0.0.1-rc1
git push origin v0.0.1-rc1
```

Watch the Actions run at
<https://github.com/jqueguiner/whatsapp-desktop-mcp/actions>.

Expected outputs (when all secrets are configured):

| Job | Expected outcome |
|-----|------------------|
| `ci` | Lint + tests pass |
| `publish` | PyPI release at `whatsapp-desktop-mcp 0.0.1rc1` |
| `pkg-build` | GitHub release has `whatsapp-desktop-mcp-0.0.1rc1.pkg` attached; `spctl --assess` passes |
| `tap-update` | PR opened against `jqueguiner/homebrew-whatsapp-desktop-mcp` with the new Formula |

> **Don't promote `0.0.1-rc1` to brew users.** This is a dry-run gate
> only. Once everything is green, delete the test release and tag:
> ```bash
> git tag -d v0.0.1-rc1
> git push origin :refs/tags/v0.0.1-rc1
> # Also delete the GitHub release via the web UI.
> ```
> Then re-tag with the real version (`v0.1.0`) for the actual release.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Gatekeeper dialog when running `whatsapp-desktop-mcp` post-install (Pitfall 2) | The launcher shell script at `/usr/local/bin/whatsapp-desktop-mcp` was flagged | Run `spctl --assess /usr/local/bin/whatsapp-desktop-mcp` to confirm. Usually shell scripts at `/usr/local/bin` skip Gatekeeper; if not, add a `codesign -s "Developer ID Application: …" /usr/local/bin/whatsapp-desktop-mcp` step in `build-pkg.sh` |
| `notarytool submit --wait` returns "Invalid" status with errors about pyobjc `.so` files (Pitfall 8) | pyobjc wheels on PyPI are NOT signed with our Developer ID; notarization rejects | Provision the **Developer ID Application** cert (section 3 optional) and set `APPLE_DEVELOPER_ID_APP_CERT` + `APPLE_DEVELOPER_ID_APP_CERT_PASSWORD` secrets. The workflow then sets `SIGN_DYLIBS=1`, enabling the `build-pkg.sh` re-sign block |
| `tap-update` step "Compute sdist sha256" fails with PyPI 404 (Pitfall 3) | PyPI CDN hasn't propagated the new release yet | Bump `sleep 30` to `sleep 60` in the `Wait for PyPI CDN propagation` step in `release.yml` |
| `pkg-build` job skipped entirely on tag push (Pitfall 9) | `APPLE_INSTALLER_CERT_P12` secret is unset (D-07 skip-block fires) | Either complete Apple Developer enrollment + sections 3–6 above, or accept the unsigned-only release for this tag and add a "unsigned — see GitHub releases" note to the README install matrix |
| `notarytool` returns `Could not retrieve credentials from the keychain` | Used the raw Apple ID password instead of an App-Specific Password | Generate an App-Specific Password (section 5) and set `APPLE_APP_SPECIFIC_PASSWORD` to that value |
| `productsign` fails with `Could not find appropriate signing identity` | The keychain doesn't contain the Installer cert, OR `APPLE_TEAM_NAME` doesn't match the cert's display name | Verify the cert is installed in Keychain Access; check `security find-identity -v -p basic` to see the exact identity string format and update `APPLE_TEAM_NAME` to match |

---

## Reference

- Apple notarytool man page:
  <https://keith.github.io/xcode-man-pages/notarytool.1.html>
- Apple `pkgbuild`/`productbuild`/`productsign` reference:
  <https://keith.github.io/xcode-man-pages/pkgbuild.1.html>
- Homebrew Python Formula authoring:
  <https://docs.brew.sh/Python-for-Formula-Authors>
- `apple-actions/import-codesign-certs`:
  <https://github.com/apple-actions/import-codesign-certs>
- Phase 3 CONTEXT.md decisions:
  `.planning/phases/03-hardening-and-distribution/03-CONTEXT.md`
- Phase 3 RESEARCH.md (signing pipeline + Pitfall index):
  `.planning/phases/03-hardening-and-distribution/03-RESEARCH.md`

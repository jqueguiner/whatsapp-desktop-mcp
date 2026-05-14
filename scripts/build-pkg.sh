#!/usr/bin/env bash
# scripts/build-pkg.sh — build a Developer-ID-signable .pkg of whatsapp-mcp.
#
# Inputs (env):
#   VERSION       — required, e.g. 0.1.0
#   STAGING_DIR   — optional, default /tmp/whatsapp-mcp-pkg
#   SIGN_DYLIBS   — optional. When set (any non-empty value), re-signs every
#                   binary inside the staged venv with the Developer ID
#                   Application cert before packaging (Pitfall 8 mitigation:
#                   pyobjc .so files shipped on PyPI are NOT signed with our
#                   Developer ID, so notarization rejects them unless we
#                   re-sign them with `codesign --deep --options runtime`).
#                   The release.yml `pkg-build` job sets SIGN_DYLIBS=1 only
#                   when an APPLE_DEVELOPER_ID_APP_CERT secret was imported
#                   alongside the Installer cert. Local builds and community
#                   forks leave it unset → community-fork unsigned .pkgs
#                   skip this step entirely (D-07 fallback shape).
#   APPLE_TEAM_NAME / APPLE_TEAM_ID — required ONLY when SIGN_DYLIBS is set;
#                   used to construct the Developer ID Application identity
#                   string `Developer ID Application: ${APPLE_TEAM_NAME} (${APPLE_TEAM_ID})`.
#
# Outputs:
#   $PWD/dist/whatsapp-mcp-${VERSION}-component.pkg
#   $PWD/dist/whatsapp-mcp-${VERSION}-unsigned.pkg
#
# Decisions covered:
#   D-03 (self-contained Python venv bundle)
#   D-05 (stdout purity carries through the launcher — exec, no echo)
#   T-3 (stable absolute path /usr/local/bin/whatsapp-mcp; pkgbuild --identifier
#        net.gladia.whatsapp-mcp ensures macOS treats upgrades as same-package)
#
# Research lock: `python -m venv --copies` is the venv tool here.
#   The uv-side relocatable-venv flag is deliberately NOT used: uv #3587
#   was closed without confirmation and #15751 is still open as of 2026-05.
#   `--copies` ensures the staged venv carries its own python binary,
#   not a symlink to the build machine's interpreter, AND records the
#   FINAL install path in pyvenv.cfg.

set -euo pipefail

VERSION="${VERSION:?VERSION env var required}"
STAGING_DIR="${STAGING_DIR:-/tmp/whatsapp-mcp-pkg}"
BUNDLE_ID="net.gladia.whatsapp-mcp"
INSTALL_PREFIX="/usr/local"
VENV_DIR="${STAGING_DIR}${INSTALL_PREFIX}/lib/whatsapp-mcp/.venv"
BIN_DIR="${STAGING_DIR}${INSTALL_PREFIX}/bin"

# Clean staging
rm -rf "${STAGING_DIR}"
mkdir -p "${VENV_DIR}" "${BIN_DIR}"
mkdir -p dist

# 1. Build the wheel for the project itself
uv build --wheel --out-dir dist

# 2. Create a copies-mode venv at the FINAL install location.
#    --copies (NOT --symlinks) so the venv carries its own python binary,
#    not a symlink to the build machine's interpreter. Building the venv
#    AT the final install path ensures pyvenv.cfg records the exact
#    post-install interpreter path — macOS installer-tier relocation
#    isn't supported by uv venv as of 2026-05 (uv #3587 / #15751).
/usr/bin/env python3.12 -m venv --copies "${VENV_DIR}"

# 3. Install whatsapp-mcp + transitive deps into the staged venv.
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install "dist/whatsapp_mcp-${VERSION}-py3-none-any.whl"

# 4. Write the launcher shell script at the stable absolute path.
#    Phase 0 D-05 stdout-purity rule carries: NO echo, NO set -x, NO diagnostic
#    output — every byte on stdout is JSON-RPC. The exec form keeps the process
#    tree shallow (Claude Desktop spawns one PID, not two). $@ propagates
#    --read-only / --fts5-mode / --audit-log-max-bytes etc.
cat > "${BIN_DIR}/whatsapp-mcp" <<'LAUNCHER'
#!/bin/bash
exec "/usr/local/lib/whatsapp-mcp/.venv/bin/python" -m whatsapp_mcp "$@"
LAUNCHER
chmod 0755 "${BIN_DIR}/whatsapp-mcp"

# 5. Optional: re-sign every binary inside the staged venv with the
#    Developer ID Application cert (Pitfall 8 mitigation). Gated by
#    SIGN_DYLIBS so community-fork builds (no Application cert imported)
#    skip this step entirely. release.yml sets SIGN_DYLIBS=1 only when
#    an APPLE_DEVELOPER_ID_APP_CERT secret was imported.
if [ -n "${SIGN_DYLIBS:-}" ]; then
    : "${APPLE_TEAM_NAME:?SIGN_DYLIBS=1 requires APPLE_TEAM_NAME}"
    : "${APPLE_TEAM_ID:?SIGN_DYLIBS=1 requires APPLE_TEAM_ID}"
    codesign \
        --deep \
        --force \
        --options runtime \
        --sign "Developer ID Application: ${APPLE_TEAM_NAME} (${APPLE_TEAM_ID})" \
        "${VENV_DIR}"
fi

# 6. Substitute VERSION_PLACEHOLDER in distribution.xml into a copy in dist/.
#    Preserve the source-tree distribution.xml unchanged (idempotent local re-runs).
cp scripts/distribution.xml "dist/distribution.xml"
sed -i '' "s/VERSION_PLACEHOLDER/${VERSION}/g" "dist/distribution.xml"

# 7. Build the component package.
pkgbuild \
    --root "${STAGING_DIR}" \
    --identifier "${BUNDLE_ID}" \
    --version "${VERSION}" \
    --install-location / \
    --ownership recommended \
    "dist/whatsapp-mcp-${VERSION}-component.pkg"

# 8. Build a distribution archive (allows productsign + notarization).
productbuild \
    --distribution "dist/distribution.xml" \
    --package-path dist \
    --resources scripts/pkg-resources \
    "dist/whatsapp-mcp-${VERSION}-unsigned.pkg"

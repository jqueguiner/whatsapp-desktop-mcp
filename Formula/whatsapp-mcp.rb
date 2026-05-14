# Formula/whatsapp-mcp.rb — Bootstrap formula for the gladia/homebrew-whatsapp-mcp tap.
#
# This file is COMMITTED in this repo as the seed Formula that the
# `tap-update` job in .github/workflows/release.yml uses as the baseline
# to update on each release. The maintainer copies it into the empty
# tap repo (gladia/homebrew-whatsapp-mcp) on first bootstrap (see
# docs/release-setup.md §"Bootstrap the brew tap").
#
# On every release tag, the `tap-update` job:
#   1. Checks out the tap repo
#   2. Sleeps 30s for PyPI CDN propagation (Pitfall 3)
#   3. Computes the new sdist sha256 from PyPI's JSON API
#   4. Rewrites the `url` and `sha256` lines via sed
#   5. Regenerates the `resource` blocks via `brew update-python-resources whatsapp-mcp`
#      (the maintained 2026 successor to homebrew-pypi-poet, which is deprecated)
#   6. Opens a PR via peter-evans/create-pull-request@v6
#
# Decisions covered: D-09 (Language::Python::Virtualenv shape), D-10 (auto-publish
# via brew update-python-resources), D-11 (`brew install gladia/whatsapp-mcp/whatsapp-mcp`).
class WhatsappMcp < Formula
  include Language::Python::Virtualenv

  desc "MCP server controlling WhatsApp Desktop on macOS"
  homepage "https://github.com/gladia/whatsapp-mcp"
  url "https://files.pythonhosted.org/packages/source/w/whatsapp-mcp/whatsapp_mcp-0.1.0.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"

  depends_on "python@3.12"
  depends_on macos: :sequoia # macOS 15+; matches distribution.xml allowed-os-versions floor

  # `resource` blocks for every transitive dep — populated by
  # `brew update-python-resources whatsapp-mcp` during the tap-update job.
  # The placeholders below give that command a working baseline to update
  # against; the actual sha256s and versions get rewritten on each release.
  resource "mcp" do
    url "https://files.pythonhosted.org/packages/source/m/mcp/mcp-1.27.1.tar.gz"
    sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  end

  resource "pydantic" do
    url "https://files.pythonhosted.org/packages/source/p/pydantic/pydantic-2.13.4.tar.gz"
    sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  end

  resource "pyobjc-core" do
    url "https://files.pythonhosted.org/packages/source/p/pyobjc-core/pyobjc-core-12.1.tar.gz"
    sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  end

  resource "pyobjc-framework-Cocoa" do
    url "https://files.pythonhosted.org/packages/source/p/pyobjc-framework-Cocoa/pyobjc-framework-Cocoa-12.1.tar.gz"
    sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  end

  resource "pyobjc-framework-ApplicationServices" do
    url "https://files.pythonhosted.org/packages/source/p/pyobjc-framework-ApplicationServices/pyobjc-framework-ApplicationServices-12.1.tar.gz"
    sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "0.1.0", shell_output("#{bin}/whatsapp-mcp --version")
  end
end

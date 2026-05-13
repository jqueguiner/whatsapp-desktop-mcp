# whatsapp-mcp

> **Warning — WhatsApp ToS automation risk.** This MCP server automates *your personal*
> WhatsApp account by driving the macOS WhatsApp Desktop app the same way you do.
> WhatsApp's Terms of Service prohibit "automated or bulk messaging." Running the
> send tools at scale (or in patterns that look like a bot) risks an irrecoverable
> account ban. This project ships conservative rate limits (5 sends / minute,
> 30 sends / day) by default, but you accept the risk by using it.
>
> **This is your personal account, not a bot.** Treat it that way.
> No bulk messaging. No auto-reply loops.

A local Model Context Protocol (MCP) server that lets Claude Desktop / Claude Code
read and write your WhatsApp Desktop chats. macOS only. Single user, single Mac.

## Quickstart (60 seconds)

1. Add this snippet to `~/Library/Application Support/Claude/claude_desktop_config.json`
   (the exact text also lives in
   [`examples/claude_desktop_config.json`](examples/claude_desktop_config.json)):

   ```json
   {
     "mcpServers": {
       "whatsapp": {
         "command": "uvx",
         "args": ["whatsapp-mcp"]
       }
     }
   }
   ```

2. Restart Claude Desktop.

3. From the chat, ask Claude to **"call the WhatsApp doctor tool."**
   The first call will return a structured report naming the macOS permissions
   that still need to be granted, the absolute path to the binary that is asking
   for them, and a `x-apple.systempreferences:` deep-link for each one.

4. Follow the System Settings deep-links the report gives you to grant
   **Full Disk Access**, **Apple Events / Automation** (for WhatsApp), and
   **Accessibility** to the binary the report names. After granting, restart
   Claude Desktop one more time and re-call `doctor`.

That's it. Once `doctor` reports all three permissions as `granted`, the read and
send tools (Phase 1+) will work.

## Requirements

- macOS (verified on 14 Sonoma, 15 Sequoia, 26 Tahoe; Apple Silicon)
- Python 3.12+ — `uvx` fetches this for you, no manual install needed
- WhatsApp Desktop installed and logged in (the Catalyst build from the
  Mac App Store or the direct download from whatsapp.com)
- [`uv`](https://docs.astral.sh/uv/) on your `PATH` (Homebrew: `brew install uv`)

This project is macOS-only by design. The send path drives the live WhatsApp
Desktop app via AppleScript / Apple Events; the read path queries WhatsApp's
local Core Data SQLite store. Neither has a Windows or Linux equivalent.

## What `doctor` reports

A successful `doctor` call returns a structured JSON report with three buckets:

- **`full_disk_access`** — can the running Python process read WhatsApp's local
  `ChatStorage.sqlite`? Probed by `os.stat` on the actual path (no TCC.db reads).
- **`automation_whatsapp`** — can the running Python process send Apple Events
  to WhatsApp? Probed by `osascript -e 'id of application "WhatsApp"'` and a
  small decision matrix over the resulting error codes (locale-blind).
- **`accessibility`** — can the running Python process use the Accessibility
  API (used by the send path for window-state assertions)? Probed by a
  `tell System Events to count processes` round-trip.

Each bucket reports `state` (`granted` / `denied` / `whatsapp_not_installed`),
the absolute `binary_path` the user must grant the permission to (this is the
exact value of `sys.executable` inside the running server — typically the
uv-managed Python interpreter), the `system_settings_url` deep-link, and a
one-line remediation string. The `doctor` tool itself is annotated
`readOnlyHint=true` and is safe to call any time.

## Out of scope (hard rules)

This project deliberately does NOT include the following — they are anti-features:

- **No bulk send / broadcast.** One recipient per tool call. No fan-out helpers.
- **No scheduled send.** Send happens synchronously when the LLM calls the tool.
- **No auto-reply loops.** Send is a discrete LLM-triggered action with mandatory
  elicitation confirmation; the server does not subscribe to incoming messages
  for the purpose of responding.
- **No HTTP / REST / TCP / UDP listener.** The MCP server speaks stdio only.
  (`lharries/whatsapp-mcp` was hit by a path-traversal class CVE via its HTTP
  surface — that mistake is structurally avoided here.)
- **No writes to `ChatStorage.sqlite`.** WhatsApp owns the writer; reads only,
  short-lived connections, `?mode=ro`.
- **No inlined media bytes in tool responses.** Attachments surface as
  `MediaRef` structures (filename, mime, local path, size); the bytes stay on
  disk.
- **No non-macOS support.** macOS-only by design (see Requirements above).

These rules are enforced structurally (no HTTP listener exists in the codebase;
the reader and sender packages cannot import each other; `ruff T201` blocks
`print` at lint time) and by tests (CI runs a stdout-purity check that
asserts every byte the server emits on stdout is a JSON-RPC 2.0 frame).

## Development

```sh
git clone https://github.com/gladia/whatsapp-mcp
cd whatsapp-mcp
uv sync --extra dev
```

Run the test suite:

```sh
uv run pytest -m "not live"           # ~1 second; all unit tests, CI default
RUN_LIVE=1 uv run pytest -m live      # exercises live doctor against this Mac
```

Lint + format + type-check (the same set CI runs):

```sh
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
```

The `live` test marker is opt-in via `RUN_LIVE=1`; CI deselects it by default
because GitHub-hosted macOS runners do not have WhatsApp Desktop installed
or logged in.

### Cutting a release (PyPI trusted-publisher, one-time setup)

The release workflow (`.github/workflows/release.yml`) triggers on
`git tag v*` and publishes to PyPI via GitHub OIDC. There is no long-lived
PyPI credential in this repo. Before the first release, configure PyPI's
trusted-publisher binding once:

1. On PyPI, create (or claim) the project `whatsapp-mcp`.
2. Project settings → Publishing → Add a new pending publisher.
3. Fill in: Owner = `gladia` (your GitHub org / user),
   Repository = `whatsapp-mcp`, Workflow = `release.yml`, Environment = `pypi`.
4. Save.

Subsequent releases are just:

```sh
git tag v0.1.0
git push --tags
```

The release workflow runs CI first; if it passes, the `publish` job builds the
distribution with `uv build` and uploads it with `uv publish` over the OIDC
handshake. After the first successful publish, `uvx whatsapp-mcp --version`
will resolve from PyPI on any Mac with `uv` installed.

## License

MIT — see [LICENSE](LICENSE).

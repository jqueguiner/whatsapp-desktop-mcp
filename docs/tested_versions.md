# Tested WhatsApp Desktop Versions

This file lists WhatsApp Desktop versions known to work with this MCP server.
Maintainers append a row after each successful pre-release smoke run on a new
WhatsApp Catalyst build. The parser in
`src/whatsapp_desktop_mcp/reader/tested_versions.py` reads the `Z_VERSION`
column at module load to compute the `supported_version_range` reported by
the `doctor` MCP tool. Outside that range, `doctor` emits a
`degraded_mode_warning` so an LLM client knows reads may degrade silently.

The first column (WhatsApp Desktop version string) is parsed by a sibling
helper to populate the `(last tested: …)` portion of the warning when the
live `CFBundleShortVersionString` doesn't match any row in this file.

| WhatsApp Desktop | macOS  | Z_VERSION | doctor outcomes        | tested by    | date       | notes                                |
|------------------|--------|-----------|------------------------|--------------|------------|--------------------------------------|
| 26.16.74         | 26.4   | 1         | FDA/Auto/Acc all granted | maintainer | 2026-05-13 | Phase 1+2 live-verified              |

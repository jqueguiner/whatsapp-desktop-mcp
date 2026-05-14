"""Shared pytest configuration for the whatsapp-desktop-mcp test suite.

Phase 0 keeps this near-empty intentionally:

- ``[tool.pytest.ini_options].asyncio_mode = "auto"`` (PLAN 00-01 / pyproject.toml)
  means individual tests do not strictly need ``@pytest.mark.asyncio`` decorators —
  the verbatim source from ``00-RESEARCH.md`` keeps them for clarity, and that
  intent is preserved.
- The ``fp`` fixture from ``pytest-subprocess`` is auto-imported by the plugin;
  no manual fixture declaration is required here.
- The ``live`` marker is declared in ``[tool.pytest.ini_options].markers`` —
  see PLAN 00-01 for the full marker registration.

Phase 1+ may grow custom fixtures (e.g. a frozen ChatStorage.sqlite golden
sample); for Phase 0 there is nothing to share between tests.
"""

from __future__ import annotations

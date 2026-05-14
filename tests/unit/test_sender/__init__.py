"""Phase 2 Plan 02-05 — tests for the sender package.

Mirrors ``tests/unit/test_reader/`` shape. Each test file under this
directory targets ONE module under ``src/whatsapp_desktop_mcp/sender/``.

The four mandatory regression tests from CONTEXT.md §Specifics ship in
two locations:

* ``test_send_message_rate_limit_persists_across_restart`` — under
  ``test_sender/test_rate_limit.py`` (Task 2).
* ``test_send_message_refuses_string_chat_id`` /
  ``test_send_message_aborts_on_chat_header_mismatch`` /
  ``test_send_message_appends_audit_log_with_body_sha256_not_body`` —
  under ``test_tools/test_send_message.py`` (Task 3).
"""

"""Reader-tier unit tests against synthetic ChatStorage-shaped sqlite fixtures.

Phase 1 Plan 01-06 Task 2 — codifies the Plan 01-02 reader public surface
(``list_chats`` / ``window`` / ``since`` / ``context_around_stanza`` /
``parent_of_stanza`` / ``latest_timestamp`` / ``search_contacts`` /
``resolve_lid_to_phone`` / ``resolve_phone_to_lid`` / ``like_search`` /
``open_ro`` / ``probe_z_version`` / ``is_supported`` / ``is_tombstone`` /
``resolve_media_ref``) against tempfile sqlite fixtures whose schema
mirrors the verified-live ChatStorage / LID / ContactsV2 layout.
"""

from __future__ import annotations

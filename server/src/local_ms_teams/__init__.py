"""local-ms-teams: a small read-only MCP server over the new Teams client's
local message cache.

The new Teams client keeps recent conversations in a Chromium IndexedDB
(LevelDB) on this machine. The server copies that folder to a temp dir,
decodes it with ``ccl_chromium_reader`` (optional extra ``teams``) and
answers from the decoded snapshot. Nothing in Teams is changed and no
network call is made.
"""

__version__ = "0.1.0"

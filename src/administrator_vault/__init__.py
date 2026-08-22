"""administrator-vault: a small MCP server that writes the administrator plugin's
notes into an Obsidian vault in a fixed, checkable way.

Root = the ``ADMINISTRATOR_VAULT`` environment variable. Every write lands
under ``<vault>/Administrator/``; nothing else in the vault is touched.
"""

__version__ = "0.1.0"

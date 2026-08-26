"""soma-vault: a small MCP server that writes the soma plugin's
notes into an Obsidian vault in a fixed, checkable way.

Root = the ``SOMA_VAULT`` environment variable. Every write lands
under ``<vault>/Soma/``; nothing else in the vault is touched.
"""

__version__ = "0.1.0"

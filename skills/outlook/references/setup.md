# Setup — the servers ship inside the plugin

Nothing is installed by hand. The three MCP servers (`outlook-mcp`, `soma-vault`, `local-ms-teams`) live in the plugin's `server/` folder and are started by `.claude-plugin/plugin.json` with `uv run --directory ${CLAUDE_PLUGIN_ROOT}/server <script>`. On the first start `uv` builds `server/.venv` from `server/pyproject.toml` and `server/uv.lock` (Python 3.10+, `uv` on the PATH; one download from GitHub for the Teams cache reader).

If a server does not start:

1. `uv --version` — `uv` must be on the PATH of the shell that starts Claude Code.
2. In `server/`, run `uv sync` once and read the error.
3. Restart Claude Code; the tools (`outlook_*`, `vault_*`, `teams_*`) appear when the servers are up.
4. `outlook_*` tools present but every call fails: classic Outlook (`outlook.exe`) must be installed with a mail profile; the new Outlook (`olk.exe`) has no COM interface.

The Outlook server began as a fork of anasahmed07/Outlook-Classic-MCP (MIT); the vault and Teams servers were written for this plugin. Upstream's PyPI package and marketplace are not used.

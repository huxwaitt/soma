"""CLI entry point: ``local-ms-teams`` and ``python -m local_ms_teams``."""

from __future__ import annotations

import logging
import os
import sys

from local_ms_teams.server import build_server


def main() -> None:
    # stdio servers must never log to stdout: that is the JSON-RPC stream.
    logging.basicConfig(
        level=os.environ.get("LOCAL_MS_TEAMS_LOG", "INFO"),
        stream=sys.stderr,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logging.getLogger("local_ms_teams").info("Starting local-ms-teams server (stdio transport)")
    build_server().run()


if __name__ == "__main__":
    main()

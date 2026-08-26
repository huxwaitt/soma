"""CLI entry point: ``soma-vault`` and ``python -m soma_vault``."""

from __future__ import annotations

import logging
import os
import sys

from soma_vault.server import build_server


def main() -> None:
    # stdio servers must never log to stdout: that is the JSON-RPC stream.
    logging.basicConfig(
        level=os.environ.get("SOMA_VAULT_LOG", "INFO"),
        stream=sys.stderr,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logging.getLogger("soma_vault").info("Starting vault server (stdio transport)")
    build_server().run()


if __name__ == "__main__":
    main()

"""Initialize local-only IndexNow configuration for the configured site."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rankrat.operator.indexnow import IndexNowInitializationError, initialize_indexnow

_DEFAULT_BOUNDARY_FILE = Path("config/boundaries.json")
_DEFAULT_KEY_FILE = Path("secrets/indexnow/key")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="init_indexnow")
    parser.add_argument("--boundary-file", type=Path, default=_DEFAULT_BOUNDARY_FILE)
    parser.add_argument("--key-file", type=Path, default=_DEFAULT_KEY_FILE)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--host", required=True)
    return parser


def main() -> int:
    """Prepare local IndexNow setup without submitting a provider request."""
    arguments = _parser().parse_args()
    try:
        result = initialize_indexnow(
            arguments.boundary_file,
            arguments.key_file,
            target_id=arguments.target_id,
            host=arguments.host,
        )
    except IndexNowInitializationError as error:
        sys.stderr.write(f"IndexNow setup failed: {error}\n")
        return 2
    status = "created" if result.created_key else "retained"
    target = "configured" if result.configured_target else "retained"
    sys.stdout.write(f"IndexNow local setup complete: key {status}, target {target}.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

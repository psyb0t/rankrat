"""Verify the deployed IndexNow ownership file without submitting URLs."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from rankrat.operator.indexnow import (
    IndexNowPublicKeyVerificationError,
    verify_indexnow_public_key,
)

_DEFAULT_BOUNDARY_FILE = Path("config/boundaries.json")
_DEFAULT_KEY_FILE = Path("secrets/indexnow/key")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verify_indexnow_public_key")
    parser.add_argument("--boundary-file", type=Path, default=_DEFAULT_BOUNDARY_FILE)
    parser.add_argument("--key-file", type=Path, default=_DEFAULT_KEY_FILE)
    parser.add_argument("--target-id", required=True)
    return parser


def main() -> int:
    """Return a secret-free status for the directly served ownership file."""

    arguments = _parser().parse_args()
    try:
        asyncio.run(
            verify_indexnow_public_key(
                arguments.boundary_file,
                arguments.key_file,
                target_id=arguments.target_id,
            )
        )
    except IndexNowPublicKeyVerificationError as error:
        sys.stderr.write(f"IndexNow public-key verification failed: {error}\n")
        return 2
    sys.stdout.write("IndexNow public ownership file verified.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

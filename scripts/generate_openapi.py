"""Generate the deterministic JSON artifact from the YAML-first OpenAPI source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rankrat.transports.openapi import load_openapi_document

_OUTPUT_FILE = Path("openapi.json")


def main() -> None:
    """Write the JSON distribution artifact without reading a credential or provider."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    document = load_openapi_document()
    rendered_document = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if arguments.check:
        if _OUTPUT_FILE.read_text(encoding="utf-8") != rendered_document:
            raise SystemExit("openapi.json is stale; run make generate-openapi")
        return
    _OUTPUT_FILE.write_text(rendered_document, encoding="utf-8")


if __name__ == "__main__":
    main()

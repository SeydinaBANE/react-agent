#!/usr/bin/env python3
"""Export the OpenAPI schema to openapi.json for CI validation."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    try:
        from agent.api.main import app

        schema = app.openapi()
        output = Path("openapi.json")
        output.write_text(json.dumps(schema, indent=2))
        print(f"OpenAPI schema exported to {output} ({len(schema)} keys)")
    except Exception as exc:
        print(f"Failed to export schema: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

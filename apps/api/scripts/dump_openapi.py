"""Dump the FastAPI OpenAPI schema to a file (or stdout) without booting the server.

Importing ``app.main`` constructs the FastAPI app but does NOT run the lifespan,
so no database connection is made — this is safe to run in CI with no infra.

Usage:
    poetry run python scripts/dump_openapi.py [output_path]

If ``output_path`` is omitted the schema is written to stdout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the API root (apps/api) is importable regardless of invocation cwd —
# running a script otherwise only puts scripts/ on sys.path, not the package root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402


def main() -> None:
    schema = app.openapi()
    payload = json.dumps(schema, indent=2, sort_keys=True)

    if len(sys.argv) > 1:
        out_path = sys.argv[1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(payload)
            f.write("\n")
        print(f"Wrote OpenAPI schema to {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(payload)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()

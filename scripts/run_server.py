#!/usr/bin/env python
"""Launch the CAID Lite FastAPI server.

Usage::

    python scripts/run_server.py
    python scripts/run_server.py --config config/default.yaml --port 8000
    python scripts/run_server.py --reload  # development hot-reload

The server exposes:
    POST   /api/chat                  Submit a generation prompt
    GET    /api/parts                 List all parts
    GET    /api/parts/{id}            Get a single part
    DELETE /api/parts/{id}            Remove a part
    GET    /api/parts/{id}/step       Download STEP file
    GET    /api/parts/{id}/stl        Download STL file
    GET    /api/events                SSE stream for live updates
    GET    /docs                      Swagger UI
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from the project root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CAID Lite API server")
    parser.add_argument(
        "--config",
        default="config/default.yaml",
        help="Path to config YAML (default: config/default.yaml)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    parser.add_argument(
        "--reload", action="store_true", help="Enable hot-reload (development only)"
    )
    args = parser.parse_args()

    import uvicorn
    from caid_lite.api.server import create_app

    app = create_app(config_path=args.config)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()

"""CAID Lite GUI launcher.

Starts the FastAPI server and opens the browser to the 3-pane interface.

Usage::

    python gui/app.py
    python gui/app.py --port 8080 --no-browser
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Allow running directly from the project root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch CAID Lite")
    parser.add_argument("--config", default="config/default.yaml",
                        help="Path to YAML config (default: config/default.yaml)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true",
                        help="Do not open the browser automatically")
    args = parser.parse_args()

    import uvicorn
    from caid_lite.api.server import create_app

    app = create_app(config_path=args.config)
    url = f"http://{args.host}:{args.port}"

    if not args.no_browser:
        def _open_browser() -> None:
            time.sleep(1.2)  # wait for uvicorn to bind
            webbrowser.open(url)
        threading.Thread(target=_open_browser, daemon=True).start()

    print(f"CAID Lite running at {url}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

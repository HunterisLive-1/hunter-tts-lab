"""Hunter TTS Lab: start the local server and open the page.

    python app\\main.py [--port 7870] [--no-browser]

Started for the user by "Start Hunter TTS Lab.bat".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

# The private copy of Python that the start file sets up does not add the
# script's folder to the import path by itself.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import brand  # noqa: E402
import omni_engine  # noqa: E402
import paths  # noqa: E402
import server  # noqa: E402

FIRST_PORT = 7870


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=2) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == brand.NAME
    except (OSError, ValueError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=f"{brand.NAME}. {brand.CREDIT}.")
    ap.add_argument("--port", type=int, default=FIRST_PORT)
    ap.add_argument("--no-browser", action="store_true", help="do not open the page")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    print(brand.banner())
    paths.ensure()

    httpd = None
    for port in range(args.port, args.port + 20):
        try:
            httpd = server.make_server(port)
            break
        except OSError:
            if _already_running(port):
                print(f"\n  Already running. Opening http://127.0.0.1:{port}/")
                if not args.no_browser:
                    webbrowser.open(f"http://127.0.0.1:{port}/")
                return 0
    if httpd is None:
        print("\n  Could not find a free port to listen on. Close other local servers and start again.")
        return 1

    threading.Thread(target=server.scan_hardware, daemon=True, name="hardware").start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"\n  The app is open at  {url}")
    print("  Keep this window open while you use it. Close it to stop the app.\n")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        omni_engine.stop()
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # leave at once: a download thread must not keep the window open

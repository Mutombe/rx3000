"""The backend as a single executable, for the desktop app to run beside itself.

A pharmacy downloads one thing. Inside it are the till, the dispensary and the
database, and none of that is any use if installing it also means installing
Python, pip, a virtual environment and a service. So the whole backend is frozen
into one binary that the desktop shell starts on launch and stops on exit.

Run directly it behaves like `uvicorn app.main:app`, which keeps one way of
starting the server rather than two that can drift:

    rx5000-server                 # the port the desktop app expects
    rx5000-server --port 9001     # a second till on the same machine
    rx5000-server --host 0.0.0.0  # the counter's server, for the other tills
"""
from __future__ import annotations

import argparse
import os
import socket
import sys

#: What the desktop shell looks for when nothing says otherwise.
DEFAULT_PORT = 8177


def _free(port: int, host: str) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host if host != "0.0.0.0" else "", port))
            return True
        except OSError:
            return False


def main() -> int:
    parser = argparse.ArgumentParser(prog="rx5000-server", add_help=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(
        os.getenv("RX5000_PORT") or os.getenv("RX3000_PORT") or DEFAULT_PORT))
    parser.add_argument("--data-dir", default="",
                        help="where the database lives (default: this user's "
                             "application data folder)")
    args = parser.parse_args()

    if args.data_dir:
        os.environ["RX5000_DATA_DIR"] = args.data_dir

    # A second copy is not an error worth a stack trace.
    #
    # Somebody double-clicks the desktop icon twice, or leaves it running and
    # starts it again after lunch. The first server is already serving on this
    # port and is perfectly good; the second should say so in one line and stand
    # down, not crash with an address-in-use traceback that reads like a fault.
    if not _free(args.port, args.host):
        print(f"RX5000 is already serving on {args.host}:{args.port}; "
              f"this copy is not needed.", flush=True)
        return 0

    # Imported here rather than at the top so `--help` and the port check do not
    # pay for loading the whole application first.
    import uvicorn

    from app.main import app

    print(f"RX5000 server on http://{args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info",
                access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

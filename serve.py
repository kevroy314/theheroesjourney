#!/usr/bin/env python3
"""Static server for the FitRogue web build.

Binds 0.0.0.0 so the game is reachable from a phone on the same network.
Serves .wasm with the correct MIME type; the export is a nothreads build, so
no COOP/COEP cross-origin-isolation headers are required.

Usage:
  python3 serve.py [PORT]
"""
import http.server
import os
import socketserver
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8070
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build")


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".wasm": "application/wasm",
        ".js": "text/javascript",
        ".pck": "application/octet-stream",
        ".json": "application/json",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        # No caching: a rebuild is picked up on plain reload.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    if not os.path.isdir(ROOT):
        sys.exit(f"no build directory at {ROOT} — run ./run.sh first")
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        print(f"[HTTP] serving {ROOT} on http://0.0.0.0:{PORT}")
        httpd.serve_forever()

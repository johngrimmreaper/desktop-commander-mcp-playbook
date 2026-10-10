#!/usr/bin/env python3
"""A local readiness fixture for isolated systemd activation tests; no tunnel or credentials."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import time

parser = argparse.ArgumentParser()
parser.add_argument("--listen-addr", required=True)
parser.add_argument("--fail", action="store_true")
parser.add_argument("--idle", action="store_true")
args = parser.parse_args()
if args.fail:
    raise SystemExit(78)
if args.idle:
    time.sleep(300)
    raise SystemExit(0)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/readyz" else 404)
        self.end_headers()
        self.wfile.write(b"ready\n")

    def log_message(self, *_args):
        pass


host, port = args.listen_addr.split(":")
HTTPServer((host, int(port)), Handler).serve_forever()

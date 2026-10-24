"""
config/snowplow/tools/log_proxy.py — Proxy ghi log request TP2 từ Browser Tracker.

Chạy proxy ở :9091, forward sang Snowplow Micro ở :9090, đồng thời ghi lại
raw body + headers vào file để so sánh format chính xác.

    python config/snowplow/tools/log_proxy.py --out /tmp/tp2-capture.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = ("127.0.0.1", 9090)
OUT = "tp2-capture.jsonl"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # silence default logging
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "600")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)

        encoding = (self.headers.get("Content-Encoding") or "").lower()
        if "gzip" in encoding:
            try:
                decoded = gzip.decompress(raw)
            except Exception:
                decoded = raw
        else:
            decoded = raw

        record = {
            "path": self.path,
            "headers": dict(self.headers.items()),
            "raw_len": len(raw),
            "body": decoded.decode("utf-8", errors="replace"),
        }
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Forward upstream, giữ nguyên Content-Encoding.
        import http.client
        conn = http.client.HTTPConnection(*UPSTREAM, timeout=30)
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "content-length", "connection")}
        headers["Content-Length"] = str(len(raw))
        conn.request("POST", self.path, body=raw, headers=headers)
        resp = conn.getresponse()
        payload = resp.read()
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.getheader("Content-Type", "text/plain"))
        self.send_header("Content-Length", str(len(payload)))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)
        conn.close()


def main() -> None:
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9091)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    OUT = args.out
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"proxy :{args.port} -> {UPSTREAM[0]}:{UPSTREAM[1]}, log -> {OUT}")
    server.serve_forever()


if __name__ == "__main__":
    main()

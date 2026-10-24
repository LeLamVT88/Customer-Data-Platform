#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/demo/web/serve.py — static dev server cho web demo.

`python -m http.server` KHÔNG gửi header Cache-Control, nên trình duyệt
heuristic-cache các ES module (`js/*.js`) và giữ bản cũ trong cache.
Hậu quả: sau khi `git pull`, trang vẫn chạy code cũ — dashboard có thể
hiện phần trùng lặp, event mới không được gửi, v.v.

Server này phát `Cache-Control: no-store` cho mọi response để mỗi lần
reload đều lấy code mới nhất từ đĩa.

    python src/demo/web/serve.py [--port 8081] [--root src/demo/web]
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler + header chống cache."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:
        # Giữ log gọn: chỉ in lỗi.
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            super().log_message(fmt, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8081,
                        help="cổng lắng nghe (mặc định 8081)")
    parser.add_argument("--root", type=Path, default=WEB_ROOT,
                        help="thư mục gốc phục vụ (mặc định src/demo/web)")
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"Khong tim thay thu muc goc: {root}")

    handler = functools.partial(NoCacheHandler, directory=str(root))

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server(("127.0.0.1", args.port), handler) as httpd:
        print(f"Web demo: http://127.0.0.1:{args.port}/  (root: {root})")
        print("Cache disabled — moi lan reload deu tai code moi nhat.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDa dung web server.")


if __name__ == "__main__":
    main()

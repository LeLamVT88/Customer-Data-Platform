"""Trích context quanh các đoạn quan trọng trong bundle tracker."""

import re
import sys

path = "src/demo/web/vendor/snowplow-browser-tracker.min.js"
s = open(path, encoding="utf-8").read()

keywords = sys.argv[1:] or ["function b(){", "addContextEntity:function", "function R("]
for kw in keywords:
    idxs = [m.start() for m in re.finditer(re.escape(kw), s)]
    print(f"== {kw}: {len(idxs)} hits")
    for i in idxs[:3]:
        print(repr(s[max(0, i - 100):i + 3200]))
        print("=" * 70)

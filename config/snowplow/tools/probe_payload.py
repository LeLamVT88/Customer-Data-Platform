import json
import subprocess
import sys

URL = "http://127.0.0.1:9090/com.snowplowanalytics.snowplow/tp2"

base = {
    "e": "ue",
    "ue_pr": {
        "data": {"product_id": "P0010001", "price": "129.99", "currency": "USD"},
        "schema": "iglu:com.cdp.demo/product_view/jsonschema/1-0-0",
    },
    "dtm": "1761265800000",
    "eid": "11111111-2222-4333-8444-555555555555",
    "tv": "js-4.10.2",
    "p": "web",
    "tna": "cdp-demo-test",
    "aid": "cdp-demo",
    "uid": "test-user-1",
    "url": "http://localhost:8081/",
    "ip": "127.0.0.1",
}

wrapped = {
    "schema": "iglu:com.snowplowanalytics.snowplow/payload_data/jsonschema/1-0-4",
    "data": [base],
}

variants = [
    ("wrapped / application/json", wrapped, "application/json"),
    ("wrapped / application/json;charset=UTF-8", wrapped, "application/json; charset=UTF-8"),
    ("bare-array / application/json", [base], "application/json"),
    ("bare-array / application/json;charset=UTF-8", [base], "application/json; charset=UTF-8"),
    ("bare-obj / application/json", base, "application/json"),
    ("bare-obj / json;charset", base, "application/json; charset=UTF-8"),
]

for label, payload, ctype in variants:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    proc = subprocess.run(
        ["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code}", "-X", "POST", URL,
         "-H", f"Content-Type: {ctype}", "--data-binary", "@-"],
        input=body, capture_output=True,
    )
    print(f"{label:45s} -> HTTP {proc.stdout.decode().strip()}")

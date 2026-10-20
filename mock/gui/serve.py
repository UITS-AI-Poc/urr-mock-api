#!/usr/bin/env python3
"""Local server for the CatCloud mock GUI. Stdlib only.

Serves the static GUI and forwards /api/v1/* to the deployed AWS mock API, adding the x-api-key
header server-side so the key never reaches the browser or any file.

    python3 serve.py                 # proxy to AWS (needs a valid `aws sso login --profile aipoc-admin`)
    python3 serve.py --local         # no AWS: run the bundled Lambda handler in-process
    URR_MOCK_API_KEY=... python3 serve.py   # supply the key yourself instead of using the AWS CLI

Binds to 127.0.0.1 only.
"""

import argparse
import json
import mimetypes
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_BASE = "https://nzm36p0h50.execute-api.us-west-2.amazonaws.com/prod"
DEFAULT_KEY_ID = "p95shxgzr1"

args = None
_key_cache = {"value": None}
_local_handler = None


def get_key():
    if _key_cache["value"]:
        return _key_cache["value"]
    key = os.environ.get("URR_MOCK_API_KEY")
    if not key:
        cmd = ["aws", "apigateway", "get-api-key", "--api-key", args.key_id, "--include-value",
               "--query", "value", "--output", "text", "--region", args.region, "--profile", args.profile]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError("Could not fetch the API key with the AWS CLI. If the SSO session expired run: "
                               f"aws sso login --profile {args.profile}\n{r.stderr.strip()[:300]}")
        key = r.stdout.strip()
    _key_cache["value"] = key
    return key


def local_call(method, path, query, body):
    global _local_handler
    if _local_handler is None:
        sys.path.insert(0, str(HERE.parent / "lambda"))
        import handler  # noqa: PLC0415
        _local_handler = handler.handler
    ev = {"requestContext": {"http": {"method": method}}, "rawPath": path,
          "queryStringParameters": dict(urllib.parse.parse_qsl(query)) or None,
          "body": body.decode() if body else None}
    r = _local_handler(ev, None)
    return r["statusCode"], r["body"].encode()


def proxy_call(method, path, query, body):
    url = args.base_url.rstrip("/") + path + (("?" + query) if query else "")
    req = urllib.request.Request(url, data=body or None, method=method, headers={
        "x-api-key": get_key(), "content-type": "application/json", "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.command, self.path))

    def _send(self, status, body, ctype="application/json"):
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _api(self):
        u = urllib.parse.urlsplit(self.path)
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else b""
        t0 = time.time()
        try:
            status, out = (local_call if args.local else proxy_call)(self.command, u.path, u.query, body)
        except Exception as e:  # noqa: BLE001
            status, out = 502, json.dumps({"detail": str(e)}).encode()
        sys.stderr.write("   -> %s in %dms\n" % (status, (time.time() - t0) * 1000))
        self._send(status, out)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path.startswith("/api/v1/"):
            return self._api()
        if u.path == "/__config":
            return self._send(200, json.dumps({
                "mode": "local (bundled handler)" if args.local else "AWS",
                "base_url": None if args.local else args.base_url.rstrip("/") + "/api/v1"}).encode())
        rel = "index.html" if u.path in ("", "/") else u.path.lstrip("/")
        f = (HERE / rel).resolve()
        if HERE not in f.parents or not f.is_file() or f.name == "serve.py":
            return self._send(404, b"not found", "text/plain")
        self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")

    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path.startswith("/api/v1/"):
            return self._api()
        self._send(404, b"not found", "text/plain")

    def do_OPTIONS(self):
        self._send(204, b"")


def main():
    global args
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--local", action="store_true", help="use the bundled Lambda handler instead of AWS")
    ap.add_argument("--base-url", default=os.environ.get("URR_MOCK_BASE_URL", DEFAULT_BASE))
    ap.add_argument("--key-id", default=DEFAULT_KEY_ID)
    ap.add_argument("--profile", default="aipoc-admin")
    ap.add_argument("--region", default="us-west-2")
    args = ap.parse_args()
    if not args.local:
        try:
            get_key()
        except Exception as e:  # noqa: BLE001
            sys.exit(f"\n{e}\n\n(Or run with --local to use the bundled handler without AWS.)")
    where = "bundled handler (no AWS)" if args.local else args.base_url
    print(f"CatCloud mock GUI: http://127.0.0.1:{args.port}   ->  {where}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

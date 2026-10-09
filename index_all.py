#!/usr/bin/env python3
"""Queue and monitor a durable full-media indexing job."""

import base64
import getpass
import json
import os
import ssl
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("INDEX_API_URL", "https://127.0.0.1:8443").rstrip("/")
USERNAME = os.environ.get("IMAGEBOARD_USER", "")
PASSWORD = os.environ.get("IMAGEBOARD_PASSWORD", "")


def request(path: str, body: dict | None = None) -> dict:
    token = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    payload = None if body is None else json.dumps(body).encode()
    request = Request(f"{BASE_URL}{path}", data=payload, method="POST" if body is not None else "GET")
    request.add_header("Authorization", f"Basic {token}")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    context = ssl.create_default_context()
    if os.environ.get("INDEX_INSECURE") == "1":
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    with urlopen(request, context=context, timeout=15) as response:
        return json.loads(response.read().decode())


def main() -> None:
    global USERNAME, PASSWORD
    USERNAME = USERNAME or input("Imageboard username: ")
    PASSWORD = PASSWORD or getpass.getpass("Imageboard password: ")
    try:
        job = request("/api/index-jobs", {"path": "", "max_depth": None})
        print(f"Index job queued: {job['id']}")
        while job["status"] in {"pending", "running"}:
            print(f"{job['status']}: {job['processed']} files processed", flush=True)
            time.sleep(2)
            job = request(f"/api/index-jobs/{job['id']}")
    except HTTPError as error:
        print(f"HTTP {error.code}: indexing request failed", file=sys.stderr)
        raise SystemExit(1) from error
    except URLError as error:
        print(f"Network error: {error.reason}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(job, indent=2, default=str))
    if job["status"] != "succeeded":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

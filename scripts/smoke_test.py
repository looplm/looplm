#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


BASE_URL = os.getenv("LOOPLM_API_URL", "http://localhost:8000").rstrip("/")


def _request_json(path: str, method: str = "GET", payload: dict | None = None) -> bool:
    url = f"{BASE_URL}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            print(f"{method} {path} -> {resp.status}")
            if body:
                print(body[:500])
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        print(f"{method} {path} -> {exc.code}")
        if body:
            print(body[:500])
        return False
    except Exception as exc:
        print(f"{method} {path} -> ERROR: {exc}")
        return False


def main() -> int:
    ok = True
    ok &= _request_json("/health")
    ok &= _request_json("/api/v1/traces")

    if os.getenv("RUN_ANALYSIS_PREVIEW") == "1":
        ok &= _request_json(
            "/api/v1/analysis/preview",
            method="POST",
            payload={
                "trace": {"id": "smoke-test", "spans": []},
                "instructions": "Smoke test. Reply briefly.",
            },
        )

    if os.getenv("RUN_LANGSMITH_PING") == "1":
        ok &= _request_json("/api/v1/langsmith/ping")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

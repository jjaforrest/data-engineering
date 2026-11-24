#!/usr/bin/env python3
from __future__ import annotations

import os
import ssl
import sys
import urllib.error
import urllib.request

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

from api.faults import DEFAULT_SEED, faulty_page_numbers

API_URL = os.environ.get("API_URL", "").rstrip("/")
API_KEY = os.environ.get("MOCK_API_KEY", "")
SEED = int(os.environ.get("FAULT_SEED", str(DEFAULT_SEED)))

if not API_URL or not API_KEY:
    print("ERROR: Set API_URL and MOCK_API_KEY environment variables.", file=sys.stderr)
    sys.exit(1)


def send_request(
    path: str,
    api_key: str | None = API_KEY,
    timeout: float = 30.0,
) -> tuple[int, dict[str, str], bytes]:
    url = f"{API_URL}{path}"
    headers = {"Accept-Encoding": "gzip"}
    if api_key is not None:
        headers["X-API-Key"] = api_key

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()


def main() -> None:
    print(f"Target: {API_URL} (seed={SEED})")

    # 1. Cold-start / 200 OK + gzip check (timeout >= 60s)
    status, headers, _ = send_request("/v1/meta", timeout=90.0)
    assert status == 200, f"Expected 200 on /v1/meta, got {status}"
    assert headers.get("content-encoding") == "gzip", (
        f"Expected gzip encoding, got {headers.get('content-encoding')}"
    )
    print(f"[PASS] 200 OK + gzip on /v1/meta (content-encoding={headers.get('content-encoding')})")

    # 2. 401 Unauthorized check
    status, _, _ = send_request("/v1/transactions?page=1&pageSize=10", api_key="invalid-key")
    assert status == 401, f"Expected 401 on invalid key, got {status}"
    print("[PASS] 401 Unauthorized on invalid API key")

    # 3. Deterministic Injected 500 on first request + 200 on retry
    faulty_pages = faulty_page_numbers(seed=SEED, page_size=500, total_pages=200)
    assert faulty_pages, "No faulty pages found for seed; check seed/error_rate"
    target_page = faulty_pages[0]

    status_1, _, _ = send_request(f"/v1/transactions?page={target_page}&pageSize=500")
    assert status_1 == 500, (
        f"Expected injected 500 on first request to page={target_page}, got {status_1}"
    )

    status_2, headers_2, _ = send_request(f"/v1/transactions?page={target_page}&pageSize=500")
    assert status_2 == 200, f"Expected 200 on retry of page={target_page}, got {status_2}"
    assert headers_2.get("content-encoding") == "gzip", "Expected gzip on retried 200 response"
    print(f"[PASS] Injected 500 on first request (page={target_page}) -> 200 + gzip on retry")

    # 4. 429 Too Many Requests + Retry-After header (limit is 60 req / 60s)
    hit_429 = False
    for i in range(1, 70):
        st, hdrs, _ = send_request("/v1/meta")
        if st == 429:
            retry_after = hdrs.get("retry-after")
            assert retry_after and int(retry_after) >= 1, (
                f"Missing/invalid Retry-After: {retry_after}"
            )
            print(f"[PASS] 429 Too Many Requests on request #{i} with Retry-After={retry_after}s")
            hit_429 = True
            break

    assert hit_429, "Did not trigger 429 within 70 requests"
    print("\nAll smoke tests passed!")


if __name__ == "__main__":
    main()
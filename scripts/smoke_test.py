"""
Non-destructive deployment smoke-test script for PulseOps API.

Usage:
    python scripts/smoke_test.py --base-url https://pulseops-api.onrender.com
    python scripts/smoke_test.py --base-url http://127.0.0.1:8000 --expect-docs-disabled false
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx


def run_smoke_checks(
    *,
    base_url: str,
    expect_docs_disabled: bool = True,
    bearer_token: str | None = None,
) -> int:
    url = base_url.rstrip("/")
    failures = 0

    with httpx.Client(timeout=15.0) as client:
        # 1. Root endpoint
        r_root = client.get(f"{url}/")
        req_id = r_root.headers.get("X-Request-ID")
        if r_root.status_code != 200 or not req_id:
            print(f"[FAIL] GET / -> {r_root.status_code} (X-Request-ID={req_id})")
            failures += 1
        else:
            print(f"[PASS] GET / -> 200 (X-Request-ID={req_id})")

        # 2. Database health check
        r_health = client.get(f"{url}/health")
        if r_health.status_code != 200 or r_health.json().get("status") != "ok":
            print(f"[FAIL] GET /health -> {r_health.status_code} {r_health.text}")
            failures += 1
        else:
            print("[PASS] GET /health -> 200 {'status': 'ok'}")

        # 2b. Service readiness check (DB + Redis)
        r_ready = client.get(f"{url}/readiness")
        if r_ready.status_code != 200 or r_ready.json().get("status") != "ready":
            print(f"[FAIL] GET /readiness -> {r_ready.status_code} {r_ready.text}")
            failures += 1
        else:
            print(f"[PASS] GET /readiness -> 200 {r_ready.json()}")

        # 2c. Prometheus metrics endpoint
        r_metrics = client.get(f"{url}/metrics")
        if r_metrics.status_code != 200 or "pulseops_http_requests_total" not in r_metrics.text:
            print(f"[FAIL] GET /metrics -> {r_metrics.status_code}")
            failures += 1
        else:
            print("[PASS] GET /metrics -> 200 (Prometheus exposition)")

        # 3. OpenAPI docs guard
        r_docs = client.get(f"{url}/docs")
        expected_docs_status = 404 if expect_docs_disabled else 200
        if r_docs.status_code != expected_docs_status:
            print(
                f"[FAIL] GET /docs -> {r_docs.status_code} (expected {expected_docs_status})"
            )
            failures += 1
        else:
            print(f"[PASS] GET /docs -> {r_docs.status_code}")

        # 4. Unauthenticated /me rejects cleanly with 401
        r_unauth = client.get(f"{url}/me")
        if r_unauth.status_code != 401:
            print(f"[FAIL] GET /me (unauthenticated) -> {r_unauth.status_code} (expected 401)")
            failures += 1
        else:
            print("[PASS] GET /me (unauthenticated) -> 401")

        # 5. Optional authenticated read-only check
        if bearer_token:
            headers = {"Authorization": f"Bearer {bearer_token}"}
            r_me = client.get(f"{url}/me", headers=headers)
            r_orgs = client.get(f"{url}/me/organizations", headers=headers)
            if r_me.status_code != 200 or r_orgs.status_code != 200:
                print(
                    f"[FAIL] Authenticated /me={r_me.status_code}, /me/organizations={r_orgs.status_code}"
                )
                failures += 1
            else:
                print(
                    f"[PASS] Authenticated /me & /me/organizations -> 200 "
                    f"({len(r_orgs.json())} orgs)"
                )

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="PulseOps deployment smoke test")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PULSEOPS_API_URL", "http://127.0.0.1:8000"),
        help="Target PulseOps API base URL",
    )
    parser.add_argument(
        "--expect-docs-disabled",
        default="true",
        choices=["true", "false"],
        help="Whether /docs should return 404 (production default: true)",
    )
    args = parser.parse_args()

    token = os.environ.get("PULSEOPS_SMOKE_TOKEN")
    return run_smoke_checks(
        base_url=args.base_url,
        expect_docs_disabled=args.expect_docs_disabled == "true",
        bearer_token=token,
    )


if __name__ == "__main__":
    sys.exit(main())

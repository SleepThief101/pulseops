"""
Idempotent synthetic demo data seeder for PulseOps (S38).

Creates an isolated synthetic organization with a read-only ``viewer`` account,
synthetic team members, multi-month Razorpay/GitHub/CSV operational events,
SyncRuns, ActionProposals, and AuditLogs. Never uses real customer data, never
touches ``pulseops_test``, and never modifies existing user records.

Usage (from host or inside API container):
    python scripts/seed_demo_data.py
    docker exec pulseops-api python -m app.services.demo_service
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.demo_service import seed_synthetic_demo  # noqa: E402


def _resolve_dev_database_url() -> str:
    url = settings.sqlalchemy_database_url
    if "@db:" in url:
        try:
            socket.gethostbyname("db")
        except (socket.gaierror, OSError):
            url = url.replace("@db:", "@127.0.0.1:")
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed synthetic PulseOps demo workspace")
    parser.add_argument(
        "--password",
        default=os.environ.get("PULSEOPS_DEMO_PASSWORD"),
        help="Optional password to set for the read-only demo viewer account.",
    )
    args = parser.parse_args()

    engine = create_engine(_resolve_dev_database_url(), pool_pre_ping=True)
    try:
        with Session(engine) as db:
            summary = seed_synthetic_demo(db, demo_password=args.password)
    finally:
        engine.dispose()

    print("Synthetic demo workspace seeded:")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

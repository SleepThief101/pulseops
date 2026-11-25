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
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.demo_service import seed_synthetic_demo  # noqa: E402

_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}


def _resolve_dev_database_url() -> str:
    url = settings.sqlalchemy_database_url
    if "@db:" in url:
        try:
            socket.gethostbyname("db")
        except (socket.gaierror, OSError):
            url = url.replace("@db:", "@127.0.0.1:")
    return url


def _guard_target_database(url: str, *, allow_remote: bool) -> None:
    """Prevent accidental execution against pulseops_test or remote production DBs."""
    parsed = make_url(url)
    db_name = (parsed.database or "").strip()
    host = (parsed.host or "").strip().lower()

    if db_name == "pulseops_test" or "test" in db_name.lower():
        raise SystemExit(
            f"ERROR: Refusing to run demo seeder against test database {db_name!r}."
        )

    is_local = host in _LOCAL_DB_HOSTS and not settings.is_production
    if not is_local and not allow_remote:
        raise SystemExit(
            f"ERROR: Target environment={settings.environment!r}, host={host!r} is non-local or production. "
            "Pass --allow-remote-target explicitly if you truly intend to seed this target."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed synthetic PulseOps demo workspace")
    parser.add_argument(
        "--password",
        default=os.environ.get("PULSEOPS_DEMO_PASSWORD"),
        help="Optional password to set for the read-only demo viewer account.",
    )
    parser.add_argument(
        "--allow-remote-target",
        action="store_true",
        help="Explicitly confirm seeding when ENVIRONMENT=production or targeting a non-local database host.",
    )
    args = parser.parse_args()

    target_url = _resolve_dev_database_url()
    _guard_target_database(target_url, allow_remote=args.allow_remote_target)

    engine = create_engine(target_url, pool_pre_ping=True)
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

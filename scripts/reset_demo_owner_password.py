"""
Local-development-only interactive password reset for the synthetic demo owner account.

Usage:
    python scripts/reset_demo_owner_password.py
    python scripts/reset_demo_owner_password.py --check-only
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys

TARGET_EMAIL = "demo-admin@pulseops.example.com"
TARGET_ORG_NAME = "PulseOps Synthetic Demo"
TARGET_ROLE = "owner"
CONTAINER_NAME = "pulseops-api"
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 128

_BACKEND_RUNNER = r"""
import json
import sys

import httpx
from sqlalchemy import select

from app.config import settings
from app.core.auth import get_password_hash, verify_password
from app.db.session import SessionLocal, engine
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User

TARGET_EMAIL = "demo-admin@pulseops.example.com"
TARGET_ORG_NAME = "PulseOps Synthetic Demo"
TARGET_ROLE = MembershipRole.OWNER.value


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "reset"

    if settings.is_production:
        print("ERROR: Refusing to run demo password reset in production environment.", file=sys.stderr)
        return 2

    db_name = (engine.url.database or "").strip()
    db_host = (engine.url.host or "").strip().lower()
    if db_host not in {"localhost", "127.0.0.1", "::1", "db"}:
        print(f"ERROR: Refusing to run against non-local database host {db_host!r}.", file=sys.stderr)
        return 2
    if not db_name or db_name == "pulseops_test" or "test" in db_name.lower():
        print(f"ERROR: Refusing to run against database {db_name!r}.", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == TARGET_EMAIL))
        if user is None:
            print(f"ERROR: Account {TARGET_EMAIL!r} does not exist. No changes made.", file=sys.stderr)
            return 1

        memberships = db.execute(
            select(Membership.role, Organization.id, Organization.name)
            .join(Organization, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user.id)
        ).all()

        matching_owner = [
            (role, str(org_id), org_name)
            for role, org_id, org_name in memberships
            if org_name == TARGET_ORG_NAME and role == TARGET_ROLE
        ]
        if len(matching_owner) != 1:
            print(
                f"ERROR: Expected exactly 1 '{TARGET_ROLE}' membership for {TARGET_EMAIL!r} in "
                f"{TARGET_ORG_NAME!r}; found {len(matching_owner)}. No changes made.",
                file=sys.stderr,
            )
            return 1

        if mode == "check":
            print(
                json.dumps(
                    {
                        "status": "verified",
                        "database": db_name,
                        "email": user.email,
                        "organization": TARGET_ORG_NAME,
                        "role": TARGET_ROLE,
                    }
                )
            )
            return 0

        raw_payload = sys.stdin.read()
        if not raw_payload:
            print("ERROR: No password payload provided on stdin. No changes made.", file=sys.stderr)
            return 1
        payload = json.loads(raw_payload)
        password = payload.get("password", "")
        del raw_payload, payload

        if not isinstance(password, str) or not (8 <= len(password) <= 128):
            print("ERROR: Password must be between 8 and 128 characters. No changes made.", file=sys.stderr)
            return 1

        new_hash = get_password_hash(password)
        user.password_hash = new_hash
        db.commit()
        del new_hash

    with SessionLocal() as verify_db:
        refreshed = verify_db.scalar(select(User).where(User.email == TARGET_EMAIL))
        if refreshed is None or not verify_password(password, refreshed.password_hash):
            del password
            print("ERROR: Password hash verification failed after update.", file=sys.stderr)
            return 1

    try:
        resp = httpx.post(
            "http://127.0.0.1:8000/auth/login",
            json={"email": TARGET_EMAIL, "password": password},
            timeout=10.0,
        )
    finally:
        del password

    if resp.status_code != 200 or not resp.json().get("access_token"):
        print(f"ERROR: Login endpoint check failed with HTTP {resp.status_code}.", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "reset_complete",
                "database": db_name,
                "email": TARGET_EMAIL,
                "organization": TARGET_ORG_NAME,
                "role": TARGET_ROLE,
                "auth_verified": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


def _prompt_password() -> str:
    """Prompt interactively with terminal echo disabled and validate length."""
    password = getpass.getpass(
        f"Enter new temporary password for {TARGET_EMAIL} ({MIN_PASSWORD_LEN}-{MAX_PASSWORD_LEN} chars): "
    )
    if not (MIN_PASSWORD_LEN <= len(password) <= MAX_PASSWORD_LEN):
        raise ValueError(
            f"Password must be between {MIN_PASSWORD_LEN} and {MAX_PASSWORD_LEN} characters."
        )
    confirm = getpass.getpass("Confirm new temporary password: ")
    if password != confirm:
        del confirm
        raise ValueError("Passwords do not match. No changes were made.")
    del confirm
    return password


def _backend_is_importable() -> bool:
    backend_dir = Path(__file__).resolve().parent.parent / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    try:
        import app.core.auth  # noqa: F401
        import httpx  # noqa: F401
        import sqlalchemy  # noqa: F401
    except ImportError:
        return False
    return True


def _run_via_docker(mode: str, stdin_payload: str | None) -> int:
    cmd = ["docker", "exec", "-i", CONTAINER_NAME, "python", "-c", _BACKEND_RUNNER, mode]
    proc = subprocess.run(
        cmd,
        input=stdin_payload,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if proc.stderr:
        print(proc.stderr.strip(), file=sys.stderr)
    if proc.returncode != 0:
        return proc.returncode

    info = json.loads(proc.stdout.strip())
    _print_result(info)
    return 0


def _print_result(info: dict[str, object]) -> None:
    print(f"Database: {info['database']}")
    print(f"Login email: {info['email']}")
    print(f"Organization: {info['organization']}")
    print(f"Role: {info['role']}")
    if info.get("status") == "verified":
        print("Account check: passed (no changes made)")
    else:
        print("Password reset: completed (Argon2id)")
        print("Authentication verification: passed")


def _run_locally(mode: str, stdin_payload: str | None) -> int:
    """Execute runner in-process when backend dependencies are available locally."""
    import contextlib
    import io

    ns: dict[str, object] = {"__name__": "__main__"}
    prev_argv = sys.argv
    prev_stdin = sys.stdin
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    exit_code = 0
    try:
        sys.argv = ["reset_demo_owner_password", mode]
        if stdin_payload is not None:
            sys.stdin = io.StringIO(stdin_payload)
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            exec(compile(_BACKEND_RUNNER, "<reset_runner>", "exec"), ns)
    except SystemExit as exc:
        exit_code = int(exc.code) if isinstance(exc.code, int) else 1
    finally:
        sys.argv = prev_argv
        sys.stdin = prev_stdin

    err_text = stderr_buf.getvalue().strip()
    if err_text:
        print(err_text, file=sys.stderr)
    if exit_code != 0:
        return exit_code

    info = json.loads(stdout_buf.getvalue().strip())
    _print_result(info)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Interactively reset the local demo owner account password."
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Verify target account and owner membership without modifying anything.",
    )
    args = parser.parse_args()

    use_local = _backend_is_importable() and not os.environ.get("FORCE_DOCKER_EXEC")
    runner = _run_locally if use_local else _run_via_docker

    check_rc = runner("check", None)
    if check_rc != 0 or args.check_only:
        return check_rc

    try:
        password = _prompt_password()
    except (ValueError, KeyboardInterrupt, EOFError) as exc:
        print(f"\nAborted: {exc}", file=sys.stderr)
        return 1

    payload = json.dumps({"password": password})
    del password
    try:
        return runner("reset", payload)
    finally:
        del payload


if __name__ == "__main__":
    raise SystemExit(main())

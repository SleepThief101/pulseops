from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import secrets
from typing import Any
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.connectors import GitHubConnector, RazorpayConnector
from app.core.auth import get_password_hash
from app.core.security import encrypt_credentials
from app.db.session import SessionLocal
from app.models.action_proposal import ActionProposal, ProposalStatus
from app.models.audit_log import AuditLog
from app.models.event import Event
from app.models.integration import Integration, IntegrationStatus
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.sync_run import SyncRun, SyncRunStatus
from app.models.user import User
from app.schemas.event import NormalizedEvent
from app.services import event_service, integration_service

DEMO_ORG_NAME = "PulseOps Synthetic Demo"
DEMO_OWNER_EMAIL = "demo-admin@pulseops.example.com"
DEMO_MEMBER_EMAIL = "demo-ops@pulseops.example.com"

_DEMO_UUID_NS = uuid.UUID("8b2d5b7c-3e4a-4c18-9d21-10f0a0b0c0d0")


def _demo_uuid(label: str) -> uuid.UUID:
    return uuid.uuid5(_DEMO_UUID_NS, label)


def _anchor_day() -> datetime:
    """Stable UTC noon anchor for the current day so same-day re-runs are identical."""
    return datetime.now(timezone.utc).replace(
        hour=12, minute=0, second=0, microsecond=0
    )


def _build_synthetic_billing_events(anchor: datetime) -> list[NormalizedEvent]:
    """
    Generate ~3 months of consistent synthetic SaaS subscription charges,
    one-time payments, a refund, and two churned subscriptions.
    """
    events: list[NormalizedEvent] = []

    monthly_customers = [
        ("cust_synth_northstar", "plan_scale", 29900, [75, 45, 15]),
        ("cust_synth_bluepine", "plan_growth", 14900, [80, 50, 20]),
        ("cust_synth_brightleaf", "plan_growth", 14900, [70, 40, 10]),
        ("cust_synth_cinderblock", "plan_starter", 4900, [65, 35, 5]),
        ("cust_synth_driftwood", "plan_scale", 29900, [60, 30, 3]),
        ("cust_synth_emberforge", "plan_pro", 19900, [55, 25, 2]),
        ("cust_synth_frostpeak", "plan_starter", 4900, [68, 38]),
        ("cust_synth_galaxyloom", "plan_growth", 14900, [82, 52]),
    ]

    for actor, plan, amount_cents, day_offsets in monthly_customers:
        for cycle_idx, days_ago in enumerate(day_offsets, start=1):
            events.append(
                NormalizedEvent(
                    source="razorpay",
                    external_id=f"demo_rzp_sub_{actor}_c{cycle_idx}",
                    event_type="subscription.charged",
                    occurred_at=anchor - timedelta(days=days_ago, hours=2),
                    amount_minor=amount_cents,
                    currency="USD",
                    actor=actor,
                    is_synthetic=True,
                    payload={
                        "synthetic": True,
                        "plan_id": plan,
                        "billing_cycle": cycle_idx,
                        "billing_mode": "mock_fallback",
                    },
                )
            )

    # One-time payments, refund, and subscription cancellations across windows
    extra_billing = [
        NormalizedEvent(
            source="razorpay",
            external_id="demo_rzp_pay_harborwave_1",
            event_type="payment.captured",
            occurred_at=anchor - timedelta(days=12, hours=3),
            amount_minor=9900,
            currency="USD",
            actor="cust_synth_harborwave",
            is_synthetic=True,
            payload={"synthetic": True, "method": "card", "billing_mode": "mock_fallback"},
        ),
        NormalizedEvent(
            source="razorpay",
            external_id="demo_rzp_pay_harborwave_2",
            event_type="payment.captured",
            occurred_at=anchor - timedelta(days=1, hours=4),
            amount_minor=12900,
            currency="USD",
            actor="cust_synth_harborwave",
            is_synthetic=True,
            payload={"synthetic": True, "method": "upi", "billing_mode": "mock_fallback"},
        ),
        NormalizedEvent(
            source="razorpay",
            external_id="demo_rzp_ref_frostpeak_1",
            event_type="payment.refunded",
            occurred_at=anchor - timedelta(days=36, hours=1),
            amount_minor=4900,
            currency="USD",
            actor="cust_synth_frostpeak",
            is_synthetic=True,
            payload={"synthetic": True, "reason": "requested_by_customer"},
        ),
        NormalizedEvent(
            source="razorpay",
            external_id="demo_rzp_cancel_galaxyloom",
            event_type="subscription.cancelled",
            occurred_at=anchor - timedelta(days=48, hours=1),
            amount_minor=14900,
            currency="USD",
            actor="cust_synth_galaxyloom",
            is_synthetic=True,
            payload={"synthetic": True, "cancelled_at_cycle_end": True},
        ),
        NormalizedEvent(
            source="razorpay",
            external_id="demo_rzp_cancel_frostpeak",
            event_type="subscription.cancelled",
            occurred_at=anchor - timedelta(days=22, hours=1),
            amount_minor=4900,
            currency="USD",
            actor="cust_synth_frostpeak",
            is_synthetic=True,
            payload={"synthetic": True, "cancelled_at_cycle_end": False},
        ),
    ]
    events.extend(extra_billing)
    return events


def _build_synthetic_github_events(anchor: datetime) -> list[NormalizedEvent]:
    """
    Generate ~3 months of consistent synthetic GitHub PRs and Issues across
    two synthetic repositories with paired open/close events and cycle times.
    """
    events: list[NormalizedEvent] = []

    pr_specs = [
        ("pulseops-demo/control-tower", 110, "dev_aria", 78, 6.0, "Add tenant query guard"),
        ("pulseops-demo/control-tower", 111, "dev_ben", 62, 11.5, "Streamline CSV dedup"),
        ("pulseops-demo/billing-sdk", 112, "dev_clara", 49, 4.5, "Support Razorpay test pagination"),
        ("pulseops-demo/control-tower", 113, "dev_aria", 34, 8.0, "Expose Prometheus readiness probe"),
        ("pulseops-demo/billing-sdk", 114, "dev_devon", 21, 5.2, "Harden webhook replay checks"),
        ("pulseops-demo/control-tower", 115, "dev_ben", 14, 7.5, "Add SSE event stream panel"),
        ("pulseops-demo/control-tower", 116, "dev_clara", 8, 3.8, "Optimize metrics timeseries SQL"),
        ("pulseops-demo/billing-sdk", 117, "dev_aria", 3, 4.2, "Enforce MCP key revocation"),
        # Still-open PR
        ("pulseops-demo/control-tower", 118, "dev_devon", 1, None, "Add export CSV filter badge"),
    ]
    for repo, num, actor, open_days_ago, cycle_hours, title in pr_specs:
        opened_at = anchor - timedelta(days=open_days_ago, hours=10)
        events.append(
            NormalizedEvent(
                source="github",
                external_id=f"demo_gh_{repo}_pr_{num}_opened",
                event_type="pr.opened",
                occurred_at=opened_at,
                actor=actor,
                payload={"synthetic": True, "repo": repo, "number": num, "title": title, "state": "open"},
            )
        )
        if cycle_hours is not None:
            merged_at = opened_at + timedelta(hours=cycle_hours)
            events.append(
                NormalizedEvent(
                    source="github",
                    external_id=f"demo_gh_{repo}_pr_{num}_merged",
                    event_type="pr.merged",
                    occurred_at=merged_at,
                    actor=actor,
                    payload={
                        "synthetic": True,
                        "repo": repo,
                        "number": num,
                        "title": title,
                        "state": "closed",
                        "cycle_time_hours": cycle_hours,
                    },
                )
            )

    issue_specs = [
        ("pulseops-demo/control-tower", 210, "dev_aria", 74, 18.0, "Fix chart axis label wrapping"),
        ("pulseops-demo/billing-sdk", 211, "dev_ben", 58, 22.5, "Handle zero-amount invoice row"),
        ("pulseops-demo/control-tower", 212, "dev_clara", 44, 12.0, "Normalize timezone on CSV import"),
        ("pulseops-demo/control-tower", 213, "dev_devon", 27, 9.5, "Expose X-Request-ID on CORS"),
        ("pulseops-demo/billing-sdk", 214, "dev_aria", 17, 14.5, "Document ARQ retry recovery"),
        ("pulseops-demo/control-tower", 215, "dev_ben", 6, 8.0, "Add copilot cache invalidation"),
        ("pulseops-demo/control-tower", 216, "dev_clara", 2, 6.5, "Validate AI tool schema extras"),
        # Open issues (no issue.closed event)
        ("pulseops-demo/control-tower", 217, "dev_devon", 11, None, "Add date preset shortcuts"),
        ("pulseops-demo/billing-sdk", 218, "dev_aria", 4, None, "Support multi-currency CSV formatting"),
        ("pulseops-demo/control-tower", 219, "dev_ben", 1, None, "Highlight churn spikes in overview"),
    ]
    for repo, num, actor, open_days_ago, cycle_hours, title in issue_specs:
        opened_at = anchor - timedelta(days=open_days_ago, hours=9)
        events.append(
            NormalizedEvent(
                source="github",
                external_id=f"demo_gh_{repo}_issue_{num}_opened",
                event_type="issue.opened",
                occurred_at=opened_at,
                actor=actor,
                payload={"synthetic": True, "repo": repo, "number": num, "title": title, "state": "open"},
            )
        )
        if cycle_hours is not None:
            closed_at = opened_at + timedelta(hours=cycle_hours)
            events.append(
                NormalizedEvent(
                    source="github",
                    external_id=f"demo_gh_{repo}_issue_{num}_closed",
                    event_type="issue.closed",
                    occurred_at=closed_at,
                    actor=actor,
                    payload={
                        "synthetic": True,
                        "repo": repo,
                        "number": num,
                        "title": title,
                        "state": "closed",
                        "cycle_time_hours": cycle_hours,
                    },
                )
            )

    return events


def _seed_demo_sync_runs(
    db: Session,
    *,
    organization_id: uuid.UUID,
    by_provider: dict[str, Integration],
    anchor: datetime,
) -> int:
    """Idempotently seed historical SyncRun records for demo integrations."""
    specs: list[tuple[str, str, int, str, int, int, int, str | None]] = [
        ("sr_rzp_60d", "razorpay", 60, SyncRunStatus.COMPLETED.value, 12, 12, 0, None),
        ("sr_gh_45d", "github", 45, SyncRunStatus.FAILED.value, 0, 0, 0, "Transient synthetic API timeout (recovered on retry)"),
        ("sr_gh_44d", "github", 44, SyncRunStatus.COMPLETED.value, 18, 18, 0, None),
        ("sr_rzp_15d", "razorpay", 15, SyncRunStatus.COMPLETED.value, 10, 8, 2, None),
        ("sr_gh_3d", "github", 3, SyncRunStatus.COMPLETED.value, 14, 10, 4, None),
        ("sr_rzp_1d", "razorpay", 1, SyncRunStatus.COMPLETED.value, 8, 5, 3, None),
    ]
    rows = []
    for key, provider, days_ago, status, recv, ins, skip, err in specs:
        integ = by_provider.get(provider)
        if integ is None:
            continue
        started = anchor - timedelta(days=days_ago, minutes=15)
        finished = started + timedelta(seconds=3)
        rows.append(
            {
                "id": _demo_uuid(f"sync_run:{key}"),
                "organization_id": organization_id,
                "integration_id": integ.id,
                "status": status,
                "events_received": recv,
                "events_inserted": ins,
                "events_skipped": skip,
                "error_message": err,
                "started_at": started,
                "finished_at": finished,
            }
        )
        integ.last_synced_at = max(integ.last_synced_at or finished, finished)

    if not rows:
        return 0
    stmt = (
        pg_insert(SyncRun)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(SyncRun.id)
    )
    return len(list(db.scalars(stmt).all()))


def _seed_demo_proposals_and_audits(
    db: Session,
    *,
    organization_id: uuid.UUID,
    owner_id: uuid.UUID,
    member_id: uuid.UUID,
    by_provider: dict[str, Integration],
    anchor: datetime,
) -> tuple[int, int]:
    """Idempotently seed sample ActionProposals and AuditLog records."""
    proposals_inserted = 0
    rzp = by_provider.get("razorpay")
    gh = by_provider.get("github")

    proposal_rows = []
    if rzp is not None:
        proposal_rows.append(
            {
                "id": _demo_uuid("proposal:rzp_executed"),
                "organization_id": organization_id,
                "proposed_by_user_id": member_id,
                "tool_name": "sync_organization_integration",
                "title": "Sync razorpay integration",
                "description": "Backfill recent synthetic Razorpay billing and churn events.",
                "arguments": {"integration_id": str(rzp.id), "full_sync": False},
                "status": ProposalStatus.EXECUTED.value,
                "reviewed_by_user_id": owner_id,
                "reviewed_at": anchor - timedelta(days=2, hours=1),
                "execution_result": {"provider": "razorpay", "inserted_count": 5, "skipped_count": 0},
                "created_at": anchor - timedelta(days=2, hours=2),
            }
        )
    if gh is not None:
        proposal_rows.append(
            {
                "id": _demo_uuid("proposal:gh_pending"),
                "organization_id": organization_id,
                "proposed_by_user_id": member_id,
                "tool_name": "sync_organization_integration",
                "title": "Sync github integration",
                "description": "Pull latest synthetic PRs and open issues for weekly review.",
                "arguments": {"integration_id": str(gh.id), "full_sync": True},
                "status": ProposalStatus.PENDING.value,
                "reviewed_by_user_id": None,
                "reviewed_at": None,
                "execution_result": None,
                "created_at": anchor - timedelta(hours=4),
            }
        )

    if proposal_rows:
        stmt_p = (
            pg_insert(ActionProposal)
            .values(proposal_rows)
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(ActionProposal.id)
        )
        proposals_inserted = len(list(db.scalars(stmt_p).all()))

    audit_rows = [
        {
            "id": _demo_uuid("audit:org_seeded"),
            "organization_id": organization_id,
            "user_id": owner_id,
            "action": "demo.workspace_initialized",
            "resource_type": "organization",
            "resource_id": str(organization_id),
            "details": {"organization_name": DEMO_ORG_NAME},
            "ip_address": "127.0.0.1",
            "created_at": anchor - timedelta(days=82),
        },
        {
            "id": _demo_uuid("audit:member_added"),
            "organization_id": organization_id,
            "user_id": owner_id,
            "action": "member.added",
            "resource_type": "membership",
            "resource_id": str(member_id),
            "details": {"target_email": DEMO_MEMBER_EMAIL, "role": MembershipRole.MEMBER.value},
            "ip_address": "127.0.0.1",
            "created_at": anchor - timedelta(days=80),
        },
    ]
    stmt_a = (
        pg_insert(AuditLog)
        .values(audit_rows)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(AuditLog.id)
    )
    audits_inserted = len(list(db.scalars(stmt_a).all()))
    return proposals_inserted, audits_inserted


def seed_synthetic_demo(
    db: Session,
    *,
    demo_password: str | None = None,
) -> dict[str, Any]:
    """
    Create or update an isolated synthetic demo organization with multi-month
    billing, churn, GitHub engineering, CSV, integration, SyncRun, team,
    ActionProposal, and AuditLog records.

    Strictly idempotent and non-destructive to existing organizations/users.
    """
    demo_email = settings.demo_account_email.strip().lower()
    viewer_password = demo_password or secrets.token_urlsafe(16)
    anchor = _anchor_day()

    org = db.scalar(select(Organization).where(Organization.name == DEMO_ORG_NAME))
    org_created = False
    if org is None:
        org = Organization(name=DEMO_ORG_NAME)
        db.add(org)
        db.flush()
        org_created = True

    def _ensure_user(email: str, password: str | None, *, update_pw: bool = False) -> tuple[User, bool]:
        u = db.scalar(select(User).where(User.email == email))
        if u is None:
            u = User(
                email=email,
                password_hash=get_password_hash(password or secrets.token_urlsafe(24)),
            )
            db.add(u)
            db.flush()
            return u, True
        if update_pw and password is not None:
            u.password_hash = get_password_hash(password)
        return u, False

    def _ensure_membership(user_id: uuid.UUID, role: str) -> bool:
        m = db.scalar(
            select(Membership).where(
                Membership.organization_id == org.id,
                Membership.user_id == user_id,
            )
        )
        if m is None:
            db.add(Membership(organization_id=org.id, user_id=user_id, role=role))
            return True
        m.role = role
        return False

    admin_user, admin_created = _ensure_user(DEMO_OWNER_EMAIL, None)
    member_user, member_created = _ensure_user(DEMO_MEMBER_EMAIL, None)
    demo_user, demo_created = _ensure_user(
        demo_email, viewer_password, update_pw=(demo_password is not None)
    )

    m1 = _ensure_membership(admin_user.id, MembershipRole.OWNER.value)
    m2 = _ensure_membership(member_user.id, MembershipRole.MEMBER.value)
    m3 = _ensure_membership(demo_user.id, MembershipRole.VIEWER.value)

    db.commit()
    db.refresh(org)
    db.refresh(demo_user)

    existing_providers = set(
        db.scalars(
            select(Integration.provider).where(Integration.organization_id == org.id)
        ).all()
    )
    integrations_created = 0
    if "razorpay" not in existing_providers:
        integration_service.create_integration(
            db,
            organization_id=org.id,
            provider="razorpay",
            credentials={"mode": "mock"},
        )
        integrations_created += 1
    if "github" not in existing_providers:
        integration_service.create_integration(
            db,
            organization_id=org.id,
            provider="github",
            credentials={"mode": "mock", "repo": "pulseops-demo/control-tower"},
        )
        integrations_created += 1
    if "fake" not in existing_providers:
        db.add(
            Integration(
                organization_id=org.id,
                provider="fake",
                status=IntegrationStatus.ACTIVE.value,
                credentials_encrypted=encrypt_credentials(json.dumps({"synthetic": True})),
            )
        )
        db.commit()
        integrations_created += 1

    integrations = integration_service.list_integrations(db, organization_id=org.id)
    by_provider = {integ.provider: integ for integ in integrations}

    total_inserted = 0
    if "razorpay" in by_provider:
        rzp_events = RazorpayConnector().fetch_events(credentials={"mode": "mock"})
        rzp_events.extend(_build_synthetic_billing_events(anchor))
        res = event_service.ingest_events(
            db,
            organization_id=org.id,
            events=rzp_events,
            integration_id=by_provider["razorpay"].id,
        )
        total_inserted += res.inserted_count

    if "github" in by_provider:
        gh_events = GitHubConnector().fetch_events(
            credentials={"mode": "mock", "repo": "pulseops-demo/control-tower"}
        )
        gh_events.extend(_build_synthetic_github_events(anchor))
        res = event_service.ingest_events(
            db,
            organization_id=org.id,
            events=gh_events,
            integration_id=by_provider["github"].id,
        )
        total_inserted += res.inserted_count

    synthetic_csv_events = [
        NormalizedEvent(
            source="csv",
            external_id="demo_csv_sub_hist_01",
            event_type="subscription.charged",
            occurred_at=anchor - timedelta(days=72),
            amount_cents=19900,
            currency="USD",
            actor="synthetic_tenant_northstar",
            payload={"synthetic": True, "plan": "growth"},
        ),
        NormalizedEvent(
            source="csv",
            external_id="demo_csv_sub_hist_02",
            event_type="subscription.charged",
            occurred_at=anchor - timedelta(days=42),
            amount_cents=19900,
            currency="USD",
            actor="synthetic_tenant_northstar",
            payload={"synthetic": True, "plan": "growth"},
        ),
        NormalizedEvent(
            source="csv",
            external_id="demo_csv_sub_01",
            event_type="subscription.charged",
            occurred_at=anchor - timedelta(days=5),
            amount_cents=19900,
            currency="USD",
            actor="synthetic_tenant_northstar",
            payload={"synthetic": True, "plan": "growth"},
        ),
        NormalizedEvent(
            source="csv",
            external_id="demo_csv_sub_02",
            event_type="subscription.charged",
            occurred_at=anchor - timedelta(days=2),
            amount_cents=29900,
            currency="USD",
            actor="synthetic_tenant_bluepine",
            payload={"synthetic": True, "plan": "scale"},
        ),
    ]
    csv_res = event_service.ingest_events(
        db,
        organization_id=org.id,
        events=synthetic_csv_events,
    )
    total_inserted += csv_res.inserted_count

    sync_runs_inserted = _seed_demo_sync_runs(
        db,
        organization_id=org.id,
        by_provider=by_provider,
        anchor=anchor,
    )
    proposals_inserted, audits_inserted = _seed_demo_proposals_and_audits(
        db,
        organization_id=org.id,
        owner_id=admin_user.id,
        member_id=member_user.id,
        by_provider=by_provider,
        anchor=anchor,
    )
    db.commit()

    totals = {
        "users_total": db.scalar(
            select(func.count(Membership.id)).where(Membership.organization_id == org.id)
        ),
        "integrations_total": db.scalar(
            select(func.count(Integration.id)).where(Integration.organization_id == org.id)
        ),
        "events_total": db.scalar(
            select(func.count(Event.id)).where(Event.organization_id == org.id)
        ),
        "sync_runs_total": db.scalar(
            select(func.count(SyncRun.id)).where(SyncRun.organization_id == org.id)
        ),
        "action_proposals_total": db.scalar(
            select(func.count(ActionProposal.id)).where(ActionProposal.organization_id == org.id)
        ),
        "audit_logs_total": db.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.organization_id == org.id)
        ),
    }

    return {
        "organization_id": str(org.id),
        "organization_name": org.name,
        "organizations_created": 1 if org_created else 0,
        "users_created": int(admin_created) + int(member_created) + int(demo_created),
        "memberships_created": int(m1) + int(m2) + int(m3),
        "integrations_created": integrations_created,
        "events_inserted": total_inserted,
        "sync_runs_inserted": sync_runs_inserted,
        "action_proposals_inserted": proposals_inserted,
        "audit_logs_inserted": audits_inserted,
        "demo_user_id": str(demo_user.id),
        "demo_user_email": demo_user.email,
        "demo_role": MembershipRole.VIEWER.value,
        "copilot_daily_limit": settings.demo_copilot_daily_limit,
        "demo_org_totals": totals,
    }


if __name__ == "__main__":
    with SessionLocal() as session:
        result = seed_synthetic_demo(session)
    print(json.dumps(result, indent=2))

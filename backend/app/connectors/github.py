from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.connectors.base import BaseConnector, ConnectorAuthError, ConnectorError
from app.schemas.event import NormalizedEvent

def _mock_gh_base_time() -> datetime:
    return datetime.now(timezone.utc).replace(
        hour=10, minute=0, second=0, microsecond=0
    ) - timedelta(days=3)

_MOCK_GITHUB_EVENTS: list[dict[str, Any]] = [
    {
        "external_id": "gh_pr_101_opened",
        "event_type": "pr.opened",
        "offset_hours": 0,
        "actor": "alice",
        "payload": {"number": 101, "title": "Add billing retry handler", "state": "open"},
    },
    {
        "external_id": "gh_pr_100_merged",
        "event_type": "pr.merged",
        "offset_hours": 6,
        "actor": "bob",
        "payload": {
            "number": 100,
            "title": "Fix webhook signature validation",
            "state": "closed",
            "cycle_time_hours": 5.5,
        },
    },
    {
        "external_id": "gh_issue_201_opened",
        "event_type": "issue.opened",
        "offset_hours": 12,
        "actor": "carol",
        "payload": {"number": 201, "title": "Dashboard date filter resets", "state": "open"},
    },
    {
        "external_id": "gh_issue_200_closed",
        "event_type": "issue.closed",
        "offset_hours": 20,
        "actor": "alice",
        "payload": {
            "number": 200,
            "title": "Optimize Neon pool settings",
            "state": "closed",
            "cycle_time_hours": 14.0,
        },
    },
]


def _parse_iso_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


class GitHubConnector(BaseConnector):
    """
    GitHub REST API connector syncing repository Pull Requests and Issues,
    computing issue/PR cycle time and supporting deterministic mock mode.
    """

    provider = "github"
    base_url = "https://api.github.com"

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._http_client = http_client

    def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        if not isinstance(credentials, dict):
            raise ConnectorAuthError("GitHub credentials must be a JSON object.")

        repo = str(credentials.get("repo") or "").strip()
        if "/" not in repo or len(repo.split("/")) != 2 or not all(repo.split("/")):
            raise ConnectorAuthError(
                "GitHub credentials must include 'repo' in 'owner/name' format."
            )

        mode = str(credentials.get("mode") or "").strip().lower()
        if mode == "mock":
            return True

        token = str(credentials.get("access_token") or "").strip()
        if not token:
            raise ConnectorAuthError(
                "GitHub credentials require 'access_token' or mode='mock'."
            )
        return True

    def fetch_events(
        self,
        credentials: dict[str, Any],
        since: datetime | None = None,
    ) -> list[NormalizedEvent]:
        self.validate_credentials(credentials)

        repo = str(credentials["repo"]).strip()
        mode = str(credentials.get("mode") or "").strip().lower()

        since_utc: datetime | None = None
        if since is not None:
            since_utc = _parse_iso_dt(since)

        if mode == "mock":
            raw_items = credentials.get("mock_events", _MOCK_GITHUB_EVENTS)
            results: list[NormalizedEvent] = []
            for item in raw_items:
                dt = _mock_gh_base_time() + timedelta(hours=item.get("offset_hours", 0))
                evt = NormalizedEvent(
                    source=self.provider,
                    external_id=str(item["external_id"]),
                    event_type=str(item["event_type"]),
                    occurred_at=dt,
                    actor=item.get("actor"),
                    payload={**dict(item.get("payload") or {}), "repo": repo},
                )
                if since_utc is None or evt.occurred_at >= since_utc:
                    results.append(evt)
            return results

        token = str(credentials["access_token"]).strip()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        try:
            raw_records = self._fetch_repo_records(repo=repo, headers=headers, since=since_utc)
            events = [self.normalize({**rec, "_repo": repo}) for rec in raw_records]
            if since_utc is not None:
                events = [e for e in events if e.occurred_at >= since_utc]
            return events
        except ConnectorAuthError:
            raise
        except (httpx.HTTPError, ConnectorError, ValueError) as exc:
            raise ConnectorError(f"GitHub API sync failed: {exc}") from exc

    def _fetch_repo_records(
        self,
        *,
        repo: str,
        headers: dict[str, str],
        since: datetime | None,
        per_page: int = 100,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        pr_base_params: dict[str, Any] = {
            "state": "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": per_page,
        }
        issue_base_params: dict[str, Any] = {"state": "all", "per_page": per_page}
        if since is not None:
            issue_base_params["since"] = since.isoformat()

        def _get_paginated(path: str, base_params: dict[str, Any]) -> list[dict[str, Any]]:
            url = f"{self.base_url}{path}"
            collected: list[dict[str, Any]] = []
            for page in range(1, max_pages + 1):
                params = {**base_params, "page": page}
                if self._http_client is not None:
                    resp = self._http_client.get(url, headers=headers, params=params)
                else:
                    with httpx.Client(timeout=10.0) as client:
                        resp = client.get(url, headers=headers, params=params)
                if resp.status_code == 401:
                    raise ConnectorAuthError("GitHub rejected the access token.")
                if resp.status_code == 403:
                    raise ConnectorAuthError(
                        "GitHub denied access (token permissions or API rate limit exceeded)."
                    )
                if resp.status_code == 404:
                    raise ConnectorError(
                        f"GitHub repository {repo!r} was not found or token lacks read access."
                    )
                resp.raise_for_status()
                batch_raw = resp.json()
                if not isinstance(batch_raw, list):
                    raise ConnectorError("Unexpected non-list response from GitHub API.")
                batch = list(batch_raw)
                collected.extend(batch)
                if len(batch) < per_page:
                    break
            return collected

        pulls = _get_paginated(f"/repos/{repo}/pulls", pr_base_params)
        issues_raw = _get_paginated(f"/repos/{repo}/issues", issue_base_params)
        # GitHub's /issues endpoint includes PRs; exclude items with 'pull_request' key
        issues = [item for item in issues_raw if "pull_request" not in item]

        tagged: list[dict[str, Any]] = []
        for pr in pulls:
            tagged.append({**pr, "_kind": "pull_request"})
        for issue in issues:
            tagged.append({**issue, "_kind": "issue"})
        return tagged

    def normalize(self, raw_event: dict[str, Any]) -> NormalizedEvent:
        """
        Normalize a GitHub REST API PR/Issue object or webhook payload into a
        NormalizedEvent with cycle_time_hours computed when closed/merged.
        """
        repo = str(
            raw_event.get("_repo")
            or (raw_event.get("repository") or {}).get("full_name")
            or "unknown/repo"
        )

        # Handle GitHub webhook envelope containing 'pull_request' or 'issue'
        if "pull_request" in raw_event and isinstance(raw_event["pull_request"], dict):
            pr = raw_event["pull_request"]
            action = str(raw_event.get("action") or "opened")
            merged = bool(pr.get("merged"))
            event_type = (
                "pr.merged"
                if merged
                else ("pr.closed" if action == "closed" else "pr.opened")
            )
            obj = pr
            kind = "pr"
        elif "issue" in raw_event and isinstance(raw_event["issue"], dict):
            issue = raw_event["issue"]
            action = str(raw_event.get("action") or "opened")
            event_type = "issue.closed" if action == "closed" else "issue.opened"
            obj = issue
            kind = "issue"
        else:
            obj = raw_event
            is_pr = raw_event.get("_kind") == "pull_request" or "merged_at" in raw_event
            kind = "pr" if is_pr else "issue"
            if is_pr:
                if obj.get("merged_at"):
                    event_type = "pr.merged"
                elif obj.get("state") == "closed":
                    event_type = "pr.closed"
                else:
                    event_type = "pr.opened"
            else:
                event_type = (
                    "issue.closed" if obj.get("state") == "closed" else "issue.opened"
                )

        number = obj.get("number")
        external_id = f"gh_{repo}_{kind}_{number}_{event_type}"

        created_raw = obj.get("created_at")
        created_at = (
            _parse_iso_dt(created_raw) if created_raw else datetime.now(timezone.utc)
        )
        end_raw = obj.get("merged_at") or obj.get("closed_at")
        end_at = _parse_iso_dt(end_raw) if end_raw else None

        cycle_time_hours: float | None = None
        if end_at is not None:
            cycle_time_hours = round(
                max((end_at - created_at).total_seconds() / 3600.0, 0.0), 2
            )

        occurred_at = end_at or created_at
        user_obj = obj.get("user") or {}
        actor = user_obj.get("login") if isinstance(user_obj, dict) else None

        payload: dict[str, Any] = {
            "repo": repo,
            "number": number,
            "title": obj.get("title"),
            "state": obj.get("state"),
        }
        if cycle_time_hours is not None:
            payload["cycle_time_hours"] = cycle_time_hours

        return NormalizedEvent(
            source=self.provider,
            external_id=external_id,
            event_type=event_type,
            occurred_at=occurred_at,
            actor=str(actor) if actor else None,
            payload=payload,
        )

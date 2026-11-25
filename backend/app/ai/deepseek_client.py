from __future__ import annotations

from collections.abc import Iterator
import json
from typing import Any

import httpx

from app.config import settings


class DeepSeekError(Exception):
    """Raised when DeepSeek API communication fails."""


class DeepSeekClient:
    """
    Lightweight DeepSeek Chat Completions client (OpenAI-compatible REST API).

    Enforces ``max_tokens`` cost/budget limits per completion call and falls
    back to deterministic local analytics when DEEPSEEK_API_KEY is unset.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else settings.deepseek_api_key or ""
        ).strip()
        self.base_url = (base_url or settings.deepseek_base_url).rstrip("/")
        self.model = model or settings.deepseek_model
        self.max_tokens = (
            max_tokens if max_tokens is not None else settings.deepseek_max_tokens
        )
        self._http_client = http_client

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat_completions(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send a budget-capped chat completion request to DeepSeek."""
        if not self.is_configured:
            raise DeepSeekError("DEEPSEEK_API_KEY is not configured.")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        try:
            if self._http_client is not None:
                resp = self._http_client.post(url, json=payload, headers=headers)
            else:
                with httpx.Client(timeout=20.0) as client:
                    resp = client.post(url, json=payload, headers=headers)
            if resp.status_code in (401, 403):
                raise DeepSeekError("DeepSeek authentication failed.")
            if resp.status_code == 429:
                raise DeepSeekError("DeepSeek API rate limit exceeded.")
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise DeepSeekError("DeepSeek API returned a non-object response.")
            return dict(data)
        except DeepSeekError:
            raise
        except httpx.TimeoutException as exc:
            raise DeepSeekError("DeepSeek API request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            raise DeepSeekError(
                f"DeepSeek API returned HTTP {exc.response.status_code}."
            ) from exc
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise DeepSeekError("DeepSeek API request failed.") from exc

    def stream_chat_completions(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[str]:
        """
        Stream budget-capped chat completion tokens from DeepSeek SSE API.
        Never makes external calls when DEEPSEEK_API_KEY is unset.
        """
        if not self.is_configured:
            raise DeepSeekError("DEEPSEEK_API_KEY is not configured.")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        try:
            if self._http_client is not None:
                with self._http_client.stream(
                    "POST", url, json=payload, headers=headers
                ) as resp:
                    if resp.status_code in (401, 403):
                        raise DeepSeekError("DeepSeek authentication failed.")
                    if resp.status_code == 429:
                        raise DeepSeekError("DeepSeek API rate limit exceeded.")
                    resp.raise_for_status()
                    yield from self._iter_sse_deltas(resp)
            else:
                with httpx.Client(timeout=30.0) as client:
                    with client.stream(
                        "POST", url, json=payload, headers=headers
                    ) as resp:
                        if resp.status_code in (401, 403):
                            raise DeepSeekError("DeepSeek authentication failed.")
                        if resp.status_code == 429:
                            raise DeepSeekError("DeepSeek API rate limit exceeded.")
                        resp.raise_for_status()
                        yield from self._iter_sse_deltas(resp)
        except DeepSeekError:
            raise
        except httpx.TimeoutException as exc:
            raise DeepSeekError("DeepSeek streaming request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            raise DeepSeekError(
                f"DeepSeek streaming API returned HTTP {exc.response.status_code}."
            ) from exc
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise DeepSeekError("DeepSeek streaming request failed.") from exc

    @staticmethod
    def _iter_sse_deltas(resp: httpx.Response) -> Iterator[str]:
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            raw = line[len("data:") :].strip()
            if raw == "[DONE]":
                break
            try:
                chunk = json.loads(raw)
            except json.JSONDecodeError:
                continue
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                yield str(content)

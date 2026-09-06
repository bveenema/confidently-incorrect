"""Thin OpenRouter chat client. One key, one schema (D-7)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from council.credentials import OpenRouterCredentials, load_credentials
from council.errors import CouncilAPIError

API_BASE = "https://openrouter.ai/api/v1"
USER_AGENT = "confidently-incorrect/0.1"
DEFAULT_TIMEOUT = 60.0


@dataclass(frozen=True)
class Completion:
    model: str
    content: str
    tokens: int | None
    cost: float | None


class OpenRouterClient:
    """Load the API key from the state volume and post chat completions."""

    def __init__(
        self,
        state_dir: Path,
        http: httpx.Client | None = None,
        creds: OpenRouterCredentials | None = None,
    ) -> None:
        self._root = state_dir
        self._creds = creds or load_credentials(state_dir)
        self._owns_http = http is None
        self._http = http or httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )

    @property
    def credentials(self) -> OpenRouterCredentials:
        return self._creds

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def complete(self, *, model: str, system: str, user: str) -> Completion:
        try:
            response = self._http.post(
                f"{API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._creds.api_key}",
                    "Content-Type": "application/json",
                    "X-Title": "confidently-incorrect",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
        except httpx.HTTPError as exc:
            raise CouncilAPIError(f"OpenRouter request failed: {exc}") from exc
        if response.status_code >= 400:
            raise CouncilAPIError(
                f"OpenRouter HTTP {response.status_code}: {_short_body(response)}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise CouncilAPIError("OpenRouter returned non-JSON") from exc
        if not isinstance(payload, dict):
            raise CouncilAPIError("OpenRouter returned a non-object JSON body")
        content = _message_content(payload)
        tokens, cost = _usage(payload)
        used_model = payload.get("model")
        recorded = used_model if isinstance(used_model, str) and used_model else model
        return Completion(model=recorded, content=content, tokens=tokens, cost=cost)


def _message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise CouncilAPIError("OpenRouter response has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise CouncilAPIError("OpenRouter choice is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise CouncilAPIError("OpenRouter choice has no message")
    content = message.get("content")
    if not isinstance(content, str) or not content:
        raise CouncilAPIError("OpenRouter message content is empty")
    return content


def _usage(payload: dict[str, Any]) -> tuple[int | None, float | None]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None, None
    tokens: int | None = None
    total = usage.get("total_tokens")
    if isinstance(total, int) and not isinstance(total, bool):
        tokens = total
    else:
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        if (
            isinstance(prompt, int)
            and isinstance(completion, int)
            and not isinstance(prompt, bool)
            and not isinstance(completion, bool)
        ):
            tokens = prompt + completion
    cost_raw = usage.get("cost")
    cost: float | None
    if isinstance(cost_raw, bool) or not isinstance(cost_raw, (int, float)):
        cost = None
    else:
        cost = float(cost_raw)
    return tokens, cost


def _short_body(response: httpx.Response) -> str:
    text = response.text.strip().replace("\n", " ")
    if len(text) > 160:
        return text[:157] + "..."
    return text or "(empty)"

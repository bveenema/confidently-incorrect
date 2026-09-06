"""Load the OpenRouter key from the state volume. Never log the key."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from council.errors import CouncilConfigError
from council.paths import TEMPLATE_HINT, credentials_path

_PLACEHOLDER = "REPLACE_ME"

# Vendor routing (D-7). Operator may override per persona in openrouter.json.
DEFAULT_MODELS: dict[str, str] = {
    "belichuk": "anthropic/claude-sonnet-4.5",
    "brand": "openai/gpt-4o",
    "taco": "deepseek/deepseek-chat",
    "muskett": "x-ai/grok-4",
    "maddox": "google/gemini-2.5-pro",
    "maddox_draft": "google/gemini-2.5-flash",
    "lasso": "google/gemini-2.5-flash",
}


@dataclass(frozen=True)
class OpenRouterCredentials:
    api_key: str
    models: dict[str, str]


def load_credentials(root: Path | None = None) -> OpenRouterCredentials:
    path = credentials_path(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CouncilConfigError(f"missing file: {path}. {TEMPLATE_HINT}") from exc
    except json.JSONDecodeError as exc:
        raise CouncilConfigError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CouncilConfigError(f"{path} must contain a JSON object")
    key = raw.get("api_key")
    if not isinstance(key, str) or not key.strip() or key.strip() == _PLACEHOLDER:
        raise CouncilConfigError(f"{path} missing a real api_key. {TEMPLATE_HINT}")
    models = dict(DEFAULT_MODELS)
    extra = raw.get("models")
    if extra is not None:
        if not isinstance(extra, dict):
            raise CouncilConfigError(f"{path} models must be an object")
        for persona, model in extra.items():
            if (
                not isinstance(persona, str)
                or not isinstance(model, str)
                or not model.strip()
            ):
                raise CouncilConfigError(
                    f"{path} models.{persona!r} must be a non-empty string"
                )
            models[persona] = model.strip()
    return OpenRouterCredentials(api_key=key.strip(), models=models)


def credentials_exist(root: Path | None = None) -> bool:
    try:
        load_credentials(root)
    except CouncilConfigError:
        return False
    return True


def model_for(
    persona: str,
    creds: OpenRouterCredentials,
    *,
    decision_type: str | None = None,
) -> str:
    if decision_type == "draft" and persona == "maddox":
        override = creds.models.get("maddox_draft")
        if override:
            return override
    try:
        return creds.models[persona]
    except KeyError as exc:
        raise CouncilConfigError(
            f"no OpenRouter model configured for {persona}"
        ) from exc

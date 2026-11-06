"""Environment and flag parsing for the chat client."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
_MAX_MODEL_LENGTH = 200
_SECRET = re.compile(r"sk-[A-Za-z0-9_\-]{4,}")


class ConfigError(Exception):
    """Raised when the process environment or flags cannot start a session."""


@dataclass(frozen=True)
class Settings:
    """Resolved connection settings. The API key is redacted in ``repr``."""

    api_key: str
    base_url: str
    model: str

    def __repr__(self) -> str:
        return (
            "Settings(api_key='***', "
            f"base_url={self.base_url!r}, model={self.model!r})"
        )


def load_settings(
    *,
    model: str | None = None,
    base_url: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Build settings from explicit values and the process environment.

    Explicit ``model`` and ``base_url`` win over the environment. Blank values
    fall back to the defaults. ``OPENAI_API_KEY`` is required.
    """

    env = os.environ if environ is None else environ
    api_key = env.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(_missing_key_message())
    return Settings(
        api_key=api_key,
        base_url=normalize_base_url(_choose(base_url, env.get("OPENAI_BASE_URL"))),
        model=normalize_model(_choose(model, env.get("OPENAI_MODEL"))),
    )


def normalize_base_url(raw: str | None) -> str:
    """Return a canonical http(s) base URL without a trailing slash."""

    value = (raw or "").strip() or DEFAULT_BASE_URL
    if any(character.isspace() for character in value):
        raise ConfigError("OPENAI_BASE_URL cannot contain whitespace.")
    parts = urlsplit(value)
    if parts.username or parts.password:
        raise ConfigError(
            "OPENAI_BASE_URL includes a username or password. "
            "Remove it and set OPENAI_API_KEY instead."
        )
    if parts.query or parts.fragment:
        raise ConfigError("OPENAI_BASE_URL cannot include a query string or fragment.")
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ConfigError(
            "OPENAI_BASE_URL must be an absolute http or https URL, "
            f"for example {DEFAULT_BASE_URL}."
        )
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def normalize_model(raw: str | None) -> str:
    """Return a model id, or the default when ``raw`` is blank."""

    value = (raw or "").strip() or DEFAULT_MODEL
    if any(character.isspace() for character in value):
        raise ConfigError("The model name cannot contain whitespace.")
    if any(ord(character) < 32 for character in value):
        raise ConfigError("The model name cannot contain control characters.")
    if len(value) > _MAX_MODEL_LENGTH:
        raise ConfigError("The model name is too long.")
    return value


def redact_secrets(text: str) -> str:
    """Hide bearer tokens and ``sk-`` keys in text shown to the user."""

    redacted = _SECRET.sub("sk-…", text)
    return re.sub(r"(?i)bearer\s+\S+", "Bearer …", redacted)


def _choose(explicit: str | None, from_env: str | None) -> str:
    if explicit is not None:
        return explicit
    return from_env or ""


def _missing_key_message() -> str:
    return (
        "OPENAI_API_KEY is not set.\n"
        "Export your key before starting gptchat:\n"
        "\n"
        '  export OPENAI_API_KEY="sk-..."\n'
        "\n"
        "Optional settings:\n"
        f'  export OPENAI_BASE_URL="{DEFAULT_BASE_URL}"\n'
        f'  export OPENAI_MODEL="{DEFAULT_MODEL}"'
    )

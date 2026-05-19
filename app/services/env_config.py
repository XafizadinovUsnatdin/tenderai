from __future__ import annotations

import os
from pathlib import Path


def env_str(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def env_int(name: str, default: int) -> int:
    raw = env_str(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except Exception:
        return default
    return value if value > 0 else default


def _read_secret_file(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def get_openrouter_api_key() -> str | None:
    """
    Returns OpenRouter API key from env.

    Supported sources:
    - OPENROUTER_API_KEY
    - OPENROUTER_API_KEY_FILE (path to a file containing the key)
    """
    key = env_str("OPENROUTER_API_KEY")
    if key:
        return key

    key_file = env_str("OPENROUTER_API_KEY_FILE")
    if key_file:
        return _read_secret_file(key_file)

    return None


def get_openrouter_model(default: str = "openai/gpt-4o-mini") -> str:
    return env_str("OPENROUTER_MODEL") or default


def get_openrouter_base_url(default: str = "https://openrouter.ai/api/v1") -> str:
    return env_str("OPENROUTER_BASE_URL") or default


def get_openrouter_max_tokens(default: int = 4096) -> int:
    return env_int("OPENROUTER_MAX_TOKENS", default)


def get_openrouter_max_tokens_small(default: int = 1024) -> int:
    return env_int("OPENROUTER_MAX_TOKENS_SMALL", default)


def get_gemini_api_key() -> str | None:
    """
    Returns Gemini API key from env.

    Supported sources:
    - GEMINI_API_KEY
    - GEMINI_API_KEY_FILE (path to a file containing the key)
    """
    key = env_str("GEMINI_API_KEY")
    if key:
        return key

    key_file = env_str("GEMINI_API_KEY_FILE")
    if key_file:
        return _read_secret_file(key_file)

    return None


def get_gemini_model(default: str = "gemini-2.0-flash") -> str:
    return env_str("GEMINI_MODEL") or default


def get_gemini_base_url(default: str = "https://generativelanguage.googleapis.com") -> str:
    return env_str("GEMINI_BASE_URL") or default


def get_gemini_api_version(default: str = "v1beta") -> str:
    return env_str("GEMINI_API_VERSION") or default


def get_gemini_max_output_tokens(default: int = 1024) -> int:
    return env_int("GEMINI_MAX_OUTPUT_TOKENS", default)

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


def env_bool(name: str, default: bool = False) -> bool:
    raw = env_str(name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


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


def get_gemini_model(default: str = "gemini-2.5-flash-lite") -> str:
    return env_str("GEMINI_MODEL") or default


def get_gemini_base_url(default: str = "https://generativelanguage.googleapis.com") -> str:
    return env_str("GEMINI_BASE_URL") or default


def get_gemini_api_version(default: str = "v1beta") -> str:
    return env_str("GEMINI_API_VERSION") or default


def get_gemini_max_output_tokens(default: int = 1024) -> int:
    return env_int("GEMINI_MAX_OUTPUT_TOKENS", default)


def get_tender_archive_db_path(default: str = "data/tender_archive.sqlite3") -> str:
    return env_str("TENDER_ARCHIVE_DB_PATH") or default


def get_tender_archive_database_url() -> str | None:
    return env_str("TENDER_ARCHIVE_DATABASE_URL")


def get_tender_archive_cache_min_hits(default: int = 8) -> int:
    return env_int("TENDER_ARCHIVE_CACHE_MIN_HITS", default)


def get_tender_archive_search_limit_per_source(default: int = 20) -> int:
    return env_int("TENDER_ARCHIVE_SEARCH_LIMIT_PER_SOURCE", default)


def get_tender_archive_sync_interval_seconds(default: int = 300) -> int:
    return env_int("TENDER_ARCHIVE_SYNC_INTERVAL_SECONDS", default)


def get_tender_archive_batch_pages(default: int = 3) -> int:
    return env_int("TENDER_ARCHIVE_BATCH_PAGES", default)


def get_tender_archive_page_size(default: int = 20) -> int:
    return env_int("TENDER_ARCHIVE_PAGE_SIZE", default)


def get_tender_archive_years_back(default: int = 5) -> int:
    return env_int("TENDER_ARCHIVE_YEARS_BACK", default)


def get_app_basic_auth_username(default: str = "admin") -> str:
    return env_str("APP_BASIC_AUTH_USERNAME") or default


def get_app_basic_auth_password() -> str | None:
    password = env_str("APP_BASIC_AUTH_PASSWORD")
    if password:
        return password

    password_file = env_str("APP_BASIC_AUTH_PASSWORD_FILE")
    if password_file:
        return _read_secret_file(password_file)

    return None


def get_app_basic_auth_enabled(default: bool = False) -> bool:
    configured = env_str("APP_BASIC_AUTH_ENABLED")
    if configured is not None:
        return env_bool("APP_BASIC_AUTH_ENABLED", default)
    return bool(get_app_basic_auth_password())


def get_app_basic_auth_realm(default: str = "TenderAI") -> str:
    return env_str("APP_BASIC_AUTH_REALM") or default


def get_app_session_secret() -> str:
    secret = env_str("APP_SESSION_SECRET")
    if secret:
        return secret

    secret_file = env_str("APP_SESSION_SECRET_FILE")
    if secret_file:
        loaded = _read_secret_file(secret_file)
        if loaded:
            return loaded

    # Dev fallback; production should override this in env.
    return (get_app_basic_auth_password() or "tenderai-dev-session-secret") + "-session"


def get_app_session_cookie_name(default: str = "tenderai_session") -> str:
    return env_str("APP_SESSION_COOKIE_NAME") or default


def get_app_session_max_age_seconds(default: int = 60 * 60 * 24 * 7) -> int:
    return env_int("APP_SESSION_MAX_AGE_SECONDS", default)


def get_app_session_https_only(default: bool = False) -> bool:
    return env_bool("APP_SESSION_HTTPS_ONLY", default)

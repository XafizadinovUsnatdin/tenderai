from __future__ import annotations

from pathlib import Path

from app.services.env_config import get_tender_archive_database_url
from app.services.tender_archive_repository import TenderArchiveRepository as SqliteTenderArchiveRepository


def _is_postgres_url(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().lower()
    return normalized.startswith("postgresql://") or normalized.startswith("postgres://")


def create_tender_archive_repository(
    db_path: str | Path | None = None,
    *,
    database_url: str | None = None,
):
    resolved_database_url = (database_url or "").strip() or None
    if _is_postgres_url(resolved_database_url):
        from app.services.postgres_tender_archive_repository import PostgresTenderArchiveRepository

        return PostgresTenderArchiveRepository(resolved_database_url)

    resolved_db_path = str(db_path).strip() if db_path is not None else None
    if _is_postgres_url(resolved_db_path):
        from app.services.postgres_tender_archive_repository import PostgresTenderArchiveRepository

        return PostgresTenderArchiveRepository(resolved_db_path)

    if db_path is not None:
        return SqliteTenderArchiveRepository(db_path)

    resolved_database_url = (get_tender_archive_database_url() or "").strip() or None
    if _is_postgres_url(resolved_database_url):
        from app.services.postgres_tender_archive_repository import PostgresTenderArchiveRepository

        return PostgresTenderArchiveRepository(resolved_database_url)

    return SqliteTenderArchiveRepository(db_path)

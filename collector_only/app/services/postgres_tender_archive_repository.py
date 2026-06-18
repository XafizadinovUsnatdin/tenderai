from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row

from app.services.tender_archive_repository import (
    ALWAYS_SUCCESSFUL_SOURCE_PREFIXES,
    AUDIT_CAPTURE_COLUMNS,
    AUDIT_CAPTURE_ENDPOINT_COLUMNS,
    CATEGORY_COLUMNS,
    EVIDENCE_COLUMNS,
    EVIDENCE_FLOAT_COLUMNS,
    EVIDENCE_IDENTITY_COLUMNS,
    EVIDENCE_TABLE_COLUMNS,
    PRODUCT_COLUMNS,
    SUCCESSFUL_ETENDER_DEAL_STATUSES,
    SUCCESSFUL_ETENDER_PAYMENT_STATUSES,
    SUCCESSFUL_XARID_DEAL_STATUSES,
    SUCCESSFUL_XARID_PAYMENT_STATUSES,
    _build_search_text,
    _clean_text,
    _dedupe_phrases,
    _now_iso,
    _build_product_focus_request,
    _normalize_evidence_payload,
    _product_focus_row_key,
    _score_product_focus_row,
    _sanitize_storage_mapping,
    _sanitize_storage_value,
)


def _postgres_placeholders(count: int) -> str:
    return ", ".join("%s" for _ in range(max(0, count)))


def _search_tokens(value: str | None, *, limit: int) -> list[str]:
    cleaned = _clean_text(value).lower()
    if not cleaned:
        return []

    tokens = [
        token.lower()
        for token in re.findall(r"[\w\u0400-\u04FF]+", cleaned)
        if len(token) >= 2
    ]
    if not tokens:
        return [cleaned][:limit]
    return tokens[:limit]


def _mask_database_url(database_url: str) -> str:
    parts = urlsplit(database_url)
    if not parts.netloc or "@" not in parts.netloc:
        return database_url

    credentials, host = parts.netloc.rsplit("@", 1)
    if ":" not in credentials:
        return database_url

    username, _ = credentials.split(":", 1)
    return urlunsplit((parts.scheme, f"{username}:***@{host}", parts.path, parts.query, parts.fragment))


class PostgresTenderArchiveRepository:
    def __init__(self, database_url: str):
        self.database_url = _clean_text(database_url)
        if not self.database_url:
            raise ValueError("PostgreSQL database URL is required.")
        self._ensure_schema()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _successful_condition_sql(alias: str = "") -> tuple[str, list[Any]]:
        prefix = f"{alias}." if alias else ""
        sql = (
            "("
            f"(({prefix}source_name LIKE %s) AND ("
            f"{prefix}deal_status_name = ANY(%s) OR {prefix}payment_status = ANY(%s)"
            ")) OR "
            f"(({prefix}source_name = %s) AND ("
            f"{prefix}deal_status_name = ANY(%s) OR {prefix}payment_status = ANY(%s)"
            "))"
            ")"
        )
        params: list[Any] = [
            "xarid.uzex.uz%",
            list(SUCCESSFUL_XARID_DEAL_STATUSES),
            list(SUCCESSFUL_XARID_PAYMENT_STATUSES),
            "etender.uzex.uz",
            list(SUCCESSFUL_ETENDER_DEAL_STATUSES),
            list(SUCCESSFUL_ETENDER_PAYMENT_STATUSES),
        ]
        for source_prefix in ALWAYS_SUCCESSFUL_SOURCE_PREFIXES:
            sql = f"({sql} OR {prefix}source_name LIKE %s)"
            params.append(f"{source_prefix}%")
        return sql, params

    def _ensure_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS tender_evidences (
                id BIGSERIAL PRIMARY KEY,
                source_name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                procedure_type TEXT,
                source_url TEXT,
                lot_id TEXT,
                lot_display_no TEXT,
                product_name TEXT,
                category_name TEXT,
                condition TEXT,
                measure TEXT,
                amount DOUBLE PRECISION,
                deal_cost DOUBLE PRECISION,
                unit_price DOUBLE PRECISION,
                currency TEXT,
                region TEXT,
                provider_name TEXT,
                deal_date TEXT,
                deal_status_name TEXT,
                payment_status TEXT,
                customer_name TEXT,
                customer_inn TEXT,
                provider_inn TEXT,
                start_cost DOUBLE PRECISION,
                participants_count BIGINT,
                begin_date TEXT,
                end_date TEXT,
                time_left_second BIGINT,
                contract_file_path TEXT,
                additional_protocol_file_path TEXT,
                contract_number TEXT,
                address TEXT,
                district TEXT,
                country TEXT,
                manufacturer_country TEXT,
                status_code TEXT,
                product_code TEXT,
                category_id BIGINT,
                ingested_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payment_date TEXT,
                penalty_amount DOUBLE PRECISION
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tender_sync_state (
                state_key TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tender_categories (
                source_name TEXT NOT NULL,
                category_id BIGINT NOT NULL,
                category_name TEXT,
                raw_json TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (source_name, category_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_tender_categories_source_updated
                ON tender_categories(source_name, updated_at)
            """,
            """
            CREATE TABLE IF NOT EXISTS tender_products (
                source_name TEXT NOT NULL,
                category_id BIGINT NOT NULL,
                product_code TEXT NOT NULL,
                product_name TEXT,
                category_name TEXT,
                type_id BIGINT,
                total_count BIGINT,
                rn BIGINT,
                query_keyword TEXT,
                raw_json TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (source_name, category_id, product_code)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_tender_products_category
                ON tender_products(source_name, category_id, product_name)
            """,
            """
            CREATE TABLE IF NOT EXISTS audit_capture_catalog (
                capture_key TEXT PRIMARY KEY,
                capture_file TEXT NOT NULL,
                requested_url TEXT,
                final_url TEXT,
                title TEXT,
                site_note TEXT,
                request_count BIGINT NOT NULL,
                hosts_json TEXT NOT NULL,
                statuses_json TEXT NOT NULL,
                public_families_json TEXT NOT NULL,
                rpc_methods_json TEXT NOT NULL,
                auth_only_endpoints_json TEXT NOT NULL,
                request_failures_json TEXT NOT NULL,
                page_errors_json TEXT NOT NULL,
                source_files_json TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS audit_capture_endpoints (
                capture_key TEXT NOT NULL,
                endpoint_key TEXT NOT NULL,
                method TEXT NOT NULL,
                host TEXT NOT NULL,
                path TEXT NOT NULL,
                request_count BIGINT NOT NULL,
                families_json TEXT NOT NULL,
                sample_urls_json TEXT NOT NULL,
                statuses_json TEXT NOT NULL,
                content_types_json TEXT NOT NULL,
                resource_types_json TEXT NOT NULL,
                query_keys_json TEXT NOT NULL,
                rpc_methods_json TEXT NOT NULL,
                request_param_keys_json TEXT NOT NULL,
                response_shapes_json TEXT NOT NULL,
                sample_post_data TEXT,
                sample_response_preview TEXT,
                ingested_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (capture_key, endpoint_key)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_audit_capture_endpoints_host_path
                ON audit_capture_endpoints(host, path)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_audit_capture_endpoints_capture
                ON audit_capture_endpoints(capture_key)
            """,
            """
            CREATE OR REPLACE VIEW tender_statuses AS
            SELECT
                source_name,
                status_type,
                status_name,
                COUNT(*) AS evidence_count,
                MAX(updated_at) AS latest_updated_at
            FROM (
                SELECT source_name, 'deal_status' AS status_type, NULLIF(TRIM(deal_status_name), '') AS status_name, updated_at
                FROM tender_evidences
                UNION ALL
                SELECT source_name, 'payment_status' AS status_type, NULLIF(TRIM(payment_status), '') AS status_name, updated_at
                FROM tender_evidences
                UNION ALL
                SELECT source_name, 'status_code' AS status_type, NULLIF(TRIM(status_code), '') AS status_name, updated_at
                FROM tender_evidences
            ) statuses
            WHERE status_name IS NOT NULL
            GROUP BY source_name, status_type, status_name
            """,
        ]

        with self._connect() as conn:
            for statement in statements:
                conn.execute(statement)
            self._ensure_evidence_table_shape(conn)
            self._ensure_evidence_indexes(conn)
            self._ensure_tender_statuses_view(conn)
            self._ensure_uzbek_evidences_view(conn)

    @staticmethod
    def _create_evidence_table_sql(table_name: str) -> str:
        return f"""
            CREATE TABLE {table_name} (
                id BIGSERIAL PRIMARY KEY,
                source_name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                procedure_type TEXT,
                source_url TEXT,
                lot_id TEXT,
                lot_display_no TEXT,
                product_name TEXT,
                category_name TEXT,
                condition TEXT,
                measure TEXT,
                amount DOUBLE PRECISION,
                deal_cost DOUBLE PRECISION,
                unit_price DOUBLE PRECISION,
                currency TEXT,
                region TEXT,
                provider_name TEXT,
                deal_date TEXT,
                deal_status_name TEXT,
                payment_status TEXT,
                customer_name TEXT,
                customer_inn TEXT,
                provider_inn TEXT,
                start_cost DOUBLE PRECISION,
                participants_count BIGINT,
                begin_date TEXT,
                end_date TEXT,
                time_left_second BIGINT,
                contract_file_path TEXT,
                additional_protocol_file_path TEXT,
                contract_number TEXT,
                address TEXT,
                district TEXT,
                country TEXT,
                manufacturer_country TEXT,
                status_code TEXT,
                product_code TEXT,
                category_id BIGINT,
                ingested_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payment_date TEXT,
                penalty_amount DOUBLE PRECISION
            )
        """

    @staticmethod
    def _ensure_evidence_indexes(conn) -> None:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tender_evidences_source_date
                ON tender_evidences(source_name, deal_date)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tender_evidences_source_updated
                ON tender_evidences(source_name, updated_at)
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_tender_evidences_identity
                ON tender_evidences(
                    source_name,
                    source_url,
                    lot_id,
                    lot_display_no,
                    product_name,
                    provider_name,
                    deal_date,
                    deal_cost,
                    amount
                ) NULLS NOT DISTINCT
            """
        )
        conn.execute("DROP INDEX IF EXISTS idx_tender_evidences_search_text")

    @classmethod
    def _ensure_evidence_table_shape(cls, conn) -> None:
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'tender_evidences'
            ORDER BY ordinal_position
            """
        ).fetchall()
        existing_columns = [str(row["column_name"]) for row in rows]
        if existing_columns == EVIDENCE_TABLE_COLUMNS:
            conn.execute("DROP INDEX IF EXISTS idx_tender_evidences_search_text")
            return

        conn.execute("DROP VIEW IF EXISTS tender_evidences_uz")
        conn.execute("DROP VIEW IF EXISTS tender_statuses")
        conn.execute("DROP TABLE IF EXISTS tender_evidences__new")
        conn.execute(cls._create_evidence_table_sql("tender_evidences__new"))
        conn.execute(
            """
            CREATE UNIQUE INDEX ux_tender_evidences_identity__new
                ON tender_evidences__new(
                    source_name,
                    source_url,
                    lot_id,
                    lot_display_no,
                    product_name,
                    provider_name,
                    deal_date,
                    deal_cost,
                    amount
                ) NULLS NOT DISTINCT
            """
        )

        copy_columns = [column for column in EVIDENCE_TABLE_COLUMNS if column in existing_columns]
        if copy_columns:
            quoted = ", ".join(copy_columns)
            conn.execute(
                f"""
                INSERT INTO tender_evidences__new ({quoted})
                SELECT {quoted}
                FROM tender_evidences
                ORDER BY id
                ON CONFLICT DO NOTHING
                """
            )

        conn.execute("DROP TABLE tender_evidences")
        conn.execute("ALTER TABLE tender_evidences__new RENAME TO tender_evidences")
        conn.execute("DROP INDEX IF EXISTS ux_tender_evidences_identity__new")
        conn.execute(
            """
            SELECT setval(
                pg_get_serial_sequence('tender_evidences', 'id'),
                COALESCE((SELECT MAX(id) FROM tender_evidences), 1),
                (SELECT MAX(id) FROM tender_evidences) IS NOT NULL
            )
            """
        )

    @staticmethod
    def _ensure_tender_statuses_view(conn) -> None:
        conn.execute(
            """
            CREATE OR REPLACE VIEW tender_statuses AS
            SELECT
                source_name,
                status_type,
                status_name,
                COUNT(*) AS evidence_count,
                MAX(updated_at) AS latest_updated_at
            FROM (
                SELECT source_name, 'deal_status' AS status_type, NULLIF(TRIM(deal_status_name), '') AS status_name, updated_at
                FROM tender_evidences
                UNION ALL
                SELECT source_name, 'payment_status' AS status_type, NULLIF(TRIM(payment_status), '') AS status_name, updated_at
                FROM tender_evidences
                UNION ALL
                SELECT source_name, 'status_code' AS status_type, NULLIF(TRIM(status_code), '') AS status_name, updated_at
                FROM tender_evidences
            ) statuses
            WHERE status_name IS NOT NULL
            GROUP BY source_name, status_type, status_name
            """
        )

    @staticmethod
    def _ensure_uzbek_evidences_view(conn) -> None:
        conn.execute("DROP VIEW IF EXISTS tender_evidences_uz")
        conn.execute(
            """
            CREATE VIEW tender_evidences_uz AS
            SELECT
                customer_name AS "Buyurtmachi",
                source_name AS "Portal",
                procedure_type AS "Savdo turi",
                lot_display_no AS "Lot raqami",
                category_name AS "Tovar/xizmatning kategoriyasi",
                product_name AS "Tovar/xizmatning nomi",
                condition AS "Tovar/xizmatning texnik parametri",
                start_cost AS "Boshlang'ich summa",
                begin_date AS "Lot bosilgan/E'lon joylashtirilgan sana",
                deal_date AS "Shartnoma sanasi",
                contract_number AS "Shartnoma raqami",
                provider_name AS "Yetqazib beruvchi",
                provider_inn AS "Yetqazib beruvchi STIR raqami",
                amount AS "Miqdori",
                measure AS "O'lchov birligi",
                currency AS "Valyuta (UZS,USD,EURO,GBP,RUB)",
                deal_cost AS "Shartnoma summasi",
                deal_status_name AS "Shartnomaning holati",
                payment_date AS "To'lov qilingan sana",
                penalty_amount AS "Jarima summasi"
            FROM tender_evidences
            """
        )

    def reset_archive(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                TRUNCATE TABLE
                    tender_evidences,
                    tender_sync_state,
                    tender_categories,
                    tender_products,
                    audit_capture_endpoints,
                    audit_capture_catalog
                RESTART IDENTITY
                """
            )

    def upsert_evidences(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0

        now = _now_iso()
        updatable_columns = [column for column in EVIDENCE_COLUMNS if column != "ingested_at"]
        insert_placeholders = _postgres_placeholders(len(EVIDENCE_COLUMNS))
        identity_where = " AND ".join(
            f"{column} IS NOT DISTINCT FROM %s::DOUBLE PRECISION"
            if column in EVIDENCE_FLOAT_COLUMNS
            else f"{column} IS NOT DISTINCT FROM %s::TEXT"
            for column in EVIDENCE_IDENTITY_COLUMNS
        )

        with self._connect() as conn:
            affected = 0
            for record in records:
                payload = _normalize_evidence_payload(dict(record))
                payload.setdefault("ingested_at", now)
                payload["updated_at"] = now
                payload["source_name"] = _clean_text(payload.get("source_name"))
                payload["source_type"] = _clean_text(payload.get("source_type"))

                if not payload["source_name"] or not payload["source_type"]:
                    continue

                identity_values = [payload.get(column) for column in EVIDENCE_IDENTITY_COLUMNS]
                existing = conn.execute(
                    f"SELECT id, ingested_at FROM tender_evidences WHERE {identity_where}",
                    identity_values,
                ).fetchone()

                if existing is not None:
                    payload["ingested_at"] = existing["ingested_at"] or payload["ingested_at"]
                    update_values = [payload.get(column) for column in updatable_columns]
                    conn.execute(
                        f"""
                        UPDATE tender_evidences
                        SET {', '.join(f'{column} = %s' for column in updatable_columns)}
                        WHERE id = %s
                        """,
                        [*update_values, existing["id"]],
                    )
                    affected += 1
                    continue

                insert_values = [payload.get(column) for column in EVIDENCE_COLUMNS]
                conn.execute(
                    f"""
                    INSERT INTO tender_evidences ({', '.join(EVIDENCE_COLUMNS)})
                    VALUES ({insert_placeholders})
                    ON CONFLICT DO NOTHING
                    """,
                    insert_values,
                )
                affected += 1

        return affected

    def upsert_categories(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0

        now = _now_iso()
        insert_placeholders = _postgres_placeholders(len(CATEGORY_COLUMNS))
        updatable_columns = [
            column for column in CATEGORY_COLUMNS if column not in {"source_name", "category_id", "ingested_at"}
        ]
        update_clause = ", ".join(f"{column} = EXCLUDED.{column}" for column in updatable_columns)

        with self._connect() as conn:
            affected = 0
            for record in records:
                payload = _sanitize_storage_mapping(dict(record))
                payload.setdefault("ingested_at", now)
                payload["updated_at"] = now
                payload["source_name"] = _clean_text(payload.get("source_name"))
                payload["category_name"] = _clean_text(payload.get("category_name"))
                payload["raw_json"] = payload.get("raw_json") or "{}"

                source_name = payload["source_name"]
                category_id = payload.get("category_id")
                if not source_name:
                    continue
                try:
                    category_id = int(category_id)
                except Exception:
                    continue

                insert_values = [source_name, category_id] + [payload.get(column) for column in CATEGORY_COLUMNS[2:]]
                conn.execute(
                    f"""
                    INSERT INTO tender_categories ({', '.join(CATEGORY_COLUMNS)})
                    VALUES ({insert_placeholders})
                    ON CONFLICT (source_name, category_id) DO UPDATE SET
                        {update_clause},
                        ingested_at = tender_categories.ingested_at
                    """,
                    insert_values,
                )
                affected += 1

        return affected

    def upsert_products(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0

        now = _now_iso()
        insert_placeholders = _postgres_placeholders(len(PRODUCT_COLUMNS))
        updatable_columns = [
            column for column in PRODUCT_COLUMNS if column not in {"source_name", "category_id", "product_code", "ingested_at"}
        ]
        update_clause = ", ".join(f"{column} = EXCLUDED.{column}" for column in updatable_columns)

        with self._connect() as conn:
            affected = 0
            for record in records:
                payload = _sanitize_storage_mapping(dict(record))
                payload.setdefault("ingested_at", now)
                payload["updated_at"] = now
                payload["source_name"] = _clean_text(payload.get("source_name"))
                payload["product_code"] = _clean_text(payload.get("product_code"))
                payload["product_name"] = _clean_text(payload.get("product_name"))
                payload["category_name"] = _clean_text(payload.get("category_name"))
                payload["query_keyword"] = _clean_text(payload.get("query_keyword"))
                payload["raw_json"] = payload.get("raw_json") or "{}"

                source_name = payload["source_name"]
                product_code = payload["product_code"]
                category_id = payload.get("category_id")
                if not source_name or not product_code:
                    continue
                try:
                    category_id = int(category_id)
                except Exception:
                    continue

                insert_values = [source_name, category_id, product_code] + [payload.get(column) for column in PRODUCT_COLUMNS[3:]]
                conn.execute(
                    f"""
                    INSERT INTO tender_products ({', '.join(PRODUCT_COLUMNS)})
                    VALUES ({insert_placeholders})
                    ON CONFLICT (source_name, category_id, product_code) DO UPDATE SET
                        {update_clause},
                        ingested_at = tender_products.ingested_at
                    """,
                    insert_values,
                )
                affected += 1

        return affected

    def reset_audit_capture_catalog(self) -> None:
        with self._connect() as conn:
            conn.execute("TRUNCATE TABLE audit_capture_endpoints, audit_capture_catalog")

    def replace_audit_capture(self, capture_record: dict[str, Any], endpoint_records: list[dict[str, Any]]) -> dict[str, int]:
        now = _now_iso()
        capture_payload = _sanitize_storage_mapping(dict(capture_record))
        capture_payload.setdefault("ingested_at", now)
        capture_payload["updated_at"] = now
        capture_payload["capture_key"] = _clean_text(capture_payload.get("capture_key"))
        capture_payload["capture_file"] = _clean_text(capture_payload.get("capture_file"))
        capture_payload["requested_url"] = _clean_text(capture_payload.get("requested_url")) or None
        capture_payload["final_url"] = _clean_text(capture_payload.get("final_url")) or None
        capture_payload["title"] = _clean_text(capture_payload.get("title")) or None
        capture_payload["site_note"] = _clean_text(capture_payload.get("site_note")) or None
        capture_payload["request_count"] = int(capture_payload.get("request_count") or 0)
        capture_payload["hosts_json"] = json.dumps(capture_payload.get("hosts") or {}, ensure_ascii=False, separators=(",", ":"))
        capture_payload["statuses_json"] = json.dumps(
            capture_payload.get("statuses") or {},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        capture_payload["public_families_json"] = json.dumps(
            capture_payload.get("public_families") or [],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        capture_payload["rpc_methods_json"] = json.dumps(
            capture_payload.get("rpc_methods") or {},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        capture_payload["auth_only_endpoints_json"] = json.dumps(
            capture_payload.get("auth_only_endpoints") or [],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        capture_payload["request_failures_json"] = json.dumps(
            capture_payload.get("request_failures") or [],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        capture_payload["page_errors_json"] = json.dumps(
            capture_payload.get("page_errors") or [],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        capture_payload["source_files_json"] = json.dumps(
            capture_payload.get("source_files") or {},
            ensure_ascii=False,
            separators=(",", ":"),
        )

        capture_key = capture_payload["capture_key"]
        if not capture_key or not capture_payload["capture_file"]:
            return {"capture_records_written": 0, "endpoint_records_written": 0}

        capture_placeholders = _postgres_placeholders(len(AUDIT_CAPTURE_COLUMNS))
        capture_update_columns = [column for column in AUDIT_CAPTURE_COLUMNS if column not in {"capture_key", "ingested_at"}]
        capture_update_clause = ", ".join(f"{column} = EXCLUDED.{column}" for column in capture_update_columns)
        endpoint_placeholders = _postgres_placeholders(len(AUDIT_CAPTURE_ENDPOINT_COLUMNS))

        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO audit_capture_catalog ({', '.join(AUDIT_CAPTURE_COLUMNS)})
                VALUES ({capture_placeholders})
                ON CONFLICT (capture_key) DO UPDATE SET
                    {capture_update_clause},
                    ingested_at = audit_capture_catalog.ingested_at
                """,
                [capture_payload.get(column) for column in AUDIT_CAPTURE_COLUMNS],
            )

            conn.execute("DELETE FROM audit_capture_endpoints WHERE capture_key = %s", (capture_key,))

            endpoint_written = 0
            for record in endpoint_records:
                payload = _sanitize_storage_mapping(dict(record))
                payload.setdefault("capture_key", capture_key)
                payload.setdefault("ingested_at", now)
                payload["updated_at"] = now
                payload["endpoint_key"] = _clean_text(payload.get("endpoint_key"))
                payload["method"] = _clean_text(payload.get("method")) or "GET"
                payload["host"] = _clean_text(payload.get("host"))
                payload["path"] = _clean_text(payload.get("path")) or "/"
                payload["request_count"] = int(payload.get("request_count") or 0)
                payload["families_json"] = json.dumps(payload.get("families") or [], ensure_ascii=False, separators=(",", ":"))
                payload["sample_urls_json"] = json.dumps(payload.get("sample_urls") or [], ensure_ascii=False, separators=(",", ":"))
                payload["statuses_json"] = json.dumps(payload.get("statuses") or {}, ensure_ascii=False, separators=(",", ":"))
                payload["content_types_json"] = json.dumps(
                    payload.get("content_types") or {},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                payload["resource_types_json"] = json.dumps(
                    payload.get("resource_types") or {},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                payload["query_keys_json"] = json.dumps(payload.get("query_keys") or [], ensure_ascii=False, separators=(",", ":"))
                payload["rpc_methods_json"] = json.dumps(payload.get("rpc_methods") or [], ensure_ascii=False, separators=(",", ":"))
                payload["request_param_keys_json"] = json.dumps(
                    payload.get("request_param_keys") or [],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                payload["response_shapes_json"] = json.dumps(
                    payload.get("response_shapes") or [],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                payload["sample_post_data"] = payload.get("sample_post_data")
                payload["sample_response_preview"] = payload.get("sample_response_preview")

                if not payload["endpoint_key"] or not payload["host"]:
                    continue

                conn.execute(
                    f"""
                    INSERT INTO audit_capture_endpoints ({', '.join(AUDIT_CAPTURE_ENDPOINT_COLUMNS)})
                    VALUES ({endpoint_placeholders})
                    """,
                    [payload.get(column) for column in AUDIT_CAPTURE_ENDPOINT_COLUMNS],
                )
                endpoint_written += 1

        return {"capture_records_written": 1, "endpoint_records_written": endpoint_written}

    def get_audit_capture_stats(self, *, limit: int = 20) -> dict[str, Any]:
        with self._connect() as conn:
            summary_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS capture_count,
                    COALESCE(SUM(request_count), 0) AS request_count,
                    MAX(updated_at) AS latest_updated_at
                FROM audit_capture_catalog
                """
            ).fetchone()
            endpoint_total_row = conn.execute("SELECT COUNT(*) AS count FROM audit_capture_endpoints").fetchone()
            capture_rows = conn.execute(
                """
                SELECT
                    c.capture_key,
                    c.capture_file,
                    c.final_url,
                    c.site_note,
                    c.request_count,
                    c.updated_at,
                    COUNT(e.endpoint_key) AS endpoint_count
                FROM audit_capture_catalog c
                LEFT JOIN audit_capture_endpoints e ON e.capture_key = c.capture_key
                GROUP BY c.capture_key, c.capture_file, c.final_url, c.site_note, c.request_count, c.updated_at
                ORDER BY c.updated_at DESC, c.capture_key ASC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
            host_rows = conn.execute(
                """
                SELECT
                    host,
                    COUNT(*) AS endpoint_count,
                    COUNT(DISTINCT capture_key) AS capture_count
                FROM audit_capture_endpoints
                GROUP BY host
                ORDER BY endpoint_count DESC, host ASC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()

        return {
            "capture_count": int(summary_row["capture_count"] if summary_row else 0),
            "endpoint_count": int(endpoint_total_row["count"] if endpoint_total_row else 0),
            "request_count": int(summary_row["request_count"] if summary_row else 0),
            "latest_updated_at": summary_row["latest_updated_at"] if summary_row else None,
            "captures": [
                {
                    "capture_key": row["capture_key"],
                    "capture_file": row["capture_file"],
                    "final_url": row["final_url"],
                    "site_note": row["site_note"],
                    "request_count": int(row["request_count"] or 0),
                    "endpoint_count": int(row["endpoint_count"] or 0),
                    "updated_at": row["updated_at"],
                }
                for row in capture_rows
            ],
            "top_hosts": [
                {
                    "host": row["host"],
                    "endpoint_count": int(row["endpoint_count"] or 0),
                    "capture_count": int(row["capture_count"] or 0),
                }
                for row in host_rows
            ],
        }

    def get_recent_product_names(self, *, category_id: int, limit: int = 20) -> list[str]:
        limit = max(1, int(limit))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT product_name, MAX(updated_at) AS last_updated_at
                FROM (
                    SELECT product_name, updated_at
                    FROM tender_evidences
                    WHERE category_id = %s AND product_name IS NOT NULL AND TRIM(product_name) <> ''
                    UNION ALL
                    SELECT product_name, updated_at
                    FROM tender_products
                    WHERE category_id = %s AND product_name IS NOT NULL AND TRIM(product_name) <> ''
                ) items
                GROUP BY product_name
                ORDER BY last_updated_at DESC, product_name ASC
                LIMIT %s
                """,
                (category_id, category_id, limit),
            ).fetchall()

        return [row["product_name"] for row in rows if row["product_name"]]

    def get_product_codes(self, *, category_id: int, limit: int = 1000) -> list[str]:
        limit = max(1, int(limit))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT product_code
                FROM tender_products
                WHERE category_id = %s AND product_code IS NOT NULL AND TRIM(product_code) <> ''
                ORDER BY updated_at DESC, product_code ASC
                LIMIT %s
                """,
                (int(category_id), limit),
            ).fetchall()

        return [row["product_code"] for row in rows if row["product_code"]]

    def get_product_code_for_name(self, *, category_id: int, product_name: str) -> str | None:
        cleaned_name = _clean_text(product_name)
        if not cleaned_name:
            return None

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT product_code
                FROM tender_products
                WHERE category_id = %s AND LOWER(product_name) = LOWER(%s)
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (int(category_id), cleaned_name),
            ).fetchone()

        if row is None:
            return None

        product_code = _clean_text(row["product_code"])
        return product_code or None

    def search_product_catalog(
        self,
        *,
        query: str,
        source_names: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        cleaned_query = _clean_text(query)
        if not cleaned_query:
            return []

        tokens = _search_tokens(cleaned_query, limit=8)
        if not tokens:
            tokens = [cleaned_query.lower()]

        limit = max(1, int(limit))
        fetch_limit = max(limit * 6, 100)

        with self._connect() as conn:
            params: list[Any] = []
            where_parts: list[str] = []

            if source_names:
                where_parts.append(f"source_name IN ({_postgres_placeholders(len(source_names))})")
                params.extend(source_names)

            token_clauses: list[str] = []
            for token in tokens:
                token_clauses.append(
                    "("
                    "LOWER(COALESCE(product_name, '')) LIKE %s OR "
                    "LOWER(COALESCE(category_name, '')) LIKE %s OR "
                    "LOWER(COALESCE(product_code, '')) LIKE %s OR "
                    "LOWER(COALESCE(query_keyword, '')) LIKE %s"
                    ")"
                )
                like = f"%{token}%"
                params.extend([like, like, like, like])

            where_parts.append("(" + " OR ".join(token_clauses) + ")")
            params.append(fetch_limit)

            rows = conn.execute(
                f"""
                SELECT *
                FROM tender_products
                {"WHERE " + " AND ".join(where_parts) if where_parts else ""}
                ORDER BY updated_at DESC, product_name ASC, product_code ASC
                LIMIT %s
                """,
                params,
            ).fetchall()

        scored_rows: list[tuple[float, dict[str, Any]]] = []
        query_lower = cleaned_query.lower()

        for row in rows:
            item = dict(row)
            product_name = _clean_text(item.get("product_name")).lower()
            category_name = _clean_text(item.get("category_name")).lower()
            product_code = _clean_text(item.get("product_code")).lower()
            query_keyword = _clean_text(item.get("query_keyword")).lower()
            score = 0.0

            if query_lower == product_name:
                score += 100.0
            if query_lower == product_code:
                score += 98.0
            if query_lower == query_keyword:
                score += 95.0
            if query_lower and query_lower in product_name:
                score += 80.0
            if query_lower and query_lower in product_code:
                score += 70.0
            if query_lower and query_lower in query_keyword:
                score += 65.0
            if query_lower and query_lower in category_name:
                score += 30.0

            for token in tokens:
                if token in product_name:
                    score += 8.0
                if token in product_code:
                    score += 7.0
                if token in query_keyword:
                    score += 6.0
                if token in category_name:
                    score += 3.0

            if score > 0:
                item["score"] = score
                scored_rows.append((score, item))

        scored_rows.sort(
            key=lambda entry: (
                -entry[0],
                str(entry[1].get("updated_at") or ""),
                str(entry[1].get("product_name") or ""),
                str(entry[1].get("product_code") or ""),
            )
        )

        return [item for _, item in scored_rows[:limit]]

    def search_evidence_matches(
        self,
        *,
        query: str,
        source_names: list[str] | None = None,
        limit: int = 100,
        successful_only: bool = False,
    ) -> list[dict[str, Any]]:
        cleaned_query = _clean_text(query)
        if not cleaned_query:
            return []

        tokens = _search_tokens(cleaned_query, limit=8)
        if not tokens:
            tokens = [cleaned_query.lower()]

        limit = max(1, int(limit))
        fetch_limit = max(limit * 6, 120)

        with self._connect() as conn:
            params: list[Any] = []
            where_parts: list[str] = []

            if source_names:
                where_parts.append(f"source_name IN ({_postgres_placeholders(len(source_names))})")
                params.extend(source_names)

            if successful_only:
                successful_sql, successful_params = self._successful_condition_sql()
                where_parts.append(successful_sql)
                params.extend(successful_params)

            direct_clauses: list[str] = []
            direct_fields = [
                "product_name",
                "category_name",
                "condition",
                "measure",
                "provider_name",
                "customer_name",
                "lot_display_no",
                "lot_id",
                "deal_status_name",
                "payment_status",
                "product_code",
                "contract_number",
                "region",
                "district",
                "address",
            ]

            for field in direct_fields:
                direct_clauses.append(f"LOWER(COALESCE({field}, '')) LIKE %s")
                params.append(f"%{cleaned_query.lower()}%")

            for token in tokens:
                for field in direct_fields:
                    direct_clauses.append(f"LOWER(COALESCE({field}, '')) LIKE %s")
                    params.append(f"%{token}%")

            where_parts.append("(" + " OR ".join(direct_clauses) + ")")
            params.append(fetch_limit)

            rows = conn.execute(
                f"""
                SELECT e.*, 0.0 AS score
                FROM tender_evidences e
                {"WHERE " + " AND ".join(where_parts) if where_parts else ""}
                ORDER BY e.updated_at DESC, e.deal_date DESC
                LIMIT %s
                """,
                params,
            ).fetchall()

        scored_rows: list[tuple[float, dict[str, Any]]] = []
        query_lower = cleaned_query.lower()

        for row in rows:
            item = dict(row)
            product_name = _clean_text(item.get("product_name")).lower()
            category_name = _clean_text(item.get("category_name")).lower()
            condition = _clean_text(item.get("condition")).lower()
            search_text = _build_search_text(item).lower()
            product_code = _clean_text(item.get("product_code")).lower()
            score = 0.0

            if query_lower == product_name:
                score += 120.0
            if query_lower == product_code:
                score += 115.0
            if query_lower and query_lower in product_name:
                score += 90.0
            if query_lower and query_lower in product_code:
                score += 85.0
            if query_lower and query_lower in condition:
                score += 70.0
            if query_lower and query_lower in search_text:
                score += 60.0
            if query_lower and query_lower in category_name:
                score += 35.0

            for token in tokens:
                if token in product_name:
                    score += 10.0
                if token in product_code:
                    score += 9.0
                if token in condition:
                    score += 6.0
                if token in search_text:
                    score += 5.0
                if token in category_name:
                    score += 3.0

            if score > 0:
                item["score"] = score
                scored_rows.append((score, item))

        scored_rows.sort(
            key=lambda entry: (
                -entry[0],
                str(entry[1].get("updated_at") or ""),
                str(entry[1].get("deal_date") or ""),
                str(entry[1].get("product_name") or ""),
                str(entry[1].get("lot_display_no") or ""),
            )
        )

        return [item for _, item in scored_rows[:limit]]

    def search_product_focused_evidences(
        self,
        *,
        detected_item_type: str | None,
        selected_product_names: list[str] | None = None,
        brand: str | None = None,
        model: str | None = None,
        important_tokens: list[str] | None = None,
        auxiliary_tokens: list[str] | None = None,
        exclude_tokens: list[str] | None = None,
        source_names: list[str] | None = None,
        limit: int = 100,
        successful_only: bool = False,
        include_service_matches: bool = False,
    ) -> list[dict[str, Any]]:
        focus = _build_product_focus_request(
            detected_item_type=detected_item_type,
            selected_product_names=selected_product_names,
            brand=brand,
            model=model,
            important_tokens=important_tokens,
            auxiliary_tokens=auxiliary_tokens,
            exclude_tokens=exclude_tokens,
            include_service_matches=include_service_matches,
        )
        if not focus["anchor_phrases"] and not focus["important_terms"] and not focus["fts_tokens"]:
            return []

        limit = max(1, int(limit))
        fetch_limit = max(limit * 10, 240)
        collected_rows: list[dict[str, Any]] = []
        seen_row_keys: set[str] = set()

        def add_rows(rows: list[dict[str, Any]]) -> None:
            for row in rows:
                item = dict(row)
                row_key = _product_focus_row_key(item)
                if not row_key or row_key in seen_row_keys:
                    continue
                seen_row_keys.add(row_key)
                collected_rows.append(item)

        with self._connect() as conn:
            like_params: list[Any] = []
            like_where_parts: list[str] = []
            if source_names:
                like_where_parts.append(f"e.source_name IN ({_postgres_placeholders(len(source_names))})")
                like_params.extend(source_names)
            if successful_only:
                successful_sql, successful_params = self._successful_condition_sql("e")
                like_where_parts.append(successful_sql)
                like_params.extend(successful_params)

            positive_clauses: list[str] = []
            anchor_fields = ["product_name", "condition", "product_code", "category_name", "measure", "lot_display_no"]
            token_fields = ["product_name", "condition", "product_code", "category_name", "measure"]
            for phrase in focus["anchor_phrases"][:8]:
                clause = "(" + " OR ".join(f"LOWER(COALESCE(e.{field}, '')) LIKE %s" for field in anchor_fields) + ")"
                positive_clauses.append(clause)
                like_params.extend([f"%{phrase}%"] * len(anchor_fields))
            for token in [*focus["important_terms"][:8], *focus["auxiliary_terms"][:4]]:
                clause = "(" + " OR ".join(f"LOWER(COALESCE(e.{field}, '')) LIKE %s" for field in token_fields) + ")"
                positive_clauses.append(clause)
                like_params.extend([f"%{token}%"] * len(token_fields))

            if not positive_clauses:
                return []

            like_where_parts.append("(" + " OR ".join(positive_clauses) + ")")
            like_params.append(fetch_limit)
            add_rows(
                conn.execute(
                    f"""
                    SELECT e.*, 0.0 AS rank_score
                    FROM tender_evidences e
                    {"WHERE " + " AND ".join(like_where_parts) if like_where_parts else ""}
                    ORDER BY e.updated_at DESC, e.deal_date DESC
                    LIMIT %s
                    """,
                    like_params,
                ).fetchall()
            )

        scored_rows: list[tuple[float, dict[str, Any]]] = []
        for item in collected_rows:
            base_score_raw = item.get("rank_score")
            base_score = float(base_score_raw) if isinstance(base_score_raw, (int, float)) else 0.0
            score = _score_product_focus_row(item, focus=focus, base_score=base_score)
            if score <= 0:
                continue
            item["score"] = round(score, 4)
            scored_rows.append((score, item))

        scored_rows.sort(
            key=lambda entry: (
                -entry[0],
                str(entry[1].get("updated_at") or ""),
                str(entry[1].get("deal_date") or ""),
                str(entry[1].get("product_name") or ""),
                str(entry[1].get("lot_display_no") or ""),
            )
        )
        return [item for _, item in scored_rows[:limit]]

    def search_structured_evidences(
        self,
        *,
        source_names: list[str] | None = None,
        product_codes: list[str] | None = None,
        lot_references: list[str] | None = None,
        product_phrases: list[str] | None = None,
        include_terms: list[str] | None = None,
        exclude_terms: list[str] | None = None,
        brand: str | None = None,
        model: str | None = None,
        customer_terms: list[str] | None = None,
        provider_terms: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        order_by: str = "latest",
        limit: int = 100,
        successful_only: bool = False,
    ) -> list[dict[str, Any]]:
        if source_names is not None and not source_names:
            return []

        limit = max(1, int(limit))
        normalized_product_codes = _dedupe_phrases(product_codes or [], limit=8)
        normalized_lot_refs = _dedupe_phrases(lot_references or [], limit=8)
        normalized_product_phrases = _dedupe_phrases(product_phrases or [], limit=8)
        normalized_include_terms = _dedupe_phrases(include_terms or [], limit=10)
        normalized_exclude_terms = _dedupe_phrases(exclude_terms or [], limit=8)
        normalized_customer_terms = _dedupe_phrases(customer_terms or [], limit=6)
        normalized_provider_terms = _dedupe_phrases(provider_terms or [], limit=6)
        normalized_brand = _clean_text(brand).lower()
        normalized_model = _clean_text(model).lower()

        with self._connect() as conn:
            params: list[Any] = []
            where_parts: list[str] = []

            if source_names:
                where_parts.append(f"e.source_name IN ({_postgres_placeholders(len(source_names))})")
                params.extend(source_names)

            if successful_only:
                successful_sql, successful_params = self._successful_condition_sql("e")
                where_parts.append(successful_sql)
                params.extend(successful_params)

            anchor_clauses: list[str] = []

            if normalized_product_codes:
                anchor_clauses.append(
                    f"LOWER(COALESCE(e.product_code, '')) IN ({_postgres_placeholders(len(normalized_product_codes))})"
                )
                params.extend(normalized_product_codes)

            if normalized_lot_refs:
                placeholders = _postgres_placeholders(len(normalized_lot_refs))
                anchor_clauses.append(
                    f"(COALESCE(e.lot_id, '') IN ({placeholders}) OR COALESCE(e.lot_display_no, '') IN ({placeholders}))"
                )
                params.extend(normalized_lot_refs)
                params.extend(normalized_lot_refs)

            for phrase in normalized_product_phrases:
                like = f"%{phrase}%"
                anchor_clauses.append(
                    "("
                    "LOWER(COALESCE(e.product_name, '')) LIKE %s OR "
                    "LOWER(COALESCE(e.category_name, '')) LIKE %s OR "
                    "LOWER(COALESCE(e.condition, '')) LIKE %s OR "
                    "LOWER(COALESCE(e.measure, '')) LIKE %s OR "
                    "LOWER(COALESCE(e.product_code, '')) LIKE %s"
                    ")"
                )
                params.extend([like, like, like, like, like])

            if anchor_clauses:
                where_parts.append("(" + " OR ".join(anchor_clauses) + ")")
            elif normalized_include_terms:
                include_group: list[str] = []
                for term in normalized_include_terms:
                    like = f"%{term}%"
                    include_group.append(
                        "("
                        "LOWER(COALESCE(e.product_name, '')) LIKE %s OR "
                        "LOWER(COALESCE(e.category_name, '')) LIKE %s OR "
                        "LOWER(COALESCE(e.condition, '')) LIKE %s OR "
                        "LOWER(COALESCE(e.measure, '')) LIKE %s"
                        ")"
                    )
                    params.extend([like, like, like, like])
                where_parts.append("(" + " OR ".join(include_group) + ")")

            if normalized_brand:
                like = f"%{normalized_brand}%"
                where_parts.append(
                    "("
                    "LOWER(COALESCE(e.product_name, '')) LIKE %s OR "
                    "LOWER(COALESCE(e.condition, '')) LIKE %s OR "
                    "LOWER(COALESCE(e.measure, '')) LIKE %s OR "
                    "LOWER(COALESCE(e.product_code, '')) LIKE %s"
                    ")"
                )
                params.extend([like, like, like, like])

            if normalized_model:
                like = f"%{normalized_model}%"
                where_parts.append(
                    "("
                    "LOWER(COALESCE(e.product_name, '')) LIKE %s OR "
                    "LOWER(COALESCE(e.condition, '')) LIKE %s OR "
                    "LOWER(COALESCE(e.measure, '')) LIKE %s OR "
                    "LOWER(COALESCE(e.product_code, '')) LIKE %s"
                    ")"
                )
                params.extend([like, like, like, like])

            for field_name, terms in (
                ("customer_name", normalized_customer_terms),
                ("provider_name", normalized_provider_terms),
            ):
                if not terms:
                    continue
                org_group: list[str] = []
                for term in terms:
                    org_group.append(f"LOWER(COALESCE(e.{field_name}, '')) LIKE %s")
                    params.append(f"%{term}%")
                where_parts.append("(" + " OR ".join(org_group) + ")")

            if normalized_exclude_terms:
                exclude_group: list[str] = []
                for term in normalized_exclude_terms:
                    exclude_group.append(
                        "("
                        "LOWER(COALESCE(e.product_name, '')) LIKE %s OR "
                        "LOWER(COALESCE(e.category_name, '')) LIKE %s OR "
                        "LOWER(COALESCE(e.condition, '')) LIKE %s OR "
                        "LOWER(COALESCE(e.measure, '')) LIKE %s OR "
                        "LOWER(COALESCE(e.product_code, '')) LIKE %s"
                        ")"
                    )
                    params.extend([f"%{term}%"] * 5)
                where_parts.append("NOT (" + " OR ".join(exclude_group) + ")")

            if date_from:
                where_parts.append("COALESCE(e.deal_date, '') >= %s")
                params.append(str(date_from))

            if date_to:
                where_parts.append("COALESCE(e.deal_date, '') < %s")
                params.append(str(date_to))

            order_sql = {
                "highest_price": "COALESCE(e.unit_price, e.deal_cost, 0) DESC NULLS LAST, COALESCE(e.deal_date, '') DESC, e.updated_at DESC",
                "lowest_price": "COALESCE(e.unit_price, e.deal_cost, 0) ASC NULLS LAST, COALESCE(e.deal_date, '') DESC, e.updated_at DESC",
                "oldest": "COALESCE(e.deal_date, '') ASC NULLS LAST, e.updated_at DESC",
            }.get(order_by, "COALESCE(e.deal_date, '') DESC NULLS LAST, e.updated_at DESC")

            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT e.*, 0.0 AS score
                FROM tender_evidences e
                {"WHERE " + " AND ".join(where_parts) if where_parts else ""}
                ORDER BY {order_sql}
                LIMIT %s
                """,
                params,
            ).fetchall()

        return [dict(row) for row in rows]

    def backfill_evidence_product_codes(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                WITH latest_products AS (
                    SELECT DISTINCT ON (category_id, LOWER(product_name))
                        category_id,
                        LOWER(product_name) AS product_name_key,
                        product_code
                    FROM tender_products
                    WHERE product_name IS NOT NULL AND TRIM(product_name) <> ''
                    ORDER BY category_id, LOWER(product_name), updated_at DESC
                )
                UPDATE tender_evidences e
                SET product_code = p.product_code
                FROM latest_products p
                WHERE e.category_id IS NOT NULL
                  AND e.product_name IS NOT NULL
                  AND TRIM(e.product_name) <> ''
                  AND (e.product_code IS NULL OR TRIM(e.product_code) = '')
                  AND p.category_id = e.category_id
                  AND p.product_name_key = LOWER(e.product_name)
                """
            )

        return int(cursor.rowcount or 0)

    def search(
        self,
        *,
        match_query: str | None,
        source_names: list[str] | None = None,
        limit: int = 100,
        successful_only: bool = False,
    ) -> list[dict[str, Any]]:
        if source_names is not None and not source_names:
            return []

        limit = max(1, int(limit))
        search_terms = _search_tokens(match_query, limit=12)
        if match_query and not search_terms:
            cleaned_match = _clean_text(match_query).lower()
            if cleaned_match:
                search_terms = [cleaned_match]

        with self._connect() as conn:
            params: list[Any] = []
            where_parts: list[str] = []

            if search_terms:
                search_fields = [
                    "product_name",
                    "category_name",
                    "condition",
                    "measure",
                    "provider_name",
                    "customer_name",
                    "lot_display_no",
                    "lot_id",
                    "deal_status_name",
                    "payment_status",
                    "product_code",
                    "contract_number",
                    "region",
                    "district",
                    "address",
                ]
                term_groups: list[str] = []
                for term in search_terms:
                    term_groups.append(
                        "(" + " OR ".join(f"LOWER(COALESCE(e.{field}, '')) LIKE %s" for field in search_fields) + ")"
                    )
                    params.extend([f"%{term}%"] * len(search_fields))
                where_parts.append("(" + " AND ".join(term_groups) + ")")

            if source_names:
                where_parts.append(f"e.source_name IN ({_postgres_placeholders(len(source_names))})")
                params.extend(source_names)

            if successful_only:
                successful_sql, successful_params = self._successful_condition_sql("e")
                where_parts.append(successful_sql)
                params.extend(successful_params)

            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT e.*, 0.0 AS score
                FROM tender_evidences e
                {"WHERE " + " AND ".join(where_parts) if where_parts else ""}
                ORDER BY e.updated_at DESC, e.deal_date DESC
                LIMIT %s
                """,
                params,
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            score = item.get("score")
            item["score"] = float(score) if isinstance(score, (int, float)) else 0.0
            results.append(item)

        return results

    def get_state(self, state_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM tender_sync_state WHERE state_key = %s",
                (state_key,),
            ).fetchone()

        if row is None:
            return None

        try:
            data = json.loads(row["state_json"])
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def set_state(self, state_key: str, state: dict[str, Any]) -> None:
        now = _now_iso()
        state_key = _clean_text(state_key)
        state = _sanitize_storage_value(state)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tender_sync_state (state_key, state_json, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (state_key) DO UPDATE SET
                    state_json = EXCLUDED.state_json,
                    updated_at = EXCLUDED.updated_at
                """,
                (state_key, json.dumps(state, ensure_ascii=False, separators=(",", ":")), now),
            )

    def get_dashboard_stats(self, *, months: int = 12, limit: int = 10) -> dict[str, Any]:
        months = max(1, int(months))
        limit = max(1, int(limit))
        recent_limit = min(max(limit * 4, 24), 80)

        successful_condition, successful_params = self._successful_condition_sql()

        with self._connect() as conn:
            summary_row = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total_evidences,
                    COUNT(DISTINCT CASE WHEN provider_name IS NOT NULL AND TRIM(provider_name) <> '' THEN provider_name END) AS total_suppliers,
                    COUNT(DISTINCT CASE WHEN customer_name IS NOT NULL AND TRIM(customer_name) <> '' THEN customer_name END) AS total_customers,
                    COUNT(DISTINCT CASE WHEN product_name IS NOT NULL AND TRIM(product_name) <> '' THEN product_name END) AS unique_products_in_deals,
                    COUNT(DISTINCT CASE WHEN category_name IS NOT NULL AND TRIM(category_name) <> '' THEN category_name END) AS unique_categories_in_deals,
                    SUM(CASE WHEN deal_cost IS NOT NULL THEN deal_cost ELSE 0 END) AS total_deal_cost,
                    AVG(CASE WHEN deal_cost IS NOT NULL THEN deal_cost END) AS avg_deal_cost,
                    SUM(CASE WHEN {successful_condition} THEN 1 ELSE 0 END) AS successful_evidences,
                    SUM(CASE WHEN {successful_condition} AND deal_cost IS NOT NULL THEN deal_cost ELSE 0 END) AS successful_deal_cost,
                    MAX(deal_date) AS latest_deal_date,
                    MAX(updated_at) AS latest_updated_at
                FROM tender_evidences
                """,
                [*successful_params, *successful_params],
            ).fetchone()

            catalog_row = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM tender_categories) AS categories_total,
                    (SELECT COUNT(*) FROM tender_products) AS products_total,
                    (SELECT MAX(updated_at) FROM tender_products) AS latest_product_updated_at
                """
            ).fetchone()

            by_source_rows = conn.execute(
                """
                SELECT
                    source_name,
                    COUNT(*) AS evidence_count,
                    COUNT(DISTINCT CASE WHEN provider_name IS NOT NULL AND TRIM(provider_name) <> '' THEN provider_name END) AS supplier_count,
                    COUNT(DISTINCT CASE WHEN customer_name IS NOT NULL AND TRIM(customer_name) <> '' THEN customer_name END) AS customer_count,
                    SUM(CASE WHEN deal_cost IS NOT NULL THEN deal_cost ELSE 0 END) AS total_deal_cost,
                    MAX(updated_at) AS latest_updated_at
                FROM tender_evidences
                GROUP BY source_name
                ORDER BY evidence_count DESC, source_name ASC
                """
            ).fetchall()

            monthly_rows = conn.execute(
                """
                SELECT
                    LEFT(deal_date, 7) AS month,
                    COUNT(*) AS evidence_count,
                    COUNT(DISTINCT CASE WHEN provider_name IS NOT NULL AND TRIM(provider_name) <> '' THEN provider_name END) AS supplier_count,
                    SUM(CASE WHEN deal_cost IS NOT NULL THEN deal_cost ELSE 0 END) AS total_deal_cost
                FROM tender_evidences
                WHERE deal_date IS NOT NULL AND TRIM(deal_date) <> ''
                GROUP BY LEFT(deal_date, 7)
                ORDER BY month DESC
                LIMIT %s
                """,
                (months,),
            ).fetchall()

            top_product_rows = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(TRIM(product_name), ''), NULLIF(TRIM(category_name), ''), 'Noma''lum') AS name,
                    COUNT(*) AS evidence_count,
                    SUM(CASE WHEN deal_cost IS NOT NULL THEN deal_cost ELSE 0 END) AS total_deal_cost,
                    MAX(deal_date) AS latest_deal_date
                FROM tender_evidences
                GROUP BY name
                ORDER BY evidence_count DESC, total_deal_cost DESC, name ASC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()

            top_supplier_rows = conn.execute(
                """
                SELECT
                    provider_name AS name,
                    COUNT(*) AS evidence_count,
                    SUM(CASE WHEN deal_cost IS NOT NULL THEN deal_cost ELSE 0 END) AS total_deal_cost,
                    COUNT(DISTINCT CASE WHEN category_name IS NOT NULL AND TRIM(category_name) <> '' THEN category_name END) AS category_count,
                    MAX(deal_date) AS latest_deal_date
                FROM tender_evidences
                WHERE provider_name IS NOT NULL AND TRIM(provider_name) <> ''
                GROUP BY provider_name
                ORDER BY evidence_count DESC, total_deal_cost DESC, provider_name ASC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()

            top_customer_rows = conn.execute(
                """
                SELECT
                    customer_name AS name,
                    COUNT(*) AS evidence_count,
                    SUM(CASE WHEN deal_cost IS NOT NULL THEN deal_cost ELSE 0 END) AS total_deal_cost,
                    COUNT(DISTINCT CASE WHEN category_name IS NOT NULL AND TRIM(category_name) <> '' THEN category_name END) AS category_count,
                    MAX(deal_date) AS latest_deal_date
                FROM tender_evidences
                WHERE customer_name IS NOT NULL AND TRIM(customer_name) <> ''
                GROUP BY customer_name
                ORDER BY evidence_count DESC, total_deal_cost DESC, customer_name ASC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()

            top_category_rows = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(TRIM(category_name), ''), 'Noma''lum') AS name,
                    COUNT(*) AS evidence_count,
                    SUM(CASE WHEN deal_cost IS NOT NULL THEN deal_cost ELSE 0 END) AS total_deal_cost,
                    MAX(deal_date) AS latest_deal_date
                FROM tender_evidences
                GROUP BY name
                ORDER BY evidence_count DESC, total_deal_cost DESC, name ASC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()

            status_rows = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(TRIM(deal_status_name), ''), NULLIF(TRIM(payment_status), ''), 'Noma''lum') AS status_name,
                    COUNT(*) AS evidence_count
                FROM tender_evidences
                GROUP BY status_name
                ORDER BY evidence_count DESC, status_name ASC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()

            state_rows = conn.execute(
                """
                SELECT state_key, state_json, updated_at
                FROM tender_sync_state
                WHERE state_key LIKE 'collector:%'
                ORDER BY updated_at DESC, state_key ASC
                """
            ).fetchall()

            recent_rows = conn.execute(
                """
                SELECT
                    source_name,
                    lot_display_no,
                    lot_id,
                    product_name,
                    category_name,
                    procedure_type,
                    contract_number,
                    customer_name,
                    provider_name,
                    deal_date,
                    updated_at,
                    deal_cost,
                    currency,
                    deal_status_name,
                    payment_status,
                    source_url
                FROM tender_evidences
                ORDER BY updated_at DESC NULLS LAST, deal_date DESC NULLS LAST, source_name ASC
                LIMIT %s
                """,
                (recent_limit,),
            ).fetchall()

        return {
            "summary": {
                "total_evidences": int(summary_row["total_evidences"] if summary_row else 0),
                "total_suppliers": int(summary_row["total_suppliers"] if summary_row else 0),
                "total_customers": int(summary_row["total_customers"] if summary_row else 0),
                "unique_products_in_deals": int(summary_row["unique_products_in_deals"] if summary_row else 0),
                "unique_categories_in_deals": int(summary_row["unique_categories_in_deals"] if summary_row else 0),
                "total_deal_cost": float(summary_row["total_deal_cost"] or 0),
                "avg_deal_cost": float(summary_row["avg_deal_cost"] or 0),
                "successful_evidences": int(summary_row["successful_evidences"] if summary_row else 0),
                "successful_deal_cost": float(summary_row["successful_deal_cost"] or 0),
                "latest_deal_date": summary_row["latest_deal_date"] if summary_row else None,
                "latest_updated_at": summary_row["latest_updated_at"] if summary_row else None,
                "catalog_products_total": int(catalog_row["products_total"] if catalog_row else 0),
                "catalog_categories_total": int(catalog_row["categories_total"] if catalog_row else 0),
                "latest_product_updated_at": catalog_row["latest_product_updated_at"] if catalog_row else None,
            },
            "by_source": [
                {
                    "source_name": row["source_name"],
                    "evidence_count": int(row["evidence_count"]),
                    "supplier_count": int(row["supplier_count"]),
                    "customer_count": int(row["customer_count"]),
                    "total_deal_cost": float(row["total_deal_cost"] or 0),
                    "latest_updated_at": row["latest_updated_at"],
                }
                for row in by_source_rows
            ],
            "monthly_trend": [
                {
                    "month": row["month"],
                    "evidence_count": int(row["evidence_count"]),
                    "supplier_count": int(row["supplier_count"]),
                    "total_deal_cost": float(row["total_deal_cost"] or 0),
                }
                for row in reversed(list(monthly_rows))
            ],
            "top_products": [
                {
                    "name": row["name"],
                    "evidence_count": int(row["evidence_count"]),
                    "total_deal_cost": float(row["total_deal_cost"] or 0),
                    "latest_deal_date": row["latest_deal_date"],
                }
                for row in top_product_rows
            ],
            "top_suppliers": [
                {
                    "name": row["name"],
                    "evidence_count": int(row["evidence_count"]),
                    "total_deal_cost": float(row["total_deal_cost"] or 0),
                    "category_count": int(row["category_count"]),
                    "latest_deal_date": row["latest_deal_date"],
                }
                for row in top_supplier_rows
            ],
            "top_customers": [
                {
                    "name": row["name"],
                    "evidence_count": int(row["evidence_count"]),
                    "total_deal_cost": float(row["total_deal_cost"] or 0),
                    "category_count": int(row["category_count"]),
                    "latest_deal_date": row["latest_deal_date"],
                }
                for row in top_customer_rows
            ],
            "top_categories": [
                {
                    "name": row["name"],
                    "evidence_count": int(row["evidence_count"]),
                    "total_deal_cost": float(row["total_deal_cost"] or 0),
                    "latest_deal_date": row["latest_deal_date"],
                }
                for row in top_category_rows
            ],
            "status_breakdown": [
                {
                    "status_name": row["status_name"],
                    "evidence_count": int(row["evidence_count"]),
                }
                for row in status_rows
            ],
            "sync_state": [
                {
                    "state_key": row["state_key"],
                    "state": json.loads(row["state_json"]) if row["state_json"] else None,
                    "updated_at": row["updated_at"],
                }
                for row in state_rows
            ],
            "recent_evidences": [
                {
                    "source_name": row["source_name"],
                    "lot_display_no": row["lot_display_no"],
                    "lot_id": row["lot_id"],
                    "product_name": row["product_name"],
                    "category_name": row["category_name"],
                    "procedure_type": row["procedure_type"],
                    "contract_number": row["contract_number"],
                    "customer_name": row["customer_name"],
                    "provider_name": row["provider_name"],
                    "deal_date": row["deal_date"],
                    "updated_at": row["updated_at"],
                    "deal_cost": float(row["deal_cost"] or 0) if row["deal_cost"] is not None else None,
                    "currency": row["currency"],
                    "deal_status_name": row["deal_status_name"],
                    "payment_status": row["payment_status"],
                    "source_url": row["source_url"],
                }
                for row in recent_rows
            ],
        }

    def get_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total_row = conn.execute("SELECT COUNT(*) AS count FROM tender_evidences").fetchone()
            source_rows = conn.execute(
                """
                SELECT source_name, COUNT(*) AS count, MAX(updated_at) AS last_updated_at
                FROM tender_evidences
                GROUP BY source_name
                ORDER BY source_name
                """
            ).fetchall()
            latest_row = conn.execute(
                "SELECT MAX(updated_at) AS latest_updated_at, MIN(ingested_at) AS oldest_ingested_at FROM tender_evidences"
            ).fetchone()
            state_rows = conn.execute(
                "SELECT state_key, state_json, updated_at FROM tender_sync_state ORDER BY state_key"
            ).fetchall()
            category_total_row = conn.execute("SELECT COUNT(*) AS count FROM tender_categories").fetchone()
            product_total_row = conn.execute("SELECT COUNT(*) AS count FROM tender_products").fetchone()
            category_source_rows = conn.execute(
                """
                SELECT source_name, COUNT(*) AS count, MAX(updated_at) AS last_updated_at
                FROM tender_categories
                GROUP BY source_name
                ORDER BY source_name
                """
            ).fetchall()
            product_source_rows = conn.execute(
                """
                SELECT source_name, COUNT(*) AS count, MAX(updated_at) AS last_updated_at
                FROM tender_products
                GROUP BY source_name
                ORDER BY source_name
                """
            ).fetchall()
        audit_capture_stats = self.get_audit_capture_stats(limit=20)

        return {
            "db_path": _mask_database_url(self.database_url),
            "total_records": int(total_row["count"] if total_row else 0),
            "by_source": [
                {
                    "source_name": row["source_name"],
                    "count": int(row["count"]),
                    "last_updated_at": row["last_updated_at"],
                }
                for row in source_rows
            ],
            "latest_updated_at": latest_row["latest_updated_at"] if latest_row else None,
            "oldest_ingested_at": latest_row["oldest_ingested_at"] if latest_row else None,
            "catalog": {
                "categories_total": int(category_total_row["count"] if category_total_row else 0),
                "products_total": int(product_total_row["count"] if product_total_row else 0),
                "categories_by_source": [
                    {
                        "source_name": row["source_name"],
                        "count": int(row["count"]),
                        "last_updated_at": row["last_updated_at"],
                    }
                    for row in category_source_rows
                ],
                "products_by_source": [
                    {
                        "source_name": row["source_name"],
                        "count": int(row["count"]),
                        "last_updated_at": row["last_updated_at"],
                    }
                    for row in product_source_rows
                ],
            },
            "sync_state": [
                {
                    "state_key": row["state_key"],
                    "state": json.loads(row["state_json"]) if row["state_json"] else None,
                    "updated_at": row["updated_at"],
                }
                for row in state_rows
            ],
            "audit_capture_catalog": audit_capture_stats,
        }

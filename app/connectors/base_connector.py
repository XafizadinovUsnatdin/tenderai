from __future__ import annotations

from typing import Any

from app.schemas import Evidence


class BaseTenderConnector:
    source_name: str
    source_type: str

    async def search(
        self,
        query: str,
        period_months: int = 12,
        page_size: int = 20,
        max_pages: int = 3,
        **kwargs: Any,
    ) -> list[Evidence]:
        raise NotImplementedError


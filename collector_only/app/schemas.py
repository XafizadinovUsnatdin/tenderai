from dataclasses import dataclass
from typing import Any


@dataclass
class ProductCandidate:
    id: int
    product_code: str
    name: str
    category_id: int
    category_name: str
    score: float = 0.0
    selection_reason: str | None = None


@dataclass
class Evidence:
    source_name: str
    source_type: str
    source_url: str | None
    lot_id: str | None
    lot_display_no: str | None
    product_name: str | None
    category_name: str | None
    condition: str | None
    amount: float | None
    deal_cost: float | None
    unit_price: float | None
    currency: str
    region: str | None
    provider_name: str | None
    deal_date: str | None
    deal_status_name: str | None
    payment_status: str | None
    raw_payload: dict[str, Any]
    raw_text: str
    participants_count: int | None = None
    customer_name: str | None = None
    customer_inn: str | None = None
    provider_inn: str | None = None
    start_cost: float | None = None
    contract_file_name: str | None = None
    contract_file_path: str | None = None
    additional_protocol_file_name: str | None = None
    additional_protocol_file_path: str | None = None
    procedure_type: str | None = None
    contract_number: str | None = None
    begin_date: str | None = None
    end_date: str | None = None
    address: str | None = None
    district: str | None = None
    country: str | None = None
    measure: str | None = None
    manufacturer_country: str | None = None
    status_code: str | None = None
    time_left_second: int | None = None
    product_code: str | None = None
    category_id: int | None = None
    payment_date: str | None = None
    penalty_amount: float | None = None

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from api.faults import (
    DEFAULT_SEED,
    FaultState,
    get_repeated_records_for_page,
)

# --- Configuration & Constants ---

DATA_FILE_PATH = Path(
    os.getenv("PAYSIM_DATA_PATH", Path(__file__).parent / "data" / "paysim_api_v1.csv.gz")
)
API_KEY_VALUE = os.getenv("MOCK_API_KEY", "dev-processor-key")
DATASET_VERSION = "v1"
MAX_RECORDS = 100_000
FAULT_SEED = int(os.getenv("FAULT_SEED", str(DEFAULT_SEED)))

# Fixed UUIDv5 namespace for deterministic row-number IDs (document in DDR-GA addendum)
TRANSACTION_NAMESPACE = uuid.UUID("7f3b9c2a-4d1e-4b8a-9c6f-2e5d8a1b4c7f")

BASE_TIMESTAMP = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

TYPE_MAP: dict[str, str] = {
    "CASH_IN": "cash-in",
    "CASH_OUT": "cash-out",
    "DEBIT": "debit",
    "PAYMENT": "payment",
    "TRANSFER": "transfer",
}

# --- Pydantic Schemas (G0 Contract) ---

TransactionType = Literal["cash-in", "cash-out", "debit", "payment", "transfer"]


class TransactionRecord(BaseModel):
    transactionId: str
    step: int
    timestamp: str
    transactionType: TransactionType
    amountCents: int
    originAccount: str
    originOldBalanceCents: int
    originNewBalanceCents: int
    destinationAccount: str
    destinationOldBalanceCents: int
    destinationNewBalanceCents: int


class TransactionsResponse(BaseModel):
    data: list[TransactionRecord]
    page: int
    pageSize: int
    totalRecords: int
    nextPage: int | None


class MetaResponse(BaseModel):
    datasetVersion: str
    totalRecords: int
    contentHash: str


# --- Transformation Helpers ---


def to_cents(value: str) -> int:
    """Convert decimal string to integer cents using ROUND_HALF_UP."""
    dec = Decimal(value.strip()) * Decimal("100")
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def step_to_iso(step: int) -> str:
    """Convert 1-based PaySim step to ISO 8601 UTC timestamp starting 2024-01-01T00:00:00Z."""
    ts = BASE_TIMESTAMP + timedelta(hours=step - 1)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def row_to_uuid(row_number: int) -> str:
    """Deterministic UUIDv5 derived from 1-based file row number."""
    return str(uuid.uuid5(TRANSACTION_NAMESPACE, str(row_number)))


def transform_row(row_number: int, row: dict[str, str]) -> TransactionRecord:
    """Map raw PaySim CSV row to camelCase G0 contract, stripping fraud flags."""
    step = int(row["step"])
    raw_type = row["type"].strip().upper()
    if raw_type not in TYPE_MAP:
        raise ValueError(f"Unsupported PaySim transaction type at row {row_number}: {raw_type}")

    return TransactionRecord(
        transactionId=row_to_uuid(row_number),
        step=step,
        timestamp=step_to_iso(step),
        transactionType=TYPE_MAP[raw_type],  # type: ignore[arg-type]
        amountCents=to_cents(row["amount"]),
        originAccount=row["nameOrig"].strip(),
        originOldBalanceCents=to_cents(row["oldbalanceOrg"]),
        originNewBalanceCents=to_cents(row["newbalanceOrig"]),
        destinationAccount=row["nameDest"].strip(),
        destinationOldBalanceCents=to_cents(row["oldbalanceDest"]),
        destinationNewBalanceCents=to_cents(row["newbalanceDest"]),
    )


def load_dataset(path: Path, limit: int = MAX_RECORDS) -> tuple[list[TransactionRecord], str]:
    """Load up to `limit` records from gzipped CSV in file order and compute SHA-256 hash."""
    records: list[TransactionRecord] = []
    hasher = hashlib.sha256()

    with gzip.open(path, mode="rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            if idx > limit:
                break
            record = transform_row(idx, row)
            records.append(record)
            # Hash canonical JSON representation of each served record
            canonical = json.dumps(record.model_dump(), sort_keys=True, separators=(",", ":"))
            hasher.update(canonical.encode("utf-8"))
            hasher.update(b"\n")

    return records, hasher.hexdigest()


# --- Application Lifecycle & Security ---

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
fault_state = FaultState(seed=FAULT_SEED)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    if not api_key or api_key != API_KEY_VALUE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
        )
    return api_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    records, content_hash = load_dataset(DATA_FILE_PATH, limit=MAX_RECORDS)
    app.state.records = records
    app.state.content_hash = content_hash
    yield
    app.state.records = []


app = FastAPI(
    title="Mock Processor API (G0 Contract)",
    version=DATASET_VERSION,
    lifespan=lifespan,
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in ("/health", "/docs", "/openapi.json"):
        return await call_next(request)

    api_key = request.headers.get("X-API-Key")
    if api_key and api_key == API_KEY_VALUE:
        retry_after = fault_state.check_rate_limit(api_key)
        if retry_after is not None:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded (60 requests/min per key)."},
                headers={"Retry-After": str(retry_after)},
            )

    return await call_next(request)


app.add_middleware(GZipMiddleware, minimum_size=500)


# --- Endpoints ---


@app.get(
    "/v1/transactions",
    response_model=TransactionsResponse,
    dependencies=[Depends(verify_api_key)],
)
def get_transactions(
    page: int = Query(1, ge=1, description="1-based page number"),
    pageSize: int = Query(500, ge=1, le=1000, description="Items per page (default 500, max 1000)"),
) -> TransactionsResponse:
    # 1. Fail with 500 on first request only for faulty (seed, page, pageSize)
    if fault_state.should_fail_with_500(page=page, page_size=pageSize):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Simulated transient upstream failure",
        )

    records: list[TransactionRecord] = app.state.records
    total_records = len(records)
    total_pages = (total_records + pageSize - 1) // pageSize if total_records > 0 else 0

    start_idx = (page - 1) * pageSize
    end_idx = start_idx + pageSize
    page_items = list(records[start_idx:end_idx])

    # 2. Deterministically append >= 100 earlier records across later pages
    def fetch_record(earlier_page: int, earlier_index: int, p_size: int) -> TransactionRecord | None:
        idx = (earlier_page - 1) * p_size + earlier_index
        return records[idx] if 0 <= idx < total_records else None

    duplicates = get_repeated_records_for_page(
        seed=fault_state.seed,
        page=page,
        page_size=pageSize,
        total_pages=total_pages,
        fetch_record_fn=fetch_record,
    )
    page_items.extend(duplicates)

    next_page = page + 1 if end_idx < total_records else None

    return TransactionsResponse(
        data=page_items,
        page=page,
        pageSize=pageSize,
        totalRecords=total_records,
        nextPage=next_page,
    )


@app.get(
    "/v1/meta",
    response_model=MetaResponse,
    dependencies=[Depends(verify_api_key)],
)
def get_meta() -> MetaResponse:
    records: list[TransactionRecord] = app.state.records
    return MetaResponse(
        datasetVersion=DATASET_VERSION,
        totalRecords=len(records),
        contentHash=app.state.content_hash,
    )
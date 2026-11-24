import csv
import gzip
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_module
from api.main import (
    TRANSACTION_NAMESPACE,
    app,
    row_to_uuid,
    step_to_iso,
    to_cents,
)

SAMPLE_ROWS = [
    {
        "step": "1",
        "type": "PAYMENT",
        "amount": "9839.64",
        "nameOrig": "C1231006815",
        "oldbalanceOrg": "170136.0",
        "newbalanceOrig": "160296.36",
        "nameDest": "M1979787155",
        "oldbalanceDest": "0.0",
        "newbalanceDest": "0.0",
        "isFraud": "0",
        "isFlaggedFraud": "0",
    },
    {
        "step": "2",
        "type": "CASH_OUT",
        "amount": "181.00",
        "nameOrig": "C840083671",
        "oldbalanceOrg": "181.0",
        "newbalanceOrig": "0.0",
        "nameDest": "C38997010",
        "oldbalanceDest": "21182.0",
        "newbalanceDest": "0.0",
        "isFraud": "1",
        "isFlaggedFraud": "0",
    },
    {
        "step": "743",
        "type": "TRANSFER",
        "amount": "2500.555",
        "nameOrig": "C111111111",
        "oldbalanceOrg": "5000.00",
        "newbalanceOrig": "2499.44",
        "nameDest": "C222222222",
        "oldbalanceDest": "100.00",
        "newbalanceDest": "2600.56",
        "isFraud": "1",
        "isFlaggedFraud": "1",
    },
]


@pytest.fixture
def sample_gz_file(tmp_path: Path) -> Path:
    file_path = tmp_path / "paysim_sample.csv.gz"
    fieldnames = list(SAMPLE_ROWS[0].keys())
    with gzip.open(file_path, mode="wt", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(SAMPLE_ROWS)
    return file_path


@pytest.fixture
def client(sample_gz_file: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(api_module, "DATA_FILE_PATH", sample_gz_file)
    monkeypatch.setattr(api_module, "API_KEY_VALUE", "test-secret-key")
    with TestClient(app) as test_client:
        yield test_client


# --- Unit Tests: Transformations ---


def test_rounding_half_up():
    assert to_cents("9839.64") == 983964
    assert to_cents("10.005") == 1001
    assert to_cents("10.015") == 1002
    assert to_cents("10.004") == 1000
    assert to_cents("0.0") == 0


def test_timestamps_from_step():
    assert step_to_iso(1) == "2024-01-01T00:00:00Z"
    assert step_to_iso(25) == "2024-01-02T00:00:00Z"
    # 742 hours = 30 days (Jan 31) + 22 hours -> 2024-01-31T22:00:00Z
    assert step_to_iso(743) == "2024-01-31T22:00:00Z"


def test_uuid_v5_deterministic():
    import uuid

    expected = str(uuid.uuid5(TRANSACTION_NAMESPACE, "1"))
    assert row_to_uuid(1) == expected
    assert row_to_uuid(1) != row_to_uuid(2)


# --- Integration Tests: Auth, Contract, Pagination, Meta, GZip ---


def test_auth_missing_or_wrong_key_returns_401(client: TestClient):
    # Missing key
    resp_missing = client.get("/v1/transactions")
    assert resp_missing.status_code == 401

    # Wrong key
    resp_wrong = client.get("/v1/transactions", headers={"X-API-Key": "wrong-key"})
    assert resp_wrong.status_code == 401

    # Meta endpoint also protected
    resp_meta = client.get("/v1/meta", headers={"X-API-Key": "wrong-key"})
    assert resp_meta.status_code == 401


def test_transactions_contract_and_no_fraud_fields(client: TestClient):
    resp = client.get("/v1/transactions", headers={"X-API-Key": "test-secret-key"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["page"] == 1
    assert body["pageSize"] == 500
    assert body["totalRecords"] == 3
    assert body["nextPage"] is None
    assert len(body["data"]) == 3

    first = body["data"][0]
    assert first == {
        "transactionId": row_to_uuid(1),
        "step": 1,
        "timestamp": "2024-01-01T00:00:00Z",
        "transactionType": "payment",
        "amountCents": 983964,
        "originAccount": "C1231006815",
        "originOldBalanceCents": 17013600,
        "originNewBalanceCents": 16029636,
        "destinationAccount": "M1979787155",
        "destinationOldBalanceCents": 0,
        "destinationNewBalanceCents": 0,
    }
    assert "isFraud" not in first
    assert "isFlaggedFraud" not in first


def test_pagination_last_page_next_page_is_null(client: TestClient):
    headers = {"X-API-Key": "test-secret-key"}

    # Page 1 of 2 (2 items) -> nextPage should be 2
    p1 = client.get("/v1/transactions?page=1&pageSize=2", headers=headers).json()
    assert len(p1["data"]) == 2
    assert p1["page"] == 1
    assert p1["pageSize"] == 2
    assert p1["totalRecords"] == 3
    assert p1["nextPage"] == 2

    # Page 2 of 2 (1 item, last page) -> nextPage must be null
    p2 = client.get("/v1/transactions?page=2&pageSize=2", headers=headers).json()
    assert len(p2["data"]) == 1
    assert p2["page"] == 2
    assert p2["nextPage"] is None
    assert p2["data"][0]["timestamp"] == "2024-01-31T22:00:00Z"
    assert p2["data"][0]["transactionType"] == "transfer"


def test_page_size_validation(client: TestClient):
    headers = {"X-API-Key": "test-secret-key"}
    resp = client.get("/v1/transactions?pageSize=1001", headers=headers)
    assert resp.status_code == 422


def test_meta_endpoint(client: TestClient):
    resp = client.get("/v1/meta", headers={"X-API-Key": "test-secret-key"})
    assert resp.status_code == 200
    meta = resp.json()
    assert meta["datasetVersion"] == "v1"
    assert meta["totalRecords"] == 3
    assert len(meta["contentHash"]) == 64  # SHA-256 hex digest


def test_gzip_compression_enabled(client: TestClient):
    resp = client.get(
        "/v1/transactions",
        headers={"X-API-Key": "test-secret-key", "Accept-Encoding": "gzip"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"
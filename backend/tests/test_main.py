import asyncio
from pathlib import Path
import os
import sys
import datetime

import pytest
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("STATIC_FILES_PATH", "static")
Path("static").mkdir(exist_ok=True)

from backend.app.main import app, _clean, _detect_delivery_tag  # noqa: E402
from backend.app import database, models  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def patch_external(monkeypatch):
    async def fake_find_order(order_name: str):
        return {
            "tags": "fast",
            "fulfillment": "fulfilled",
            "status": "open",
            "store": "main",
            "result": "✅ OK",
        }

    async def fake_append_row(values: list[str]):
        return None

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import text

    monkeypatch.setattr("backend.app.shopify.find_order", fake_find_order)
    monkeypatch.setattr("backend.app.sheets.append_row", fake_append_row)

    original_execute = AsyncSession.execute

    async def execute_wrapper(self, statement, *args, **kwargs):
        if isinstance(statement, str):
            statement = text(statement)
        return await original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", execute_wrapper)


@pytest.fixture()
def seed_scan():
    async def _seed():
        async with database.AsyncSessionLocal() as db:
            scan = models.Scan(
                order_name="#999",
                tags="fast",
                fulfillment="fulfilled",
                status="open",
                store="main",
                result="✅ OK",
            )
            db.add(scan)
            await db.commit()
            await db.refresh(scan)
            return scan.ts.isoformat().replace("+00:00", "Z")

    return asyncio.run(_seed())


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_clean_valid():
    assert _clean("00123") == "#123"
    assert _clean("abc123def") == "#123"


def test_clean_invalid():
    with pytest.raises(ValueError):
        _clean("abc")
    with pytest.raises(ValueError):
        _clean("1234567")


def test_scan_and_summary(client):
    resp = client.post("/scan", json={"barcode": "123"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "✅ OK"
    assert data["order"] == "#123"
    assert data["tag"] == "fast"

    resp = client.get("/tag-summary")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary.get("fast") == 1


def test_scan_repeat(client, seed_scan):
    resp = client.post("/scan", json={"barcode": "999"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "⚠️ Already Scanned"
    assert data["order"] == "#999"
    assert data["tag"] == "fast"


def test_scan_invalid_barcode(client):
    resp = client.post("/scan", json={"barcode": "abc"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "❌ Invalid barcode"


def test_unfulfilled_order_no_tag(client, monkeypatch):
    async def fake_fetch_order(session, store, name):
        return {
            "tags": "",
            "fulfillment_status": None,
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            "cancelled_at": None,
        }

    import importlib
    from backend.app import main as main_mod
    from backend.app import shopify as shopify_mod

    shopify = importlib.reload(shopify_mod)
    monkeypatch.setattr(main_mod, "shopify", shopify)
    monkeypatch.setattr(shopify, "_fetch_order", fake_fetch_order)
    monkeypatch.setattr(
        shopify,
        "_stores",
        lambda: [{"name": "test", "api_key": "x", "password": "y", "domain": "z"}],
    )

    resp = client.post("/scan", json={"barcode": "777"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "❌ Unfulfilled order with no tag — not added"
    assert data["order"] == "#777"
    assert data["tag"] == ""


def test_scan_filters_tags(client, monkeypatch):
    async def custom_find_order(order_name: str):
        return {
            "tags": "cod 24/07/25, FAST, urgent",
            "fulfillment": "fulfilled",
            "status": "open",
            "store": "main",
            "result": "✅ OK",
        }

    monkeypatch.setattr("backend.app.shopify.find_order", custom_find_order)

    resp = client.post("/scan", json={"barcode": "321"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tag"] == "fast"


def test_detect_delivery_tag_exact_match():
    assert _detect_delivery_tag("fast, urgent") == "fast"
    assert _detect_delivery_tag("K, other") == "k"
    # partial words should not match
    assert _detect_delivery_tag("snack") == ""


def test_tag_summary_counts(client, monkeypatch):
    calls = []

    async def custom_find_order(order_name: str):
        calls.append(order_name)
        if order_name == "#555":
            return {
                "tags": "fast, urgent",
                "fulfillment": "fulfilled",
                "status": "open",
                "store": "main",
                "result": "✅ OK",
            }
        return {
            "tags": "K",
            "fulfillment": "fulfilled",
            "status": "open",
            "store": "main",
            "result": "✅ OK",
        }

    monkeypatch.setattr("backend.app.shopify.find_order", custom_find_order)

    before = client.get("/tag-summary").json()

    client.post("/scan", json={"barcode": "555"})
    client.post("/scan", json={"barcode": "556"})

    after = client.get("/tag-summary").json()
    assert after.get("fast") >= before.get("fast") + 1
    assert after.get("k") >= before.get("k") + 1

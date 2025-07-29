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

from backend.app.main import (
    app,
    _clean,
    _detect_delivery_tag,
    RECENT_SCAN_DAYS,
)  # noqa: E402
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
def seed_recent_scan():
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


@pytest.fixture()
def seed_old_scan():
    async def _seed():
        async with database.AsyncSessionLocal() as db:
            scan = models.Scan(
                order_name="#998",
                tags="fast",
                fulfillment="fulfilled",
                status="open",
                store="main",
                result="✅ OK",
                ts=datetime.datetime.utcnow()
                - datetime.timedelta(days=RECENT_SCAN_DAYS + 1),
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

    today = datetime.datetime.utcnow().date().isoformat()
    resp = client.get(f"/tag-summary?date={today}")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary.get("fast") == 1


def test_scan_repeat_recent(client, seed_recent_scan):
    resp = client.post("/scan", json={"barcode": "999"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == "⚠️ Already Scanned"
    assert data["order"] == "#999"
    assert data["tag"] == "fast"


def test_scan_old_not_duplicate(client, seed_old_scan):
    resp = client.post("/scan", json={"barcode": "998"})
    assert resp.status_code == 200
    data = resp.json()
    # Should treat as a new scan because the existing one is older than cutoff
    assert data["result"] == "✅ OK"
    assert data["order"] == "#998"


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
    # whitespace should also work as a delimiter
    assert _detect_delivery_tag("fast urgent") == "fast"
    # partial words should not match
    assert _detect_delivery_tag("snack") == ""


def test_detect_delivery_tag_variants():
    assert _detect_delivery_tag("SANDY") == "sand"
    assert _detect_delivery_tag("12livrey") == "12livery"
    assert _detect_delivery_tag("12 livery") == "12livery"
    assert _detect_delivery_tag("khaso") == ""


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

    today = datetime.datetime.utcnow().date().isoformat()
    before = client.get(f"/tag-summary?date={today}").json()

    client.post("/scan", json={"barcode": "555"})
    client.post("/scan", json={"barcode": "556"})

    after = client.get(f"/tag-summary?date={today}").json()
    assert after.get("fast") >= before.get("fast") + 1
    assert after.get("k") >= before.get("k") + 1


def test_tag_summary_counts_variants(client, monkeypatch):
    async def custom_find_order(order_name: str):
        if order_name == "#701":
            return {
                "tags": "SANDY",
                "fulfillment": "fulfilled",
                "status": "open",
                "store": "main",
                "result": "✅ OK",
            }
        return {
            "tags": "12 livery",
            "fulfillment": "fulfilled",
            "status": "open",
            "store": "main",
            "result": "✅ OK",
        }

    monkeypatch.setattr("backend.app.shopify.find_order", custom_find_order)

    today = datetime.datetime.utcnow().date().isoformat()
    before = client.get(f"/tag-summary?date={today}").json()

    client.post("/scan", json={"barcode": "701"})
    client.post("/scan", json={"barcode": "702"})

    after = client.get(f"/tag-summary?date={today}").json()
    assert after.get("sand") >= before.get("sand") + 1
    assert after.get("12livery") >= before.get("12livery") + 1


def test_tag_summary_date_filter(client):
    today = datetime.datetime.utcnow().date().isoformat()
    yesterday = (
        (datetime.datetime.utcnow() - datetime.timedelta(days=1)).date().isoformat()
    )

    before_today = client.get(f"/tag-summary?date={today}").json()
    before_yday = client.get(f"/tag-summary?date={yesterday}").json()

    async def seed():
        async with database.AsyncSessionLocal() as db:
            scan = models.Scan(
                order_name="#yday",
                tags="fast",
                fulfillment="fulfilled",
                status="open",
                store="main",
                result="✅ OK",
                ts=datetime.datetime.utcnow() - datetime.timedelta(days=1),
            )
            db.add(scan)
            await db.commit()

    asyncio.run(seed())

    after_today = client.get(f"/tag-summary?date={today}").json()
    after_yday = client.get(f"/tag-summary?date={yesterday}").json()

    assert after_today.get("fast") == before_today.get("fast")
    assert after_yday.get("fast") >= before_yday.get("fast") + 1


def test_tag_summary_by_store(client, monkeypatch):
    async def custom_find_order(order_name: str):
        if order_name == "#601":
            return {
                "tags": "fast",
                "fulfillment": "fulfilled",
                "status": "open",
                "store": "irrakids",
                "result": "✅ OK",
            }
        return {
            "tags": "k",
            "fulfillment": "fulfilled",
            "status": "open",
            "store": "irranova",
            "result": "✅ OK",
        }

    monkeypatch.setattr("backend.app.shopify.find_order", custom_find_order)

    before = client.get("/tag-summary/by-store").json()

    client.post("/scan", json={"barcode": "601"})
    client.post("/scan", json={"barcode": "602"})

    after = client.get("/tag-summary/by-store").json()
    assert (
        after.get("irrakids", {}).get("fast", 0)
        >= before.get("irrakids", {}).get("fast", 0) + 1
    )
    assert (
        after.get("irranova", {}).get("k", 0)
        >= before.get("irranova", {}).get("k", 0) + 1
    )


def test_list_and_update_scans(client):
    today = datetime.datetime.utcnow().date().isoformat()
    client.post("/scan", json={"barcode": "601"})
    resp = client.get(f"/scans?date={today}")
    assert resp.status_code == 200
    scans = resp.json()
    assert len(scans) >= 1
    first_id = scans[0]["id"]

    update = {"driver": "alice", "tags": "fast", "status": "dispatched"}
    resp = client.patch(f"/scans/{first_id}", json=update)
    assert resp.status_code == 200
    data = resp.json()
    assert data["driver"] == "alice"
    assert data["status"] == "dispatched"


def test_delete_scan(client):
    today = datetime.datetime.utcnow().date().isoformat()
    client.post("/scan", json={"barcode": "701"})
    resp = client.get(f"/scans?date={today}")
    first_id = resp.json()[0]["id"]

    resp = client.delete(f"/scans/{first_id}")
    assert resp.status_code == 204

    resp = client.get(f"/scans?date={today}")
    ids = [s["id"] for s in resp.json()]
    assert first_id not in ids

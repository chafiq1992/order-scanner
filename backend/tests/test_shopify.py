import asyncio
import datetime
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))
from backend.app import shopify


def test_find_order_returns_dict(monkeypatch):
    async def fake_fetch_order(session, store, name):
        return {
            "tags": "foo",
            "fulfillment_status": "fulfilled",
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            "cancelled_at": None,
        }

    monkeypatch.setattr(shopify, "_fetch_order", fake_fetch_order)
    monkeypatch.setattr(
        shopify,
        "_stores",
        lambda: [{"name": "test", "api_key": "x", "password": "y", "domain": "z"}],
    )

    result = asyncio.run(shopify.find_order("#123"))
    assert result["result"] == "✅ OK"
    assert result["store"] == "test"


import asyncio
import datetime
import sys
from pathlib import Path
import os

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


def test_normalize_domain_env(monkeypatch):
    env = {
        "FOO_API_KEY": "x",
        "FOO_PASSWORD": "y",
        "FOO_DOMAIN": "https://example.myshopify.com/",
    }
    monkeypatch.setattr(os, "environ", env, raising=False)
    stores = shopify._stores()
    assert stores[0]["domain"] == "example.myshopify.com"


def test_fulfillment_defaults_to_unfulfilled(monkeypatch):
    async def fake_fetch_order(session, store, name):
        return {
            "tags": "",
            "fulfillment_status": None,
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
    assert result["fulfillment"] == "unfulfilled"
    assert result["result"] == "❌ Unfulfilled"


def test_fetch_order_uses_query_params():
    captured = {}

    class FakeResp:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def json(self):
            return {"orders": [None]}

    class FakeSession:
        def get(self, url, headers=None, params=None):
            captured["url"] = url
            captured["params"] = params
            return FakeResp()

    store = {"domain": "example.myshopify.com", "api_key": "k", "password": "p"}

    asyncio.run(shopify._fetch_order(FakeSession(), store, "#123"))

    assert captured["params"] == {"status": "any", "name": "#123"}


def test_fetch_order_empty_list_returns_none():
    class FakeResp:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
        async def json(self):
            return {"orders": []}

    class FakeSession:
        def get(self, url, headers=None, params=None):
            return FakeResp()

    store = {"domain": "example.myshopify.com", "api_key": "k", "password": "p"}

    result = asyncio.run(shopify._fetch_order(FakeSession(), store, "#123"))
    assert result is None


def test_find_order_returns_most_recent(monkeypatch):
    now = datetime.datetime.utcnow()

    async def fake_fetch_order(session, store, name):
        if store["name"] == "old":
            return {
                "tags": "",
                "fulfillment_status": "fulfilled",
                "created_at": (now - datetime.timedelta(days=2)).isoformat() + "Z",
                "cancelled_at": None,
            }
        return {
            "tags": "",
            "fulfillment_status": "fulfilled",
            "created_at": (now - datetime.timedelta(days=1)).isoformat() + "Z",
            "cancelled_at": None,
        }

    stores = [
        {"name": "old", "api_key": "1", "password": "1", "domain": "d1"},
        {"name": "new", "api_key": "2", "password": "2", "domain": "d2"},
    ]

    monkeypatch.setattr(shopify, "_fetch_order", fake_fetch_order)
    monkeypatch.setattr(shopify, "_stores", lambda: stores)

    result = asyncio.run(shopify.find_order("#123"))
    assert result["store"] == "new"

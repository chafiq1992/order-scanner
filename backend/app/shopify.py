import aiohttp
import asyncio
import base64
import json
import os
import re
import datetime as dt
import time
from typing import Any, Dict, List


# ---------------- configuration -------------
CONFIG = {
    "MAX_DIGITS": 6,
    "ORDER_CUTOFF_DAYS": 50,  
    "RETRY_ATTEMPTS": 3,
    "RETRY_DELAY": 1.0,       
}

# ---------------- env‑var helpers --------------
_key_re = re.compile(r"^(.*)_API_KEY$")


def _normalize_domain(domain: str) -> str:
    """Strip scheme and trailing path from the given domain string."""
    domain = re.sub(r"^https?://", "", domain, flags=re.I)
    # keep only the hostname portion
    return domain.split("/")[0].rstrip("/")


def _stores_from_individual_vars() -> List[Dict[str, str]]:
    """Build store list from *_API_KEY / *_PASSWORD / *_DOMAIN env‑vars."""
    env = os.environ
    stores: List[Dict[str, str]] = []

    for var, value in env.items():
        m = _key_re.match(var)
        if not m:
            continue
        store_id = m.group(1)
        # required companions
        pwd_var = f"{store_id}_PASSWORD"
        dom_var = f"{store_id}_DOMAIN"
        # Skip incomplete store configurations instead of raising
        if pwd_var not in env or dom_var not in env:
            continue
        domain = _normalize_domain(env.get(dom_var, ""))
        if not value or not env.get(pwd_var) or not domain:
            continue
        stores.append(
            {
                "name": store_id.lower(),
                "api_key": value,
                "password": env[pwd_var],
                "domain": domain,
            }
        )
    return stores


def _stores() -> List[Dict[str, str]]:
    """Return a list[dict] describing every Shopify store to query.

    When no credentials are provided the function returns an empty list so that
    the rest of the application can operate without the Shopify integration.
    """
    json_blob = os.getenv("SHOPIFY_STORES_JSON")
    if json_blob:
        try:
            raw_stores = json.loads(json_blob)
        except json.JSONDecodeError:
            # Ignore invalid JSON and behave as if no stores are configured
            return []
        validated: List[Dict[str, str]] = []
        for s in raw_stores or []:
            name = (s.get("name") or "").lower()
            api_key = s.get("api_key") or ""
            password = s.get("password") or ""
            domain = _normalize_domain(s.get("domain") or "")
            # Keep only fully specified stores
            if name and api_key and password and domain:
                validated.append(
                    {"name": name, "api_key": api_key, "password": password, "domain": domain}
                )
        return validated

    # fall back to individual env-vars
    return _stores_from_individual_vars()


# ---------------- low‑level helpers -----------


def _auth_hdr(api_key: str, password: str) -> Dict[str, str]:
    cred = f"{api_key}:{password}".encode()
    token = base64.b64encode(cred).decode()
    return {"Authorization": "Basic " + token}


def _normalize_phone(phone: str | None) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D+", "", phone)
    # Keep last 10-12 digits to avoid country code discrepancies
    return digits[-12:]


def _extract_phone_from_order(order: Dict[str, Any]) -> str:
    # Try common locations for phone numbers in Shopify order payloads
    candidates: List[str | None] = [
        order.get("phone"),
        (order.get("shipping_address") or {}).get("phone"),
        (order.get("billing_address") or {}).get("phone"),
        (order.get("customer") or {}).get("phone"),
        ((order.get("customer") or {}).get("default_address") or {}).get("phone"),
    ]
    for c in candidates:
        normalized = _normalize_phone(c)
        if normalized:
            return normalized
    return ""


async def _fetch_order(
    session: aiohttp.ClientSession, store: Dict[str, str], name: str
) -> Dict[str, Any] | None:
    url = f"https://{store['domain']}/admin/api/2023-07/orders.json"
    async with session.get(
        url,
        headers=_auth_hdr(store["api_key"], store["password"]),
        params={"status": "any", "name": name},
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"{store['name']} responded {r.status}")
        data = await r.json()

    orders = data.get("orders")
    if not orders:
        return None
    return orders[0]

# ---------------- public API ------------------


async def find_order(order_name: str) -> Dict[str, str]:
    """
    Look up `order_name` (e.g. "#123456") across all configured stores.

    Returns the first recent match (newest order within ORDER_CUTOFF_DAYS).
    """
    # Simple in-process cache to speed up repeated lookups for the same order
    # within a short window during concurrent scans.
    CACHE_TTL_SEC = 300
    cache_key = f"find_order::{order_name}"
    _cache = getattr(find_order, "_cache", None)
    if _cache is None:
        _cache = {}
        setattr(find_order, "_cache", _cache)  # type: ignore[attr-defined]
    now_ts = time.time()
    cached = _cache.get(cache_key)  # type: ignore[index]
    if cached and now_ts - cached[0] < CACHE_TTL_SEC:  # type: ignore[index]
        return dict(cached[1])  # shallow copy

    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=CONFIG["ORDER_CUTOFF_DAYS"])
    best: Dict[str, str] = {
        "tags": "",
        "fulfillment": "unfulfilled",
        "status": "open",
        "store": "",
        "result": "❌ Not Found",
        "phone": "",
    }

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(15)
    ) as session:
        async def lookup(store: Dict[str, str]):
            for attempt in range(1, CONFIG["RETRY_ATTEMPTS"] + 1):
                try:
                    order = await _fetch_order(session, store, order_name)
                    return store, order
                except Exception as e:
                    # On final attempt, return the exception so we can ignore it later
                    if attempt == CONFIG["RETRY_ATTEMPTS"]:
                        return e
                    await asyncio.sleep(CONFIG["RETRY_DELAY"] * attempt)

        tasks = [lookup(s) for s in _stores()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect only successful (store, order) tuples
    orders = []
    for r in results:
        if isinstance(r, Exception):
            continue
        store, order = r  # type: ignore[misc]
        if not order:
            continue
        created = dt.datetime.fromisoformat(
            order["created_at"].replace("Z", "+00:00")
        )
        orders.append((created, store, order))

    orders.sort(key=lambda x: x[0], reverse=True)

    for created, store, order in orders:
        if created < cutoff:
            continue
        best = {
            "tags": order.get("tags") or "",
            "fulfillment": order.get("fulfillment_status") or "unfulfilled",
            "status": "closed" if order.get("cancelled_at") else "open",
            "store": store["name"],
            "result": (
                "⚠️ Cancelled"
                if order.get("cancelled_at")
                else (
                    "❌ Unfulfilled"
                    if order.get("fulfillment_status") != "fulfilled"
                    else "✅ OK"
                )
            ),
            "phone": _extract_phone_from_order(order),
        }
        return best

    # Store in cache
    _cache[cache_key] = (now_ts, dict(best))  # type: ignore[index]
    return best


async def _orders_count(
    session: aiohttp.ClientSession, store: Dict[str, str], params: Dict[str, str]
) -> int:
    """Return Shopify Orders count for a store with given filters."""
    url = f"https://{store['domain']}/admin/api/2023-07/orders/count.json"
    async with session.get(
        url, headers=_auth_hdr(store["api_key"], store["password"]), params=params
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"{store['name']} responded {r.status}")
        data = await r.json()
    return int(data.get("count", 0))


async def fulfilled_counts_by_store(date_iso: str) -> Dict[str, int]:
    """Return a mapping of store_name -> fulfilled orders count for the given UTC date.

    Uses Shopify Orders count endpoint filtered by fulfillment_status=shipped and
    updated_at in the day window. This approximates orders fulfilled that day.
    """
    # Calculate day window in UTC
    day = dt.datetime.fromisoformat(date_iso)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)

    params = {
        "status": "any",
        # Shopify filter expects 'shipped' for fulfilled orders
        "fulfillment_status": "shipped",
        "updated_at_min": start.isoformat().replace("+00:00", "Z"),
        "updated_at_max": end.isoformat().replace("+00:00", "Z"),
    }

    stores = _stores()
    if not stores:
        return {}

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(15)) as session:
        tasks = [
            _orders_count(session, store, params)  # type: ignore[arg-type]
            for store in stores
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    counts: Dict[str, int] = {}
    for store, result in zip(stores, results):
        if isinstance(result, Exception):
            # On error, default to 0 for that store
            counts[store["name"].lower()] = 0
        else:
            counts[store["name"].lower()] = int(result)
    return counts
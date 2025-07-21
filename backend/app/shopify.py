import aiohttp, base64, json, asyncio, os, datetime as dt
from typing import Dict, Any, List

CONFIG = {
    "MAX_DIGITS": 6,
    "ORDER_CUTOFF_DAYS": 50,
    "RETRY_ATTEMPTS": 3,
    "RETRY_DELAY": 1.0,
}

def _stores() -> List[Dict[str, str]]:
    return json.loads(os.getenv("SHOPIFY_STORES_JSON", "[]"))

def _auth_hdr(api_key: str, password: str) -> Dict[str, str]:
    cred = f"{api_key}:{password}".encode()
    return {"Authorization": "Basic " + base64.b64encode(cred).decode()}

async def fetch_order(session: aiohttp.ClientSession, store: Dict[str,str], name: str) -> Dict[str,Any] | None:
    url = f"https://{store['domain']}/admin/api/2023-07/orders.json?name={name}"
    async with session.get(url, headers=_auth_hdr(store["api_key"], store["password"])) as r:
        if r.status != 200:
            raise RuntimeError(f"{store['name']} responded {r.status}")
        data = await r.json()
        return data.get("orders", [None])[0]

async def find_order(order_name: str) -> Dict[str,str]:
    now      = dt.datetime.utcnow()
    cutoff   = now - dt.timedelta(days=CONFIG["ORDER_CUTOFF_DAYS"])
    best     = {"result": "❌ Not Found"}

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(15)) as session:
        for store in _stores():
            for attempt in range(1, CONFIG["RETRY_ATTEMPTS"]+1):
                try:
                    order = await fetch_order(session, store, order_name)
                    if not order: break
                    created = dt.datetime.fromisoformat(order["created_at"].replace("Z","+00:00"))
                    if created < cutoff: break
                    best = {
                        "tags": order.get("tags",""),
                        "fulfillment": order.get("fulfillment_status","unfulfilled"),
                        "status": "closed" if order.get("cancelled_at") else "open",
                        "store": store["name"],
                        "result": "⚠️ Cancelled" if order.get("cancelled_at")
                                  else ("❌ Unfulfilled" if order.get("fulfillment_status")!='fulfilled' else '✅ OK')
                    }
                    return best
                except Exception as e:
                    if attempt == CONFIG["RETRY_ATTEMPTS"]:
                        raise
                    await asyncio.sleep(CONFIG["RETRY_DELAY"]*attempt)
    return best
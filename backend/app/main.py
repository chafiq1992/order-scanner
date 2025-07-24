from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from .schemas import ScanIn, ScanOut
from . import shopify, database, models, sheets
from sqlalchemy import select
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with database.engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    yield


app = FastAPI(title="Order‑Scanner API", lifespan=lifespan)

_barcode_re = re.compile(r"\d+")


def _clean(barcode: str) -> str:
    digits = _barcode_re.findall(barcode)
    digits = "".join(digits).lstrip("0")
    max_digits = shopify.CONFIG.get("MAX_DIGITS", 6)
    if not digits or len(digits) > max_digits:
        raise ValueError("Invalid barcode")
    return "#" + digits


@app.post("/scan", response_model=ScanOut)
async def scan(data: ScanIn):
    try:
        order_name = _clean(data.barcode)
    except ValueError:
        raise HTTPException(400, "❌ Invalid barcode")

    async with database.AsyncSessionLocal() as db:
        stmt = select(models.Scan).filter_by(order_name=order_name).limit(1)
        q = await db.execute(stmt)
        if (row := q.scalar()):
            return ScanOut(
                result="⚠️ Already Scanned",
                order=row.order_name,
                tag=row.tags,
                ts=row.ts,
            )

    order = await shopify.find_order(order_name)

    if order["fulfillment"].lower() == "unfulfilled" and not order["tags"]:
        return ScanOut(
            result="❌ Unfulfilled order with no tag — not added",
            order=order_name,
            tag="",
            ts=datetime.utcnow()
        )

    scan = models.Scan(
        order_name=order_name,
        tags=order.get("tags", ""),
        fulfillment=order["fulfillment"],
        status=order["status"],
        store=order["store"],
        result=order["result"],
    )
    async with database.AsyncSessionLocal() as db:
        db.add(scan)
        await db.commit()

    await sheets.append_row([
        scan.ts.isoformat(" ", "seconds"),
        order_name,
        scan.tags,
        scan.fulfillment,
        scan.status,
        scan.store,
        scan.result
    ])
    return ScanOut(
        result=scan.result,
        order=order_name,
        tag=scan.tags,
        ts=scan.ts,
    )


@app.get("/tag-summary")
async def tag_summary():
    async with database.AsyncSessionLocal() as db:
        q = await db.execute("SELECT tags FROM scans")
        counts = {
            "k": 0,
            "big": 0,
            "12livery": 0,
            "12livrey": 0,
            "fast": 0,
            "oscario": 0,
            "sand": 0,
        }
        for (t,) in q:
            low = (t or "").lower()
            for k in counts:
                if k in low:
                    counts[k] += 1
    return counts


@app.get("/health")
def health():
    return {"ok": True}


# Serve built frontend files if available
static_path = os.getenv("STATIC_FILES_PATH", "static")
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")


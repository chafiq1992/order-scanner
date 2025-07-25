from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from .schemas import ScanIn, ScanOut, ScanRecord, ScanUpdate
from . import shopify, database, models, sheets
from sqlalchemy import select, text
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from sqlalchemy import inspect

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with database.engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)

        def get_columns(sync_conn):
            return [c["name"] for c in inspect(sync_conn).get_columns("scans")]

        columns = await conn.run_sync(get_columns)

        if "driver" not in columns:
            await conn.execute(text("ALTER TABLE scans ADD COLUMN driver VARCHAR DEFAULT ''"))

        if "cod" not in columns:
            await conn.execute(text("ALTER TABLE scans ADD COLUMN cod BOOLEAN DEFAULT FALSE"))

    yield

app = FastAPI(title="Order‑Scanner API", lifespan=lifespan)

_barcode_re = re.compile(r"\d+")

DELIVERY_TAGS = [
    "big",
    "k",
    "12livery",
    "12livrey",
    "fast",
    "oscario",
    "sand",
]

# Number of days to consider a previous scan as recent when checking for
# duplicates. This can be overridden with the ``RECENT_SCAN_DAYS``
# environment variable.
RECENT_SCAN_DAYS = int(os.getenv("RECENT_SCAN_DAYS", 7))


def _detect_delivery_tag(tag_str: str) -> str:
    """Return the first known delivery tag found in *tag_str*.

    Shopify stores tags as a comma separated list, however some installations
    have been observed to use spaces instead.  To make the detection more
    resilient we split the string on commas **and** whitespace.  Each resulting
    token is then matched (case-insensitively) against
    :data:`DELIVERY_TAGS`.
    """

    import re

    tokens = re.split(r"[,\s]+", tag_str or "")
    tokens = [t.strip().lower() for t in tokens if t.strip()]

    for tag in DELIVERY_TAGS:
        for tok in tokens:
            if tok == tag:
                return tag
    return ""


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
        cutoff = datetime.utcnow() - timedelta(days=RECENT_SCAN_DAYS)
        stmt = select(models.Scan).where(
            models.Scan.order_name == order_name,
            models.Scan.ts >= cutoff,
        ).limit(1)
        q = await db.execute(stmt)
        if (row := q.scalar()):
            return ScanOut(
                result="⚠️ Already Scanned",
                order=row.order_name,
                tag=_detect_delivery_tag(row.tags),
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

    delivery_tag = _detect_delivery_tag(order.get("tags", ""))
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
        tag=delivery_tag,
        ts=scan.ts,
    )


@app.get("/tag-summary")
async def tag_summary():
    async with database.AsyncSessionLocal() as db:
        q = await db.execute(text("SELECT tags FROM scans"))
        counts = {tag: 0 for tag in DELIVERY_TAGS}
        for (t,) in q:
            tokens = [(tok or "").strip().lower() for tok in (t or "").split(",")]
            for tok in tokens:
                if tok in counts:
                    counts[tok] += 1
    return counts


@app.get("/tag-summary/by-store")
async def tag_summary_by_store():
    """Return tag counts grouped by store."""
    async with database.AsyncSessionLocal() as db:
        q = await db.execute(text("SELECT store, tags FROM scans"))
        summary: dict[str, dict[str, int]] = {}
        for store, tags in q:
            store_counts = summary.setdefault(store, {tag: 0 for tag in DELIVERY_TAGS})
            tokens = [(tok or "").strip().lower() for tok in (tags or "").split(",")]
            for tok in tokens:
                if tok in store_counts:
                    store_counts[tok] += 1
    return summary


@app.get("/scans", response_model=list[ScanRecord])
async def list_scans(date: str, tag: str | None = None):
    """Return scans for a given *date* (YYYY-MM-DD) optionally filtered by tag."""
    day = datetime.fromisoformat(date)
    next_day = day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    async with database.AsyncSessionLocal() as db:
        stmt = select(models.Scan).where(models.Scan.ts >= day, models.Scan.ts < next_day)
        if tag:
            stmt = stmt.where(models.Scan.tags.ilike(f"%{tag}%"))
        stmt = stmt.order_by(models.Scan.ts.desc())
        q = await db.execute(stmt)
        rows = q.scalars().all()
        return [ScanRecord.model_validate(r.__dict__) for r in rows]


@app.patch("/scans/{scan_id}", response_model=ScanRecord)
async def update_scan(scan_id: int, data: ScanUpdate):
    async with database.AsyncSessionLocal() as db:
        scan = await db.get(models.Scan, scan_id)
        if not scan:
            raise HTTPException(404, "Scan not found")
        if data.tags is not None:
            scan.tags = data.tags
        if data.driver is not None:
            scan.driver = data.driver
        if data.status is not None:
            scan.status = data.status
        await db.commit()
        await db.refresh(scan)
        return ScanRecord.model_validate(scan.__dict__)


@app.get("/health")
def health():
    return {"ok": True}


# Serve built frontend files if
static_path = os.getenv("STATIC_FILES_PATH", "static")
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")


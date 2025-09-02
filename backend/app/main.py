from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
from fastapi.staticfiles import StaticFiles
from .schemas import ScanIn, ScanOut, ScanRecord, ScanUpdate, ScanCreate
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
            await conn.execute(
                text("ALTER TABLE scans ADD COLUMN driver VARCHAR DEFAULT ''")
            )

        if "cod" not in columns:
            await conn.execute(
                text("ALTER TABLE scans ADD COLUMN cod BOOLEAN DEFAULT FALSE")
            )

        if "phone" not in columns:
            await conn.execute(
                text("ALTER TABLE scans ADD COLUMN phone VARCHAR DEFAULT ''")
            )

    yield


app = FastAPI(title="Order‑Scanner API", lifespan=lifespan)

_barcode_re = re.compile(r"\d+")


# Split a tag string into tokens.  If commas are present they are treated as the
# delimiter and spaces inside tokens are preserved.  Otherwise whitespace acts as
# the separator.
def _tokenize_tags(tag_str: str) -> list[str]:
    if not tag_str:
        return []
    if "," in tag_str:
        tokens = [t.strip() for t in tag_str.split(",") if t.strip()]
    else:
        tokens = re.split(r"\s+", tag_str)
        tokens = [t.strip() for t in tokens if t.strip()]
    return tokens


# Mapping of tag variants to their canonical form.  Tags not listed here are
# ignored.  Keys and values should be lowercase.
_TAG_VARIANTS = {
    "big": "big",
    "k": "k",
    "12livery": "12livery",
    "12livrey": "12livery",
    "fast": "fast",
    "oscario": "oscario",
    "sand": "sand",
    "sandy": "sand",
}

# List of canonical delivery tags.  This is derived from the variant mapping
# above and used by various endpoints when returning summary information.
DELIVERY_TAGS = list(dict.fromkeys(_TAG_VARIANTS.values()))

# Number of days to consider a previous scan as recent when checking for
# duplicates. This can be overridden with the ``RECENT_SCAN_DAYS``
# environment variable.
RECENT_SCAN_DAYS = int(os.getenv("RECENT_SCAN_DAYS", 7))


def _detect_delivery_tag(tag_str: str) -> str:
    """Return the first known delivery tag found in *tag_str*.

    Shopify typically stores tags as a comma separated list, however some
    installations have been observed to use spaces instead. Tokens are extracted
    with :func:`_tokenize_tags` and matched case-insensitively against
    :data:`DELIVERY_TAGS`.
    """

    tokens = [t.lower() for t in _tokenize_tags(tag_str or "")]

    for i, tok in enumerate(tokens):
        canonical = _TAG_VARIANTS.get(tok) or _TAG_VARIANTS.get(tok.replace(" ", ""))
        if canonical:
            return canonical
        if i + 1 < len(tokens):
            combined = tok + tokens[i + 1]
            canonical = _TAG_VARIANTS.get(combined) or _TAG_VARIANTS.get(
                combined.replace(" ", "")
            )
            if canonical:
                return canonical
    return ""


def _extract_canonical_tags(tag_str: str) -> list[str]:
    """Return a list of all known delivery tags found in *tag_str*."""

    tokens = [t.lower() for t in _tokenize_tags(tag_str or "")]
    found: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        canonical = _TAG_VARIANTS.get(tok) or _TAG_VARIANTS.get(tok.replace(" ", ""))
        if not canonical and i + 1 < len(tokens):
            combined = tok + tokens[i + 1]
            canonical = _TAG_VARIANTS.get(combined) or _TAG_VARIANTS.get(
                combined.replace(" ", "")
            )
            if canonical:
                i += 1  # skip next token
        if canonical:
            found.append(canonical)
        i += 1
    return found


def _clean(barcode: str) -> str:
    digits = _barcode_re.findall(barcode)
    digits = "".join(digits).lstrip("0")
    max_digits = shopify.CONFIG.get("MAX_DIGITS", 6)
    if not digits or len(digits) > max_digits:
        raise ValueError("Invalid barcode")
    return "#" + digits


@app.post("/scan", response_model=ScanOut)
async def scan(data: ScanIn, background_tasks: BackgroundTasks):
    try:
        order_name = _clean(data.barcode)
    except ValueError:
        raise HTTPException(400, "❌ Invalid barcode")

    async with database.AsyncSessionLocal() as db:
        cutoff = datetime.utcnow() - timedelta(days=RECENT_SCAN_DAYS)
        stmt = (
            select(models.Scan)
            .where(
                models.Scan.order_name == order_name,
                models.Scan.ts >= cutoff,
            )
            .limit(1)
        )
        q = await db.execute(stmt)
        if row := q.scalar():
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
            ts=datetime.utcnow(),
        )

    delivery_tag = _detect_delivery_tag(order.get("tags", ""))
    phone = order.get("phone", "")

    # Check for duplicate phone in the last 3 days
    dup_phone_note = ""
    if phone:
        phone_cutoff = datetime.utcnow() - timedelta(days=3)
        async with database.AsyncSessionLocal() as db:
            stmt = (
                select(models.Scan)
                .where(
                    models.Scan.phone == phone,
                    models.Scan.ts >= phone_cutoff,
                )
                .limit(1)
            )
            q = await db.execute(stmt)
            if q.scalar():
                dup_phone_note = " ⚠️ Duplicate phone in last 3 days"

    scan = models.Scan(
        order_name=order_name,
        phone=phone,
        tags=order.get("tags", ""),
        fulfillment=order["fulfillment"],
        status=order["status"],
        store=order["store"],
        result=order["result"],
    )
    async with database.AsyncSessionLocal() as db:
        db.add(scan)
        await db.commit()

    background_tasks.add_task(
        sheets.append_row,
        [
            scan.ts.isoformat(" ", "seconds"),
            order_name,
            scan.tags,
            scan.fulfillment,
            scan.status,
            scan.store,
            scan.result,
        ],
    )
    return ScanOut(
        result=(scan.result + dup_phone_note).strip(),
        order=order_name,
        tag=delivery_tag,
        ts=scan.ts,
    )


@app.get("/tag-summary")
async def tag_summary(date: str | None = None):
    """Return delivery tag counts for the given *date* (YYYY-MM-DD)."""

    if not date:
        date = datetime.utcnow().date().isoformat()

    day = datetime.fromisoformat(date)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    async with database.AsyncSessionLocal() as db:
        stmt = select(models.Scan.tags).where(
            models.Scan.ts >= start,
            models.Scan.ts < end,
        )
        q = await db.execute(stmt)
        counts = {tag: 0 for tag in DELIVERY_TAGS}
        for (t,) in q:
            for canonical in _extract_canonical_tags(t or ""):
                if canonical in counts:
                    counts[canonical] += 1
        return counts


@app.get("/tag-summary/by-store")
async def tag_summary_by_store():
    """Return tag counts grouped by store."""
    async with database.AsyncSessionLocal() as db:
        q = await db.execute(text("SELECT store, tags FROM scans"))
        summary: dict[str, dict[str, int]] = {}
        for store, tags in q:
            store_counts = summary.setdefault(store, {tag: 0 for tag in DELIVERY_TAGS})
            for canonical in _extract_canonical_tags(tags or ""):
                if canonical in store_counts:
                    store_counts[canonical] += 1
        return summary


@app.get("/scans", response_model=list[ScanRecord])
async def list_scans(date: str, tag: str | None = None):
    """Return scans for a given *date* (YYYY-MM-DD) optionally filtered by tag."""
    day = datetime.fromisoformat(date)
    next_day = day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=1
    )
    async with database.AsyncSessionLocal() as db:
        stmt = select(models.Scan).where(
            models.Scan.ts >= day, models.Scan.ts < next_day
        )
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


@app.delete("/scans/{scan_id}", status_code=204)
async def delete_scan(scan_id: int):
    async with database.AsyncSessionLocal() as db:
        scan = await db.get(models.Scan, scan_id)
        if not scan:
            raise HTTPException(404, "Scan not found")
        await db.delete(scan)
        await db.commit()
    return Response(status_code=204)


@app.post("/scans", response_model=ScanRecord)
async def create_scan(data: ScanCreate, background_tasks: BackgroundTasks):
    """Create a scan record manually.

    Accepts an order name (with or without the leading '#'), optional tags,
    fulfillment, status and store. Result is marked as manually added.
    """
    # Normalize the order name using the same logic as barcode cleaning
    try:
        order_name = _clean(data.order_name)
    except ValueError:
        raise HTTPException(400, "❌ Invalid order number")

    scan = models.Scan(
        order_name=order_name,
        phone="",
        tags=data.tags or "",
        fulfillment=(data.fulfillment or "").lower(),
        status=data.status or "",
        store=(data.store or "").lower(),
        result="✅ Added manually",
    )

    async with database.AsyncSessionLocal() as db:
        db.add(scan)
        await db.commit()
        await db.refresh(scan)

    # Append to the sheet for consistency
    background_tasks.add_task(
        sheets.append_row,
        [
            scan.ts.isoformat(" ", "seconds"),
            order_name,
            scan.tags,
            scan.fulfillment,
            scan.status,
            scan.store,
            scan.result,
        ],
    )

    return ScanRecord.model_validate(scan.__dict__)


@app.get("/fulfilled-counts")
async def fulfilled_counts(date: str | None = None):
    """Return counts of fulfilled orders by store for a given date (UTC) directly from Shopify."""
    if not date:
        date = datetime.utcnow().date().isoformat()
    try:
        counts = await shopify.fulfilled_counts_by_store(date)
        return counts
    except Exception as e:
        # Surface a friendly error
        raise HTTPException(502, f"Failed to fetch from Shopify: {e}")

@app.get("/health")
def health():
    return {"ok": True}


# Serve built frontend files if
static_path = os.getenv("STATIC_FILES_PATH", "static")
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")

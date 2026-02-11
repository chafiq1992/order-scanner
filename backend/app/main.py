from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .schemas import (
    ScanIn,
    ScanOut,
    ReturnScanOut,
    ReturnScanRecord,
    ReturnScanCreate,
    ScanRecord,
    ScanUpdate,
    ScanCreate,
    DeliveryTagUpdate,
)
from . import shopify, database, models, sheets
from sqlalchemy import select, text
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with database.engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)

        def get_columns(sync_conn, table_name: str):
            return [c["name"] for c in inspect(sync_conn).get_columns(table_name)]

        columns = await conn.run_sync(get_columns, "scans")

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

        # Create a unique index on order_name to avoid duplicate inserts during concurrent scans.
        try:
            await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_scans_order_name ON scans(order_name)"))
        except Exception:
            # Ignore if DB does not support IF NOT EXISTS or duplicates exist
            pass

        # --- best-effort Return Scanner schema ensure/migrate ---
        # We store return scans in a separate table. For existing deployments we need to add any
        # missing columns (e.g. 'tags') without breaking startup.
        try:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS return_scans (
                      id SERIAL PRIMARY KEY,
                      ts TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() at time zone 'utc'),
                      order_name VARCHAR NOT NULL,
                      tags VARCHAR DEFAULT '',
                      store VARCHAR DEFAULT '',
                      fulfillment VARCHAR DEFAULT '',
                      status VARCHAR DEFAULT '',
                      financial VARCHAR DEFAULT '',
                      result VARCHAR DEFAULT ''
                    )
                    """
                )
            )
        except Exception:
            # If CREATE TABLE isn't permitted (managed DB), we still try to ALTER below.
            pass

        try:
            return_cols = await conn.run_sync(get_columns, "return_scans")
        except Exception:
            return_cols = []

        try:
            if "tags" not in return_cols:
                await conn.execute(text("ALTER TABLE return_scans ADD COLUMN tags VARCHAR DEFAULT ''"))
            if "store" not in return_cols:
                await conn.execute(text("ALTER TABLE return_scans ADD COLUMN store VARCHAR DEFAULT ''"))
            if "fulfillment" not in return_cols:
                await conn.execute(text("ALTER TABLE return_scans ADD COLUMN fulfillment VARCHAR DEFAULT ''"))
            if "status" not in return_cols:
                await conn.execute(text("ALTER TABLE return_scans ADD COLUMN status VARCHAR DEFAULT ''"))
            if "financial" not in return_cols:
                await conn.execute(text("ALTER TABLE return_scans ADD COLUMN financial VARCHAR DEFAULT ''"))
            if "result" not in return_cols:
                await conn.execute(text("ALTER TABLE return_scans ADD COLUMN result VARCHAR DEFAULT ''"))
        except Exception:
            pass

        try:
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_return_scans_ts ON return_scans(ts)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_return_scans_order_name ON return_scans(order_name)"))
        except Exception:
            pass

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
    "meta": "meta",
    "sand": "meta",
    "sandy": "meta",
    "lx": "lx",
    "pal": "pal",
    "l24": "l24",
    "ibex": "ibex",
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
    # Some systems prefix an order number with a merchant id, e.g. "7-125652".
    # For these, keep only the part after the last dash before extracting digits.
    s = str(barcode or "").strip()
    if "-" in s:
        s = s.split("-")[-1]

    digits = _barcode_re.findall(s)
    digits = "".join(digits).lstrip("0")
    max_digits = shopify.CONFIG.get("MAX_DIGITS", 6)
    if not digits or len(digits) > max_digits:
        raise ValueError("Invalid barcode")
    return "#" + digits


@app.post("/return-scan", response_model=ReturnScanOut)
async def return_scan(data: ScanIn):
    """Return scanner flow: normalize the barcode and verify it exists in Shopify.

    Unlike /scan, this endpoint does NOT block on fulfillment/tag rules; it will
    accept fulfilled/unfulfilled and any status as long as the order exists.
    """
    try:
        order_name = _clean(data.barcode)
    except ValueError:
        raise HTTPException(400, "❌ Invalid barcode")

    try:
        order = await shopify.find_order(order_name)
    except Exception as e:
        raise HTTPException(502, f"Shopify lookup failed: {e}")

    found = not ((order.get("result") or "") == "❌ Not Found" or not (order.get("store") or ""))
    payload = {
        "result": ("✅ Found" if found else "❌ Order not found"),
        "order": order_name,
        "store": (order.get("store") or "") if found else "",
        "fulfillment": (order.get("fulfillment") or "") if found else "",
        "status": (order.get("status") or "") if found else "",
        "financial": (order.get("financial") or "") if found else "",
        "ts": datetime.utcnow(),
    }

    # Persist return scans in DB so the Return list can be loaded across devices.
    try:
        tags = (order.get("tags") or "") if found else ""
        row = models.ReturnScan(
            order_name=order_name,
            tags=tags,
            store=(payload["store"] or "").lower(),
            fulfillment=(payload["fulfillment"] or "").lower(),
            status=payload["status"] or "",
            financial=payload["financial"] or "",
            result=payload["result"] or "",
        )
        async with database.AsyncSessionLocal() as db:
            db.add(row)
            await db.commit()
    except Exception:
        # Don't fail the scan UI if persistence is temporarily unavailable.
        pass

    return ReturnScanOut(**payload)


@app.get("/return-scans", response_model=list[ReturnScanRecord])
async def list_return_scans(start: str, end: str | None = None, tag: str | None = None):
    """Return return-scans in an inclusive date range [start, end] (YYYY-MM-DD, UTC).

    If *end* is omitted, it defaults to *start*.
    """
    start_day = datetime.fromisoformat(start).replace(hour=0, minute=0, second=0, microsecond=0)
    end_str = end or start
    end_day = datetime.fromisoformat(end_str).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    async with database.AsyncSessionLocal() as db:
        stmt = select(models.ReturnScan).where(
            models.ReturnScan.ts >= start_day, models.ReturnScan.ts < end_day
        )
        if tag:
            stmt = stmt.where(models.ReturnScan.tags.ilike(f"%{tag}%"))
        stmt = stmt.order_by(models.ReturnScan.ts.desc())
        q = await db.execute(stmt)
        rows = q.scalars().all()
        return [ReturnScanRecord.model_validate(r.__dict__) for r in rows]


@app.post("/return-scans", response_model=ReturnScanRecord)
async def create_return_scan(data: ReturnScanCreate):
    """Create a return-scan record manually by typed order number.

    This follows the same flow as /return-scan: normalize the order number and
    look it up in Shopify, then persist to DB.
    """
    try:
        order_name = _clean(data.order_name)
    except ValueError:
        raise HTTPException(400, "❌ Invalid order number")

    try:
        order = await shopify.find_order(order_name)
    except Exception as e:
        raise HTTPException(502, f"Shopify lookup failed: {e}")

    found = not ((order.get("result") or "") == "❌ Not Found" or not (order.get("store") or ""))
    result = "✅ Found" if found else "❌ Order not found"
    row = models.ReturnScan(
        order_name=order_name,
        tags=((order.get("tags") or "") if found else ""),
        store=((order.get("store") or "") if found else "").lower(),
        fulfillment=((order.get("fulfillment") or "") if found else "").lower(),
        status=(order.get("status") or "") if found else "",
        financial=(order.get("financial") or "") if found else "",
        result=result,
    )

    async with database.AsyncSessionLocal() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)

    return ReturnScanRecord.model_validate(row.__dict__)


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
            if not (data.confirm_duplicate or False):
                return ScanOut(
                    scan_id=row.id,
                    result="⚠️ Already Scanned",
                    order=row.order_name,
                    tag=_detect_delivery_tag(row.tags),
                    ts=row.ts,
                    needs_confirmation=True,
                    reason="order_duplicate",
                )

    try:
        order = await shopify.find_order(order_name)
    except Exception as e:
        # Avoid surfacing 500s when Shopify/store lookups fail
        raise HTTPException(502, f"Shopify lookup failed: {e}")

    # If no store returned a match, don't create a scan entry
    if (order.get("result") or "") == "❌ Not Found":
        return ScanOut(
            scan_id=None,
            result="❌ Order not found — not added",
            order=order_name,
            tag="",
            ts=datetime.utcnow(),
        )

    if order["fulfillment"].lower() == "unfulfilled" and not order["tags"]:
        return ScanOut(
            scan_id=None,
            result="❌ Unfulfilled order with no tag — not added",
            order=order_name,
            tag="",
            ts=datetime.utcnow(),
        )

    delivery_tag = _detect_delivery_tag(order.get("tags", ""))
    phone = order.get("phone", "")

    # Check for duplicate phone in the last 3 days
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
            if q.scalar() and not (data.confirm_duplicate or False):
                return ScanOut(
                    scan_id=None,
                    result="⚠️ Duplicate phone in last 3 days",
                    order=order_name,
                    tag=delivery_tag,
                    ts=datetime.utcnow(),
                    needs_confirmation=True,
                    reason="phone_duplicate",
                )

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
        try:
            await db.commit()
        except IntegrityError:
            # Another request already created this scan; load and return as already scanned
            await db.rollback()
            stmt = select(models.Scan).where(models.Scan.order_name == order_name).limit(1)
            q = await db.execute(stmt)
            row = q.scalar()
            return ScanOut(
                scan_id=(row.id if row else None),
                result="⚠️ Already Scanned",
                order=order_name,
                tag=_detect_delivery_tag(row.tags if row else ""),
                ts=(row.ts if row else datetime.utcnow()),
                needs_confirmation=True,
                reason="order_duplicate",
            )

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
        scan_id=scan.id,
        result=scan.result,
        order=order_name,
        tag=delivery_tag,
        ts=scan.ts,
    )


def _replace_delivery_tag_in_tags(tags: str, new_tag: str) -> str:
    """Replace (or clear) delivery-company tag in a Shopify-like tag string, preserving other tags."""
    tokens = _tokenize_tags(tags or "")
    kept: list[str] = []
    for t in tokens:
        low = t.lower().strip()
        canonical = _TAG_VARIANTS.get(low) or _TAG_VARIANTS.get(low.replace(" ", ""))
        if canonical and canonical in DELIVERY_TAGS:
            continue
        kept.append(t.strip())

    new_tag = (new_tag or "").strip().lower()
    if new_tag:
        kept.append(new_tag)

    # Use comma-separated output to match Shopify convention
    return ", ".join([t for t in kept if t])


@app.patch("/scans/{scan_id}/delivery-tag", response_model=ScanRecord)
async def update_scan_delivery_tag(scan_id: int, data: DeliveryTagUpdate, background_tasks: BackgroundTasks):
    new_tag = (data.tag or "").strip().lower()
    if new_tag and new_tag not in DELIVERY_TAGS:
        raise HTTPException(400, f"Invalid delivery tag: {new_tag}")

    async with database.AsyncSessionLocal() as db:
        scan = await db.get(models.Scan, scan_id)
        if not scan:
            raise HTTPException(404, "Scan not found")

        scan.tags = _replace_delivery_tag_in_tags(scan.tags or "", new_tag)
        await db.commit()
        await db.refresh(scan)

        # Update Shopify in background so UI is instant even if Shopify is slow
        background_tasks.add_task(shopify.update_order_delivery_tag, scan.order_name, new_tag)

        return ScanRecord.model_validate(scan.__dict__)


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


# Allow deep-linking directly to the Return Scanner page.
# This must be defined before the StaticFiles mount (which is a catch-all).
# Keep /return-scan for backwards compatibility; prefer /return-scanner.
@app.get("/return-scan", include_in_schema=False)
@app.get("/return-scanner", include_in_schema=False)
def return_scanner_page():
    static_root = os.getenv("STATIC_FILES_PATH", "static")
    index_path = os.path.join(static_root, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(404, "Frontend not built")
    return FileResponse(index_path)


# Serve built frontend files if
static_path = os.getenv("STATIC_FILES_PATH", "static")
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")

from pydantic import BaseModel, Field
from datetime import datetime


class ScanIn(BaseModel):
    barcode: str = Field(
        ..., json_schema_extra={"example": "#123456"}
    )
    confirm_duplicate: bool | None = False


class ScanOut(BaseModel):
    scan_id: int | None = None
    result: str
    order: str
    tag: str
    ts: datetime
    needs_confirmation: bool | None = False
    reason: str | None = ""

class ReturnScanOut(BaseModel):
    """Response for the Return Scanner flow.

    Unlike the delivery scanner, return scanning is allowed for any fulfillment / status
    as long as the order exists in Shopify.
    """

    result: str
    order: str
    store: str | None = ""
    fulfillment: str | None = ""
    status: str | None = ""
    financial: str | None = ""
    ts: datetime


class ReturnScanRecord(BaseModel):
    id: int
    ts: datetime
    order_name: str
    tags: str | None = ""
    store: str | None = ""
    fulfillment: str | None = ""
    status: str | None = ""
    financial: str | None = ""
    result: str | None = ""


class ReturnScanCreate(BaseModel):
    order_name: str


class DeliveryTagUpdate(BaseModel):
    tag: str | None = ""


class ScanRecord(BaseModel):
    id: int
    ts: datetime
    order_name: str
    phone: str | None = ""
    tags: str | None
    fulfillment: str | None
    status: str | None
    store: str | None
    result: str | None
    driver: str | None = ""
    cod: bool | None = False


class ScanUpdate(BaseModel):
    tags: str | None = None
    driver: str | None = None
    status: str | None = None


class ScanCreate(BaseModel):
    order_name: str
    tags: str | None = ""
    fulfillment: str | None = None
    status: str | None = None
    store: str | None = ""
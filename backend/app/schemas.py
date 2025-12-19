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
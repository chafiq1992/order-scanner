from pydantic import BaseModel, Field
from datetime import datetime


class ScanIn(BaseModel):
    barcode: str = Field(
        ..., json_schema_extra={"example": "#123456"}
    )


class ScanOut(BaseModel):
    result: str
    order: str
    tag: str
    ts: datetime


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

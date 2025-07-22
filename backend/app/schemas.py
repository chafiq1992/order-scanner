from pydantic import BaseModel, Field
from datetime import datetime

class ScanIn(BaseModel):
    barcode: str = Field(..., example="#123456")

class ScanOut(BaseModel):
    result: str
    order:  str
    tag:    str
    ts:     datetime

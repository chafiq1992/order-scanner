from sqlalchemy import Column, String, DateTime, Integer
from .database import Base
from datetime import datetime


class Scan(Base):
    __tablename__ = "scans"
    id = Column(Integer, primary_key=True, index=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    order_name = Column(String, index=True)
    tags = Column(String)
    fulfillment = Column(String)
    status = Column(String)
    store = Column(String)
    result = Column(String)

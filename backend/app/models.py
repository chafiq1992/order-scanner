from sqlalchemy import Column, String, DateTime, Integer, Boolean
from .database import Base
from datetime import datetime


class Scan(Base):
    __tablename__ = "scans"
    id = Column(Integer, primary_key=True, index=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    order_name = Column(String, index=True)
    phone = Column(String, index=True, default="")
    tags = Column(String)
    fulfillment = Column(String)
    status = Column(String)
    store = Column(String)
    result = Column(String)
    driver = Column(String, default="")
    cod = Column(Boolean, default=False)


class ReturnScan(Base):
    __tablename__ = "return_scans"
    id = Column(Integer, primary_key=True, index=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    order_name = Column(String, index=True)
    tags = Column(String, default="")
    store = Column(String, default="")
    fulfillment = Column(String, default="")
    status = Column(String, default="")
    financial = Column(String, default="")
    result = Column(String, default="")
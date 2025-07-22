import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys
import os

sys.path.append(str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("STATIC_FILES_PATH", "static")
Path("static").mkdir(exist_ok=True)
from backend.app.main import app, _clean

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}

def test_clean_valid():
    assert _clean("00123") == "#123"
    assert _clean("abc123def") == "#123"

def test_clean_invalid():
    with pytest.raises(ValueError):
        _clean("abc")
    with pytest.raises(ValueError):
        _clean("1234567")


"""Golden-path API test with Sarvam mocked out. Run: pytest tests/test_api.py"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_munimai.db"
os.environ["N8N_WEBHOOK_URL"] = ""          # simulated WhatsApp send
os.environ["N8N_CALLBACK_SECRET"] = "s3cret"

import pytest
from fastapi.testclient import TestClient

from app import main
from app.db import Base, engine
from app.schemas import ParsedOrder


@pytest.fixture()
def client(monkeypatch):
    Base.metadata.drop_all(engine)
    monkeypatch.setattr(main.parser, "parse_order", lambda t: ParsedOrder(
        intent="LOG_PURCHASE_ORDER", supplier="Amul", item="milk", quantity=50, unit="packet", total_amount=1500))
    with TestClient(main.app) as c:
        yield c


def test_golden_path(client):
    r = client.post("/voice", data={"text": "Amul ke 50 packet, 1500 ka bill"})
    assert r.status_code == 200
    o = r.json()
    assert o["status"] == "PENDING_CONFIRMATION" and o["supplier"] == "Amul"

    r = client.post("/confirm", data={"order_id": o["order_id"], "text": "haan"})
    assert r.status_code == 200 and r.json()["status"] == "EXECUTED"

    ledger = client.get("/ledger").json()
    assert ledger["grand_total"] == 1500

    # confirming again is idempotent: no second ledger entry
    client.post("/confirm", data={"order_id": o["order_id"], "decision": "confirm"})
    assert len(client.get("/ledger").json()["entries"]) == 1


def test_reject_and_illegal_confirm(client):
    o = client.post("/voice", data={"text": "x"}).json()
    assert client.post("/confirm", data={"order_id": o["order_id"], "text": "nahi"}).json()["status"] == "CANCELLED"
    assert client.post("/confirm", data={"order_id": o["order_id"], "decision": "confirm"}).status_code == 409


def test_callback_needs_secret(client):
    o = client.post("/voice", data={"text": "x"}).json()
    assert client.post(f"/orders/{o['order_id']}/executed", json={"success": True}).status_code == 401

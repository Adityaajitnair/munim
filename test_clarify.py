"""Run:  pip install httpx pytest  &&  pytest -q test_clarify.py
Checks the stuck-order -> clarification -> ledger flow (no API keys needed)."""
from fastapi.testclient import TestClient
from app.main import app, ledger

c = TestClient(app)


def setup_function():
    ledger.clear()


def test_stuck_order_is_recorded():
    r = c.post("/clarifications", json={
        "question": "Which supplier?", "transcript": "do packet doodh",
        "item": "milk packet", "quantity": 2})
    assert r.status_code == 201
    row = r.json()
    assert row["status"] == "needs_clarification"
    assert row["missing_fields"] == ["supplier"]
    assert len(c.get("/orders").json()) == 1          # it IS in the ledger


def test_answer_completes_same_row():
    row = c.post("/clarifications", json={
        "question": "?", "item": "milk packet", "quantity": 2}).json()
    r = c.post(f"/clarifications/{row['id']}/answer", json={"supplier": " Amul "})
    out = r.json()
    assert out["status"] == "pending" and out["clarified"] is True
    assert out["supplier"] == "amul" and out["question"] is None
    assert len(c.get("/orders").json()) == 1          # same row, no duplicate


def test_partial_answer_asks_next_question():
    row = c.post("/clarifications", json={"question": "?", "quantity": 3}).json()
    out = c.post(f"/clarifications/{row['id']}/answer", json={"item": "biscuit"}).json()
    assert out["status"] == "needs_clarification"
    assert out["missing_fields"] == ["supplier"]
    assert "supplier" in out["question"]


def test_guards():
    row = c.post("/clarifications", json={"question": "?", "item": "x", "quantity": 1}).json()
    assert c.post(f"/clarifications/{row['id']}/answer", json={}).status_code == 422
    assert c.post(f"/clarifications/{row['id']}/answer", json={"quantity": -5}).status_code == 422
    c.post(f"/clarifications/{row['id']}/answer", json={"supplier": "amul"})
    assert c.post(f"/clarifications/{row['id']}/answer", json={"supplier": "x"}).status_code == 409
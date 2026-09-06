import pytest
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import engine, Base

client = TestClient(app)

@pytest.fixture(scope="function", autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

def test_full_roomie_flow():
    # 1. Register User 1 (Amit)
    r1 = client.post("/api/auth/register", json={
        "email": "amit@example.com",
        "username": "amit",
        "full_name": "Amit Sharma",
        "password": "password123"
    })
    assert r1.status_code == 201, r1.text
    amit_token = r1.json()["access_token"]
    amit_id = r1.json()["user"]["id"]
    amit_headers = {"Authorization": f"Bearer {amit_token}"}

    # 2. Register User 2 (Rahul)
    r2 = client.post("/api/auth/register", json={
        "email": "rahul@example.com",
        "username": "rahul",
        "full_name": "Rahul Verma",
        "password": "password123"
    })
    assert r2.status_code == 201, r2.text
    rahul_token = r2.json()["access_token"]
    rahul_id = r2.json()["user"]["id"]
    rahul_headers = {"Authorization": f"Bearer {rahul_token}"}

    # 3. Amit creates Room "Flat 402"
    room_resp = client.post("/api/rooms", json={
        "name": "Flat 402 - 3BHK",
        "description": "Our cozy flat near office"
    }, headers=amit_headers)
    assert room_resp.status_code == 201, room_resp.text
    room_data = room_resp.json()
    room_id = room_data["id"]
    assert room_data["total_members"] == 1

    # 4. Amit invites Rahul to the Room
    invite_resp = client.post(f"/api/rooms/{room_id}/invite", json={
        "username_or_email": "rahul"
    }, headers=amit_headers)
    assert invite_resp.status_code == 200, invite_resp.text
    membership_id = invite_resp.json()["id"]
    assert invite_resp.json()["status"] == "PENDING"

    # 5. Rahul checks pending invitations
    pending_resp = client.get("/api/rooms/invitations/pending", headers=rahul_headers)
    assert pending_resp.status_code == 200, pending_resp.text
    pending_list = pending_resp.json()
    assert any(inv["membership_id"] == membership_id for inv in pending_list)

    # 6. Rahul Approves the invitation
    respond_resp = client.post(
        f"/api/rooms/invitations/{membership_id}/respond",
        json={"action": "ACCEPT"},
        headers=rahul_headers
    )
    assert respond_resp.status_code == 200, respond_resp.text
    assert respond_resp.json()["new_status"] == "ACCEPTED"

    # Check room details now has 2 members
    details_resp = client.get(f"/api/rooms/{room_id}", headers=amit_headers)
    assert details_resp.json()["total_members"] == 2

    # 7. Amit adds expense: Groceries ₹600 (default: split equally among all members)
    exp1_resp = client.post(f"/api/rooms/{room_id}/expenses", json={
        "title": "Groceries (Milk, Veggies, Atta)",
        "amount": 600.0,
        "category": "Groceries",
        "expense_date": "2026-09-01",
    }, headers=amit_headers)
    assert exp1_resp.status_code == 201, exp1_resp.text
    exp1_data = exp1_resp.json()
    assert len(exp1_data["splits"]) == 2
    for s in exp1_data["splits"]:
        assert s["share_amount"] == 300.0

    # 8. Rahul adds expense: Special Snacks ₹300 (custom split: only Rahul)
    exp2_resp = client.post(f"/api/rooms/{room_id}/expenses", json={
        "title": "Special Protein Snacks",
        "amount": 300.0,
        "category": "Snacks",
        "expense_date": "2026-09-02",
        "split_user_ids": [rahul_id]
    }, headers=rahul_headers)
    assert exp2_resp.status_code == 201, exp2_resp.text
    exp2_data = exp2_resp.json()
    assert len(exp2_data["splits"]) == 1
    assert exp2_data["splits"][0]["user_id"] == rahul_id

    # 9. Verify Balances & Calculation
    # Total expenses: 600 + 300 = 900
    # Amit: paid 600, share 300 -> net +300
    # Rahul: paid 300, share 300 + 300 = 600 -> net -300
    # Settlement: Rahul owes Amit 300
    bal_resp = client.get(f"/api/rooms/{room_id}/balances", headers=amit_headers)
    assert bal_resp.status_code == 200, bal_resp.text
    bal_data = bal_resp.json()
    assert bal_data["total_room_expenses"] == 900.0

    amit_bal = next(m for m in bal_data["member_balances"] if m["user_id"] == amit_id)
    rahul_bal = next(m for m in bal_data["member_balances"] if m["user_id"] == rahul_id)

    assert amit_bal["net_balance"] == 300.0
    assert rahul_bal["net_balance"] == -300.0

    assert len(bal_data["suggested_settlements"]) == 1
    settle_trans = bal_data["suggested_settlements"][0]
    assert settle_trans["from_user"]["id"] == rahul_id
    assert settle_trans["to_user"]["id"] == amit_id
    assert settle_trans["amount"] == 300.0

    # 10. Rahul settles the debt with Amit
    settle_resp = client.post(f"/api/rooms/{room_id}/settle", json={
        "receiver_id": amit_id,
        "amount": 300.0,
        "notes": "Paid via UPI"
    }, headers=rahul_headers)
    assert settle_resp.status_code == 201, settle_resp.text

    # 11. Balances should now be 0 for both!
    bal_resp2 = client.get(f"/api/rooms/{room_id}/balances", headers=rahul_headers)
    bal_data2 = bal_resp2.json()
    amit_bal2 = next(m for m in bal_data2["member_balances"] if m["user_id"] == amit_id)
    rahul_bal2 = next(m for m in bal_data2["member_balances"] if m["user_id"] == rahul_id)
    assert amit_bal2["net_balance"] == 0.0
    assert rahul_bal2["net_balance"] == 0.0
    assert len(bal_data2["suggested_settlements"]) == 0

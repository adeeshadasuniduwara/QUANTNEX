

def test_archived_goal_can_be_deleted_and_is_removed_from_goal_list():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    created = client.post("/api/v1/goals", json={
        "title": "Delete archived goal test",
        "description": "Temporary test target",
        "target_amount": 100,
        "initial_amount": 100,
        "currency": "USD",
        "confirmed_available_real_funds": True,
    })
    assert created.status_code == 200
    goal_id = created.json()["id"]
    assert created.json()["achieved"] is True

    response = client.delete(f"/api/v1/goals/{goal_id}")
    assert response.status_code == 200
    assert response.json() == {"deleted": True, "goal_id": goal_id}

    remaining = client.get("/api/v1/goals")
    assert remaining.status_code == 200
    assert all(goal["id"] != goal_id for goal in remaining.json()["goals"])

    missing = client.delete(f"/api/v1/goals/{goal_id}")
    assert missing.status_code == 404

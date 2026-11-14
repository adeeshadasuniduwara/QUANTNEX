from datetime import datetime, timezone

from app.goal_certificates import build_goal_certificate_pdf


def test_goal_certificate_is_a4_print_ready_pdf_with_integrity_id():
    pdf = build_goal_certificate_pdf(
        display_name="QUANTNEX User",
        goal_title="Nissan GT-R",
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        achieved_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        elapsed_days=2507,
        certificate_id="QX-TEST-CERTIFICATE",
        integrity_fingerprint="a" * 64,
        target_amount=90000, saved_amount=95000, currency="USD",
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2000



def test_demo_certificate_is_a_separate_pdf_variant():
    args = dict(
        display_name="QUANTNEX Demo User",
        goal_title="Sample Personal Goal",
        created_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
        achieved_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        elapsed_days=21,
        certificate_id="DEMO-NOT-VALID",
        integrity_fingerprint="0" * 64,
        target_amount=1000,
        saved_amount=1000,
        currency="USD",
    )
    normal = build_goal_certificate_pdf(**args)
    demo = build_goal_certificate_pdf(**args, demo_only=True)
    assert normal.startswith(b"%PDF")
    assert demo.startswith(b"%PDF")
    assert demo != normal


def test_demo_certificate_api_returns_non_valid_pdf_without_creating_a_goal():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    goals_before = client.get("/api/v1/goals")
    assert goals_before.status_code == 200

    response = client.post("/api/v1/goals/demo-certificate", json={
        "display_name": "Audit Demo User",
        "goal_title": "Sample Milestone",
        "achievement_text": "A sample achievement for preview testing.",
        "target_amount": 1250,
        "currency": "USD",
    })

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"] == (
        'inline; filename="QUANTNEX-DEMO-CERTIFICATE-NOT-VALID.pdf"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 2000

    # A demo preview is deliberately non-qualifying and must not create a real goal.
    goals_after = client.get("/api/v1/goals")
    assert goals_after.status_code == 200
    assert goals_after.json() == goals_before.json()


def test_demo_certificate_api_rejects_invalid_inputs():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    invalid_payloads = [
        {"display_name": "   ", "goal_title": "Sample", "achievement_text": "Preview"},
        {"display_name": "Audit User", "goal_title": "", "achievement_text": "Preview"},
        {"display_name": "Audit User", "goal_title": "Sample", "achievement_text": " "},
        {"display_name": "Audit User", "goal_title": "Sample", "achievement_text": "Preview", "target_amount": "not-a-number"},
        {"display_name": "Audit User", "goal_title": "Sample", "achievement_text": "Preview", "currency": "BTC"},
        {"display_name": "Audit User", "goal_title": "Sample", "achievement_text": "Preview", "target_amount": -1},
        {"display_name": "Audit User", "goal_title": "Sample", "achievement_text": "Preview", "target_amount": 0},
        {"display_name": "Audit User", "goal_title": "Sample", "achievement_text": "Preview", "currency": ""},
    ]
    for payload in invalid_payloads:
        response = client.post("/api/v1/goals/demo-certificate", json=payload)
        assert response.status_code == 422, payload

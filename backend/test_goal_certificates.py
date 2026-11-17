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


def test_certificate_catalog_has_100_unique_designs_split_evenly_by_orientation():
    from app.certificate_designs import certificate_design_catalog, get_certificate_design

    designs = certificate_design_catalog()
    ids = [item["id"] for item in designs]
    assert len(designs) == 100
    assert len(set(ids)) == 100
    assert sum(item["orientation"] == "portrait" for item in designs) == 50
    assert sum(item["orientation"] == "landscape" for item in designs) == 50
    assert len({item["name"] for item in designs}) == 100
    assert get_certificate_design("P-01")["orientation"] == "portrait"
    assert get_certificate_design("L-50")["orientation"] == "landscape"
    import pytest
    with pytest.raises(ValueError):
        get_certificate_design("P-01", "landscape")


def test_portrait_and_landscape_certificate_designs_render_as_pdf():
    common = dict(
        display_name="Certificate Gallery User",
        goal_title="Personal Milestone",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        achieved_at=datetime(2026, 11, 18, tzinfo=timezone.utc),
        elapsed_days=321,
        certificate_id="QX-GALLERY-TEST",
        integrity_fingerprint="b" * 64,
        target_amount=5000,
        saved_amount=5000,
        currency="USD",
    )
    portrait = build_goal_certificate_pdf(**common, design_id="P-17", orientation="portrait")
    landscape_pdf = build_goal_certificate_pdf(**common, design_id="L-42", orientation="landscape")
    assert portrait.startswith(b"%PDF") and len(portrait) > 2000
    assert landscape_pdf.startswith(b"%PDF") and len(landscape_pdf) > 2000
    assert portrait != landscape_pdf


def test_demo_certificate_api_accepts_selected_landscape_design_without_creating_goal():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    before = client.get("/api/v1/goals").json()
    response = client.post("/api/v1/goals/demo-certificate", json={
        "display_name": "Gallery Demo User",
        "goal_title": "Landscape Sample",
        "achievement_text": "A selected landscape template preview.",
        "target_amount": 1000,
        "currency": "USD",
        "design_id": "L-50",
        "orientation": "landscape",
    })
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert client.get("/api/v1/goals").json() == before

    invalid = client.post("/api/v1/goals/demo-certificate", json={
        "display_name": "Gallery Demo User",
        "goal_title": "Mismatch",
        "achievement_text": "Invalid orientation must be rejected.",
        "target_amount": 1000,
        "currency": "USD",
        "design_id": "P-01",
        "orientation": "landscape",
    })
    assert invalid.status_code == 422

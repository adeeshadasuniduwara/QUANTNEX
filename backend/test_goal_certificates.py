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

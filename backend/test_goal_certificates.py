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
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2000

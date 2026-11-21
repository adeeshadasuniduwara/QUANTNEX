from io import BytesIO

from PIL import Image

from app.telegram_branding import build_personal_logo_png, normalise_telegram_name


def test_personal_logo_is_a_square_png():
    payload = build_personal_logo_png("Ada Quant", user_id=42)
    image = Image.open(BytesIO(payload))
    assert image.format == "PNG"
    assert image.size == (1024, 1024)


def test_personal_logo_supports_different_names_and_user_specific_designs():
    first = build_personal_logo_png("Ada Quant", user_id=42)
    second = build_personal_logo_png("Mira FX", user_id=77)
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    assert second.startswith(b"\x89PNG\r\n\x1a\n")
    assert first != second


def test_telegram_name_validation_accepts_unicode_and_normalizes_spacing():
    assert normalise_telegram_name("  Ada   Quant  ") == "Ada Quant"
    assert normalise_telegram_name("අදීෂ") == "අදීෂ"


def test_telegram_name_validation_rejects_commands_links_and_invalid_lengths():
    assert normalise_telegram_name("/start") is None
    assert normalise_telegram_name("https://example.com") is None
    assert normalise_telegram_name("A") is None
    assert normalise_telegram_name("x" * 33) is None

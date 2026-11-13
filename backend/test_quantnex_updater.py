from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantnex_updater import _safe_relative, _valid_sha


def test_sha_validation():
    assert _valid_sha("a" * 40)
    assert not _valid_sha("a" * 39)
    assert not _valid_sha("../" + "a" * 37)


def test_safe_source_paths():
    assert _safe_relative("backend/app/main.py") == Path("backend/app/main.py")
    assert _safe_relative("apps/web/app.js") == Path("apps/web/app.js")
    assert _safe_relative("run_quantnex_services.py") == Path("run_quantnex_services.py")


def test_user_data_and_secrets_are_never_updated():
    for path in (
        "backend/.env",
        "data/wallet.sqlite3",
        "data/quantnex.db",
        "backend/.venv/Lib/site-packages/example.py",
        "logs/app.log",
        "dist/QUANTNEX.exe",
        "../outside.py",
        "/absolute/path.py",
    ):
        assert _safe_relative(path) is None


def test_update_path_rejects_traversal_and_vendor_components():
    assert _safe_relative("apps/web/../backend/app/main.py") is None
    assert _safe_relative("apps/web/node_modules/pkg/index.js") is None

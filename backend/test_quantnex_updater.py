from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantnex_updater import UpdateError, _safe_destination, _safe_relative, _valid_sha


def test_sha_validation():
    assert _valid_sha("a" * 40)
    assert not _valid_sha("a" * 39)
    assert not _valid_sha("../" + "a" * 37)


def test_safe_source_paths():
    assert _safe_relative("backend/app/main.py") == Path("backend/app/main.py")
    assert _safe_relative("apps/web/app.js") == Path("apps/web/app.js")
    assert _safe_relative("run_quantnex_services.py") == Path("run_quantnex_services.py")
    assert _safe_relative("quantnex_updater.py") == Path("quantnex_updater.py")


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

def test_safe_relative_rejects_windows_path_and_ads_syntax():
    assert _safe_relative(r"apps\\web\\..\\..\\outside.py") is None
    assert _safe_relative("apps/web/file.txt:secret") is None
    assert _safe_relative("apps/web/file\x00.txt") is None


def test_safe_destination_rejects_parent_traversal(tmp_path):
    import pytest

    with pytest.raises(UpdateError, match="outside"):
        _safe_destination(tmp_path, Path("../outside.py"))


def test_safe_destination_rejects_existing_symlink_escape(tmp_path):
    import pytest

    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / "backend").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable in this test environment.")

    with pytest.raises(UpdateError, match="outside"):
        _safe_destination(root, Path("backend/app/main.py"))

def test_web_archive_path_validation_rejects_windows_traversal(monkeypatch, tmp_path):
    import importlib.util
    from pathlib import PurePosixPath

    web_path = Path(__file__).resolve().parents[1] / "apps" / "web" / "quantnex_local_server.py"
    spec = importlib.util.spec_from_file_location("quantnex_web_updater_test", web_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module._safe_web_relative(("index.html",)) == PurePosixPath("index.html")
    assert module._safe_web_relative((r"folder\\..\\..\\outside.txt",)) is None
    assert module._safe_web_relative(("file.txt:secret",)) is None

    web_root = tmp_path / "web"
    outside = tmp_path / "outside"
    web_root.mkdir()
    outside.mkdir()
    monkeypatch.setattr(module, "WEB", web_root)
    try:
        (web_root / "assets").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable in this test environment.")
    with pytest.raises(RuntimeError, match="escapes"):
        module._safe_web_destination(PurePosixPath("assets/evil.js"))

import sqlite3

from app import maintenance


def test_create_backup_performs_one_integrity_scan_and_one_hash(tmp_path, monkeypatch):
    source = tmp_path / "workspace.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('preserve me')")

    backup_dir = tmp_path / "backups"
    integrity_calls = []
    hash_calls = []
    original_hash = maintenance._sha256

    monkeypatch.setattr(maintenance, "_integrity_check", lambda path: integrity_calls.append(path))

    def counted_hash(path):
        hash_calls.append(path)
        return original_hash(path)

    monkeypatch.setattr(maintenance, "_sha256", counted_hash)
    monkeypatch.setattr(
        maintenance, "verify_backup",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("backup creation must not re-verify the same full file")),
    )

    result = maintenance.create_backup("sqlite:///" + str(source), backup_dir, prune=False)

    assert result["verified"] is True
    assert len(integrity_calls) == 1
    assert len(hash_calls) == 1
    assert (backup_dir / result["filename"]).is_file()
    assert (backup_dir / (result["filename"] + ".sha256")).is_file()


def test_latest_backup_freshness_avoids_full_backup_verification(tmp_path, monkeypatch):
    import os
    import time

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup = backup_dir / "quantnex-20261114T000000Z-a1b2c3d4.sqlite3"
    backup.write_bytes(b"verified-at-creation")
    manifest = backup.with_suffix(backup.suffix + ".sha256")
    manifest.write_text("a" * 64 + "  " + backup.name + "\n", encoding="ascii")
    now = time.time()
    os.utime(backup, (now - 3600, now - 3600))

    monkeypatch.setattr(
        maintenance, "verify_backup",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("hourly freshness checks must not re-hash backups")),
    )

    assert maintenance._latest_backup_is_fresh(backup_dir, now=now) is True
    assert maintenance._latest_backup_is_fresh(backup_dir, now=now + 90000) is False

    manifest.unlink()
    assert maintenance._latest_backup_is_fresh(backup_dir, now=now) is False

def test_backup_overview_is_lightweight_for_health_polling(tmp_path, monkeypatch):
    import sqlite3

    source = tmp_path / "workspace.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('health check')")

    backup_dir = tmp_path / "backups"
    backup = maintenance.create_backup("sqlite:///" + str(source), backup_dir, prune=False)
    monkeypatch.setattr(
        maintenance, "verify_backup",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("health polling must not run full verification")),
    )

    overview = maintenance.backup_overview(backup_dir)
    assert overview["count"] == 1
    assert overview["latest"] is not None
    assert overview["latest_verified"] is True
    assert "full verification" in overview["verification_note"]
    assert overview["count"] == 1

def test_system_health_uses_lightweight_backup_overview(monkeypatch):
    from app import system_security

    overview = {
        "count": 2, "latest": "2026-11-14T00:00:00+00:00",
        "latest_verified": True,
        "verification_note": "Manifest present; full verification is on demand.",
    }
    monkeypatch.setattr(system_security, "backup_overview", lambda: overview)
    monkeypatch.setattr(
        system_security, "list_backups",
        lambda: (_ for _ in ()).throw(AssertionError("health polling must not verify every retained backup")),
    )

    result = system_security.detailed_system_health()
    assert result["status"] == "ok"
    assert result["backups"] == overview

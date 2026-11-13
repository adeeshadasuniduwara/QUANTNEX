from pathlib import Path
import sqlite3
from contextlib import closing
import pytest
from sqlalchemy import create_engine
from app.maintenance import create_backup, restore_backup, verify_backup

def make_db(path: Path):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        conn.execute("INSERT INTO sample(value) VALUES ('before')")
        conn.commit()

def test_backup_manifest_and_integrity_verification(tmp_path):
    database = tmp_path / "quantnex.db"
    backup_dir = tmp_path / "backups"
    make_db(database)
    backup = create_backup("sqlite:///" + database.as_posix(), backup_dir)
    assert backup["verified"] is True
    assert verify_backup(backup["filename"], backup_dir)["sha256"] == backup["sha256"]

def test_tampered_backup_is_rejected(tmp_path):
    database = tmp_path / "quantnex.db"
    backup_dir = tmp_path / "backups"
    make_db(database)
    backup = create_backup("sqlite:///" + database.as_posix(), backup_dir)
    with (backup_dir / backup["filename"]).open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="SHA256"):
        verify_backup(backup["filename"], backup_dir)

def test_restore_creates_safety_backup_and_restores_verified_snapshot(tmp_path):
    database = tmp_path / "quantnex.db"
    backup_dir = tmp_path / "backups"
    make_db(database)
    engine = create_engine("sqlite:///" + database.as_posix())
    backup = create_backup("sqlite:///" + database.as_posix(), backup_dir)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("UPDATE sample SET value='after'")
        conn.commit()
    result = restore_backup(backup["filename"], "sqlite:///" + database.as_posix(), engine, backup_dir)
    with closing(sqlite3.connect(database)) as conn:
        value = conn.execute("SELECT value FROM sample").fetchone()[0]
    assert result["restored"] == backup["filename"]
    assert result["pre_restore_backup"]
    assert value == "before"
    engine.dispose()

def test_restore_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="Invalid backup filename"):
        verify_backup("../quantnex.db", tmp_path / "backups")


def test_live_system_metrics_returns_actual_host_samples():
    from app.system_security import live_system_metrics
    result = live_system_metrics()
    assert 0 <= result["cpu_percent"] <= 100
    assert 0 <= result["memory_percent"] <= 100
    assert result["memory_total_bytes"] > 0
    assert result["memory_used_bytes"] >= 0
    assert result["disk_total_bytes"] > 0
    assert result["disk_free_bytes"] >= 0
    assert result["timestamp"].endswith("+00:00")


def test_backup_and_restore_operations_are_serialized(monkeypatch):
    from threading import Event, Thread
    from app import maintenance

    backup_started = Event()
    allow_backup_to_finish = Event()
    restore_calling = Event()
    restore_started = Event()

    def fake_backup(*args, **kwargs):
        backup_started.set()
        assert allow_backup_to_finish.wait(3)
        return {"filename": "test.sqlite3"}

    def fake_restore(*args, **kwargs):
        restore_started.set()
        return {"restored": "test.sqlite3"}

    monkeypatch.setattr(maintenance, "_create_backup_unlocked", fake_backup)
    monkeypatch.setattr(maintenance, "_restore_backup_unlocked", fake_restore)

    first = Thread(target=lambda: maintenance.create_backup("sqlite:///unused.db"))
    def run_restore():
        restore_calling.set()
        maintenance.restore_backup("test.sqlite3", "sqlite:///unused.db", None)
    second = Thread(target=run_restore)

    first.start()
    assert backup_started.wait(2)
    second.start()
    assert restore_calling.wait(2)
    assert not restore_started.wait(0.1)
    allow_backup_to_finish.set()
    first.join(3)
    second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert restore_started.is_set()


def test_daily_backup_runs_off_event_loop_thread(monkeypatch):
    import asyncio
    import threading
    from app import maintenance

    loop_thread = threading.get_ident()
    backup_threads = []

    class FakeSession:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def commit(self):
            pass

    def fake_backup(_database_url):
        backup_threads.append(threading.get_ident())
        return {"filename": "test.sqlite3", "size_bytes": 10}

    async def cancel_after_one_cycle(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(maintenance, "_latest_backup_is_fresh", lambda: False)
    monkeypatch.setattr(maintenance, "create_backup", fake_backup)
    monkeypatch.setattr(maintenance, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(maintenance, "record_audit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(maintenance.asyncio, "sleep", cancel_after_one_cycle)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(maintenance.daily_backup_worker())

    assert backup_threads
    assert backup_threads[0] != loop_thread

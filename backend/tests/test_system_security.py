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

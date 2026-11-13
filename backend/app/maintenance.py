"""Local-only database backup, integrity verification and audit helpers."""
from __future__ import annotations
import asyncio, hashlib, hmac, json, logging, os, re, sqlite3, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing
from sqlalchemy.orm import Session
from .models import AuditEvent
from .config import DATABASE_URL
from .database import SessionLocal

BACKUP_RETENTION = 14
BACKUP_DIR = Path(__file__).resolve().parents[2] / "data" / "backups"
_BACKUP_NAME = re.compile(r"^quantnex-(?:pre-restore-)?[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.sqlite3$")

def sqlite_database_path(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Automated file backups currently support SQLite databases only.")
    raw = database_url[len("sqlite:///"):].split("?", 1)[0]
    if not raw or raw == ":memory:":
        raise ValueError("A persistent SQLite database file is required for backup and restore.")
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()

def _safe_backup_path(filename: str, backup_dir: Path) -> Path:
    if not _BACKUP_NAME.fullmatch(filename):
        raise ValueError("Invalid backup filename.")
    root = backup_dir.resolve()
    path = (root / filename).resolve()
    if path.parent != root:
        raise ValueError("Backup path is outside the backup directory.")
    return path

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _integrity_check(path: Path) -> None:
    with closing(sqlite3.connect(str(path), timeout=15)) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise ValueError("SQLite integrity_check failed for this backup.")

def verify_backup(filename: str, backup_dir: Path = BACKUP_DIR) -> dict:
    path = _safe_backup_path(filename, backup_dir)
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not path.is_file() or not sidecar.is_file():
        raise ValueError("Backup or SHA256 manifest is missing.")
    expected = sidecar.read_text(encoding="ascii").strip().split()[0].lower()
    actual = _sha256(path)
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or not hmac.compare_digest(expected, actual):
        raise ValueError("Backup SHA256 verification failed.")
    _integrity_check(path)
    return {"filename": filename, "sha256": actual, "size_bytes": path.stat().st_size, "verified": True}

def _write_manifest(path: Path, digest: str) -> None:
    manifest = path.with_suffix(path.suffix + ".sha256")
    temp = manifest.with_suffix(manifest.suffix + ".tmp")
    temp.write_text(digest + "  " + path.name + "\n", encoding="ascii")
    os.replace(temp, manifest)

def _prune_backups(backup_dir: Path, keep: int = BACKUP_RETENTION, protect: set[str] | None = None) -> int:
    files = sorted(backup_dir.glob("quantnex-*.sqlite3"), key=lambda item: item.stat().st_mtime, reverse=True)
    protected = set(protect or ())
    recent = [item.name for item in files if item.name not in protected][:max(0, keep - len(protected))]
    retained = protected | set(recent)
    removed = 0
    for old in files:
        if old.name not in retained:
            old.unlink(missing_ok=True)
            old.with_suffix(old.suffix + ".sha256").unlink(missing_ok=True)
            removed += 1
    return removed
def _latest_backup_is_fresh(backup_dir: Path = BACKUP_DIR, now: float | None = None) -> bool:
    """Cheap freshness check; full verification remains mandatory before restore.

    The manifest is written only after a successful integrity and hash pass.
    Avoid repeatedly hashing every retained database during hourly polling.
    """
    if not backup_dir.exists():
        return False
    files = sorted(backup_dir.glob("quantnex-*.sqlite3"),
                   key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        return False
    latest = files[0]
    manifest = latest.with_suffix(latest.suffix + ".sha256")
    try:
        if not latest.is_file() or latest.stat().st_size <= 0 or not manifest.is_file():
            return False
        digest = manifest.read_text(encoding="ascii").strip().split()[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            return False
        age = (time.time() if now is None else now) - latest.stat().st_mtime
        return 0 <= age < 86400
    except (OSError, ValueError, IndexError):
        return False


def create_backup(database_url: str, backup_dir: Path = BACKUP_DIR, prune: bool = True) -> dict:
    source_path = sqlite_database_path(database_url)
    if not source_path.is_file():
        raise FileNotFoundError("The configured SQLite database file does not exist yet.")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"quantnex-{stamp}-{os.urandom(4).hex()}.sqlite3"
    destination = _safe_backup_path(filename, backup_dir)
    try:
        with closing(sqlite3.connect(str(source_path), timeout=20)) as source:
            source.execute("PRAGMA busy_timeout=20000")
            with closing(sqlite3.connect(str(destination), timeout=20)) as target:
                source.backup(target, pages=256, sleep=0.05)
        # Verify once, then persist the digest; verify_backup() would repeat
        # both full-file operations unnecessarily.
        _integrity_check(destination)
        digest = _sha256(destination)
        _write_manifest(destination, digest)
        if prune:
            _prune_backups(backup_dir)
        return {"filename": filename, "sha256": digest,
                "size_bytes": destination.stat().st_size, "verified": True}
    except Exception:
        destination.unlink(missing_ok=True)
        destination.with_suffix(destination.suffix + ".sha256").unlink(missing_ok=True)
        raise

def list_backups(backup_dir: Path = BACKUP_DIR) -> list[dict]:
    if not backup_dir.exists():
        return []
    result = []
    for path in sorted(backup_dir.glob("quantnex-*.sqlite3"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            item = verify_backup(path.name, backup_dir)
            item["created_at"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        except (OSError, ValueError, IndexError):
            item = {"filename": path.name, "size_bytes": path.stat().st_size, "verified": False}
        result.append(item)
    return result

def restore_backup(filename: str, database_url: str, engine, backup_dir: Path = BACKUP_DIR) -> dict:
    verified = verify_backup(filename, backup_dir)
    database_path = sqlite_database_path(database_url)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    safety = create_backup(database_url, backup_dir, prune=False)["filename"] if database_path.is_file() else None
    engine.dispose()
    if database_path.is_file():
        with closing(sqlite3.connect(str(database_path), timeout=20)) as current:
            current.execute("PRAGMA busy_timeout=20000")
            current.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            current.execute("PRAGMA journal_mode=DELETE")
        Path(str(database_path) + "-wal").unlink(missing_ok=True)
        Path(str(database_path) + "-shm").unlink(missing_ok=True)
    source_path = _safe_backup_path(filename, backup_dir)
    fd, temporary_name = tempfile.mkstemp(prefix="quantnex-restore-", suffix=".sqlite3", dir=str(database_path.parent))
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        with closing(sqlite3.connect(str(source_path), timeout=20)) as source:
            with closing(sqlite3.connect(str(temporary_path), timeout=20)) as target:
                source.backup(target, pages=256, sleep=0.05)
        _integrity_check(temporary_path)
        os.replace(temporary_path, database_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    _prune_backups(backup_dir, protect={filename})
    return {"restored": filename, "verified": verified["verified"], "pre_restore_backup": safety}

def record_audit_event(db: Session, event_type: str, details: dict | None = None, severity: str = "info") -> None:
    payload = json.dumps(details or {}, ensure_ascii=True, separators=(",", ":"))[:2000]
    db.add(AuditEvent(event_type=event_type[:80], severity=severity[:16], details=payload))


async def daily_backup_worker() -> None:
    """Create one verified backup per 24 hours while the local API is running."""
    logger = logging.getLogger("quantnex.maintenance")
    while True:
        try:
            if DATABASE_URL.startswith("sqlite:///"):
                # Full verification happens on creation and before restore.
                # Do not re-hash every retained database during hourly polling.
                if not _latest_backup_is_fresh():
                    result = create_backup(DATABASE_URL)
                    with SessionLocal() as db:
                        record_audit_event(db, "backup.daily_created",
                                            {"filename": result["filename"], "size_bytes": result["size_bytes"]})
                        db.commit()
        except Exception as exc:
            # Keep the worker alive; do not log database contents or credentials.
            logger.warning("Daily local backup check failed: %s", type(exc).__name__)
        await asyncio.sleep(3600)

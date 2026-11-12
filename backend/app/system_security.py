"""Loopback-only system maintenance endpoints for QUANTNEX."""
from pathlib import Path
from datetime import datetime, timezone
import asyncio
import shutil
import psutil
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select, text
from .config import DATABASE_URL
from .database import Base, SessionLocal, engine, enable_sqlite_wal
from .maintenance import create_backup, daily_backup_worker, list_backups, record_audit_event, restore_backup, verify_backup
from .models import AuditEvent

router = APIRouter(prefix="/api/v1/system", tags=["local-system"])

@router.get("/health")
def detailed_system_health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        disk = shutil.disk_usage(Path.cwd())
        db_size = None
        if DATABASE_URL.startswith("sqlite:///"):
            from .maintenance import sqlite_database_path
            path = sqlite_database_path(DATABASE_URL)
            db_size = path.stat().st_size if path.exists() else 0
        backups = list_backups()
        return {
            "status": "ok",
            "database": {"engine": "sqlite" if DATABASE_URL.startswith("sqlite") else "postgresql",
                         "connected": True, "size_bytes": db_size},
            "system": {"cpu_percent": psutil.cpu_percent(interval=0),
                       "memory_percent": psutil.virtual_memory().percent,
                       "disk_free_bytes": disk.free, "disk_total_bytes": disk.total},
            "backups": {"count": len(backups),
                        "latest": backups[0].get("created_at") if backups else None,
                        "latest_verified": backups[0].get("verified") if backups else None},
        }
    except Exception:
        raise HTTPException(status_code=503, detail="System health checks are temporarily unavailable.")

@router.get("/backups")
def get_backups():
    try:
        return {"items": list_backups(), "retention": 14}
    except Exception:
        raise HTTPException(status_code=503, detail="Could not list local backups.")

@router.post("/backups", status_code=201)
def make_backup():
    try:
        result = create_backup(DATABASE_URL)
        with SessionLocal() as db:
            record_audit_event(db, "backup.created", {"filename": result["filename"], "size_bytes": result["size_bytes"]})
            db.commit()
        return result
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="Backup creation failed. The current database was not intentionally modified.")

@router.post("/backups/{filename}/verify")
def check_backup(filename: str):
    try:
        result = verify_backup(filename)
        with SessionLocal() as db:
            record_audit_event(db, "backup.verified", {"filename": filename})
            db.commit()
        return result
    except (ValueError, OSError, IndexError) as exc:
        with SessionLocal() as db:
            record_audit_event(db, "backup.verify_failed", {"filename": filename}, "warning")
            db.commit()
        raise HTTPException(status_code=422, detail=str(exc))

@router.post("/backups/{filename}/restore")
async def restore_database(filename: str, request: Request):
    # Pause DB-using background workers so Windows can safely replace the SQLite file.
    paused_telegram = getattr(request.app.state, "telegram_worker_task", None) is not None
    paused_daily = getattr(request.app.state, "daily_backup_task", None) is not None
    paused_paper = getattr(request.app.state, "paper_monitor_task", None) is not None
    for attribute in ("telegram_worker_task", "daily_backup_task", "paper_monitor_task"):
        task = getattr(request.app.state, attribute, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            setattr(request.app.state, attribute, None)
    try:
        result = await asyncio.to_thread(restore_backup, filename, DATABASE_URL, engine)
        # Restore switches SQLite back to DELETE mode while replacing the file.
        # Re-enable WAL, then recreate additive Phase 07/08 tables if this is an
        # older valid backup before any route or background worker queries them.
        await asyncio.to_thread(enable_sqlite_wal)
        await asyncio.to_thread(Base.metadata.create_all, bind=engine)
        with SessionLocal() as db:
            record_audit_event(db, "backup.restored", {"filename": filename,
                                                       "pre_restore_backup": result["pre_restore_backup"]},
                               "warning")
            db.commit()
        return {"ok": True, **result}
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="Restore failed. Check the local database and restart QUANTNEX if needed.")
    finally:
        if paused_telegram:
            from .telegram_worker import telegram_worker
            request.app.state.telegram_worker_task = asyncio.create_task(telegram_worker())
        if paused_daily:
            request.app.state.daily_backup_task = asyncio.create_task(daily_backup_worker())
        if paused_paper:
            from .paper_worker import paper_trade_monitor
            request.app.state.paper_monitor_task = asyncio.create_task(paper_trade_monitor())

@router.get("/audit")
def get_audit_log(limit: int = Query(default=100, ge=1, le=500)):
    with SessionLocal() as db:
        rows = list(db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)))
        return {"items": [{"id": row.id, "created_at": row.created_at.isoformat(),
                           "event_type": row.event_type, "severity": row.severity,
                           "details": row.details} for row in rows]}


@router.get("/metrics")
def live_system_metrics():
    """One-second local telemetry sample for the QUANTNEX dashboard."""
    try:
        disk=shutil.disk_usage(Path.cwd())
        memory=psutil.virtual_memory()
        return {"timestamp":datetime.now(timezone.utc).isoformat(),
                "cpu_percent":psutil.cpu_percent(interval=0),
                "memory_percent":memory.percent,"memory_used_bytes":memory.used,
                "memory_total_bytes":memory.total,"disk_free_bytes":disk.free,
                "disk_total_bytes":disk.total}
    except Exception:
        raise HTTPException(status_code=503,detail="Local system metrics are temporarily unavailable.")

from types import SimpleNamespace
import asyncio

from app.main import app
from app import system_security


def test_background_worker_lifecycle_is_registered():
    import inspect
    from app.main import lifespan

    lifecycle = inspect.getsource(lifespan)
    assert "await prepare_local_workspace()" in lifecycle
    assert "await start_telegram_background_worker()" in lifecycle
    assert "await start_daily_backup_worker()" in lifecycle
    assert "await start_paper_autopilot_worker()" in lifecycle
    assert "await start_prop_challenge_guardian()" in lifecycle
    assert "await stop_daily_backup_worker()" in lifecycle
    assert "await stop_paper_autopilot_worker()" in lifecycle
    # The old unscoped monitor closed manually opened paper positions and
    # raced the opt-in autopilot worker. Manual positions stay user-controlled.
    assert "start_phase07_paper_monitor" not in lifecycle


class _FakeTask:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def __await__(self):
        async def done():
            return None
        return done().__await__()


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def commit(self):
        pass


def test_database_restore_pauses_and_restarts_database_workers(monkeypatch):
    tasks = {
        "telegram_worker_task": _FakeTask(),
        "daily_backup_task": _FakeTask(),
        "paper_autopilot_task": _FakeTask(),
        "prop_challenge_guardian_task": _FakeTask(),
    }
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**tasks)))
    scheduled = []

    async def fake_to_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    def fake_create_task(coroutine):
        coroutine.close()
        task = _FakeTask()
        scheduled.append(task)
        return task

    monkeypatch.setattr(system_security.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(system_security.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(system_security, "restore_backup", lambda *_args: {
        "restored": "backup.sqlite3", "verified": True, "pre_restore_backup": "safety.sqlite3"
    })
    monkeypatch.setattr(system_security, "enable_sqlite_wal", lambda: None)
    monkeypatch.setattr(system_security.Base.metadata, "create_all", lambda **_kwargs: None)
    monkeypatch.setattr(system_security, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(system_security, "record_audit_event", lambda *_args, **_kwargs: None)
    guardian_waited = []
    from app import prop_challenge
    monkeypatch.setattr(prop_challenge, "wait_for_mt5_guardian_idle", lambda: guardian_waited.append(True))

    result = asyncio.run(system_security.restore_database("backup.sqlite3", request))

    assert result["ok"] is True
    assert all(task.cancelled for task in tasks.values())
    assert len(scheduled) == 4
    assert guardian_waited == [True]
    assert request.app.state.paper_autopilot_task is scheduled[2]
    assert request.app.state.prop_challenge_guardian_task is scheduled[3]

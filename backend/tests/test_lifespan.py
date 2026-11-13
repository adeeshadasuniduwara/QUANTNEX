import asyncio

from app import main


def test_fastapi_lifespan_starts_and_stops_all_background_workers(monkeypatch):
    calls = []

    async def prepare():
        calls.append("prepare")

    async def start_telegram():
        calls.append("telegram-start")

    async def start_guardian():
        calls.append("guardian-start")

    async def start_backup():
        calls.append("backup-start")

    async def start_paper():
        calls.append("paper-start")

    async def stop_paper():
        calls.append("paper-stop")

    async def stop_backup():
        calls.append("backup-stop")

    async def stop_guardian():
        calls.append("guardian-stop")

    async def stop_telegram():
        calls.append("telegram-stop")

    monkeypatch.setattr(main, "prepare_local_workspace", prepare)
    monkeypatch.setattr(main, "start_telegram_background_worker", start_telegram)
    monkeypatch.setattr(main, "start_prop_challenge_guardian", start_guardian)
    monkeypatch.setattr(main, "start_daily_backup_worker", start_backup)
    monkeypatch.setattr(main, "start_paper_autopilot_worker", start_paper)
    monkeypatch.setattr(main, "stop_paper_autopilot_worker", stop_paper)
    monkeypatch.setattr(main, "stop_daily_backup_worker", stop_backup)
    monkeypatch.setattr(main, "stop_prop_challenge_guardian", stop_guardian)
    monkeypatch.setattr(main, "stop_telegram_background_worker", stop_telegram)

    async def exercise():
        async with main.lifespan(main.app):
            calls.append("running")

    asyncio.run(exercise())

    assert calls == [
        "prepare",
        "telegram-start",
        "guardian-start",
        "backup-start",
        "paper-start",
        "running",
        "paper-stop",
        "backup-stop",
        "guardian-stop",
        "telegram-stop",
    ]


def test_fastapi_app_does_not_register_deprecated_on_event_handlers():
    import inspect

    source = inspect.getsource(main)
    assert "@app.on_event" not in source
    assert "lifespan=lifespan" in source

# QUANTNEX Windows Desktop — Phase 03

Lightweight native Windows desktop MVP using Tkinter and SQLite.

## Included
- Plain, low-distraction Overview screen.
- Position size calculator.
- Local trade journal stored under `%LOCALAPPDATA%\QUANTNEX\journal.sqlite3`.
- Update check against public GitHub Releases; opens the release page when a newer version exists.

## Build locally (Windows, Python 3.11+)
```powershell
py -m pip install pyinstaller
py -m PyInstaller --noconfirm --clean --onefile --windowed --name QUANTNEX quantnex_desktop.py
```
Output: `dist\QUANTNEX.exe`.

## Limits
This is a local desktop MVP, not a live trading terminal. It does not connect to brokers, stream live prices, run bots or place orders. The calculator requires correct broker-specific pip values. The updater currently checks published releases and opens the official release page; it does not silently replace a running executable. A signed staged installer with backup and rollback is a separate security-sensitive milestone.

Never commit API keys, passwords, signing keys or broker tokens.

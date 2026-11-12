# QUANTNEX Windows Desktop

Lightweight native Windows desktop application built with Python and Tkinter.

## Included

- Monochrome workspace UI.
- Position size calculator with broker-specific pip value input.
- Local SQLite trade journal with delete support.
- Bot monitor status panel (connection is not enabled yet).
- Automatic GitHub Releases check when the packaged app starts.
- Downloads the latest EXE and verifies its SHA256 checksum.
- User-confirmed update installation with a previous executable backup.

## Run from Command Prompt

From the repository root, run:

```bat
run_quantnex.bat
```

Choose **Start Windows Desktop**. Python 3.11+ is required for source mode.

## Build locally

```powershell
py -m pip install pyinstaller
py -m PyInstaller --noconfirm --clean --onefile --windowed --name QUANTNEX apps/windows/quantnex_desktop.py
```

Output: `dist\QUANTNEX.exe`.

## Releases and updates

Push a version tag such as `v0.4.0` to build the Windows EXE and publish it with a SHA256 checksum on GitHub Releases. The app checks the latest published release, downloads the EXE, verifies the checksum and asks the user before installing and restarting.

The updater is designed for packaged EXE mode. It has not yet been security-audited as a signed enterprise updater; keep a backup of important data and review release notes before installing.

## Limits

The app does not connect to brokers, stream live prices, run bots or place orders. The calculator requires correct broker-specific pip values. The journal is stored locally under `%LOCALAPPDATA%\QUANTNEX\journal.sqlite3`. Never commit API keys, passwords, signing keys or broker tokens.

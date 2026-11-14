from __future__ import annotations
import base64, hashlib, json, math, os, shutil, sqlite3, subprocess, sys, threading, urllib.error, urllib.parse, urllib.request, webbrowser
from datetime import datetime
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

APP_VERSION = "0.6.0"
REPO = "adeeshadasuniduwara/QUANTNEX"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

def app_data():
    path = Path.home() / "AppData" / "Local" / "QUANTNEX"
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_device_id():
    """Create a stable random installation ID; never read hardware serials."""
    identity_file = app_data() / "device_id.txt"
    try:
        value = identity_file.read_text(encoding="utf-8").strip()
        return str(uuid.UUID(value))
    except (OSError, ValueError, AttributeError):
        value = str(uuid.uuid4())
        identity_file.write_text(value, encoding="utf-8")
        return value

def calculate_position_size(equity, risk_percent, stop_pips, pip_value):
    if equity <= 0 or not 0 < risk_percent <= 100 or stop_pips <= 0 or pip_value <= 0:
        raise ValueError("Use positive values; risk must be above 0 and at most 100%.")
    risk_amount = equity * risk_percent / 100
    return risk_amount, risk_amount / (stop_pips * pip_value)

def validate_wallet_amount(value):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise ValueError("Enter a valid wallet amount.") from None
    if not math.isfinite(amount) or not 0 < amount <= 1000000000:
        raise ValueError("Wallet amount must be finite, greater than zero and no more than $1,000,000,000.")
    return amount


def fetch_chart_data(symbol, urlopen=None):
    """Fetch real BTC Binance candles or read-only Gold candles from the local MT5 API."""
    normalized = str(symbol or "").strip().upper()
    opener = urlopen or urllib.request.urlopen
    if normalized == "BTCUSDT":
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=60"
        provider = "Binance Spot"
    elif normalized == "XAUUSD":
        url = "http://127.0.0.1:8000/api/v1/market/mt5/candles?interval=15m&limit=250"
        provider = "MetaTrader 5 local terminal"
    else:
        raise ValueError("Windows charts support BTCUSDT and XAUUSD.")

    request = urllib.request.Request(url, headers={"User-Agent": "QUANTNEX-Desktop"})
    try:
        with opener(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw).get("detail") or raw[:240]
        except (ValueError, AttributeError):
            detail = raw[:240] or str(exc.reason)
        raise RuntimeError(str(detail)) from None

    if normalized == "BTCUSDT":
        if not isinstance(payload, list):
            raise RuntimeError("Binance returned an unexpected candle response.")
        rows = payload
    else:
        if not isinstance(payload, dict):
            raise RuntimeError("The local MT5 API returned an unexpected candle response.")
        if payload.get("orders_enabled") is not False or payload.get("mode") != "read_only_market_data":
            raise RuntimeError("The Gold chart source did not confirm read-only market-data mode.")
        rows = payload.get("candles")
        if not isinstance(rows, list):
            raise RuntimeError("The local MT5 API did not return a candle list.")

    candles = []
    for row in rows:
        try:
            if normalized == "BTCUSDT":
                values = [float(row[index]) for index in (1, 2, 3, 4)]
            else:
                values = [float(row[key]) for key in ("open", "high", "low", "close")]
            if not all(math.isfinite(value) and value > 0 for value in values):
                continue
            open_price, high, low, close = values
            if high < max(open_price, close, low) or low > min(open_price, close, high):
                continue
            candles.append({"open": open_price, "high": high, "low": low, "close": close})
        except (KeyError, IndexError, TypeError, ValueError, OverflowError):
            continue
    if not candles:
        raise RuntimeError("The selected provider returned no valid candles.")
    return candles[-60:], candles[-1]["close"], provider


def is_trusted_release_asset_url(value):
    try:
        parsed = urllib.parse.urlparse(str(value))
        return (
            parsed.scheme.lower() == "https"
            and parsed.hostname.lower() == "github.com"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and "/releases/download/" in parsed.path
        )
    except (TypeError, ValueError, AttributeError):
        return False


def expected_release_checksum(checksum_text, file_name):
    for line in str(checksum_text).splitlines():
        fields = line.strip().split()
        if len(fields) < 2 or fields[1].lstrip("*") != file_name:
            continue
        digest = fields[0].lower()
        if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
            return digest
    return None


def verify_release_file(path, checksum_text, file_name):
    expected = expected_release_checksum(checksum_text, file_name)
    if not expected:
        return False
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == expected


def stage_verified_release_exe(asset_url, checksum_url, destination, urlopen=None,
                               max_bytes=200 * 1024 * 1024, min_bytes=100000):
    """Download to a temporary file and atomically stage only an exact SHA256 match."""
    if not is_trusted_release_asset_url(asset_url) or not is_trusted_release_asset_url(checksum_url):
        raise ValueError("Release EXE and checksum must use official HTTPS GitHub release asset URLs.")
    opener = urlopen or urllib.request.urlopen
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.unlink(missing_ok=True)
    try:
        request = urllib.request.Request(asset_url, headers={"User-Agent": "QUANTNEX-Desktop"})
        total = 0
        with opener(request, timeout=45) as response, partial.open("wb") as output:
            headers = getattr(response, "headers", {}) or {}
            advertised = headers.get("Content-Length")
            if advertised:
                try:
                    advertised_size = int(advertised)
                except (TypeError, ValueError):
                    raise ValueError("Release EXE has an invalid Content-Length header.") from None
                if advertised_size > max_bytes:
                    raise ValueError("Release EXE exceeds the 200 MB safety limit.")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Release EXE exceeds the 200 MB safety limit.")
                output.write(chunk)
        if total < min_bytes:
            raise ValueError("Downloaded EXE failed the minimum file-size check.")

        checksum_request = urllib.request.Request(checksum_url, headers={"User-Agent": "QUANTNEX-Desktop"})
        with opener(checksum_request, timeout=15) as response:
            manifest = response.read(16385)
        if len(manifest) > 16384:
            raise ValueError("Release checksum manifest exceeds the 16 KB safety limit.")
        checksum_text = manifest.decode("utf-8")
        if not verify_release_file(partial, checksum_text, "QUANTNEX.exe"):
            raise ValueError("Update SHA256 verification failed. The downloaded file was rejected.")
        partial.replace(destination)
        return destination
    except Exception:
        partial.unlink(missing_ok=True)
        raise


class TradeJournal:
    def __init__(self):
        self.path = app_data() / "journal.sqlite3"
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS trades(
                id INTEGER PRIMARY KEY, created TEXT NOT NULL, symbol TEXT NOT NULL,
                side TEXT NOT NULL, outcome TEXT NOT NULL, pnl REAL NOT NULL, notes TEXT NOT NULL,
                sync_status TEXT NOT NULL DEFAULT 'PENDING')""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(trades)")}
            if "sync_status" not in columns:
                # Old rows have unknown sync history; do not replay them into wallet P&L.
                db.execute("ALTER TABLE trades ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'UNKNOWN'")

    def add(self, symbol, side, outcome, pnl, notes):
        with sqlite3.connect(self.path) as db:
            cursor = db.execute(
                "INSERT INTO trades(created,symbol,side,outcome,pnl,notes,sync_status) VALUES(?,?,?,?,?,?, 'PENDING')",
                (datetime.now().astimezone().isoformat(timespec="seconds"), symbol.upper(), side, outcome, pnl, notes))
            return cursor.lastrowid

    def mark_synced(self, local_id):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE trades SET sync_status='SYNCED' WHERE id=?", (int(local_id),))

    def pending(self):
        with sqlite3.connect(self.path) as db:
            return db.execute(
                "SELECT id,symbol,side,outcome,pnl,notes FROM trades WHERE sync_status='PENDING' ORDER BY id ASC"
            ).fetchall()

    def unknown_sync_count(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT COUNT(*) FROM trades WHERE sync_status='UNKNOWN'").fetchone()[0]

    def recent(self):
        with sqlite3.connect(self.path) as db:
            return db.execute(
                "SELECT created,symbol,side,outcome,pnl,sync_status FROM trades ORDER BY id DESC LIMIT 100"
            ).fetchall()

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QUANTNEX — Trading Workspace")
        self.geometry("1000x680"); self.minsize(850, 560); self.configure(bg="#080808")
        self._app_icon = tk.PhotoImage(data=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAABUUlEQVR42u2bvQ4DIQyDb+f9H5W53aobigiQOD/YElsP8He0AuI+D0VRFEVR1KZaax/PdqXpd+u9/1po4++JjppWnyHMSwyfAJk96wZAw/gMhOQZuHkL4yMQ0s/DACDMvyGEAaD1fV79oYQCQP6qS/pfBW8CwNL4bKzVF6AOAGn+35jSuajtFFeWJmLXJ5mP6lY5inm3s0Jm8wSgBSCreVMAGcyrAMj89s0AZDF/BQDzfQABJFj+plthxEHnegAWR+d0AE76LgNgt/+0ALQgpAagASE9gFMIJQCcQIACiAah5FZ4ZcyyZwHpuC4AokCQzC39jdBqkbTkneBJDbLMrfBuLbLUtbgrgOgQzAsjUWqDcADSVYA+LEGWf4QS+UkCxTQi45UQGaVFzFOkUTJC0v6gOUF0SswtQxwlJ+geoPZOiqZIjqOM8w8LFEVRFEXt6gvb1Kw0LPnuxQAAAABJRU5ErkJggg=="))
        self.iconphoto(True, self._app_icon)
        self.journal = TradeJournal()
        self._journal_sync_running = False
        self.update_check_running = False
        self.update_timer_id = None
        self.staged_update = None
        self.style = ttk.Style(self)
        try: self.style.theme_use("clam")
        except tk.TclError: pass
        self.style.configure("TFrame", background="#101010")
        self.style.configure("TLabel", background="#101010", foreground="#f2f2f2", font=("Segoe UI", 10))
        self.style.configure("Title.TLabel", background="#080808", foreground="#ffffff", font=("Segoe UI", 24, "bold"))
        self.style.configure("Muted.TLabel", background="#101010", foreground="#929292")
        self.style.configure("TButton", background="#202020", foreground="#f5f5f5", bordercolor="#3a3a3a", font=("Segoe UI", 10, "bold"), padding=9)
        self.style.map("TButton", background=[("active", "#353535"), ("disabled", "#151515")], foreground=[("disabled", "#666666")])
        self.style.configure("Accent.TButton", background="#f2f2f2", foreground="#080808", padding=10)
        self.style.map("Accent.TButton", background=[("active", "#ffffff")], foreground=[("active", "#080808")])
        self.style.configure("TNotebook", background="#080808", borderwidth=0)
        self.style.configure("TNotebook.Tab", background="#171717", foreground="#999999", padding=(16, 10), borderwidth=0)
        self.style.map("TNotebook.Tab", background=[("selected", "#eeeeee")], foreground=[("selected", "#080808")])
        self.style.configure("TEntry", fieldbackground="#090909", foreground="#ffffff", insertcolor="#ffffff", bordercolor="#3a3a3a", padding=8)
        self.style.configure("TCombobox", fieldbackground="#090909", background="#202020", foreground="#ffffff", arrowcolor="#ffffff", padding=7)
        self.style.configure("Treeview", background="#111111", fieldbackground="#111111", foreground="#eeeeee", rowheight=31, font=("Segoe UI", 9), borderwidth=0)
        self.style.configure("Treeview.Heading", background="#222222", foreground="#dddddd", font=("Segoe UI", 9, "bold"), relief="flat")
        self.style.map("Treeview", background=[("selected", "#444444")], foreground=[("selected", "#ffffff")])
        self.style.configure("Horizontal.TProgressbar", troughcolor="#292929", background="#f0f0f0", bordercolor="#292929", lightcolor="#f0f0f0", darkcolor="#f0f0f0")
        self.style.configure("Accent.TButton", background="#111111", foreground="white")
        self.style.configure("Treeview", rowheight=28, font=("Segoe UI", 9))
        self._build()
        self._fade_in()
        self.after(1600, self._check_background)
        self.after(1200, self._refresh_chart)

    def _fade_in(self, step=0):
        try:
            self.attributes("-alpha", min(1.0, step / 10))
            if step < 10:
                self.after(28, lambda: self._fade_in(step + 1))
        except tk.TclError:
            pass

    def _build(self):
        root = ttk.Frame(self, padding=22); root.pack(fill="both", expand=True)
        brand = ttk.Frame(root); brand.pack(anchor="w", fill="x")
        ttk.Label(brand, image=self._app_icon).pack(side="left", padx=(0,10))
        ttk.Label(brand, text="Q U A N T N E X", foreground="#ffffff", font=("Segoe UI", 12, "bold")).pack(side="left")
        ttk.Label(root, text="Trading Workspace", style="Title.TLabel").pack(anchor="w", pady=(4, 2))
        ttk.Label(root, text=f"WINDOWS DESKTOP  /  VERSION {APP_VERSION}  /  LOCAL MODE", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))
        tabs = ttk.Notebook(root); tabs.pack(fill="both", expand=True)
        self.home = ttk.Frame(tabs, padding=18); self.calc = ttk.Frame(tabs, padding=18)
        self.journal_tab = ttk.Frame(tabs, padding=18); self.account_tab = ttk.Frame(tabs, padding=18)
        self.updates = ttk.Frame(tabs, padding=18); self.charts = ttk.Frame(tabs, padding=18)
        self.device_tab = ttk.Frame(tabs, padding=18)
        tabs.add(self.home, text="Overview"); tabs.add(self.charts, text="Charts")
        tabs.add(self.calc, text="Position Calculator")
        tabs.add(self.journal_tab, text="Trade Journal"); tabs.add(self.account_tab, text="Local Wallet")
        tabs.add(self.device_tab, text="Device"); tabs.add(self.updates, text="Updates")
        self._home(); self._charts(); self._calculator(); self._journal(); self._account(); self._device(); self._updates()
        ttk.Label(root, text="Local demo workspace • No broker connection • No orders placed", style="Muted.TLabel").pack(anchor="w", pady=(12,0))

    def _home(self):
        ttk.Label(self.home, text="Welcome to QUANTNEX", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(self.home, text="A clean workspace to plan risk and review completed trades.", style="Muted.TLabel").pack(anchor="w", pady=(5,18))
        for heading, body in [
            ("Risk management", "Estimate position size using your account equity and broker-specific pip value."),
            ("Trade journal", "Your trade records are saved locally on this computer."),
            ("Software updates", "Check the official GitHub Releases page for published versions.")
        ]:
            card = ttk.Frame(self.home, padding=16, relief="solid"); card.pack(fill="x", pady=6)
            ttk.Label(card, text=heading, font=("Segoe UI", 12, "bold")).pack(anchor="w")
            ttk.Label(card, text=body, style="Muted.TLabel").pack(anchor="w", pady=(5,0))

    def _calculator(self):
        ttk.Label(self.calc, text="Position Size Calculator", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(self.calc, text="Enter the pip value for the symbol from your broker's contract specifications.", style="Muted.TLabel").pack(anchor="w", pady=(5,15))
        self.inputs = {}
        form = ttk.Frame(self.calc); form.pack(anchor="w")
        for i,(name,default) in enumerate([("Account equity ($)","1000"),("Risk (%)","1"),("Stop distance (pips)","30"),("Pip value per 1.00 lot ($)","10")]):
            ttk.Label(form,text=name).grid(row=i,column=0,sticky="w",padx=(0,20),pady=8)
            self.inputs[name]=tk.StringVar(value=default)
            ttk.Entry(form,textvariable=self.inputs[name],width=22).grid(row=i,column=1,sticky="w",pady=8)
        ttk.Button(self.calc,text="Calculate",style="Accent.TButton",command=self._calculate).pack(anchor="w",pady=14)
        self.calc_result=ttk.Label(self.calc,text="Enter values and calculate.",font=("Segoe UI",12,"bold")); self.calc_result.pack(anchor="w")
        ttk.Label(self.calc,text="Formula: risk amount ÷ (stop pips × pip value). Estimate only. XAUUSD and crypto contract values vary by broker.",style="Muted.TLabel",wraplength=800).pack(anchor="w",pady=12)

    def _calculate(self):
        try:
            vals=[float(v.get()) for v in self.inputs.values()]
            risk,lots=calculate_position_size(*vals)
            self.calc_result.configure(text=f"Risk amount: ${risk:,.2f}     Estimated size: {lots:.4f} lots")
        except (ValueError,TypeError) as e: messagebox.showerror("Invalid input",str(e))

    def _journal(self):
        ttk.Label(self.journal_tab,text="Trade Journal",font=("Segoe UI",17,"bold")).pack(anchor="w")
        form=ttk.Frame(self.journal_tab); form.pack(fill="x",pady=12)
        self.trade={k:tk.StringVar(value=v) for k,v in {"Symbol":"XAUUSD","Direction":"Buy","Outcome":"Win","P&L ($)":"0"}.items()}
        for col,(key,var) in enumerate(self.trade.items()):
            cell=ttk.Frame(form); cell.grid(row=0,column=col,sticky="ew",padx=(0,10))
            ttk.Label(cell,text=key).pack(anchor="w")
            if key=="Direction": ttk.Combobox(cell,textvariable=var,values=["Buy","Sell"],state="readonly",width=13).pack(pady=4)
            elif key=="Outcome": ttk.Combobox(cell,textvariable=var,values=["Win","Loss","Breakeven"],state="readonly",width=13).pack(pady=4)
            else: ttk.Entry(cell,textvariable=var,width=16).pack(pady=4)
        ttk.Label(self.journal_tab,text="Notes").pack(anchor="w")
        self.notes=tk.Text(self.journal_tab,height=3,wrap="word",font=("Segoe UI",10)); self.notes.pack(fill="x",pady=5)
        actions=ttk.Frame(self.journal_tab); actions.pack(fill="x",pady=8)
        ttk.Button(actions,text="Save trade",style="Accent.TButton",command=self._save).pack(side="left")
        ttk.Button(actions,text="Sync pending trades",command=self._sync_pending_journal_trades).pack(side="left",padx=8)
        self.journal_sync_status=ttk.Label(self.journal_tab,text="New trades sync automatically to the local QUANTNEX workspace. Older entries with unknown sync history are not automatically replayed.",style="Muted.TLabel",wraplength=850)
        self.journal_sync_status.pack(anchor="w",pady=(0,6))
        cols=("date","symbol","side","outcome","pnl","sync"); self.table=ttk.Treeview(self.journal_tab,columns=cols,show="headings",height=9)
        for c,label,w in zip(cols,["Date","Symbol","Side","Outcome","P&L ($)","Sync"],[180,100,80,100,90,90]):
            self.table.heading(c,text=label); self.table.column(c,width=w,anchor="w")
        self.table.pack(fill="both",expand=True); self._refresh()
        self.after(2500,self._sync_pending_journal_trades)

    def _save(self):
        try:
            symbol=self.trade["Symbol"].get().strip()
            if not symbol or len(symbol)>20: raise ValueError("Enter a symbol up to 20 characters.")
            pnl=float(self.trade["P&L ($)"].get())
            if not math.isfinite(pnl): raise ValueError("P&L must be a finite number.")
            direction=self.trade["Direction"].get(); outcome=self.trade["Outcome"].get()
            notes=self.notes.get("1.0","end").strip()[:500]
            local_id=self.journal.add(symbol,direction,outcome,pnl,notes)
            self.notes.delete("1.0","end"); self._refresh()
            self._sync_journal_trade(local_id)
        except ValueError as e: messagebox.showerror("Invalid trade",str(e))

    def _refresh(self):
        for item in self.table.get_children(): self.table.delete(item)
        for row in self.journal.recent():
            self.table.insert("","end",values=(row[0],row[1],row[2],row[3],f"{row[4]:.2f}",row[5]))

    def _charts(self):
        ttk.Label(self.charts, text="Live Market Charts", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(self.charts, text="Select BTCUSDT for Binance Spot candles or XAUUSD for read-only candles from your local MT5 broker feed.", style="Muted.TLabel", wraplength=850).pack(anchor="w", pady=(4,12))
        top = ttk.Frame(self.charts); top.pack(fill="x", pady=(0,10))
        self.chart_symbol = tk.StringVar(value="BTCUSDT")
        self.chart_selector = ttk.Combobox(top, textvariable=self.chart_symbol, values=["BTCUSDT", "XAUUSD"], state="readonly", width=10)
        self.chart_selector.pack(side="left", padx=(0,12))
        self.chart_selector.bind("<<ComboboxSelected>>", lambda _event: self._refresh_chart())
        self.chart_quote = ttk.Label(top, text="BTCUSDT  •  Connecting…", font=("Segoe UI", 14, "bold"))
        self.chart_quote.pack(side="left")
        self.chart_status = ttk.Label(top, text="15m · Binance Spot feed", style="Muted.TLabel")
        self.chart_status.pack(side="right")
        self.chart_canvas = tk.Canvas(self.charts, height=390, bg="#090909", highlightthickness=1, highlightbackground="#303030")
        self.chart_canvas.pack(fill="both", expand=True)
        actions = ttk.Frame(self.charts); actions.pack(fill="x", pady=(12,0))
        ttk.Button(actions, text="Open BTC TradingView", command=lambda:webbrowser.open("https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT")).pack(side="left")
        ttk.Button(actions, text="Open Gold XAUUSD Chart", style="Accent.TButton", command=lambda:webbrowser.open("https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD")).pack(side="left", padx=8)
        ttk.Label(self.charts, text="Market data is for charting and analysis only. It is not a broker quote guarantee or an order connection.", style="Muted.TLabel", wraplength=850).pack(anchor="w", pady=(10,0))

    def _refresh_chart(self):
        if not hasattr(self, "chart_canvas"):
            return
        if getattr(self, "_chart_loading", False):
            self.after(5000, self._refresh_chart)
            return
        self._chart_loading = True
        symbol = self.chart_symbol.get()
        def worker():
            try:
                candles, price, provider = fetch_chart_data(symbol)
                self.after(0, lambda: self._chart_loaded(candles, price, None, symbol, provider))
            except Exception as exc:
                message = str(exc)
                self.after(0, lambda: self._chart_loaded([], None, message, symbol, None))
        threading.Thread(target=worker, daemon=True).start()

    def _chart_loaded(self, candles, price, error, symbol, provider):
        self._chart_loading = False
        if symbol != self.chart_symbol.get():
            self.after(0, self._refresh_chart)
            return
        if error:
            self.chart_status.configure(text=f"{symbol} feed unavailable · retrying")
            self.chart_quote.configure(text=symbol)
            self.chart_canvas.delete("all")
            if symbol == "XAUUSD":
                message = "Gold MT5 feed unavailable. Start the local QUANTNEX backend, set QUANTNEX_MT5_ENABLED=true and check your broker symbol. Details: " + error
            else:
                message = "Could not load Binance BTCUSDT candles. Check your internet connection. Details: " + error
            self.chart_canvas.create_text(20, 24, anchor="nw", fill="#aaaaaa", width=max(self.chart_canvas.winfo_width()-40, 300), text=message)
        else:
            self.chart_status.configure(text=f"LIVE · {provider} · 15m candles")
            self.chart_quote.configure(text=f"{symbol}  ${price:,.2f}" if price else symbol)
            self._draw_candles(candles)
        self.after(15000, self._refresh_chart)

    def _draw_candles(self, candles):
        canvas = self.chart_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 400); height = max(canvas.winfo_height(), 260)
        left, right, top, bottom = 66, width-18, 18, height-34
        if not candles:
            canvas.create_text(left, top, anchor="nw", fill="#aaaaaa", text="Waiting for market data…")
            return
        low = min(c["low"] for c in candles); high = max(c["high"] for c in candles)
        pad = max((high-low)*0.08, high*0.0005); low -= pad; high += pad
        plot_h = bottom-top; plot_w = right-left
        for i in range(5):
            y = top + plot_h*i/4
            value = high - (high-low)*i/4
            canvas.create_line(left,y,right,y,fill="#252525")
            canvas.create_text(left-8,y,anchor="e",fill="#888888",font=("Segoe UI",8),text=f"{value:,.0f}")
        step = plot_w/len(candles); body_w=max(3,step*0.58)
        for i,c in enumerate(candles):
            x=left+step*(i+0.5)
            y=lambda v: bottom-(v-low)/(high-low)*plot_h
            up=c["close"]>=c["open"]; color="#d8d8d8" if up else "#777777"
            canvas.create_line(x,y(c["high"]),x,y(c["low"]),fill=color,width=1)
            y1,y2=sorted((y(c["open"]),y(c["close"])))
            if y2-y1<1: y2=y1+1
            canvas.create_rectangle(x-body_w/2,y1,x+body_w/2,y2,fill=color,outline=color)
        canvas.create_text(left,bottom+12,anchor="w",fill="#777777",font=("Segoe UI",8),text="60 × 15-minute candles · Latest at right")


    def _account(self):
        ttk.Label(self.account_tab,text="QUANTNEX Local Wallet",font=("Segoe UI",17,"bold")).pack(anchor="w")
        ttk.Label(self.account_tab,text="This workspace runs on this Windows computer. No QUANTNEX login, registration, password or remote account is used.",style="Muted.TLabel",wraplength=850).pack(anchor="w",pady=(4,10))
        actions=ttk.Frame(self.account_tab); actions.pack(fill="x",pady=5)
        ttk.Button(actions,text="Refresh local wallet",style="Accent.TButton",command=self._account_refresh).pack(side="left")
        self.account_status=ttk.Label(self.account_tab,text="Connecting to the local QUANTNEX API…",style="Muted.TLabel",wraplength=850)
        self.account_status.pack(anchor="w",pady=(5,9))
        summary=ttk.Frame(self.account_tab,padding=10,relief="solid"); summary.pack(fill="x",pady=4)
        self.wallet_balance_label=ttk.Label(summary,text="Balance: $0.00",font=("Segoe UI",13,"bold")); self.wallet_balance_label.pack(side="left",padx=8)
        self.wallet_deposits_label=ttk.Label(summary,text="Deposits: $0.00",style="Muted.TLabel"); self.wallet_deposits_label.pack(side="left",padx=8)
        self.wallet_withdrawals_label=ttk.Label(summary,text="Withdrawals: $0.00",style="Muted.TLabel"); self.wallet_withdrawals_label.pack(side="left",padx=8)
        self.wallet_pnl_label=ttk.Label(summary,text="Trading P&L: $0.00",style="Muted.TLabel"); self.wallet_pnl_label.pack(side="left",padx=8)
        form=ttk.Frame(self.account_tab); form.pack(fill="x",pady=7)
        self.wallet_amount_var=tk.StringVar(value="10")
        self.wallet_description_var=tk.StringVar(value="Manual record")
        ttk.Label(form,text="Amount ($)").pack(side="left")
        ttk.Entry(form,textvariable=self.wallet_amount_var,width=12).pack(side="left",padx=6)
        ttk.Label(form,text="Description").pack(side="left",padx=(10,0))
        ttk.Entry(form,textvariable=self.wallet_description_var,width=28).pack(side="left",padx=6)
        ttk.Button(form,text="Add deposit record",command=lambda:self._wallet_submit("deposit")).pack(side="left",padx=5)
        ttk.Button(form,text="Add withdrawal record",command=lambda:self._wallet_submit("withdrawal")).pack(side="left")
        ttk.Label(self.account_tab,text="Manual bookkeeping only — these are not verified bank deposits or payments. All shared wallet and journal records stay in the local QUANTNEX database.",style="Muted.TLabel",wraplength=850).pack(anchor="w",pady=(2,7))
        cols=("date","type","amount","description")
        self.wallet_table=ttk.Treeview(self.account_tab,columns=cols,show="headings",height=6)
        for col,label,width in zip(cols,("Date","Type","Amount ($)","Description"),(170,110,110,430)):
            self.wallet_table.heading(col,text=label); self.wallet_table.column(col,width=width,anchor="w")
        self.wallet_table.pack(fill="both",expand=True)
        self.after(900,self._account_refresh)

    def _api_base(self):
        return "http://127.0.0.1:8000"

    def _api_request(self,method,path,payload=None,base=None):
        base=base or self._api_base()
        data=json.dumps(payload).encode("utf-8") if payload is not None else None
        headers={"User-Agent":"QUANTNEX-Desktop/0.7.0","Accept":"application/json"}
        if data is not None: headers["Content-Type"]="application/json"
        request=urllib.request.Request(base+path,data=data,headers=headers,method=method)
        try:
            with urllib.request.urlopen(request,timeout=18) as response:
                raw=response.read()
                return json.loads(raw.decode("utf-8")) if raw else None
        except urllib.error.HTTPError as exc:
            try: detail=json.loads(exc.read().decode("utf-8")).get("detail",str(exc))
            except Exception: detail=str(exc)
            raise RuntimeError(f"API error {exc.code}: {detail}")
        except urllib.error.URLError as exc:
            raise RuntimeError("Cannot reach the local QUANTNEX API. Start Web + Backend from run_quantnex.bat.") from exc

    def _fetch_wallet(self,base):
        summary=self._api_request("GET","/api/v1/wallet/summary",base=base)
        rows=self._api_request("GET","/api/v1/wallet/transactions?limit=100",base=base)
        return summary,rows

    def _show_wallet(self,summary,rows):
        self.wallet_balance_label.configure(text="Balance: $" + format(summary.get("balance",0),",.2f"))
        self.wallet_deposits_label.configure(text="Deposits: $" + format(summary.get("deposits",0),",.2f"))
        self.wallet_withdrawals_label.configure(text="Withdrawals: $" + format(summary.get("withdrawals",0),",.2f"))
        self.wallet_pnl_label.configure(text="Trading P&L: $" + format(summary.get("trading_pnl",0),",.2f"))
        for item in self.wallet_table.get_children(): self.wallet_table.delete(item)
        for row in rows:
            amount=float(row.get("amount",0))
            self.wallet_table.insert("","end",values=(row.get("created_at","").replace("T"," ")[:19],
                row.get("transaction_type",""),format(amount,",.2f"),row.get("description","")))

    def _account_refresh(self):
        base=self._api_base()
        self.account_status.configure(text="Loading your local wallet…")
        def worker():
            try:
                summary,rows=self._fetch_wallet(base)
                self.after(0,lambda:self._show_wallet(summary,rows))
                self.after(0,lambda:self.account_status.configure(text="Local wallet connected. Your data stays on this computer."))
            except Exception as exc:
                message=str(exc)
                self.after(0,lambda:self.account_status.configure(text=message))
        threading.Thread(target=worker,daemon=True).start()

    def _wallet_submit(self,transaction_type):
        try:
            amount=validate_wallet_amount(self.wallet_amount_var.get())
        except ValueError as exc:
            self.account_status.configure(text=str(exc)); return
        base=self._api_base()
        payload={"transaction_type":transaction_type,"amount":amount,
                 "description":self.wallet_description_var.get().strip()[:240]}
        self.account_status.configure(text="Saving local wallet record…")
        def worker():
            try:
                self._api_request("POST","/api/v1/wallet/transactions",payload,base=base)
                summary,rows=self._fetch_wallet(base)
                self.after(0,lambda:self._show_wallet(summary,rows))
                self.after(0,lambda:self.account_status.configure(text="Manual wallet record saved locally."))
            except Exception as exc:
                message=str(exc)
                self.after(0,lambda:self.account_status.configure(text=message))
        threading.Thread(target=worker,daemon=True).start()

    def _sync_journal_trade(self, local_id):
        self._sync_pending_journal_trades()

    def _sync_pending_journal_trades(self):
        if self._journal_sync_running:
            return
        pending=self.journal.pending()
        unknown=self.journal.unknown_sync_count()
        if not pending:
            message="No pending new trades."
            if unknown:
                message+=f" {unknown} older entries have unknown sync history and were not re-sent, to avoid duplicate wallet P&L."
            self.journal_sync_status.configure(text=message)
            self._refresh()
            return
        self._journal_sync_running=True
        base=self._api_base()
        self.journal_sync_status.configure(text=f"Syncing {len(pending)} pending local trade(s) to the QUANTNEX workspace…")
        def worker():
            synced=0
            errors=[]
            for local_id,symbol,side,outcome,pnl,notes in pending:
                payload={
                    "symbol":symbol,"direction":side.lower(),"outcome":outcome.lower(),
                    "pnl":pnl,"notes":notes,"client_ref":f"windows:{local_id}",
                }
                try:
                    self._api_request("POST","/api/v1/journal",payload,base=base)
                    self.journal.mark_synced(local_id)
                    synced+=1
                except Exception as exc:
                    errors.append(str(exc))
            def finish():
                self._journal_sync_running=False
                self._refresh()
                remaining=len(self.journal.pending())
                message=f"Synced {synced} trade(s). {remaining} remain pending."
                if errors:
                    message+=" Last error: "+errors[-1]
                unknown_now=self.journal.unknown_sync_count()
                if unknown_now:
                    message+=f" {unknown_now} older entries have unknown sync history and were not automatically re-sent."
                self.journal_sync_status.configure(text=message)
            self.after(0,finish)
        threading.Thread(target=worker,daemon=True).start()

    def _device(self):
        ttk.Label(self.device_tab, text="Device & Security", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(self.device_tab, text="A random installation ID for future account/device linking. No hardware serial number or MAC address is collected.", style="Muted.TLabel", wraplength=800).pack(anchor="w", pady=(5,18))
        self.device_id = tk.StringVar(value=get_device_id())
        card=ttk.Frame(self.device_tab, padding=18, relief="solid"); card.pack(fill="x")
        ttk.Label(card,text="THIS INSTALLATION ID",style="Muted.TLabel").pack(anchor="w")
        ttk.Label(card,textvariable=self.device_id,font=("Consolas",12,"bold"),wraplength=780).pack(anchor="w",pady=10)
        actions=ttk.Frame(card); actions.pack(anchor="w")
        ttk.Button(actions,text="Copy ID",command=self._copy_device_id).pack(side="left")
        ttk.Button(actions,text="Reset / Generate new ID",command=self._reset_device_id).pack(side="left",padx=8)
        ttk.Label(self.device_tab,text="Resetting the ID creates a new random local installation identifier. It does not change your local journal, wallet or workspace data.",style="Muted.TLabel",wraplength=820).pack(anchor="w",pady=14)

    def _copy_device_id(self):
        self.clipboard_clear(); self.clipboard_append(self.device_id.get())
        messagebox.showinfo("Device ID","Installation ID copied.")

    def _reset_device_id(self):
        if not messagebox.askyesno("Reset Device ID","Generate a new installation ID for this copy of QUANTNEX?"):
            return
        value=str(uuid.uuid4())
        (app_data()/"device_id.txt").write_text(value,encoding="utf-8")
        self.device_id.set(value)

    def _updates(self):
        ttk.Label(self.updates,text="Software Updates",font=("Segoe UI",17,"bold")).pack(anchor="w")
        ttk.Label(self.updates,text=f"Installed version: {APP_VERSION}",style="Muted.TLabel").pack(anchor="w",pady=(5,15))
        actions=ttk.Frame(self.updates); actions.pack(anchor="w",fill="x")
        self.check_button=ttk.Button(actions,text="Check for updates",style="Accent.TButton",command=self._check_background)
        self.check_button.pack(side="left")
        ttk.Button(actions,text="Open GitHub repository",command=lambda:webbrowser.open(f"https://github.com/{REPO}")).pack(side="left",padx=8)
        ttk.Button(actions,text="Open releases page",command=lambda:webbrowser.open(f"https://github.com/{REPO}/releases")).pack(side="left")
        self.update_status=ttk.Label(self.updates,text="Ready. Select Check for updates to inspect the official update channel.",style="Muted.TLabel",wraplength=780)
        self.update_status.pack(anchor="w",pady=14)
        self.update_progress=ttk.Progressbar(self.updates,mode="indeterminate",length=420,style="Horizontal.TProgressbar")
        ttk.Label(self.updates,text="SOURCE MODE: GIT SYNC  •  EXE MODE: RELEASE DOWNLOAD + SHA256 VERIFICATION",style="Muted.TLabel").pack(anchor="w",pady=(8,4))
        self.install_button=ttk.Button(self.updates,text="Download & install update",command=self._install_update)

    def _schedule_update_check(self):
        # Keep exactly one periodic updater timer, even after manual checks.
        if self.update_timer_id is not None:
            try:
                self.after_cancel(self.update_timer_id)
            except Exception:
                pass
        self.update_timer_id = self.after(300000, self._check_background)

    def _set_update_status(self, message):
        def finish():
            self.update_status.configure(text=message)
            self.update_progress.stop()
            self.update_progress.pack_forget()
            self.update_check_running = False
            self.check_button.configure(state="normal")
            self._schedule_update_check()
        self.after(0, finish)

    def _check_background(self):
        if self.update_timer_id is not None:
            try:
                self.after_cancel(self.update_timer_id)
            except Exception:
                pass
            self.update_timer_id = None
        if self.update_check_running:
            return
        self.update_check_running = True
        self.check_button.configure(state="disabled")
        self.update_status.configure(text="Connecting securely to GitHub and checking the QUANTNEX update channel…")
        self.update_progress.pack(anchor="w",pady=(0,12))
        self.update_progress.start(12)
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self):
        try:
            # When launched from the .bat/source checkout, update the clean Git working tree
            # directly so the user does not need a packaged EXE for routine source updates.
            if not getattr(sys, "frozen", False):
                repo_root = Path(__file__).resolve().parents[2]
                if not (repo_root / ".git").exists():
                    # ZIP-installed source: download the latest repository archive to Downloads.
                    # The running extracted folder is never overwritten; user replaces it manually.
                    downloads = Path.home() / "Downloads"
                    downloads.mkdir(parents=True, exist_ok=True)
                    archive = downloads / "QUANTNEX-latest.zip"
                    archive_url = f"https://codeload.github.com/{REPO}/zip/refs/heads/main"
                    request = urllib.request.Request(archive_url, headers={"User-Agent":"QUANTNEX-Desktop"})
                    temp_archive = archive.with_suffix(".zip.part")
                    with urllib.request.urlopen(request, timeout=60) as response, temp_archive.open("wb") as output:
                        shutil.copyfileobj(response, output)
                    if temp_archive.stat().st_size < 10000:
                        temp_archive.unlink(missing_ok=True)
                        raise ValueError("The downloaded source archive is unexpectedly small.")
                    # Confirm it is a readable ZIP before making it the latest download.
                    import zipfile
                    with zipfile.ZipFile(temp_archive, "r") as bundle:
                        if bundle.testzip() is not None:
                            raise ValueError("The source ZIP failed its integrity check.")
                    temp_archive.replace(archive)
                    self.staged_update = archive
                    self.after(0, lambda: self.install_button.configure(text="Open Downloads folder"))
                    self.after(0, lambda: self.install_button.configure(command=lambda: os.startfile(str(downloads))))
                    self.after(0, lambda: self.install_button.pack(anchor="w", pady=(10,0)))
                    self._set_update_status("Latest source ZIP downloaded and integrity-checked: Downloads\\QUANTNEX-latest.zip. Close QUANTNEX, keep a backup of your current folder, extract this ZIP to a new folder, then launch run_quantnex.bat. Your trade journal is stored separately in AppData and is not inside the ZIP.")
                    return
                if (repo_root / ".git").exists():
                    status = subprocess.run(["git", "-C", str(repo_root), "status", "--porcelain"],
                        capture_output=True, text=True, timeout=15)
                    if status.returncode != 0:
                        raise RuntimeError("Git could not inspect this workspace: " + status.stderr.strip())
                    if status.stdout.strip():
                        self._set_update_status("Update paused: local files have uncommitted changes. Commit or back them up before updating.")
                        return
                    pull = subprocess.run(["git", "-C", str(repo_root), "pull", "--ff-only", "origin", "main"],
                        capture_output=True, text=True, timeout=45)
                    if pull.returncode != 0:
                        raise RuntimeError("Source update failed: " + (pull.stderr.strip() or pull.stdout.strip()))
                    if "Already up to date" in pull.stdout:
                        self._set_update_status("You already have the latest QUANTNEX workspace from GitHub.")
                        return
                    self._set_update_status("Update downloaded successfully. Restarting QUANTNEX with the new workspace…")
                    self.after(900, self._restart_source)
                    return
            req=urllib.request.Request(LATEST_URL,headers={"User-Agent":"QUANTNEX-Desktop","Accept":"application/vnd.github+json"})
            with urllib.request.urlopen(req,timeout=12) as response:
                release=json.loads(response.read().decode("utf-8"))
            latest=str(release.get("tag_name","")).lstrip("v")
            if not latest:
                raise ValueError("No release version tag found.")
            def version(value):
                try: return tuple(int(x) for x in value.split(".")[:3])
                except ValueError: return (0,)
            if version(latest) <= version(APP_VERSION):
                self._set_update_status("You have the latest published version ("+latest+").")
                return
            asset=next((a for a in release.get("assets",[]) if a.get("name","").lower()=="quantnex.exe"),None)
            checksum_asset=next((a for a in release.get("assets",[]) if a.get("name","").lower()=="sha256sums.txt"),None)
            if not asset or not checksum_asset:
                self._set_update_status("Version "+latest+" is available, but its EXE or SHA256 checksum is missing.")
                return
            staged=app_data()/"updates"/"QUANTNEX.exe"
            stage_verified_release_exe(asset["browser_download_url"],checksum_asset["browser_download_url"],staged)
            self.staged_update=staged
            self.after(0,lambda:self.install_button.configure(text="Install "+latest+" & restart"))
            self.after(0,lambda:self.install_button.pack(anchor="w",pady=(10,0)))
            self._set_update_status("New QUANTNEX version "+latest+" detected and downloaded. SHA256 verification passed. Select Install & restart to apply it safely. Your local journal and settings remain in AppData.")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                self._set_update_status("No official QUANTNEX release has been published yet. Your app is not broken. Source mode can update through Git; packaged EXE updates will become available after the first GitHub Release is published.")
            else:
                self._set_update_status(f"GitHub returned HTTP {exc.code}. Check your internet connection and try again.")
        except (urllib.error.URLError,TimeoutError,ValueError,json.JSONDecodeError,OSError,KeyError,RuntimeError,subprocess.SubprocessError) as exc:
            self._set_update_status("Update check failed safely: "+str(exc))

    def _restart_source(self):
        repo_root = Path(__file__).resolve().parents[2]
        script = Path(__file__).resolve()
        subprocess.Popen([sys.executable, str(script)], cwd=str(repo_root))
        self.destroy()

    def _install_update(self):
        if not getattr(self,"staged_update",None) or not self.staged_update.exists():
            messagebox.showerror("Update","No downloaded update is available.")
            return
        if not getattr(sys,"frozen",False):
            messagebox.showinfo("Development mode","The installer works with the packaged Windows EXE. Build and run the EXE to test it.")
            return
        if not messagebox.askyesno("Install update","Install the downloaded QUANTNEX update and restart now?"):
            return
        target=Path(sys.executable).resolve()
        staged=self.staged_update.resolve()
        update_dir=app_data()/"updates"
        update_dir.mkdir(parents=True,exist_ok=True)
        helper=update_dir/"apply_update.ps1"
        config=update_dir/"apply_update.json"
        config.write_text(json.dumps({
            "target":str(target),
            "staged":str(staged),
            "pid":os.getpid()
        }),encoding="utf-8")
        helper.write_text(r"""
$ErrorActionPreference = "Stop"
try {
$config = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "apply_update.json") | ConvertFrom-Json
$target = [IO.Path]::GetFullPath([string]$config.target)
$staged = [IO.Path]::GetFullPath([string]$config.staged)
$backup = $target + ".previous.exe"
$temp = $target + ".new"
$processId = [int]$config.pid
# Wait until the current app has fully exited before touching the running EXE.
for ($i = 0; $i -lt 180; $i++) {
    if (-not (Get-Process -Id $processId -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 500
}
if (Get-Process -Id $processId -ErrorAction SilentlyContinue) { throw "QUANTNEX did not close in time." }
if (-not (Test-Path -LiteralPath $staged -PathType Leaf)) { throw "Verified update file is missing." }
Copy-Item -LiteralPath $staged -Destination $temp -Force
if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
$hadOriginal = Test-Path -LiteralPath $target -PathType Leaf
try {
    if ($hadOriginal) { Move-Item -LiteralPath $target -Destination $backup -Force }
    Move-Item -LiteralPath $temp -Destination $target -Force
    Start-Process -FilePath $target
    Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue
} catch {
    if ($hadOriginal -and (Test-Path -LiteralPath $backup)) {
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue }
        Move-Item -LiteralPath $backup -Destination $target -Force
        Start-Process -FilePath $target
    } elseif (-not $hadOriginal -and (Test-Path -LiteralPath $target)) {
        Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
    }
    throw
} finally {
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
}
} catch {
    $message = "QUANTNEX update failed: " + $_.Exception.Message
    $message | Out-File -LiteralPath (Join-Path $PSScriptRoot "apply_update.log") -Append -Encoding utf8
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($message + "`nYour existing EXE was preserved or restored when possible.", "QUANTNEX Update", "OK", "Warning") | Out-Null
}
""",encoding="utf-8")
        subprocess.Popen(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(helper)],
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        self.destroy()

if __name__ == "__main__":
    App().mainloop()

from __future__ import annotations
import hashlib, json, os, shutil, sqlite3, subprocess, sys, threading, urllib.error, urllib.request, webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

APP_VERSION = "0.4.0"
REPO = "adeeshadasuniduwara/QUANTNEX"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

def app_data():
    path = Path.home() / "AppData" / "Local" / "QUANTNEX"
    path.mkdir(parents=True, exist_ok=True)
    return path

def calculate_position_size(equity, risk_percent, stop_pips, pip_value):
    if equity <= 0 or not 0 < risk_percent <= 100 or stop_pips <= 0 or pip_value <= 0:
        raise ValueError("Use positive values; risk must be above 0 and at most 100%.")
    risk_amount = equity * risk_percent / 100
    return risk_amount, risk_amount / (stop_pips * pip_value)

class TradeJournal:
    def __init__(self):
        self.path = app_data() / "journal.sqlite3"
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS trades(
                id INTEGER PRIMARY KEY, created TEXT NOT NULL, symbol TEXT NOT NULL,
                side TEXT NOT NULL, outcome TEXT NOT NULL, pnl REAL NOT NULL, notes TEXT NOT NULL)""")
    def add(self, symbol, side, outcome, pnl, notes):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO trades(created,symbol,side,outcome,pnl,notes) VALUES(?,?,?,?,?,?)",
                (datetime.now().astimezone().isoformat(timespec="seconds"), symbol.upper(), side, outcome, pnl, notes))
    def recent(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT created,symbol,side,outcome,pnl FROM trades ORDER BY id DESC LIMIT 100").fetchall()

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QUANTNEX — Trading Workspace")
        self.geometry("1000x680"); self.minsize(850, 560); self.configure(bg="#080808")
        self.journal = TradeJournal()
        self.update_check_running = False
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

    def _fade_in(self, step=0):
        try:
            self.attributes("-alpha", min(1.0, step / 10))
            if step < 10:
                self.after(28, lambda: self._fade_in(step + 1))
        except tk.TclError:
            pass

    def _build(self):
        root = ttk.Frame(self, padding=22); root.pack(fill="both", expand=True)
        ttk.Label(root, text="Q U A N T N E X", foreground="#ffffff", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(root, text="Trading Workspace", style="Title.TLabel").pack(anchor="w", pady=(4, 2))
        ttk.Label(root, text=f"WINDOWS DESKTOP  /  VERSION {APP_VERSION}  /  LOCAL MODE", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))
        tabs = ttk.Notebook(root); tabs.pack(fill="both", expand=True)
        self.home = ttk.Frame(tabs, padding=18); self.calc = ttk.Frame(tabs, padding=18)
        self.journal_tab = ttk.Frame(tabs, padding=18); self.updates = ttk.Frame(tabs, padding=18)
        tabs.add(self.home, text="Overview"); tabs.add(self.calc, text="Position Calculator")
        tabs.add(self.journal_tab, text="Trade Journal"); tabs.add(self.updates, text="Updates")
        self._home(); self._calculator(); self._journal(); self._updates()
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
        ttk.Button(self.journal_tab,text="Save trade",style="Accent.TButton",command=self._save).pack(anchor="w",pady=8)
        cols=("date","symbol","side","outcome","pnl"); self.table=ttk.Treeview(self.journal_tab,columns=cols,show="headings",height=9)
        for c,label,w in zip(cols,["Date","Symbol","Side","Outcome","P&L ($)"],[190,110,90,110,100]):
            self.table.heading(c,text=label); self.table.column(c,width=w,anchor="w")
        self.table.pack(fill="both",expand=True); self._refresh()

    def _save(self):
        try:
            symbol=self.trade["Symbol"].get().strip()
            if not symbol or len(symbol)>20: raise ValueError("Enter a symbol up to 20 characters.")
            pnl=float(self.trade["P&L ($)"].get())
            self.journal.add(symbol,self.trade["Direction"].get(),self.trade["Outcome"].get(),pnl,self.notes.get("1.0","end").strip()[:500])
            self.notes.delete("1.0","end"); self._refresh()
        except ValueError as e: messagebox.showerror("Invalid trade",str(e))

    def _refresh(self):
        for item in self.table.get_children(): self.table.delete(item)
        for row in self.journal.recent(): self.table.insert("","end",values=(row[0],row[1],row[2],row[3],f"{row[4]:.2f}"))

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
        self.install_button=ttk.Button(self.updates,text="Install verified update and restart",command=self._install_update)

    def _set_update_status(self, message):
        def finish():
            self.update_status.configure(text=message)
            self.update_progress.stop()
            self.update_progress.pack_forget()
            self.update_check_running = False
            self.check_button.configure(state="normal")
        self.after(0, finish)

    def _check_background(self):
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
            staged.parent.mkdir(parents=True,exist_ok=True)
            download=urllib.request.Request(asset["browser_download_url"],headers={"User-Agent":"QUANTNEX-Desktop"})
            with urllib.request.urlopen(download,timeout=45) as response, staged.open("wb") as output:
                shutil.copyfileobj(response,output)
            if staged.stat().st_size < 100000:
                staged.unlink(missing_ok=True)
                raise ValueError("Downloaded file failed the basic size check.")
            checksum_req=urllib.request.Request(checksum_asset["browser_download_url"],headers={"User-Agent":"QUANTNEX-Desktop"})
            with urllib.request.urlopen(checksum_req,timeout=15) as response:
                checksum_text=response.read().decode("utf-8")
            expected=next((line.split()[0].lower() for line in checksum_text.splitlines() if "quantnex.exe" in line.lower()),"")
            actual=hashlib.sha256(staged.read_bytes()).hexdigest().lower()
            if not expected or actual != expected:
                staged.unlink(missing_ok=True)
                raise ValueError("Update SHA256 verification failed. The downloaded file was rejected.")
            self.staged_update=staged
            self.after(0,lambda:self.install_button.pack(anchor="w",pady=(10,0)))
            self._set_update_status("Version "+latest+" downloaded. Review release notes, then choose Install and restart.")
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
        backup=target.with_name(target.stem+".previous.exe")
        helper=app_data()/"updates"/"apply_update.cmd"
        helper.write_text(
            "@echo off\r\nsetlocal EnableDelayedExpansion\r\n"
            "set \"TARGET="+str(target)+"\"\r\n"
            "set \"STAGED="+str(staged)+"\"\r\n"
            "set \"BACKUP="+str(backup)+"\"\r\n"
            "timeout /t 2 /nobreak >nul\r\ncopy /y \"%TARGET%\" \"%BACKUP%\" >nul\r\n"
            "set TRY=0\r\n:retry\r\ncopy /y \"%STAGED%\" \"%TARGET%\" >nul\r\n"
            "if errorlevel 1 (set /a TRY+=1 & if !TRY! LSS 20 (timeout /t 1 /nobreak >nul & goto retry) else (exit /b 1))\r\n"
            "start \"\" \"%TARGET%\"\r\ndel \"%STAGED%\"\r\nendlocal\r\n",
            encoding="utf-8")
        subprocess.Popen(["cmd.exe","/c",str(helper)],creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        self.destroy()

if __name__ == "__main__":
    App().mainloop()

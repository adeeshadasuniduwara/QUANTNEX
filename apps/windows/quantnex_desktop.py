from __future__ import annotations
import json, sqlite3, urllib.error, urllib.request, webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

APP_VERSION = "0.3.0"
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
        self.geometry("1000x680"); self.minsize(850, 560); self.configure(bg="#f3f5f8")
        self.journal = TradeJournal()
        self.style = ttk.Style(self)
        try: self.style.theme_use("clam")
        except tk.TclError: pass
        self.style.configure("TFrame", background="#f3f5f8")
        self.style.configure("TLabel", background="#f3f5f8", foreground="#182235", font=("Segoe UI", 10))
        self.style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        self.style.configure("Muted.TLabel", foreground="#697589")
        self.style.configure("TButton", font=("Segoe UI", 10), padding=8)
        self.style.configure("Accent.TButton", background="#2457d6", foreground="white")
        self.style.configure("Treeview", rowheight=28, font=("Segoe UI", 9))
        self._build()

    def _build(self):
        root = ttk.Frame(self, padding=22); root.pack(fill="both", expand=True)
        ttk.Label(root, text="QUANTNEX", foreground="#2457d6", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(root, text="Trading Workspace", style="Title.TLabel").pack(anchor="w", pady=(4, 2))
        ttk.Label(root, text=f"Windows desktop • Version {APP_VERSION} • Local mode", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))
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
        ttk.Button(self.updates,text="Check for updates",style="Accent.TButton",command=self._check).pack(anchor="w")
        self.update_status=ttk.Label(self.updates,text="Checks the public QUANTNEX GitHub Releases page.",style="Muted.TLabel",wraplength=780)
        self.update_status.pack(anchor="w",pady=14)
        ttk.Button(self.updates,text="Open releases page",command=lambda:webbrowser.open(f"https://github.com/{REPO}/releases")).pack(anchor="w")

    def _check(self):
        self.update_status.configure(text="Checking for updates…"); self.update_status.update_idletasks()
        try:
            req=urllib.request.Request(LATEST_URL,headers={"User-Agent":"QUANTNEX-Desktop"})
            with urllib.request.urlopen(req,timeout=8) as response: release=json.loads(response.read().decode())
            latest=str(release.get("tag_name","")).lstrip("v")
            if not latest: raise ValueError("No release version tag found.")
            if latest != APP_VERSION:
                self.update_status.configure(text=f"Version {latest} is available. Open Releases to review it.")
                if messagebox.askyesno("Update available",f"QUANTNEX {latest} is available. Open the official release page?"):
                    webbrowser.open(release.get("html_url",f"https://github.com/{REPO}/releases"))
            else: self.update_status.configure(text="You have the latest published version.")
        except (urllib.error.URLError,TimeoutError,ValueError,json.JSONDecodeError) as e:
            self.update_status.configure(text=f"Could not check now: {e}. Try the Releases page later.")

if __name__ == "__main__":
    App().mainloop()

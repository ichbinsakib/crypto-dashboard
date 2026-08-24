"""
Teka Alerts Manager - small GUI to add, toggle, and delete BTC/ETH price
alerts without hand-editing alerts_config.json.

Run:  python add_alert.py    (or double-click add_alert.bat)
"""
import os
import sys
import time
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashboard import load_alerts_config, save_alerts_config, BASE_DIR, COINS  # noqa: E402

COIN_KEYS = [c["key"] for c in COINS]


def get_config():
    cfg = load_alerts_config()
    if cfg is None:
        cfg = {"alerts": []}
    return cfg


def regenerate_dashboard():
    try:
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "dashboard.py")],
                        cwd=BASE_DIR, timeout=30)
        return True
    except Exception:
        return False  # non-fatal; the next scheduled run (within 1 min) picks it up regardless


class AlertsManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Teka - Price Alerts Manager")
        self.geometry("580x460")
        self.configure(bg="#0a0e14")
        self.config_data = get_config()
        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background="#0a0e14")
        style.configure("TLabel", background="#0a0e14", foreground="#e5e7eb")
        style.configure("TButton", padding=6)

        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Existing alerts", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.listbox = tk.Listbox(frm, height=10, bg="#10151f", fg="#e5e7eb",
                                   selectbackground="#38bdf8", selectforeground="#04121c",
                                   font=("Consolas", 10), borderwidth=0, highlightthickness=1,
                                   highlightbackground="#1f2937")
        self.listbox.pack(fill="both", expand=True, pady=(6, 10))

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x", pady=(0, 14))
        ttk.Button(btn_row, text="Toggle Enabled", command=self.toggle_selected).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Delete Selected", command=self.delete_selected).pack(side="left")

        ttk.Separator(frm).pack(fill="x", pady=(0, 12))

        ttk.Label(frm, text="Add new alert", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        form = ttk.Frame(frm)
        form.pack(fill="x", pady=(8, 0))

        ttk.Label(form, text="Coin:").grid(row=0, column=0, sticky="w", pady=4)
        self.coin_var = tk.StringVar(value=COIN_KEYS[0])
        ttk.Combobox(form, textvariable=self.coin_var, values=COIN_KEYS, width=10,
                     state="readonly").grid(row=0, column=1, sticky="w", padx=(8, 20))

        ttk.Label(form, text="Condition:").grid(row=0, column=2, sticky="w", pady=4)
        self.cond_var = tk.StringVar(value="above")
        ttk.Combobox(form, textvariable=self.cond_var, values=["above", "below"], width=10,
                     state="readonly").grid(row=0, column=3, sticky="w", padx=(8, 0))

        ttk.Label(form, text="Target price (USD):").grid(row=1, column=0, sticky="w", pady=4)
        self.price_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.price_var, width=16).grid(row=1, column=1, sticky="w", padx=(8, 20))

        ttk.Label(form, text="Label (optional):").grid(row=1, column=2, sticky="w", pady=4)
        self.label_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.label_var, width=24).grid(row=1, column=3, sticky="w", padx=(8, 0))

        ttk.Button(frm, text="+ Add Alert", command=self.add_alert).pack(anchor="e", pady=(14, 0))

        self.status_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.status_var, foreground="#34d399").pack(anchor="w", pady=(10, 0))

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for a in self.config_data.get("alerts", []):
            state = "ON " if a.get("enabled", True) else "OFF"
            try:
                price_str = f"${float(a['price']):,.2f}"
            except (TypeError, ValueError):
                price_str = str(a.get("price"))
            self.listbox.insert(
                tk.END,
                f"[{state}] {a.get('coin', '?')} {a.get('condition', '?'):>5} {price_str}  -  "
                f"{a.get('label', a.get('id', ''))}"
            )

    def add_alert(self):
        coin = self.coin_var.get()
        cond = self.cond_var.get()
        price_raw = self.price_var.get().strip().replace(",", "").replace("$", "")
        label = self.label_var.get().strip()

        if not price_raw:
            messagebox.showerror("Missing price", "Enter a target price.")
            return
        try:
            price = float(price_raw)
            if price <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid price", "Price must be a positive number.")
            return

        if not label:
            label = f"{coin} {cond} ${price:,.2f}"

        rule_id = f"{coin.lower()}-{cond}-{int(price)}-{int(time.time())}"
        self.config_data.setdefault("alerts", []).append({
            "id": rule_id, "coin": coin, "condition": cond, "price": price,
            "label": label, "enabled": True,
        })
        save_alerts_config(self.config_data)
        self._refresh_list()
        self.price_var.set("")
        self.label_var.set("")
        self._finish_action(f"Added: {label}.")

    def _selected_index(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("No selection", "Select an alert first.")
            return None
        return sel[0]

    def toggle_selected(self):
        idx = self._selected_index()
        if idx is None:
            return
        alerts = self.config_data.get("alerts", [])
        alerts[idx]["enabled"] = not alerts[idx].get("enabled", True)
        save_alerts_config(self.config_data)
        self._refresh_list()
        self._finish_action("Toggled.")

    def delete_selected(self):
        idx = self._selected_index()
        if idx is None:
            return
        alerts = self.config_data.get("alerts", [])
        removed = alerts.pop(idx)
        save_alerts_config(self.config_data)
        self._refresh_list()
        self._finish_action(f"Deleted: {removed.get('label', removed.get('id', ''))}.")

    def _finish_action(self, message):
        self.status_var.set(f"{message} Refreshing dashboard...")
        self.update_idletasks()
        ok = regenerate_dashboard()
        self.status_var.set(f"{message} {'Dashboard updated.' if ok else 'Saved (dashboard will pick it up within 1 min).'}")


if __name__ == "__main__":
    app = AlertsManager()
    app.mainloop()

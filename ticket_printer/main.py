import tkinter as tk
from tkinter import ttk, messagebox
import requests
import json
import subprocess
import tempfile
from datetime import datetime

CONFIG_FILE = 'printer_config.json'

DEFAULT_CONFIG = {
    "server_url": "https://5.75.162.179",
    "cups_printer": "ferre",
    "store_name": "FERRETERÍA LEON",
}


def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


class TicketPrinterApp:
    W = 32  # 55mm paper width
    def __init__(self, root):
        self.root = root
        self.root.title("Ticket Printer")
        self.root.geometry("500x650")
        self.root.resizable(False, False)

        self.config = load_config()

        main = ttk.Frame(root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="Ticket Printer", font=("Arial", 16, "bold")).pack(pady=(0, 8))
        ttk.Separator(main, orient='horizontal').pack(fill=tk.X, pady=4)

        fetch_frame = ttk.LabelFrame(main, text="Fetch Sale", padding=10)
        fetch_frame.pack(fill=tk.X, pady=6)

        ttk.Label(fetch_frame, text="Sale ID:").grid(row=0, column=0, sticky=tk.W)
        self.sale_id_entry = ttk.Entry(fetch_frame, width=20)
        self.sale_id_entry.grid(row=0, column=1, padx=(6, 0), sticky=tk.EW)
        fetch_frame.columnconfigure(1, weight=1)

        btn_frame = ttk.Frame(fetch_frame)
        btn_frame.grid(row=1, column=0, columnspan=2, pady=(8, 0))
        self.fetch_btn = ttk.Button(btn_frame, text="Fetch & Preview", command=self.fetch_sale)
        self.fetch_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.print_btn = ttk.Button(btn_frame, text="Print Ticket", command=self.print_ticket, state=tk.DISABLED)
        self.print_btn.pack(side=tk.LEFT)

        preview_frame = ttk.LabelFrame(main, text="Ticket Preview", padding=6)
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=6)

        text_frame = ttk.Frame(preview_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)
        self.preview_text = tk.Text(text_frame, font=("Courier", 10), wrap=tk.NONE, height=18)
        self.preview_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scroll_y = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.preview_text.yview)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.preview_text.configure(yscrollcommand=scroll_y.set)

        scroll_x = ttk.Scrollbar(preview_frame, orient=tk.HORIZONTAL, command=self.preview_text.xview)
        scroll_x.pack(fill=tk.X)
        self.preview_text.configure(xscrollcommand=scroll_x.set)

        ttk.Separator(main, orient='horizontal').pack(fill=tk.X, pady=4)

        config_frame = ttk.LabelFrame(main, text="Printer Config", padding=8)
        config_frame.pack(fill=tk.X)

        row = ttk.Frame(config_frame)
        row.pack(fill=tk.X)
        ttk.Label(row, text="Server URL:", width=14).pack(side=tk.LEFT)
        self.server_url_var = tk.StringVar(value=self.config.get("server_url", DEFAULT_CONFIG["server_url"]))
        url_entry = ttk.Entry(row, textvariable=self.server_url_var)
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        row2 = ttk.Frame(config_frame)
        row2.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(row2, text="Store Name:", width=14).pack(side=tk.LEFT)
        self.store_name_var = tk.StringVar(value=self.config.get("store_name", DEFAULT_CONFIG["store_name"]))
        store_entry = ttk.Entry(row2, textvariable=self.store_name_var)
        store_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        self.sale_data = None
        self.ticket_text = ""

    def fetch_sale(self):
        sale_id = self.sale_id_entry.get().strip()
        if not sale_id:
            messagebox.showwarning("Input required", "Enter a Sale ID")
            return
        if not sale_id.isdigit():
            messagebox.showwarning("Invalid ID", "Sale ID must be a number")
            return

        server_url = self.server_url_var.get().strip().rstrip('/')
        url = f"{server_url}/sale/sale_ticket_json/{sale_id}"

        try:
            self.fetch_btn.config(text="Fetching...", state=tk.DISABLED)
            self.root.update()
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            self.sale_data = resp.json()
            self.build_ticket_text()
            self.print_btn.config(state=tk.NORMAL)
            self.fetch_btn.config(text="Fetch & Preview", state=tk.NORMAL)
        except requests.ConnectionError:
            messagebox.showerror("Connection Error", f"Cannot reach server:\n{url}")
            self.fetch_btn.config(text="Fetch & Preview", state=tk.NORMAL)
        except requests.HTTPError as e:
            messagebox.showerror("HTTP Error", str(e))
            self.fetch_btn.config(text="Fetch & Preview", state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.fetch_btn.config(text="Fetch & Preview", state=tk.NORMAL)

    def build_ticket_text(self):
        if not self.sale_data:
            return
        s = self.sale_data
        store = self.store_name_var.get().strip() or DEFAULT_CONFIG["store_name"]
        w = self.W
        lines = []
        lines.append("")
        lines.append(store.center(w))
        lines.append("")
        lines.append("-" * w)
        lines.append(f"Venta: #{s['sale_id']}")
        try:
            dt = datetime.fromisoformat(s['date'].replace('Z', '+00:00'))
            date_str = dt.strftime("%d/%m/%Y %H:%M")
        except (ValueError, AttributeError):
            date_str = str(s.get('date', ''))
        lines.append(f"Fecha: {date_str}")
        lines.append(f"Cliente: {s['client']}")
        lines.append("-" * w)
        lines.append(f"{'Producto':15s} {'Cant':4s} {'Precio':7s} {'Total':6s}")
        lines.append("-" * w)

        for item in s['items']:
            name = item['name'][:15].ljust(15)
            qty = f"{item['quantity']:.0f}".rjust(4)
            price = f"${item['price']:.2f}".rjust(7)
            total = f"${item['item_total']:.2f}".rjust(6)
            lines.append(f"{name}{qty}{price}{total}")

        lines.append("-" * w)
        total_str = f"${s['total']:.2f}"
        lines.append(f"{'TOTAL:':24s} {total_str:>7s}")
        lines.append("")
        lines.append("Gracias por su compra!".center(w))
        lines.append("")

        self.ticket_text = "\n".join(lines)
        self.preview_text.delete(1.0, tk.END)
        self.preview_text.insert(1.0, self.ticket_text)

    def print_ticket(self):
        if not self.ticket_text:
            return

        try:
            self.print_btn.config(text="Printing...", state=tk.DISABLED)
            self.root.update()

            store = self.store_name_var.get().strip() or DEFAULT_CONFIG["store_name"]
            w = self.W
            s = self.sale_data

            try:
                dt = datetime.fromisoformat(s['date'].replace('Z', '+00:00'))
                date_str = dt.strftime("%d/%m/%Y %H:%M")
            except (ValueError, AttributeError):
                date_str = str(s.get('date', ''))

            lines = []
            lines.append(store.center(w))
            lines.append("")
            lines.append("Venta #" + str(s['sale_id']))
            lines.append("Fecha: " + date_str)
            lines.append("Cliente: " + s['client'])
            lines.append("-" * w)
            lines.append("{:15s} {:4s} {:7s} {:6s}".format('Producto', 'Cant', 'Precio', 'Total'))
            lines.append("-" * w)
            for item in s['items']:
                name = item['name'][:15].ljust(15)
                qty = f"{item['quantity']:.0f}".rjust(4)
                price = f"${item['price']:.2f}".rjust(7)
                total = f"${item['item_total']:.2f}".rjust(6)
                lines.append(f"{name}{qty}{price}{total}")
            lines.append("-" * w)
            total_str = f"${s['total']:.2f}"
            lines.append(f"{'TOTAL:':24s} {total_str:>7s}")
            lines.append("")
            lines.append("Gracias por su compra!")
            lines.append("")

            text = "\n".join(lines)

            printer_name = self.config.get("cups_printer", DEFAULT_CONFIG["cups_printer"])

            with tempfile.NamedTemporaryFile(mode='wb', suffix='.bin', delete=False) as f:
                f.write(text.encode('cp437', errors='replace'))
                f.write(b'\n\n\n')
                f.write(b'\x1d\x56\x00')
                temp_path = f.name

            result = subprocess.run(
                ['lp', '-d', printer_name, '-o', 'raw', temp_path],
                capture_output=True, text=True, timeout=30
            )

            import os
            os.unlink(temp_path)

            if result.returncode == 0:
                messagebox.showinfo("Success", "Ticket printed successfully!")
            else:
                raise RuntimeError(result.stderr.strip())

            self.print_btn.config(text="Print Ticket", state=tk.NORMAL)

        except Exception as e:
            messagebox.showerror("Print Error", f"Error printing ticket:\n{str(e)}")
            self.print_btn.config(text="Print Ticket", state=tk.NORMAL)

    def open_config_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Printer Configuration")
        dialog.geometry("400x200")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        main = ttk.Frame(dialog, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="Printer Configuration", font=("Arial", 14, "bold")).pack(pady=(0, 10))

        frame = ttk.Frame(main)
        frame.pack(fill=tk.X, pady=6)

        ttk.Label(frame, text="CUPS Printer Name:", width=18).pack(side=tk.LEFT)
        cups_var = tk.StringVar(value=self.config.get("cups_printer", DEFAULT_CONFIG["cups_printer"]))
        ttk.Entry(frame, textvariable=cups_var, width=20).pack(side=tk.LEFT, padx=(4, 0))

        frame2 = ttk.Frame(main)
        frame2.pack(fill=tk.X, pady=6)
        ttk.Label(frame2, text="", width=18).pack(side=tk.LEFT)
        ttk.Label(frame2, text="Find printer name with: lpstat -p",
                  foreground="gray").pack(side=tk.LEFT)

        def save_config_dialog():
            self.config["server_url"] = self.server_url_var.get().strip()
            self.config["store_name"] = self.store_name_var.get().strip()
            self.config["cups_printer"] = cups_var.get().strip()
            save_config(self.config)
            messagebox.showinfo("Saved", "Configuration saved to printer_config.json")
            dialog.destroy()

        btn_row = ttk.Frame(main)
        btn_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_row, text="Save", command=save_config_dialog).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)


if __name__ == "__main__":
    root = tk.Tk()
    app = TicketPrinterApp(root)
    root.mainloop()

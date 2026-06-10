import tkinter as tk
from tkinter import ttk, messagebox
import requests
import json
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import re
import unicodedata
import subprocess
import tempfile
import sys
import threading
from datetime import datetime
from flask import Flask, request, jsonify


def clean_text(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^a-zA-Z0-9\s\#\$\-\.\,]', '', text)
    return text


def title_case(text):
    text = clean_text(text).lower()
    return ' '.join(w.capitalize() for w in text.split())

CONFIG_FILE = 'printer_config.json'

DEFAULT_CONFIG = {
    "server_url": "https://5.75.162.179",
    "cups_printer": "ferre",
    "store_name": "Ferreteria Leon",
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


def fetch_sale_data(server_url, sale_id):
    url = f"{server_url.rstrip('/')}/sale/sale_ticket_json/{sale_id}"
    resp = requests.get(url, timeout=10, verify=False)
    resp.raise_for_status()
    return resp.json()


def format_ticket(sale_data, store_name):
    s = sale_data
    store = clean_text(store_name)
    w = 32
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
    lines.append(f"{'Producto':13s} {'Cant':4s}{'Precio':7s}{'Total':6s}")
    lines.append("-" * w)
    for item in s['items']:
        name = title_case(item['name'])[:13].ljust(13)
        qty = f"{item['quantity']:.0f}".rjust(4)
        price = f"${item['price']:.0f}".rjust(7)
        total = f"${item['item_total']:.0f}".rjust(6)
        lines.append(f"{name} {qty}{price}{total}")
    lines.append("-" * w)
    total_str = f"${s['total']:.0f}"
    lines.append(f"{'TOTAL:':20s}  {total_str:>6s}")
    lines.append("")
    lines.append("Gracias por su compra!".center(w))
    lines.append("")
    return "\n".join(lines)


def print_ticket_text(text, printer_name):
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
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return True


class TicketPrinterApp:
    W = 32  # 55mm paper width
    def __init__(self, root):
        self.root = root
        self.root.title("Ticket Printer")
        self.root.geometry("520x650")
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
        self.preview_text = tk.Text(text_frame, font=("Courier", 7), wrap=tk.NONE, height=20)
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

        server_url = self.server_url_var.get().strip()
        try:
            self.fetch_btn.config(text="Fetching...", state=tk.DISABLED)
            self.root.update()
            self.sale_data = fetch_sale_data(server_url, sale_id)
            self.build_ticket_text()
            self.print_btn.config(state=tk.NORMAL)
            self.fetch_btn.config(text="Fetch & Preview", state=tk.NORMAL)
        except requests.ConnectionError:
            messagebox.showerror("Connection Error", f"Cannot reach server:\n{server_url}")
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
        store = self.store_name_var.get().strip() or DEFAULT_CONFIG["store_name"]
        self.ticket_text = format_ticket(self.sale_data, store)
        self.preview_text.delete(1.0, tk.END)
        self.preview_text.insert(1.0, self.ticket_text)

    def print_ticket(self):
        if not self.ticket_text:
            return
        try:
            self.print_btn.config(text="Printing...", state=tk.DISABLED)
            self.root.update()
            printer_name = self.config.get("cups_printer", DEFAULT_CONFIG["cups_printer"])
            print_ticket_text(self.ticket_text, printer_name)
            messagebox.showinfo("Success", "Ticket printed successfully!")
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


# ---------------------------------------------------------------------------
# Web server mode
# ---------------------------------------------------------------------------
web_app = Flask(__name__)
web_app.config.from_mapping(load_config())

WEB_HTML = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,user-scalable=no">
<title>Ticket Printer</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f0f0f0;color:#333;font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;justify-content:center;padding:16px;min-height:100dvh}
.container{width:100%;max-width:420px;display:flex;flex-direction:column;gap:14px}
.header{background:#fff;border-radius:10px;padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.1)}
.header h1{font-size:1.2rem;color:#444;font-weight:600}
.header p{font-size:.8rem;color:#888;margin-top:4px}
.card{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.1);display:flex;flex-direction:column;gap:12px}
label{font-size:.85rem;color:#666;font-weight:500}
input[type=number]{width:100%;padding:14px;font-size:1.2rem;border:1px solid #ccc;border-radius:8px;background:#fafafa;color:#333;outline:none;transition:border-color .2s}
input[type=number]:focus{border-color:#888;background:#fff}
.btn{width:100%;padding:14px;font-size:1.1rem;border:none;border-radius:8px;cursor:pointer;color:#fff;font-weight:600;transition:opacity .2s}
.btn-preview{background:#777}
.btn-preview:hover{opacity:.9}
.btn-print{background:#444}
.btn-print:hover{opacity:.9}
.btn:disabled{opacity:.4;cursor:not-allowed}
#preview{background:#fafafa;border:1px solid #ddd;border-radius:8px;padding:12px;font-family:monospace;font-size:11px;line-height:1.3;white-space:pre;overflow-x:auto;min-height:60px;color:#333;display:none}
.toast{position:fixed;top:20px;left:50%;transform:translateX(-50%);padding:12px 24px;border-radius:8px;color:#fff;font-weight:600;z-index:999;display:none;max-width:90%;box-shadow:0 2px 8px rgba(0,0,0,.15)}
.toast.ok{background:#555}
.toast.err{background:#999}
.footer{text-align:center;font-size:.75rem;color:#aaa;padding:4px 0}
</style>
</head>
<body>
<div class=container>
<div class=header>
<h1>Ticket Printer</h1>
<p>Ferreteria Leon</p>
</div>
<div class=card>
<label for=sale_id>Sale ID</label>
<input type=number id=sale_id placeholder="Ingrese ID de venta" inputmode=numeric>
<button class="btn btn-preview" id=previewBtn onclick=doPreview()>&#x1F50D; Vista Previa</button>
<div id=preview></div>
<button class="btn btn-print" id=printBtn onclick=doPrint() disabled>&#x1F5B6; Imprimir</button>
</div>
<div class=footer>Ticket Printer v2</div>
</div>
<div id=toast class=toast></div>
<script>
let currentId='';
function showToast(msg,type){const t=document.getElementById('toast');t.textContent=msg;t.className='toast '+type;t.style.display='block';setTimeout(()=>t.style.display='none',3000)}
async function doPreview(){
const id=document.getElementById('sale_id').value.trim();
if(!id)return showToast('Ingrese un Sale ID','err');
document.getElementById('previewBtn').disabled=true;
document.getElementById('previewBtn').textContent='Cargando...';
try{
const r=await fetch('/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sale_id:id})});
const d=await r.json();
if(d.error){showToast(d.error,'err');document.getElementById('preview').style.display='none';return}
document.getElementById('preview').textContent=d.ticket_text;
document.getElementById('preview').style.display='block';
currentId=id;
document.getElementById('printBtn').disabled=false;
showToast('Vista previa lista','ok')
}catch(e){showToast('Error de conexion','err')}
finally{document.getElementById('previewBtn').disabled=false;document.getElementById('previewBtn').innerHTML='&#x1F50D; Vista Previa'}
}
async function doPrint(){
if(!currentId)return showToast('Primero haga vista previa','err');
document.getElementById('printBtn').disabled=true;
document.getElementById('printBtn').textContent='Imprimiendo...';
try{
const r=await fetch('/print',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sale_id:currentId})});
const d=await r.json();
if(d.success){showToast('Ticket impreso exitosamente','ok')}else{showToast(d.error||'Error al imprimir','err')}
}catch(e){showToast('Error de conexion','err')}
finally{document.getElementById('printBtn').disabled=false;document.getElementById('printBtn').innerHTML='&#x1F5B6; Imprimir'}
}
</script>
</body>
</html>
"""


@web_app.route('/')
def index():
    return WEB_HTML


@web_app.route('/preview', methods=['POST'])
def preview():
    data = request.get_json(silent=True)
    if not data or 'sale_id' not in data:
        return jsonify(error="Sale ID requerido"), 400
    sale_id = str(data['sale_id']).strip()
    if not sale_id.isdigit():
        return jsonify(error="Sale ID debe ser un numero"), 400
    cfg = web_app.config
    try:
        sale_data = fetch_sale_data(cfg.get("server_url", DEFAULT_CONFIG["server_url"]), sale_id)
        ticket_text = format_ticket(sale_data, cfg.get("store_name", DEFAULT_CONFIG["store_name"]))
        return jsonify(ticket_text=ticket_text)
    except requests.ConnectionError:
        return jsonify(error="No se pudo conectar al servidor"), 502
    except requests.HTTPError as e:
        return jsonify(error=str(e)), 502
    except Exception as e:
        return jsonify(error=str(e)), 500


@web_app.route('/print', methods=['POST'])
def web_print():
    data = request.get_json(silent=True)
    if not data or 'sale_id' not in data:
        return jsonify(error="Sale ID requerido"), 400
    sale_id = str(data['sale_id']).strip()
    if not sale_id.isdigit():
        return jsonify(error="Sale ID debe ser un numero"), 400
    cfg = web_app.config
    try:
        sale_data = fetch_sale_data(cfg.get("server_url", DEFAULT_CONFIG["server_url"]), sale_id)
        ticket_text = format_ticket(sale_data, cfg.get("store_name", DEFAULT_CONFIG["store_name"]))
        printer_name = cfg.get("cups_printer", DEFAULT_CONFIG["cups_printer"])
        print_ticket_text(ticket_text, printer_name)
        return jsonify(success=True, message="Ticket impreso exitosamente")
    except requests.ConnectionError:
        return jsonify(error="No se pudo conectar al servidor"), 502
    except Exception as e:
        return jsonify(error=str(e)), 500


def start_web_server():
    print("Web server starting on http://0.0.0.0:5000")
    web_app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--web':
        start_web_server()
    else:
        root = tk.Tk()
        app = TicketPrinterApp(root)
        root.mainloop()

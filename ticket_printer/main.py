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
import os
import sys
import threading
import time
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from io import BytesIO
import evdev
from evdev import ecodes

from reportlab.graphics.barcode import code128
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch, mm
from reportlab.lib.pagesizes import letter, landscape


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
    "pos_barcode_url": "https://5.75.162.179/pos/scanner-push/",
}

TICKET_TYPES = {
    "sale": {"endpoint": "/sale/sale_ticket_json/", "label": "Venta"},
    "quote": {"endpoint": "/quote/quote_ticket_json/", "label": "Cotizacion"},
    "devolution": {"endpoint": "/devolution/devolution_ticket_json/", "label": "Devolucion"},
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


def fetch_ticket_data(server_url, doc_id, ticket_type="sale", session=None):
    ep = TICKET_TYPES.get(ticket_type, TICKET_TYPES["sale"])["endpoint"]
    url = f"{server_url.rstrip('/')}{ep}{doc_id}"
    http = session if session is not None else requests.Session()
    close = session is None
    try:
        resp = http.get(url, timeout=10, verify=False)
        resp.raise_for_status()
        return resp.json()
    finally:
        if close:
            http.close()


def format_ticket(sale_data, store_name, ticket_type="sale"):
    s = sale_data
    store = clean_text(store_name)
    label = TICKET_TYPES.get(ticket_type, TICKET_TYPES["sale"])["label"]
    w = 32
    lines = []
    lines.append("")
    lines.append(store.center(w))
    lines.append("")
    lines.append("-" * w)
    lines.append(f"{label}: #{s['sale_id']}")
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


# ---------------------------------------------------------------------------
# Barcode scanner listener (evdev)
# ---------------------------------------------------------------------------
KEY_MAP = {
    2: '1', 3: '2', 4: '3', 5: '4', 6: '5',
    7: '6', 8: '7', 9: '8', 10: '9', 11: '0',
    71: '7', 72: '8', 73: '9', 74: '-', 75: '4',
    76: '5', 77: '6', 78: '+', 79: '1', 80: '2',
    81: '3', 82: '0', 83: '.', 96: '\n', 98: '/',
    55: '*',
}


def _read_until_enter(device, timeout=0.5):
    """Read digits from an evdev device until Enter or timeout."""
    barcode = []
    latest = 0
    for event in device.read_loop():
        if event.type != ecodes.EV_KEY or event.value != 1:
            continue
        now = time.time()
        if latest and (now - latest) > timeout:
            barcode.clear()
        latest = now
        code = event.code
        if code == ecodes.KEY_ENTER or code == ecodes.KEY_KPENTER:
            raw = ''.join(barcode)
            if len(raw) >= 3:
                return raw
            barcode.clear()
            continue
        ch = KEY_MAP.get(code)
        if ch is not None:
            barcode.append(ch)


def _find_scanner(known_name=None):
    """Find a barcode scanner input device."""
    candidates = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except PermissionError:
            print("Permission denied reading {}".format(path), flush=True)
            print("Add user to 'input' group: sudo usermod -a -G input $USER", flush=True)
            continue
        except Exception as e:
            continue
        try:
            caps = dev.capabilities()
            if ecodes.EV_KEY not in caps:
                continue
            keys = caps[ecodes.EV_KEY]
            has_digits = any(c in keys for c in range(2, 12))
            has_enter = ecodes.KEY_ENTER in keys or ecodes.KEY_KPENTER in keys
            if not (has_digits and has_enter):
                continue
            name = (dev.name or '').lower()
            phys = (dev.phys or '').lower()
            if known_name and known_name in dev.name:
                candidates.append(dev)
                continue
            if 'scan' in name or 'usbscn' in name or 'barcode' in name:
                candidates.append(dev)
                continue
            if 'usb' in phys and 'keyboard' not in name and 'at' not in phys:
                candidates.append(dev)
                continue
            if ('usb' in name or 'hid' in name) and 'keyboard' not in name:
                candidates.append(dev)
                continue
        except Exception:
            pass
        finally:
            if dev not in candidates:
                dev.close()
    if candidates:
        print("Scanner candidates: {}".format([(c.path, c.name) for c in candidates]), flush=True)
        for c in candidates[1:]:
            c.close()
        return candidates[0]
    # fallback: try ALL keyboard devices, pick first non-AT
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            caps = dev.capabilities()
            if ecodes.EV_KEY in caps:
                keys = caps[ecodes.EV_KEY]
                if (any(c in keys for c in range(2, 11)) and
                        ecodes.KEY_ENTER in keys):
                    name = (dev.name or '').lower()
                    if 'keyboard' not in name:
                        return dev
            dev.close()
        except Exception:
            pass
    return None


class BarcodeScannerListener:
    """Read barcode scanner via evdev and POST to POS endpoint."""

    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.device = None

    def find_and_listen(self):
        device = _find_scanner()
        if device is None:
            print("No barcode scanner device found", flush=True)
            return
        self.device = device
        print("Scanner device: {} ({})".format(device.path, device.name), flush=True)
        try:
            while True:
                barcode = _read_until_enter(device)
                if barcode:
                    print("Scanned: {}".format(barcode), flush=True)
                    try:
                        resp = requests.post(
                            self.endpoint,
                            json={"barcode": barcode},
                            timeout=10,
                            verify=False,
                        )
                        print("POST {} -> {}".format(self.endpoint, resp.status_code), flush=True)
                    except Exception as e:
                        print("POST failed: {}".format(e), flush=True)
        except evdev.InputClosedError:
            print("Scanner device disconnected", flush=True)
        finally:
            device.close()

    def start(self):
        t = threading.Thread(target=self.find_and_listen, daemon=True)
        t.start()
        return t


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

        fetch_frame = ttk.LabelFrame(main, text="Fetch Document", padding=10)
        fetch_frame.pack(fill=tk.X, pady=6)

        ttk.Label(fetch_frame, text="Type:").grid(row=0, column=0, sticky=tk.W)
        self.ticket_type_var = tk.StringVar(value="sale")
        type_combo = ttk.Combobox(fetch_frame, textvariable=self.ticket_type_var,
                                  values=["sale", "quote", "devolution"], state="readonly", width=14)
        type_combo.grid(row=0, column=1, padx=(6, 0), sticky=tk.W)
        fetch_frame.columnconfigure(1, weight=1)

        ttk.Label(fetch_frame, text="ID:").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        self.sale_id_entry = ttk.Entry(fetch_frame, width=20)
        self.sale_id_entry.grid(row=1, column=1, padx=(6, 0), pady=(4, 0), sticky=tk.EW)

        btn_frame = ttk.Frame(fetch_frame)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=(8, 0))
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
        doc_id = self.sale_id_entry.get().strip()
        if not doc_id:
            messagebox.showwarning("Input required", "Enter an ID")
            return
        if not doc_id.isdigit():
            messagebox.showwarning("Invalid ID", "ID must be a number")
            return

        server_url = self.server_url_var.get().strip()
        ticket_type = self.ticket_type_var.get()
        try:
            self.fetch_btn.config(text="Fetching...", state=tk.DISABLED)
            self.root.update()
            self.sale_data = fetch_ticket_data(server_url, doc_id, ticket_type)
            self.ticket_type = ticket_type
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
        ticket_type = getattr(self, 'ticket_type', 'sale')
        self.ticket_text = format_ticket(self.sale_data, store, ticket_type)
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
# Barcode label generation
# ---------------------------------------------------------------------------
COLS = 14
ROWS = 16
LABELS_PER_SHEET = COLS * ROWS
MARGIN = 6 * mm          # top, left, right target margins
MARGIN_B = 4 * mm        # bottom digital margin (printer adds +2mm → 6mm physical)

SHEET_W = 279 * mm
SHEET_H = 215 * mm

LABEL_W = 19 * mm
LABEL_H = (SHEET_H - MARGIN - MARGIN_B) / ROWS  # 12.8125mm

OFFSET_X = 2 * mm   # shift right
OFFSET_Y = -2 * mm  # shift down (negative in PDF coords)

MARGIN_L = (SHEET_W - COLS * LABEL_W) / 2 + OFFSET_X  # ~8.5mm
MARGIN_T = MARGIN + OFFSET_Y  # 4mm

BARCODE_MAX_W = LABEL_W * 0.85


def get_barcode_drawing(data):
    return code128.Code128(str(data), barHeight=10 * mm,
                           barWidth=0.15 * mm, quiet=False,
                           humanReadable=False)


def draw_barcode(c, bc, x, y):
    w = bc.width
    h = bc.height
    scale = min(BARCODE_MAX_W / w if w > 0 else 1, 1.0)
    if scale < 1.0:
        c.saveState()
        c.translate(x + (LABEL_W - w * scale) / 2,
                    y + (LABEL_H - h * scale) / 2)
        c.scale(scale, scale)
        bc.drawOn(c, 0, 0)
        c.restoreState()
    else:
        bx = x + (LABEL_W - w) / 2
        by = y + (LABEL_H - h) / 2
        bc.drawOn(c, bx, by)


def generate_barcode_pdf(number, sheets, blank=False):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(SHEET_W, SHEET_H))
    for sheet in range(sheets):
        bc = get_barcode_drawing(number) if not blank else None
        for row in range(ROWS):
            for col in range(COLS):
                x = MARGIN_L + col * LABEL_W
                y = MARGIN_T + (ROWS - 1 - row) * LABEL_H
                if blank:
                    c.setStrokeColorRGB(0, 0, 0)
                    c.setLineWidth(0.5)
                    c.rect(x, y, LABEL_W, LABEL_H)
                else:
                    draw_barcode(c, bc, x, y)
        if sheet < sheets - 1:
            c.showPage()
    c.save()
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Web server mode
# ---------------------------------------------------------------------------
web_app = Flask(__name__)
web_app.config.from_mapping(load_config())

WEB_HTML_TICKET = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,user-scalable=no">
<title>Ferreteria Leon - Ticket</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f0f0f0;color:#333;font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;justify-content:center;padding:16px;min-height:100dvh}
.container{width:100%;max-width:420px;display:flex;flex-direction:column;gap:14px}
.header{background:#fff;border-radius:10px;padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.1)}
.header h1{font-size:1.2rem;color:#444;font-weight:600}
.nav{display:flex;justify-content:center;gap:20px;margin-top:8px}
.nav a{text-decoration:none;font-size:.85rem;font-weight:500;color:#999;padding:4px 0;transition:color .2s}
.nav a.active{color:#444;font-weight:700}
.nav a:hover{color:#666}
.card{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.1);display:flex;flex-direction:column;gap:12px}
label{font-size:.85rem;color:#666;font-weight:500}
input[type=number],input[type=text]{width:100%;padding:14px;font-size:1.2rem;border:1px solid #ccc;border-radius:8px;background:#fafafa;color:#333;outline:none;transition:border-color .2s}
input[type=number]:focus,input[type=text]:focus{border-color:#888;background:#fff}
input.small{width:100px;font-size:1rem;padding:10px 14px}
.hint{font-size:.75rem;color:#999;margin-top:2px}
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
<h1>Ferreteria Leon</h1>
<div class=nav>
 <a href=/ class=active>Ticket</a>
<a href=/barcode>Codigos de Barras</a>
<a href=/scan>Escaner</a>
</div>
</div>
<div class=card>
<label for=ticket_type>Tipo</label>
<select id=ticket_type style="width:100%;padding:14px;font-size:1.2rem;border:1px solid #ccc;border-radius:8px;background:#fafafa;color:#333;outline:none;appearance:auto">
<option value=sale>Venta</option>
<option value=quote>Cotizacion</option>
<option value=devolution>Devolucion</option>
</select>
<label for=sale_id style=margin-top:4px>ID</label>
<input type=number id=sale_id placeholder="Ingrese ID" inputmode=numeric>
<button class="btn btn-preview" id=previewBtn onclick=doPreview()>&#x1F50D; Vista Previa</button>
<div id=preview></div>
<button class="btn btn-print" id=printBtn onclick=doPrint() disabled>&#x1F5B6; Imprimir</button>
</div>
<div class=footer>v2</div>
</div>
<div id=toast class=toast></div>
<script>
let currentId='';
function showToast(msg,type){const t=document.getElementById('toast');t.textContent=msg;t.className='toast '+type;t.style.display='block';setTimeout(()=>t.style.display='none',3000)}
async function doPreview(){
const id=document.getElementById('sale_id').value.trim();
if(!id)return showToast('Ingrese un ID','err');
const tt=document.getElementById('ticket_type').value;
document.getElementById('previewBtn').disabled=true;
document.getElementById('previewBtn').textContent='Cargando...';
try{
const r=await fetch('/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sale_id:id,ticket_type:tt})});
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
const tt=document.getElementById('ticket_type').value;
document.getElementById('printBtn').disabled=true;
document.getElementById('printBtn').textContent='Imprimiendo...';
try{
const r=await fetch('/print',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sale_id:currentId,ticket_type:tt})});
const d=await r.json();
if(d.success){showToast('Ticket impreso exitosamente','ok')}else{showToast(d.error||'Error al imprimir','err')}
}catch(e){showToast('Error de conexion','err')}
finally{document.getElementById('printBtn').disabled=false;document.getElementById('printBtn').innerHTML='&#x1F5B6; Imprimir'}
}
</script>
</body>
</html>
"""

WEB_HTML_BARCODE = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,user-scalable=no">
<title>Ferreteria Leon - Codigos de Barras</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f0f0f0;color:#333;font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;justify-content:center;padding:16px;min-height:100dvh}
.container{width:100%;max-width:420px;display:flex;flex-direction:column;gap:14px}
.header{background:#fff;border-radius:10px;padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.1)}
.header h1{font-size:1.2rem;color:#444;font-weight:600}
.nav{display:flex;justify-content:center;gap:20px;margin-top:8px}
.nav a{text-decoration:none;font-size:.85rem;font-weight:500;color:#999;padding:4px 0;transition:color .2s}
.nav a.active{color:#444;font-weight:700}
.nav a:hover{color:#666}
.card{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.1);display:flex;flex-direction:column;gap:12px}
label{font-size:.85rem;color:#666;font-weight:500}
input[type=number],input[type=text]{width:100%;padding:14px;font-size:1.2rem;border:1px solid #ccc;border-radius:8px;background:#fafafa;color:#333;outline:none;transition:border-color .2s}
input[type=number]:focus,input[type=text]:focus{border-color:#888;background:#fff}
input.small{width:100px;font-size:1rem;padding:10px 14px}
.hint{font-size:.75rem;color:#999;margin-top:2px}
.toggle-row{display:flex;align-items:center;gap:10px;padding:4px 0}
.toggle-row input[type=checkbox]{width:20px;height:20px;accent-color:#2a7a4a;cursor:pointer}
.toggle-row label{cursor:pointer;user-select:none}
.btn{width:100%;padding:14px;font-size:1.1rem;border:none;border-radius:8px;cursor:pointer;color:#fff;font-weight:600;transition:opacity .2s}
.btn-barcode{background:#2a7a4a}
.btn-barcode:hover{opacity:.9}
.btn:disabled{opacity:.4;cursor:not-allowed}
.toast{position:fixed;top:20px;left:50%;transform:translateX(-50%);padding:12px 24px;border-radius:8px;color:#fff;font-weight:600;z-index:999;display:none;max-width:90%;box-shadow:0 2px 8px rgba(0,0,0,.15)}
.toast.ok{background:#555}
.toast.err{background:#999}
.footer{text-align:center;font-size:.75rem;color:#aaa;padding:4px 0}
</style>
</head>
<body>
<div class=container>
<div class=header>
<h1>Ferreteria Leon</h1>
<div class=nav>
 <a href=/>Ticket</a>
<a href=/barcode class=active>Codigos de Barras</a>
<a href=/scan>Escaner</a>
</div>
</div>
<div class=card>
<label for=bc_number>Numero del codigo de barras</label>
<input type=text id=bc_number placeholder="Ej: 123456" inputmode=numeric>
<div class=toggle-row>
<input type=checkbox id=bc_blank>
<label for=bc_blank>Hoja en blanco (solo bordes, test)</label>
</div>
<label for=bc_sheets style=margin-top:4px>Cantidad de hojas</label>
<div style=display:flex;align-items:center;gap:8px>
<input type=number class=small id=bc_sheets value=1 min=1>
<span class=hint>224 etiquetas / hoja</span>
</div>
<button class="btn btn-barcode" id=barcodeBtn onclick=downloadBarcode()>&#x1F4E5; Generar PDF</button>
</div>
<div class=footer>v2</div>
</div>
<div id=toast class=toast></div>
<script>
function showToast(msg,type){const t=document.getElementById('toast');t.textContent=msg;t.className='toast '+type;t.style.display='block';setTimeout(()=>t.style.display='none',3000)}
async function downloadBarcode(){
const blank=document.getElementById('bc_blank').checked;
let num='';
if(!blank){
num=document.getElementById('bc_number').value.trim();
if(!num)return showToast('Ingrese un numero','err');
if(!/^\d+$/.test(num))return showToast('Solo digitos permitidos','err');
}
const sheets=parseInt(document.getElementById('bc_sheets').value)||1;
if(sheets<1)return showToast('Hojas debe ser >= 1','err');
document.getElementById('barcodeBtn').disabled=true;
document.getElementById('barcodeBtn').textContent='Generando...';
try{
const r=await fetch('/barcode/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({number:num,sheets:sheets,blank:blank})});
if(!r.ok){const d=await r.json();showToast(d.error||'Error al generar','err');return}
const blob=await r.blob();
const url=URL.createObjectURL(blob);
const a=document.createElement('a');
a.href=url;
const fname=blank?'test_blanco_s16986.pdf':'codigo_'+num+'_s16986.pdf';
a.download=fname;
document.body.appendChild(a);
a.click();
document.body.removeChild(a);
URL.revokeObjectURL(url);
showToast('PDF generado exitosamente','ok')
}catch(e){showToast('Error de conexion','err')}
finally{document.getElementById('barcodeBtn').disabled=false;document.getElementById('barcodeBtn').innerHTML='&#x1F4E5; Generar PDF'}
}
</script>
</body>
</html>
"""


@web_app.route('/')
def index():
    return WEB_HTML_TICKET


@web_app.route('/barcode')
def barcode_page():
    return WEB_HTML_BARCODE


@web_app.route('/preview', methods=['POST'])
def preview():
    data = request.get_json(silent=True)
    if not data or 'sale_id' not in data:
        return jsonify(error="ID requerido"), 400
    doc_id = str(data['sale_id']).strip()
    if not doc_id.isdigit():
        return jsonify(error="ID debe ser un numero"), 400
    ticket_type = data.get('ticket_type', 'sale')
    if ticket_type not in TICKET_TYPES:
        return jsonify(error="Tipo de ticket invalido"), 400
    cfg = web_app.config
    try:
        ticket_data = fetch_ticket_data(cfg.get("server_url", DEFAULT_CONFIG["server_url"]), doc_id, ticket_type)
        ticket_text = format_ticket(ticket_data, cfg.get("store_name", DEFAULT_CONFIG["store_name"]), ticket_type)
        return jsonify(ticket_text=ticket_text)
    except requests.ConnectionError:
        return jsonify(error="No se pudo conectar al servidor"), 502
    except requests.HTTPError as e:
        return jsonify(error=str(e)), 502
    except Exception as e:
        return jsonify(error=str(e)), 500


@web_app.route('/print', methods=['GET', 'POST'])
def web_print():
    if request.method == 'GET':
        doc_id = request.args.get('sale_id', '').strip()
        ticket_type = request.args.get('ticket_type', 'sale')
    else:
        data = request.get_json(silent=True)
        if not data or 'sale_id' not in data:
            return jsonify(error="ID requerido"), 400
        doc_id = str(data['sale_id']).strip()
        ticket_type = data.get('ticket_type', 'sale')
    if not doc_id.isdigit():
        return jsonify(error="ID debe ser un numero"), 400
    if ticket_type not in TICKET_TYPES:
        return jsonify(error="Tipo de ticket invalido"), 400
    cfg = web_app.config
    try:
        ticket_data = fetch_ticket_data(cfg.get("server_url", DEFAULT_CONFIG["server_url"]), doc_id, ticket_type)
        ticket_text = format_ticket(ticket_data, cfg.get("store_name", DEFAULT_CONFIG["store_name"]), ticket_type)
        printer_name = cfg.get("cups_printer", DEFAULT_CONFIG["cups_printer"])
        print_ticket_text(ticket_text, printer_name)
        if request.method == 'GET':
            return f'''<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>Imprimiendo...</title></head>
<body style="font-family:sans-serif;text-align:center;padding-top:40px;background:#f5f5f5"
      onload="setTimeout(window.close, 2000)">
  <div style="background:#fff;border-radius:8px;padding:30px;margin:20px;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
    <h2 style="color:#28a745">✅ Imprimiendo</h2>
    <p style="color:#555;font-size:16px">Ticket #{doc_id} enviado a la impresora</p>
    <p style="color:#999;font-size:12px">Esta ventana se cerrar\u00e1 autom\u00e1ticamente</p>
  </div>
</body>
</html>'''
        return jsonify(success=True, message="Ticket impreso exitosamente")
    except requests.ConnectionError:
        if request.method == 'GET':
            return '''<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>Error</title></head>
<body style="font-family:sans-serif;text-align:center;padding-top:40px;background:#f5f5f5"
      onload="setTimeout(window.close, 3000)">
  <div style="background:#fff;border-radius:8px;padding:30px;margin:20px;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
    <h2 style="color:#dc3545">\u274c Error de conexi\u00f3n</h2>
    <p style="color:#555;font-size:16px">No se pudo conectar al servidor</p>
  </div>
</body>
</html>'''
        return jsonify(error="No se pudo conectar al servidor"), 502
    except Exception as e:
        if request.method == 'GET':
            return f'''<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>Error</title></head>
<body style="font-family:sans-serif;text-align:center;padding-top:40px;background:#f5f5f5"
      onload="setTimeout(window.close, 3000)">
  <div style="background:#fff;border-radius:8px;padding:30px;margin:20px;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
    <h2 style="color:#dc3545">\u274c Error</h2>
    <p style="color:#555;font-size:16px">{str(e)}</p>
  </div>
</body>
</html>'''
        return jsonify(error=str(e)), 500


@web_app.route('/api/barcode-scan', methods=['POST'])
def api_barcode_scan():
    data = request.get_json(silent=True)
    if not data or 'barcode' not in data:
        return jsonify(error="Barcode requerido"), 400
    code = str(data['barcode']).strip()
    if not code:
        return jsonify(error="Barcode vacio"), 400
    cfg = web_app.config
    url = cfg.get("pos_barcode_url", DEFAULT_CONFIG["pos_barcode_url"])
    try:
        resp = requests.post(url, json={"barcode": code}, timeout=10, verify=False)
        return jsonify(success=True, status=resp.status_code)
    except requests.ConnectionError:
        return jsonify(error="No se pudo conectar al POS"), 502
    except Exception as e:
        return jsonify(error=str(e)), 500


WEB_HTML_SCAN = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,user-scalable=no">
<title>Ferreteria Leon - Escaner</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f0f0f0;color:#333;font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;justify-content:center;padding:16px;min-height:100dvh}
.container{width:100%;max-width:420px;display:flex;flex-direction:column;gap:14px}
.header{background:#fff;border-radius:10px;padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.1)}
.header h1{font-size:1.2rem;color:#444;font-weight:600}
.nav{display:flex;justify-content:center;gap:20px;margin-top:8px}
.nav a{text-decoration:none;font-size:.85rem;font-weight:500;color:#999;padding:4px 0;transition:color .2s}
.nav a.active{color:#444;font-weight:700}
.card{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.1)}
input[type=text]{width:100%;padding:20px;font-size:2rem;border:2px solid #ccc;border-radius:8px;background:#fafafa;color:#333;outline:none;text-align:center;letter-spacing:4px;transition:border-color .2s}
input[type=text]:focus{border-color:#2a7a4a;background:#fff}
#feedback{margin-top:12px;padding:12px;border-radius:8px;text-align:center;font-weight:600;font-size:1rem;display:none}
#feedback.ok{background:#d4edda;color:#155724;display:block}
#feedback.err{background:#f8d7da;color:#721c24;display:block}
#feedback.info{background:#cce5ff;color:#004085;display:block}
.hint{text-align:center;color:#999;font-size:.8rem;margin-top:8px}
.footer{text-align:center;font-size:.75rem;color:#aaa;padding:4px 0}
</style>
</head>
<body>
<div class=container>
<div class=header>
<h1>Ferreteria Leon</h1>
<div class=nav>
<a href=/>Ticket</a>
<a href=/barcode>Codigos de Barras</a>
<a href=/scan class=active>Escaner</a>
</div>
</div>
<div class=card>
<label for=barcode_input>Codigo de Barras</label>
<input type=text id=barcode_input placeholder="Escanee o escriba..." inputmode=numeric autofocus>
<div id=feedback></div>
<p class=hint>Escanee el codigo de barras o escribalo manualmente</p>
</div>
<div class=footer>v2</div>
</div>
<script>
const input=document.getElementById('barcode_input');
const fb=document.getElementById('feedback');
let timer=null;
let buf='';
input.addEventListener('input',function(){buf=this.value.replace(/[^0-9]/g,'');this.value=buf;clearTimeout(timer);if(buf.length>=3){timer=setTimeout(()=>submitBarcode(buf),200)}});
input.addEventListener('keydown',function(e){if(e.key==='Enter'&&buf.length>=3){clearTimeout(timer);submitBarcode(buf)}});
async function submitBarcode(code){const v=code||buf;if(!v||v.length<3)return;input.disabled=true;fb.className='';fb.textContent='Enviando...';fb.style.display='block';fb.className='info';try{const r=await fetch('/api/barcode-scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({barcode:v})});const d=await r.json();if(d.error){fb.className='err';fb.textContent='Error: '+d.error}else{fb.className='ok';fb.textContent='Enviado: '+v}buf='';input.value=''}catch(e){fb.className='err';fb.textContent='Error de conexion'}input.disabled=false;setTimeout(()=>{fb.style.display='none'},3000);input.focus()}
</script>
</body>
</html>
"""


@web_app.route('/scan')
def scan_page():
    return WEB_HTML_SCAN


@web_app.route('/barcode/generate', methods=['POST'])
def barcode_generate():
    data = request.get_json(silent=True)
    if not data:
        return jsonify(error="Solicitud inválida"), 400
    blank = data.get('blank', False)
    number = str(data.get('number', '')).strip()
    if not blank:
        if not number:
            return jsonify(error="Número requerido"), 400
        if not number.isdigit():
            return jsonify(error="El número debe contener solo dígitos"), 400

    sheets = 1
    if 'sheets' in data:
        try:
            sheets = int(data['sheets'])
            if sheets < 1:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify(error="Hojas debe ser un número entero >= 1"), 400

    try:
        pdf_buf = generate_barcode_pdf(number, sheets, blank=blank)
        filename = f"codigo_{number}_s16986.pdf" if not blank else "test_blanco_s16986.pdf"
        return send_file(
            pdf_buf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify(error=str(e)), 500


def auto_print_worker():
    """Poll VPS for queued print jobs (no ID tracking, no .last_printed_id)."""
    print("Auto-print worker started")
    cfg = load_config()
    server_url = cfg.get("server_url", DEFAULT_CONFIG["server_url"]).rstrip('/')
    printer_name = cfg.get("cups_printer", DEFAULT_CONFIG["cups_printer"])
    store_name = cfg.get("store_name", DEFAULT_CONFIG["store_name"])
    poll_url = server_url + '/pos/get-pending-prints/'
    print("Polling URL: {}".format(poll_url))

    with requests.Session() as session:
        while True:
            try:
                resp = session.get(poll_url, timeout=15, verify=False)
                if resp.status_code == 200:
                    jobs = resp.json()
                    if jobs:
                        print("Found {} pending print job(s)".format(len(jobs)))
                    for job in jobs:
                        sid = job['sale_id']
                        jid = job['job_id']
                        print("Printing job {} (sale #{})...".format(jid, sid))
                        try:
                            ticket_type = job.get('ticket_type')
                            if not ticket_type:
                                parts = jid.split('_')
                                ticket_type = parts[1] if len(parts) >= 4 and parts[0] == 'print' else 'sale'
                            ticket_data = fetch_ticket_data(server_url, sid, ticket_type, session=session)
                            ticket_text = format_ticket(ticket_data, store_name, ticket_type)
                            print_ticket_text(ticket_text, printer_name)
                            session.post(server_url + '/pos/ack-print/{}/'.format(jid),
                                          timeout=10, verify=False)
                            print("Printed job {}".format(jid))
                        except Exception as e:
                            print("FAILED job {}: {}".format(jid, e))
                else:
                    print("Poll returned status {} for URL: {}".format(
                        resp.status_code, poll_url))
            except requests.ConnectionError as e:
                print("Poll: VPS unreachable - {} {}".format(type(e).__name__, e))
            except Exception as e:
                print("Poll error: {}: {}".format(type(e).__name__, e))
            time.sleep(5)


def start_web_server():
    cfg = load_config()
    print("Web server starting on http://0.0.0.0:5000")
    t1 = threading.Thread(target=auto_print_worker, daemon=True)
    t1.start()
    barcode_url = cfg.get("pos_barcode_url", DEFAULT_CONFIG["pos_barcode_url"])
    scanner = BarcodeScannerListener(barcode_url)
    scanner.start()
    web_app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--web':
        start_web_server()
    else:
        root = tk.Tk()
        app = TicketPrinterApp(root)
        root.mainloop()

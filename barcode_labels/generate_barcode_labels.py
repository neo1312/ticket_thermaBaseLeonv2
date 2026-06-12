#!/usr/bin/env python3
"""GUI app for generating Code128 barcode PDFs on Uline S-16986 labels."""

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from reportlab.graphics.barcode import code128
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

COLS = 14
ROWS = 16
LABELS_PER_SHEET = COLS * ROWS

LABEL_W = 19 * mm
LABEL_H = 13 * mm

SHEET_W = 279 * mm
SHEET_H = 215 * mm
MARGIN_L = 6 * mm
MARGIN_T = 6 * mm

BARCODE_MAX_W = LABEL_W * 0.85

DEFAULT_DIR = os.path.expanduser("~/Downloads/scripsbaseleonV2")


def get_barcode_drawing(data):
    bc = code128.Code128(str(data), barHeight=10 * mm,
                         barWidth=0.15 * mm, quiet=False,
                         humanReadable=False)
    return bc


def draw_barcode(c, bc, x, y):
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.5)
    c.rect(x, y, LABEL_W, LABEL_H)
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


def create_pdf(number, sheets, output_path, blank=False):
    c = canvas.Canvas(output_path, pagesize=(SHEET_W, SHEET_H))
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


class BarcodeLabelApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Generador de Códigos de Barras - S-16986")
        self.root.geometry("480x320")
        self.root.resizable(False, False)

        main = ttk.Frame(root, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="Código de Barras S-16986",
                  font=("Arial", 14, "bold")).pack(pady=(0, 4))
        ttk.Label(main, text="Uline 3/4\" x 1/2\" · 224 etiquetas/hoja",
                  font=("Arial", 9), foreground="gray").pack(pady=(0, 12))

        entry_frame = ttk.Frame(main)
        entry_frame.pack(fill=tk.X, pady=4)
        ttk.Label(entry_frame, text="Número:", width=12).pack(side=tk.LEFT)
        self.number_var = tk.StringVar()
        ttk.Entry(entry_frame, textvariable=self.number_var, width=30).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        self.blank_var = tk.BooleanVar()
        blank_cb = ttk.Checkbutton(main, text="Hoja en blanco (solo bordes, test)",
                                   variable=self.blank_var)
        blank_cb.pack(anchor=tk.W, pady=(2, 0))

        sheet_frame = ttk.Frame(main)
        sheet_frame.pack(fill=tk.X, pady=4)
        ttk.Label(sheet_frame, text="Hojas:", width=12).pack(side=tk.LEFT)
        self.sheets_var = tk.StringVar(value="1")
        ttk.Entry(sheet_frame, textvariable=self.sheets_var, width=10).pack(
            side=tk.LEFT, padx=(4, 0))
        ttk.Label(sheet_frame, text="(c/u = 224 etiquetas)",
                  foreground="gray").pack(side=tk.LEFT, padx=(6, 0))

        output_frame = ttk.Frame(main)
        output_frame.pack(fill=tk.X, pady=4)
        ttk.Label(output_frame, text="Guardar en:", width=12).pack(side=tk.LEFT)
        self.output_path_var = tk.StringVar(
            value=os.path.join(DEFAULT_DIR, "codigo_s16986.pdf"))
        ttk.Entry(output_frame, textvariable=self.output_path_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        ttk.Button(output_frame, text="...", width=3,
                   command=self.browse_output).pack(side=tk.LEFT, padx=(2, 0))

        ttk.Button(main, text="Generar PDF", command=self.generate).pack(
            pady=(16, 0))

        self.status_var = tk.StringVar()
        ttk.Label(main, textvariable=self.status_var,
                  foreground="green").pack(pady=(6, 0))

    def browse_output(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialdir=DEFAULT_DIR,
            initialfile=os.path.basename(self.output_path_var.get()))
        if path:
            self.output_path_var.set(path)

    def generate(self):
        blank = self.blank_var.get()
        number = self.number_var.get().strip()
        if not blank:
            if not number:
                messagebox.showwarning("Campo vacío", "Ingrese un número para el código de barras.")
                return
            if not number.isdigit():
                messagebox.showwarning("Número inválido", "Solo se permiten dígitos.")
                return

        sheets_str = self.sheets_var.get().strip()
        try:
            sheets = int(sheets_str) if sheets_str else 1
            if sheets < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Hojas inválidas", "Ingrese un número válido de hojas (>= 1).")
            return

        output_path = self.output_path_var.get().strip()
        if not output_path:
            output_path = os.path.join(DEFAULT_DIR, f"codigo_{number}_s16986.pdf")
            self.output_path_var.set(output_path)

        base, ext = os.path.splitext(output_path)
        if ext.lower() != ".pdf":
            output_path = base + ".pdf"

        try:
            label_text = "Blanco (test)" if blank else number
            create_pdf(number, sheets, output_path, blank=blank)
            self.status_var.set(f"✓ PDF generado: {os.path.basename(output_path)}")
            messagebox.showinfo(
                "Completado",
                f"PDF generado exitosamente.\n\n"
                f"{'Modo: Hoja en blanco' if blank else f'Número: {number}'}\n"
                f"Hojas: {sheets}\n"
                f"Etiquetas: {sheets * LABELS_PER_SHEET:,}\n"
                f"Archivo: {output_path}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el PDF:\n{e}")
            self.status_var.set("✗ Error al generar PDF")


if __name__ == "__main__":
    root = tk.Tk()
    app = BarcodeLabelApp(root)
    root.mainloop()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transaction_normalizer.py
==========================

Aplicación de escritorio (Tkinter) para normalizar transacciones financieras
provenientes de múltiples fuentes con nombres de campos y formatos distintos.

Flujo general:
    1. El usuario carga un archivo JSON.
    2. Se valida que el archivo exista, no esté vacío y sea un JSON bien
       estructurado (una lista de objetos).
    3. El usuario elige, mediante una ventana con checklist, qué campos del
       modelo normalizado se van a usar/exigir (por defecto todos).
    4. Cada transacción se normaliza de acuerdo a los campos seleccionados.
       Si un campo seleccionado no puede resolverse o no es válido, la
       transacción se marca como inválida (con el motivo).
    5. Se muestran métricas (totales, válidas/inválidas, conteo por estado,
       totales por moneda) y se permite listar/filtrar/exportar tanto las
       transacciones válidas como las inválidas.

Autor: Proyecto educativo de Jorge.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from tkinter import (
    Tk, Toplevel, Frame, Label, Button, Checkbutton, BooleanVar, IntVar, StringVar,
    Spinbox, messagebox, filedialog, ttk, END, DISABLED, NORMAL, WORD, TclError
)
from tkinter.scrolledtext import ScrolledText
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Constantes y tablas de mapeo
# ---------------------------------------------------------------------------

# Nombre interno del campo -> etiqueta legible para la interfaz.
FIELD_LABELS: dict[str, str] = {
    "id": "ID",
    "amount": "Monto",
    "currency": "Moneda",
    "timestamp": "Fecha",
    "status": "Estado",
    "source": "Origen (Débito/Crédito/Transferencia)",
}

ALL_FIELDS: list[str] = list(FIELD_LABELS.keys())

# Posibles nombres de campo (alias) que puede traer cada fuente de datos
# para representar el mismo concepto.
FIELD_ALIASES: dict[str, list[str]] = {
    "id": ["id", "transaction_id", "ref", "tx_id", "reference", "reference_id"],
    "amount": ["amount", "total", "monto", "value", "importe"],
    "currency": ["currency", "currency_code", "moneda", "curr"],
    "timestamp": ["timestamp", "created_at", "date", "fecha", "datetime"],
    "status": ["status", "state", "result", "estado"],
    "source": ["source", "type", "method", "payment_type", "tx_type", "origen"],
}

# Símbolos de moneda reconocidos dentro del propio monto (p. ej. "€99,99").
CURRENCY_SYMBOLS: dict[str, str] = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
}

# Tabla de equivalencias para el campo "status" -> valor normalizado.
STATUS_MAP: dict[str, str] = {
    "completed": "SUCCESSFUL",
    "ok": "SUCCESSFUL",
    "success": "SUCCESSFUL",
    "successful": "SUCCESSFUL",
    "approved": "SUCCESSFUL",
    "paid": "SUCCESSFUL",
    "failed": "FAILED",
    "error": "FAILED",
    "declined": "FAILED",
    "denied": "FAILED",
    "rejected": "FAILED",
    "cancelled": "FAILED",
    "canceled": "FAILED",
    "pending": "PENDING",
    "processing": "PENDING",
    "in_progress": "PENDING",
    "waiting": "PENDING",
}

# Tabla de equivalencias para el campo "source" -> valor normalizado.
SOURCE_MAP: dict[str, str] = {
    "debit": "DEBIT",
    "débito": "DEBIT",
    "debito": "DEBIT",
    "credit": "CREDIT",
    "crédito": "CREDIT",
    "credito": "CREDIT",
    "transfer": "TRANSFER",
    "transferencia": "TRANSFER",
    "wire": "TRANSFER",
}

# Formatos de fecha soportados además del ISO-8601 estándar.
DATE_FORMATS: list[str] = [
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
]


# ---------------------------------------------------------------------------
# Funciones puras de normalización (sin dependencias de la interfaz)
# ---------------------------------------------------------------------------

def find_field_value(record: dict, aliases: list[str]) -> Any:
    """Busca en `record` el primer alias presente y con valor no vacío."""
    for key in aliases:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def normalize_id(raw: Any) -> tuple[Optional[str], Optional[str]]:
    """Convierte el identificador a string. Devuelve (valor, error)."""
    if raw is None:
        return None, "id ausente"
    text = str(raw).strip()
    if not text:
        return None, "id vacío"
    return text, None


def normalize_amount(
    raw: Any, max_integer_digits: int = 4
) -> tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Normaliza el monto de una transacción.

    Reglas aplicadas:
        - Máximo `max_integer_digits` cifras enteras (4 por defecto) y 2
          decimales, sin separador de miles.
        - Si es un número entero, se le agrega ".00" como parte decimal.
        - Si hay una coma seguida de exactamente 2 dígitos al final, se
          interpreta como separador decimal y se convierte a punto.
        - Si el monto trae un símbolo de moneda (p. ej. "€", "$"), se extrae
          y se retorna como moneda inferida.

    Devuelve: (monto normalizado, moneda inferida por símbolo, error)
    """
    if raw is None:
        return None, None, "monto ausente"

    inferred_currency: Optional[str] = None

    if isinstance(raw, bool):
        # bool es subtipo de int en Python; lo descartamos explícitamente.
        return None, None, "tipo de monto no soportado"

    if isinstance(raw, (int, float)):
        numeric_str = str(raw)
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None, None, "monto vacío"

        # Detectar y extraer símbolo de moneda si está presente.
        for symbol, code in CURRENCY_SYMBOLS.items():
            if symbol in text:
                inferred_currency = code
                text = text.replace(symbol, "").strip()
                break

        # ¿Hay una coma seguida de exactamente 2 dígitos al final?
        # Ej: "99,99" -> separador decimal. "1,234" -> no aplica (3 dígitos).
        if re.search(r",\d{2}$", text) and text.count(",") == 1:
            integer_part, decimal_part = text.rsplit(",", 1)
            integer_part = integer_part.replace(".", "").replace(" ", "")
            text = f"{integer_part}.{decimal_part}"
        else:
            # Cualquier otra coma se descarta (no se admiten separadores
            # de miles según las reglas del proyecto).
            text = text.replace(",", "").replace(" ", "")

        numeric_str = text
    else:
        return None, None, "tipo de monto no soportado"

    match = re.fullmatch(r"-?(\d+)(\.(\d+))?", numeric_str)
    if not match:
        return None, inferred_currency, "el monto no tiene un formato numérico válido"

    integer_digits = match.group(1)
    decimal_digits = match.group(3) or ""

    if len(integer_digits) > max_integer_digits:
        return (
            None,
            inferred_currency,
            f"el monto excede el máximo de {max_integer_digits} cifras enteras",
        )
    if len(decimal_digits) > 2:
        return None, inferred_currency, "el monto tiene más de 2 decimales"

    try:
        amount = round(float(numeric_str), 2)
    except ValueError:
        return None, inferred_currency, "el monto no pudo convertirse a número"

    return amount, inferred_currency, None


def normalize_currency(raw: Any, inferred_from_amount: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Determina la moneda final: prioriza un campo de moneda explícito;
    si no existe, usa la moneda inferida a partir del símbolo en el monto.
    """
    candidate: Optional[str] = None
    if raw not in (None, ""):
        candidate = str(raw).strip()
    elif inferred_from_amount:
        candidate = inferred_from_amount

    if not candidate:
        return None, "moneda no determinada"

    candidate = candidate.upper()
    if not re.fullmatch(r"[A-Z]{3}", candidate):
        return None, f"código de moneda inválido: '{candidate}'"

    return candidate, None


def normalize_timestamp(raw: Any) -> tuple[Optional[str], Optional[str]]:
    """Convierte distintos formatos de fecha a ISO-8601 (UTC, 'Z')."""
    if raw is None:
        return None, "fecha ausente"
    if not isinstance(raw, str):
        return None, "formato de fecha no soportado"

    text = raw.strip()
    if not text:
        return None, "fecha vacía"

    # Intento 1: ISO-8601 nativo (admite offsets; se normaliza la 'Z' final).
    iso_candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(iso_candidate)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), None
    except ValueError:
        pass

    # Intento 2: formatos alternativos conocidos.
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), None
        except ValueError:
            continue

    return None, f"formato de fecha no reconocido: '{raw}'"


def normalize_status(raw: Any) -> tuple[Optional[str], Optional[str]]:
    """Mapea el estado original a SUCCESSFUL | FAILED | PENDING."""
    if raw is None:
        return None, "estado ausente"
    key = str(raw).strip().lower()
    if key in STATUS_MAP:
        return STATUS_MAP[key], None
    return None, f"estado no reconocido: '{raw}'"


def normalize_source(raw: Any) -> tuple[Optional[str], Optional[str]]:
    """Mapea el origen a DEBIT | CREDIT | TRANSFER."""
    if raw is None:
        return None, "campo de origen no encontrado en la transacción"
    key = str(raw).strip().lower()
    if key in SOURCE_MAP:
        return SOURCE_MAP[key], None
    return None, f"origen no reconocido: '{raw}'"


def normalize_transaction(
    record: dict, selected_fields: set[str], max_integer_digits: int = 4
) -> tuple[dict, bool, list[str]]:
    """
    Normaliza una transacción de acuerdo a los campos seleccionados.

    Devuelve: (diccionario normalizado, es_valida, lista_de_motivos_de_error)

    Solo se incluyen en el resultado los campos seleccionados por el
    usuario; un campo no seleccionado nunca invalida la transacción ni
    aparece en la salida. `max_integer_digits` controla cuántas cifras
    enteras se admiten en el monto (configurable desde la interfaz).
    """
    reasons: list[str] = []
    output: dict[str, Any] = {}
    inferred_currency: Optional[str] = None

    # El monto se procesa primero porque puede traer implícita la moneda.
    if "amount" in selected_fields:
        raw_amount = find_field_value(record, FIELD_ALIASES["amount"])
        amount, inferred_currency, err = normalize_amount(raw_amount, max_integer_digits)
        if err:
            reasons.append(f"monto: {err}")
        else:
            output["amount"] = amount

    if "currency" in selected_fields:
        raw_currency = find_field_value(record, FIELD_ALIASES["currency"])
        currency, err = normalize_currency(raw_currency, inferred_currency)
        if err:
            reasons.append(f"moneda: {err}")
        else:
            output["currency"] = currency

    if "id" in selected_fields:
        raw_id = find_field_value(record, FIELD_ALIASES["id"])
        value, err = normalize_id(raw_id)
        if err:
            reasons.append(f"id: {err}")
        else:
            output["id"] = value

    if "timestamp" in selected_fields:
        raw_ts = find_field_value(record, FIELD_ALIASES["timestamp"])
        value, err = normalize_timestamp(raw_ts)
        if err:
            reasons.append(f"fecha: {err}")
        else:
            output["timestamp"] = value

    if "status" in selected_fields:
        raw_status = find_field_value(record, FIELD_ALIASES["status"])
        value, err = normalize_status(raw_status)
        if err:
            reasons.append(f"estado: {err}")
        else:
            output["status"] = value

    if "source" in selected_fields:
        raw_source = find_field_value(record, FIELD_ALIASES["source"])
        value, err = normalize_source(raw_source)
        if err:
            reasons.append(f"origen: {err}")
        else:
            output["source"] = value

    is_valid = len(reasons) == 0
    return output, is_valid, reasons


# ---------------------------------------------------------------------------
# Utilidades de logging hacia un widget de texto
# ---------------------------------------------------------------------------

class TextHandler(logging.Handler):
    """Handler de logging que escribe los mensajes en un widget ScrolledText."""

    def __init__(self, text_widget: ScrolledText):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)

        def append() -> None:
            self.text_widget.configure(state=NORMAL)
            self.text_widget.insert(END, msg + "\n")
            self.text_widget.see(END)
            self.text_widget.configure(state=DISABLED)

        # after(0, ...) evita problemas si el logging se dispara fuera
        # del hilo principal de Tkinter.
        self.text_widget.after(0, append)


# ---------------------------------------------------------------------------
# Ventana: selección de campos (checklist)
# ---------------------------------------------------------------------------

class FieldSelectionDialog(Toplevel):
    """Ventana modal para elegir qué campos se usarán en la normalización."""

    def __init__(self, parent: Tk):
        super().__init__(parent)
        self.title("Seleccionar campos a normalizar")
        self.resizable(False, False)
        self.result: Optional[set[str]] = None
        self.max_integer_digits: int = 4
        self.vars: dict[str, BooleanVar] = {}

        Label(
            self,
            text=(
                "Selecciona los campos que se usarán para normalizar y\n"
                "validar las transacciones. Por defecto están todos activos."
            ),
            justify="left",
            padx=15,
            pady=10,
        ).pack(anchor="w")

        fields_frame = Frame(self, padx=15)
        fields_frame.pack(fill="both", expand=True)

        self.max_digits_var = IntVar(value=4)

        for field, label in FIELD_LABELS.items():
            row = Frame(fields_frame)
            row.pack(fill="x", anchor="w", pady=2)

            var = BooleanVar(value=True)
            Checkbutton(row, text=label, variable=var, anchor="w").pack(
                side="left", anchor="w"
            )
            self.vars[field] = var

            if field == "amount":
                Label(row, text="   Máx. cifras enteras:").pack(side="left")
                spin = Spinbox(
                    row,
                    from_=1,
                    to=9,
                    width=3,
                    textvariable=self.max_digits_var,
                    justify="center",
                )
                spin.pack(side="left", padx=4)
                self._amount_spin = spin

                def _toggle_spin(*_args, spin=spin, var=var) -> None:
                    spin.configure(state=NORMAL if var.get() else DISABLED)

                var.trace_add("write", _toggle_spin)

        btn_frame = Frame(self, pady=12)
        btn_frame.pack()
        Button(btn_frame, text="Confirmar", width=14, command=self._confirm).pack(
            side="left", padx=6
        )
        Button(btn_frame, text="Cancelar", width=14, command=self._cancel).pack(
            side="left", padx=6
        )

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.transient(parent)
        self.grab_set()

    def _confirm(self) -> None:
        selected = {field for field, var in self.vars.items() if var.get()}
        if not selected:
            messagebox.showwarning(
                "Selección vacía",
                "Debes seleccionar al menos un campo para continuar.",
                parent=self,
            )
            return

        try:
            max_digits = int(self.max_digits_var.get())
            if not (1 <= max_digits <= 9):
                raise ValueError
        except (ValueError, TclError):
            messagebox.showwarning(
                "Valor inválido",
                "El máximo de cifras enteras debe ser un número entre 1 y 9.",
                parent=self,
            )
            return

        self.max_integer_digits = max_digits
        self.result = selected
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


# ---------------------------------------------------------------------------
# Ventana: transacciones inválidas
# ---------------------------------------------------------------------------

class InvalidTransactionsWindow(Toplevel):
    """Muestra las transacciones inválidas y permite exportarlas a JSON."""

    def __init__(self, parent: Tk, invalid_transactions: list[dict]):
        super().__init__(parent)
        self.title(f"Transacciones inválidas ({len(invalid_transactions)})")
        self.geometry("800x400")
        self.invalid_transactions = invalid_transactions

        columns = ("index", "reasons", "original")
        tree = ttk.Treeview(self, columns=columns, show="headings")
        tree.heading("index", text="#")
        tree.heading("reasons", text="Motivo(s)")
        tree.heading("original", text="Datos originales")
        tree.column("index", width=50, anchor="center")
        tree.column("reasons", width=280, anchor="w")
        tree.column("original", width=430, anchor="w")

        vsb = ttk.Scrollbar(self, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        for item in invalid_transactions:
            tree.insert(
                "",
                END,
                values=(
                    item["index"],
                    "; ".join(item["reasons"]),
                    json.dumps(item["original"], ensure_ascii=False),
                ),
            )

        btn_frame = Frame(self)
        btn_frame.pack(side="bottom", fill="x", pady=8)
        Button(
            btn_frame, text="Exportar a JSON", command=self._export
        ).pack(side="right", padx=10)

    def _export(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Exportar transacciones inválidas",
            defaultextension=".json",
            filetypes=[("Archivo JSON", "*.json")],
        )
        if not path:
            return
        try:
            payload = [
                {
                    "index": item["index"],
                    "reasons": item["reasons"],
                    "original": item["original"],
                }
                for item in self.invalid_transactions
            ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            messagebox.showinfo(
                "Exportación exitosa",
                f"Se exportaron {len(payload)} transacciones inválidas a:\n{path}",
                parent=self,
            )
        except OSError as e:
            messagebox.showerror(
                "Error al exportar", f"No se pudo guardar el archivo:\n{e}", parent=self
            )


# ---------------------------------------------------------------------------
# Ventana: métricas
# ---------------------------------------------------------------------------

class MetricsWindow(Toplevel):
    """Muestra métricas generales y permite listar/filtrar transacciones válidas."""

    def __init__(self, parent: Tk, valid_transactions: list[dict], metrics: dict):
        super().__init__(parent)
        self.title("Métricas de procesamiento")
        self.geometry("850x550")
        self.valid_transactions = valid_transactions

        # --- Resumen general -------------------------------------------------
        summary_frame = Frame(self, padx=10, pady=10)
        summary_frame.pack(fill="x")

        summary_text = (
            f"Total procesadas: {metrics['total']}    |    "
            f"Válidas: {metrics['valid']}    |    "
            f"Inválidas: {metrics['invalid']}"
        )
        Label(summary_frame, text=summary_text, font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w"
        )

        # --- Conteo por estado y totales por moneda --------------------------
        tables_frame = Frame(self, padx=10)
        tables_frame.pack(fill="x", pady=8)

        status_frame = Frame(tables_frame)
        status_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
        Label(status_frame, text="Conteo por estado", font=("TkDefaultFont", 9, "bold")).pack(
            anchor="w"
        )
        status_tree = ttk.Treeview(
            status_frame, columns=("estado", "conteo"), show="headings", height=5
        )
        status_tree.heading("estado", text="Estado")
        status_tree.heading("conteo", text="Conteo")
        status_tree.pack(fill="x")
        for status, count in metrics["status_counts"].items():
            status_tree.insert("", END, values=(status, count))

        currency_frame = Frame(tables_frame)
        currency_frame.pack(side="left", fill="both", expand=True)
        Label(
            currency_frame, text="Totales por moneda", font=("TkDefaultFont", 9, "bold")
        ).pack(anchor="w")
        currency_tree = ttk.Treeview(
            currency_frame, columns=("moneda", "total"), show="headings", height=5
        )
        currency_tree.heading("moneda", text="Moneda")
        currency_tree.heading("total", text="Total")
        currency_tree.pack(fill="x")
        for currency, total in metrics["currency_totals"].items():
            currency_tree.insert("", END, values=(currency, f"{total:.2f}"))

        # --- Filtro sobre el listado de válidas -------------------------------
        filter_frame = Frame(self, padx=10, pady=6)
        filter_frame.pack(fill="x")
        Label(filter_frame, text="Filtrar por:").pack(side="left")

        self.filter_field_var = StringVar(value="Todos")
        field_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.filter_field_var,
            values=["Todos", "Estado", "Moneda"],
            state="readonly",
            width=12,
        )
        field_combo.pack(side="left", padx=6)
        field_combo.bind("<<ComboboxSelected>>", self._on_filter_field_change)

        self.filter_value_var = StringVar(value="")
        self.value_combo = ttk.Combobox(
            filter_frame, textvariable=self.filter_value_var, state="disabled", width=15
        )
        self.value_combo.pack(side="left", padx=6)

        Button(filter_frame, text="Aplicar filtro", command=self._apply_filter).pack(
            side="left", padx=6
        )
        Button(filter_frame, text="Mostrar todos", command=self._reset_filter).pack(
            side="left", padx=6
        )

        # --- Tabla principal de transacciones válidas -------------------------
        self.columns = [f for f in ALL_FIELDS if any(f in t for t in valid_transactions)]
        if not self.columns:
            self.columns = ALL_FIELDS

        list_frame = Frame(self, padx=10, pady=6)
        list_frame.pack(fill="both", expand=True)
        self.main_tree = ttk.Treeview(
            list_frame, columns=self.columns, show="headings"
        )
        for col in self.columns:
            self.main_tree.heading(col, text=FIELD_LABELS.get(col, col))
            self.main_tree.column(col, width=120, anchor="w")
        vsb2 = ttk.Scrollbar(list_frame, orient="vertical", command=self.main_tree.yview)
        self.main_tree.configure(yscrollcommand=vsb2.set)
        self.main_tree.pack(side="left", fill="both", expand=True)
        vsb2.pack(side="right", fill="y")

        self._populate_tree(self.valid_transactions)

    def _populate_tree(self, transactions: list[dict]) -> None:
        self.main_tree.delete(*self.main_tree.get_children())
        for t in transactions:
            row = tuple(str(t.get(col, "")) for col in self.columns)
            self.main_tree.insert("", END, values=row)

    def _on_filter_field_change(self, _event=None) -> None:
        field_choice = self.filter_field_var.get()
        if field_choice == "Estado":
            values = sorted({t["status"] for t in self.valid_transactions if "status" in t})
            self.value_combo.configure(values=values, state="readonly")
        elif field_choice == "Moneda":
            values = sorted({t["currency"] for t in self.valid_transactions if "currency" in t})
            self.value_combo.configure(values=values, state="readonly")
        else:
            self.value_combo.configure(values=[], state="disabled")
        self.filter_value_var.set("")

    def _apply_filter(self) -> None:
        field_choice = self.filter_field_var.get()
        value = self.filter_value_var.get()

        if field_choice == "Todos" or not value:
            self._populate_tree(self.valid_transactions)
            return

        key = "status" if field_choice == "Estado" else "currency"
        filtered = [t for t in self.valid_transactions if t.get(key) == value]
        self._populate_tree(filtered)

    def _reset_filter(self) -> None:
        self.filter_field_var.set("Todos")
        self.value_combo.configure(values=[], state="disabled")
        self.filter_value_var.set("")
        self._populate_tree(self.valid_transactions)


# ---------------------------------------------------------------------------
# Aplicación principal
# ---------------------------------------------------------------------------

class TransactionNormalizerApp:
    """Ventana principal: carga de archivo, resumen y acceso a resultados."""

    def __init__(self, root: Tk):
        self.root = root
        self.root.title("Normalizador de Transacciones")
        self.root.geometry("720x520")
        self.root.minsize(640, 460)

        self.raw_data: Optional[list[dict]] = None
        self.selected_fields: set[str] = set(ALL_FIELDS)
        self.max_integer_digits: int = 4
        self.valid_transactions: list[dict] = []
        self.invalid_transactions: list[dict] = []
        self.metrics: dict = {}

        self._build_widgets()
        self._setup_logging()

    # -- Construcción de la interfaz ---------------------------------------
    def _build_widgets(self) -> None:
        top_frame = Frame(self.root, padx=12, pady=12)
        top_frame.pack(fill="x")

        Button(
            top_frame, text="Cargar archivo JSON", command=self.select_file, width=22
        ).pack(side="left")

        self.file_label = Label(top_frame, text="Ningún archivo cargado.", anchor="w")
        self.file_label.pack(side="left", padx=12, fill="x", expand=True)

        summary_frame = Frame(self.root, padx=12)
        summary_frame.pack(fill="x")
        self.summary_label = Label(
            summary_frame, text="", font=("TkDefaultFont", 10, "bold"), anchor="w"
        )
        self.summary_label.pack(fill="x")

        log_frame = Frame(self.root, padx=12, pady=8)
        log_frame.pack(fill="both", expand=True)
        Label(log_frame, text="Registro de actividad:").pack(anchor="w")
        self.log_text = ScrolledText(log_frame, height=14, state=DISABLED, wrap=WORD)
        self.log_text.pack(fill="both", expand=True)

        actions_frame = Frame(self.root, padx=12, pady=10)
        actions_frame.pack(fill="x")

        self.btn_metrics = Button(
            actions_frame,
            text="Ver métricas",
            command=self.show_metrics_window,
            state=DISABLED,
            width=16,
        )
        self.btn_metrics.pack(side="left", padx=4)

        self.btn_invalid = Button(
            actions_frame,
            text="Ver inválidas",
            command=self.show_invalid_window,
            state=DISABLED,
            width=16,
        )
        self.btn_invalid.pack(side="left", padx=4)

        self.btn_export_valid = Button(
            actions_frame,
            text="Exportar válidas",
            command=self.export_valid,
            state=DISABLED,
            width=16,
        )
        self.btn_export_valid.pack(side="left", padx=4)

    def _setup_logging(self) -> None:
        self.logger = logging.getLogger("transaction_normalizer")
        self.logger.setLevel(logging.INFO)
        handler = TextHandler(self.log_text)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%H:%M:%S"))
        self.logger.addHandler(handler)

    # -- Carga y validación de archivo -------------------------------------
    def select_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Seleccionar archivo de transacciones",
            filetypes=[("Archivos JSON", "*.json"), ("Todos los archivos", "*.*")],
        )
        if not path:
            return

        try:
            data = self._load_json_file(path)
        except ValueError as e:
            messagebox.showerror("Error al cargar archivo", str(e))
            self.logger.warning(f"No se pudo cargar el archivo '{path}': {e}")
            return

        self.raw_data = data
        self.file_label.config(text=f"Archivo: {os.path.basename(path)}  ({len(data)} registros)")
        self.logger.info(f"Archivo cargado correctamente: {path} ({len(data)} transacciones).")

        self._open_field_selection()

    def _load_json_file(self, path: str) -> list[dict]:
        """Lee y valida el archivo JSON a nivel básico. Lanza ValueError con
        mensajes amigables ante cualquier problema."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            raise ValueError(f"No se pudo abrir el archivo:\n{e}") from e

        if not content.strip():
            raise ValueError("El archivo está vacío.")

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"El archivo no contiene un JSON válido.\nDetalle: {e}"
            ) from e

        if not isinstance(data, list):
            raise ValueError(
                "El JSON debe contener una lista de transacciones (formato [ {...}, {...} ])."
            )

        if len(data) == 0:
            raise ValueError("El archivo no contiene ninguna transacción.")

        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(
                    f"El elemento en la posición {i} no es un objeto JSON válido."
                )

        return data

    # -- Selección de campos y procesamiento -------------------------------
    def _open_field_selection(self) -> None:
        dialog = FieldSelectionDialog(self.root)
        self.root.wait_window(dialog)
        if dialog.result is None:
            self.logger.info("Selección de campos cancelada por el usuario.")
            return
        self.selected_fields = dialog.result
        self.max_integer_digits = dialog.max_integer_digits
        self.logger.info(
            "Campos seleccionados: " + ", ".join(FIELD_LABELS[f] for f in self.selected_fields)
        )
        if "amount" in self.selected_fields:
            self.logger.info(
                f"Máximo de cifras enteras configurado para el monto: {self.max_integer_digits}"
            )
        self._process_transactions()

    def _process_transactions(self) -> None:
        if not self.raw_data:
            return

        self.valid_transactions = []
        self.invalid_transactions = []

        try:
            for idx, record in enumerate(self.raw_data):
                try:
                    normalized, is_valid, reasons = normalize_transaction(
                        record, self.selected_fields, self.max_integer_digits
                    )
                except Exception as e:  # Protección ante datos inesperados.
                    is_valid = False
                    reasons = [f"error inesperado al procesar: {e}"]
                    normalized = {}

                if is_valid:
                    self.valid_transactions.append(normalized)
                else:
                    self.invalid_transactions.append(
                        {"index": idx, "original": record, "reasons": reasons}
                    )
        except Exception as e:
            messagebox.showerror(
                "Error de procesamiento", f"Ocurrió un error inesperado:\n{e}"
            )
            self.logger.error(f"Error inesperado durante el procesamiento: {e}")
            return

        self.metrics = self._compute_metrics()
        self._update_summary()

        self.logger.info(
            f"Procesamiento completo: {len(self.valid_transactions)} válidas, "
            f"{len(self.invalid_transactions)} inválidas de {len(self.raw_data)} totales."
        )

        self.btn_metrics.config(state=NORMAL)
        self.btn_invalid.config(state=NORMAL if self.invalid_transactions else DISABLED)
        self.btn_export_valid.config(state=NORMAL if self.valid_transactions else DISABLED)

    def _compute_metrics(self) -> dict:
        total = len(self.raw_data or [])
        valid_count = len(self.valid_transactions)
        invalid_count = len(self.invalid_transactions)

        status_counts = Counter(
            t["status"] for t in self.valid_transactions if "status" in t
        )

        currency_totals: dict[str, float] = defaultdict(float)
        for t in self.valid_transactions:
            if "currency" in t and "amount" in t:
                currency_totals[t["currency"]] += t["amount"]
        currency_totals = {k: round(v, 2) for k, v in currency_totals.items()}

        return {
            "total": total,
            "valid": valid_count,
            "invalid": invalid_count,
            "status_counts": dict(status_counts),
            "currency_totals": currency_totals,
        }

    def _update_summary(self) -> None:
        m = self.metrics
        self.summary_label.config(
            text=(
                f"Total: {m['total']}   |   Válidas: {m['valid']}   |   "
                f"Inválidas: {m['invalid']}"
            )
        )

    # -- Ventanas secundarias y exportación --------------------------------
    def show_metrics_window(self) -> None:
        MetricsWindow(self.root, self.valid_transactions, self.metrics)

    def show_invalid_window(self) -> None:
        InvalidTransactionsWindow(self.root, self.invalid_transactions)

    def export_valid(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Exportar transacciones válidas",
            defaultextension=".json",
            filetypes=[("Archivo JSON", "*.json")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.valid_transactions, f, indent=2, ensure_ascii=False)
            messagebox.showinfo(
                "Exportación exitosa",
                f"Se exportaron {len(self.valid_transactions)} transacciones válidas a:\n{path}",
            )
            self.logger.info(f"Transacciones válidas exportadas a: {path}")
        except OSError as e:
            messagebox.showerror(
                "Error al exportar", f"No se pudo guardar el archivo:\n{e}"
            )
            self.logger.error(f"Error exportando válidas: {e}")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def main() -> None:
    root = Tk()
    TransactionNormalizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()


"""Interfaz gráfica (Tkinter). Las operaciones se ejecutan en un hilo de trabajo."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from . import system
from .controller import Controller
from .operations import OperationResult, Operations
from .presentation import describe
from .state import UwfQuery, UwfStatus

COLORS = {"ok": "#1b7a3a", "warn": "#a35c00", "bad": "#b00020", "unknown": "#555555"}


class App(tk.Tk):
    def __init__(self, ops: Operations, query: UwfQuery) -> None:
        super().__init__()
        self.ops, self.query = ops, query
        self.controller = Controller(lambda fn: self.after(0, fn))
        self.title("UWF Manager")
        self.resizable(False, False)
        self._build()
        self.refresh()

    def _build(self) -> None:
        pad = {"padx": 14}
        ttk.Label(self, text="UWF Manager", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(12, 0), **pad)
        ttk.Label(self, text="Windows Write Filter Control").pack(anchor="w", **pad)
        ttk.Separator(self).pack(fill="x", pady=8, padx=14)

        self.labels: dict[str, tk.Label] = {}
        for key in ("system", "feature", "filter", "volume", "overlay", "reboot"):
            lab = tk.Label(self, text="…", anchor="w", justify="left", font=("Segoe UI", 10), wraplength=470)
            lab.pack(fill="x", **pad)
            self.labels[key] = lab

        self.btn_enable = ttk.Button(self, text="Activar congelación y protección",
                                     command=self.on_enable)
        self.btn_enable.pack(fill="x", pady=(12, 4), **pad)
        self.btn_disable = ttk.Button(self, text="Desactivar congelación", command=self.on_disable)
        self.btn_disable.pack(fill="x", pady=4, **pad)
        self.btn_refresh = ttk.Button(self, text="Actualizar estado", command=self.refresh)
        self.btn_refresh.pack(fill="x", pady=4, **pad)

        self.messages = tk.Text(self, height=9, width=64, wrap="word", state="disabled",
                                font=("Consolas", 9))
        self.messages.pack(fill="both", padx=14, pady=(8, 14))

    # ---- utilidades de interfaz ----
    def say(self, text: str) -> None:
        self.messages.configure(state="normal")
        self.messages.insert("end", text + "\n")
        self.messages.see("end")
        self.messages.configure(state="disabled")

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for b in (self.btn_enable, self.btn_disable, self.btn_refresh):
            b.configure(state=state)
        self.configure(cursor="watch" if busy else "")

    def show_status(self, st: UwfStatus) -> None:
        for key, (text, level) in describe(st).items():
            self.labels[key].configure(text=text, fg=COLORS[level])
        for err in st.errors:
            self.say(f"Aviso: {err}")

    def _start(self, task, on_result, message: str) -> None:
        self.set_busy(True)
        self.say(message)

        def done(result, error) -> None:
            self.set_busy(False)
            if error is not None:
                self.say(f"ERROR inesperado: {error}")
                messagebox.showerror("UWF Manager", f"Error inesperado:\n{error}")
            else:
                on_result(result)

        if not self.controller.run_async(task, done):
            self.set_busy(False)
            self.say("Ya hay una operación en curso.")

    # ---- acciones ----
    def refresh(self) -> None:
        self._start(self.query.read, self.show_status, "Consultando el estado real de UWF…")

    def _ensure_admin(self) -> bool:
        if system.is_admin():
            return True
        if messagebox.askyesno("Privilegios de administrador",
                               "Esta operación requiere privilegios de administrador.\n"
                               "¿Reiniciar la aplicación solicitando elevación (UAC)?"):
            res = system.relaunch_as_admin()
            self.say(res.message)
            if res.started:
                self.destroy()
            elif not res.cancelled:
                messagebox.showerror("UWF Manager", res.message)
        return False

    def _show_operation(self, res: OperationResult) -> None:
        for line in res.lines():
            self.say(line)
        if res.status:
            self.show_status(res.status)
        if res.reboot_required:
            messagebox.showwarning("Reinicio necesario",
                                   "Es necesario reiniciar Windows para aplicar los cambios.\n"
                                   "Reinícielo cuando lo desee; la aplicación no lo hará automáticamente.")
        elif not res.ok:
            messagebox.showerror("UWF Manager", res.summary)

    def on_enable(self) -> None:
        if not self._ensure_admin():
            return
        if not messagebox.askokcancel(
                "Activar congelación",
                "Al reiniciar, Windows descartará los cambios hechos durante la sesión en C:.\n"
                "Guarde sus archivos importantes antes de continuar.\n\n¿Continuar?"):
            return
        self._start(self.ops.enable_freeze, self._show_operation, "Activando congelación…")

    def on_disable(self) -> None:
        if not self._ensure_admin():
            return
        if not messagebox.askyesno(
                "Desactivar congelación",
                "Al desactivar UWF y reiniciar, los cambios que se realicen mientras el filtro "
                "esté deshabilitado podrán persistir en el sistema.\n\n"
                "La protección configurada de C: se conservará.\n\n¿Continuar?"):
            return
        self._start(self.ops.disable_freeze, self._show_operation, "Desactivando congelación…")

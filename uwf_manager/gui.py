"""Interfaz gráfica (Tkinter). Las operaciones se ejecutan en un hilo de trabajo."""
from __future__ import annotations

import os
import queue
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from . import __version__, system
from .compat import CompatReport, Level, evaluate
from .controller import Controller
from .logs import log_dir
from .operations import OperationResult, Operations
from .presentation import Item, describe, headline
from .state import UwfQuery, UwfStatus

ASSETS = Path(__file__).resolve().parent / "assets"

# Paleta
NAVY, NAVY_TEXT = "#0F2A5C", "#A9C4F5"
BG, CARD, BORDER = "#F3F5F9", "#FFFFFF", "#DCE2EB"
TEXT, MUTED = "#1F2937", "#6B7280"
PRIMARY, PRIMARY_DARK, DANGER, DANGER_BG = "#0B5CD5", "#0A4AAE", "#B42318", "#FDECEA"
LEVELS = {  # nivel -> (símbolo, color texto, color fondo)
    "ok": ("✔", "#157F3D", "#E7F6EC"),
    "warn": ("⚠", "#A15C00", "#FFF4E0"),
    "bad": ("✖", "#B42318", "#FDECEA"),
    "unknown": ("?", "#4B5563", "#EEF0F3"),
}
COMPAT_LEVEL = {Level.PASS: "ok", Level.WARN: "warn", Level.FAIL: "bad", Level.UNKNOWN: "unknown"}


def prepare_windows_process() -> None:
    """Nitidez en pantallas de alta resolución e icono propio en la barra de tareas."""
    if not system.is_windows():
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UWFManager.App")
    except Exception:
        pass


def _font_family() -> str:
    families = set(tkfont.families())
    for name in ("Segoe UI", "Segoe UI Variable Text", "DejaVu Sans", "Helvetica"):
        if name in families:
            return name
    return "TkDefaultFont"


class StatusIcon(tk.Canvas):
    """Icono de estado dibujado (no depende de que la fuente tenga ✔, ⚠ o ✖)."""

    def __init__(self, parent: tk.Misc, size: int, bg: str) -> None:
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        self.size = size

    def set(self, level: str) -> None:
        self.delete("all")
        n, color = self.size, LEVELS[level][1]
        w = max(2, n // 9)
        self.create_oval(1, 1, n - 1, n - 1, fill=color, outline=color)
        if level == "ok":
            self.create_line(n * .28, n * .52, n * .44, n * .68, n * .73, n * .34, fill="white",
                             width=w, capstyle="round", joinstyle="round")
        elif level == "bad":
            self.create_line(n * .33, n * .33, n * .67, n * .67, fill="white", width=w, capstyle="round")
            self.create_line(n * .67, n * .33, n * .33, n * .67, fill="white", width=w, capstyle="round")
        elif level == "warn":
            self.create_line(n / 2, n * .25, n / 2, n * .58, fill="white", width=w, capstyle="round")
            self.create_oval(n / 2 - w * .7, n * .70, n / 2 + w * .7, n * .70 + w * 1.4, fill="white", outline="white")
        else:
            self.create_text(n / 2, n / 2, text="?", fill="white", font=("Helvetica", -int(n * .62), "bold"))


class StatusCard(tk.Frame):
    """Tarjeta con título, símbolo, valor y una franja de color (el color nunca va solo)."""

    def __init__(self, parent: tk.Misc, caption: str, fonts: dict) -> None:
        super().__init__(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        self.accent = tk.Frame(self, width=4, bg=LEVELS["unknown"][1])
        self.accent.pack(side="left", fill="y")
        inner = tk.Frame(self, bg=CARD, padx=12, pady=10)
        inner.pack(side="left", fill="both", expand=True)
        self.caption = tk.Label(inner, text=caption.upper(), font=fonts["caption"], fg=MUTED,
                                bg=CARD, anchor="w")
        self.caption.pack(fill="x")
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(5, 0))
        self.icon = StatusIcon(row, 18, CARD)
        self.icon.pack(side="left", anchor="n", pady=1)
        self.value = tk.Label(row, text="Consultando…", font=fonts["value"], fg=TEXT, bg=CARD,
                              anchor="w", justify="left")
        self.value.pack(side="left", fill="x", expand=True, padx=(8, 0))
        row.bind("<Configure>", lambda e: self.value.configure(wraplength=max(e.width - 34, 80)))

    def set(self, item: Item) -> None:
        color = LEVELS[item.level][1]
        self.icon.set(item.level)
        self.value.configure(text=item.value, fg=color)
        self.accent.configure(bg=color)


class CompatDialog(tk.Toplevel):
    """Resultado de «Buscar compatibilidad»."""

    def __init__(self, app: "App", report: CompatReport) -> None:
        super().__init__(app)
        self.app, self.report = app, report
        f = app.fonts
        self.title("Compatibilidad del equipo · UWF Manager")
        self.configure(bg=BG)
        self.transient(app)
        app.apply_icon(self)

        verdict, level = report.verdict
        color, soft = LEVELS[level][1], LEVELS[level][2]
        banner = tk.Frame(self, bg=soft, padx=18, pady=14, highlightthickness=1, highlightbackground=color)
        banner.pack(fill="x", padx=16, pady=(16, 10))
        icon = StatusIcon(banner, 30, soft)
        icon.set(level)
        icon.pack(side="left", padx=(0, 12))
        tk.Label(banner, text=verdict, font=f["section"], fg=color, bg=soft, justify="left",
                 anchor="w", wraplength=560).pack(side="left", fill="x", expand=True)

        table = tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        table.pack(fill="both", expand=True, padx=16)
        table.columnconfigure(2, weight=1)
        for col, title in enumerate(("Resultado", "Comprobación", "Detalle")):
            tk.Label(table, text=title.upper(), font=f["caption"], fg=MUTED, bg=CARD, anchor="w",
                     padx=10, pady=8).grid(row=0, column=col, sticky="ew")
        for row, check in enumerate(report.checks, start=1):
            lv = COMPAT_LEVEL[check.level]
            _, c, bgc = LEVELS[lv]
            tk.Frame(table, height=1, bg=BORDER).grid(row=row * 2 - 1, column=0, columnspan=3, sticky="ew")
            r = row * 2
            tk.Label(table, text=f"  {check.level.value}  ", font=f["badge"], fg=c, bg=bgc,
                     ).grid(row=r, column=0, sticky="w", padx=10, pady=7)
            tk.Label(table, text=check.name, font=f["body_bold"], fg=TEXT, bg=CARD, anchor="w",
                     ).grid(row=r, column=1, sticky="w", padx=(0, 12))
            tk.Label(table, text=check.detail, font=f["body"], fg=TEXT, bg=CARD, anchor="w",
                     justify="left", wraplength=400).grid(row=r, column=2, sticky="ew", padx=(0, 10))

        tk.Label(self, text="Comprobación de solo lectura: no se ha modificado nada en el equipo.",
                 font=f["small"], fg=MUTED, bg=BG).pack(anchor="w", padx=16, pady=(8, 0))
        buttons = tk.Frame(self, bg=BG)
        buttons.pack(fill="x", padx=16, pady=14)
        ttk.Button(buttons, text="Cerrar", style="Primary.TButton", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Copiar informe", style="Secondary.TButton",
                   command=self.copy).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = app.winfo_rootx() + max((app.winfo_width() - self.winfo_reqwidth()) // 2, 0)
        y = app.winfo_rooty() + 40
        self.geometry(f"+{x}+{y}")
        self.minsize(self.winfo_reqwidth(), self.winfo_reqheight())
        self.focus_set()

    def copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.report.as_text())
        self.app.say("Informe de compatibilidad copiado al portapapeles.")


class App(tk.Tk):
    def __init__(self, ops: Operations, query: UwfQuery) -> None:
        super().__init__()
        self.ops, self.query = ops, query
        self._ui_queue: queue.Queue = queue.Queue()
        self.controller = Controller(self._ui_queue.put)  # el hilo de trabajo nunca toca Tk
        self.compat_dialog: CompatDialog | None = None
        self.last_status: UwfStatus | None = None

        self.title("UWF Manager")
        self.configure(bg=BG)
        self.minsize(780, 640)
        self.geometry("880x720")
        self._icons: list[tk.PhotoImage] = []
        self.apply_icon(self)
        self._init_style()
        self._build()
        self.bind("<F5>", lambda e: self.refresh())
        self._drain_id = self.after(50, self._drain_queue)
        self.refresh()

    # ---------- apariencia ----------
    def apply_icon(self, window: tk.Misc) -> None:
        try:
            if sys.platform == "win32":
                window.iconbitmap(default=str(ASSETS / "app.ico"))
            else:
                if not self._icons:
                    self._icons.append(tk.PhotoImage(file=str(ASSETS / "app_64.png")))
                window.iconphoto(True, self._icons[0])
        except (tk.TclError, AttributeError):
            pass  # el icono es decorativo

    def _init_style(self) -> None:
        fam = _font_family()
        self.fonts = {
            "title": (fam, 17, "bold"), "subtitle": (fam, 10), "caption": (fam, 8, "bold"),
            "value": (fam, 11, "bold"), "hero": (fam, 15, "bold"),
            "section": (fam, 11, "bold"), "body": (fam, 9), "body_bold": (fam, 9, "bold"),
            "badge": (fam, 8, "bold"), "small": (fam, 8), "button": (fam, 10, "bold"),
            "mono": ("Consolas" if sys.platform == "win32" else "DejaVu Sans Mono", 9),
        }
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", font=self.fonts["body"])
        common = dict(font=self.fonts["button"], padding=(16, 10), borderwidth=1, focusthickness=1)
        s.configure("Primary.TButton", background=PRIMARY, foreground="white", bordercolor=PRIMARY,
                    lightcolor=PRIMARY, darkcolor=PRIMARY, focuscolor="white", **common)
        s.map("Primary.TButton",
              background=[("disabled", "#9DB7E3"), ("pressed", PRIMARY_DARK), ("active", PRIMARY_DARK)],
              foreground=[("disabled", "#EEF3FB")],
              lightcolor=[("active", PRIMARY_DARK)], darkcolor=[("active", PRIMARY_DARK)])
        s.configure("Danger.TButton", background=CARD, foreground=DANGER, bordercolor=DANGER,
                    lightcolor=CARD, darkcolor=CARD, focuscolor=DANGER, **common)
        s.map("Danger.TButton", background=[("disabled", CARD), ("active", DANGER_BG)],
              foreground=[("disabled", "#E3A8A1")], bordercolor=[("disabled", "#E3A8A1")])
        s.configure("Secondary.TButton", background=CARD, foreground=TEXT, bordercolor=BORDER,
                    lightcolor=CARD, darkcolor=CARD, focuscolor=PRIMARY,
                    font=self.fonts["body_bold"], padding=(12, 7))
        s.map("Secondary.TButton", background=[("active", "#EAF1FD")],
              foreground=[("disabled", "#A0A7B4")])
        s.configure("Busy.Horizontal.TProgressbar", background=PRIMARY, troughcolor="#DCE2EB",
                    bordercolor="#DCE2EB", lightcolor=PRIMARY, darkcolor=PRIMARY)

    def _card(self, parent: tk.Misc, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        tk.Label(outer, text=title.upper(), font=self.fonts["caption"], fg=MUTED, bg=CARD,
                 anchor="w").pack(fill="x", padx=14, pady=(10, 0))
        body = tk.Frame(outer, bg=CARD)
        body.pack(fill="both", expand=True, padx=14, pady=(6, 12))
        outer.body = body  # type: ignore[attr-defined]
        return outer

    def _build(self) -> None:
        f = self.fonts
        # Cabecera
        header = tk.Frame(self, bg=NAVY, padx=20, pady=14)
        header.pack(fill="x")
        try:
            logo = tk.PhotoImage(file=str(ASSETS / "app_44.png"))
            self._icons.append(logo)
            tk.Label(header, image=logo, bg=NAVY).pack(side="left", padx=(0, 12))
        except tk.TclError:
            pass
        titles = tk.Frame(header, bg=NAVY)
        titles.pack(side="left")
        tk.Label(titles, text="UWF Manager", font=f["title"], fg="white", bg=NAVY).pack(anchor="w")
        tk.Label(titles, text="Windows Write Filter Control", font=f["subtitle"], fg=NAVY_TEXT,
                 bg=NAVY).pack(anchor="w")
        self.admin_badge = tk.Label(header, text="", font=f["badge"], padx=10, pady=4)
        self.admin_badge.pack(side="right")

        # Barra de estado (se empaqueta antes del cuerpo para que quede abajo)
        bar = tk.Frame(self, bg="#E5E9F0", padx=14, pady=5)
        bar.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=120,
                                        style="Busy.Horizontal.TProgressbar")
        self.status_text = tk.Label(bar, text="Listo", font=f["small"], fg=TEXT, bg="#E5E9F0")
        self.status_text.pack(side="left")
        tk.Label(bar, text=f"v{__version__}", font=f["small"], fg=MUTED, bg="#E5E9F0").pack(side="right")
        self.checked_text = tk.Label(bar, text="", font=f["small"], fg=MUTED, bg="#E5E9F0")
        self.checked_text.pack(side="right", padx=(0, 14))

        body = tk.Frame(self, bg=BG, padx=16, pady=14)
        body.pack(fill="both", expand=True)

        # Estado principal
        hero = tk.Frame(body, bg=CARD, highlightthickness=1, highlightbackground=BORDER, padx=18, pady=14)
        hero.pack(fill="x")
        self.hero_icon = StatusIcon(hero, 36, CARD)
        self.hero_icon.set("unknown")
        self.hero_icon.pack(side="left", padx=(0, 14))
        hero_text = tk.Frame(hero, bg=CARD)
        hero_text.pack(side="left", fill="x", expand=True)
        tk.Label(hero_text, text="ESTADO DEL EQUIPO", font=f["caption"], fg=MUTED, bg=CARD,
                 anchor="w").pack(fill="x")
        self.hero_value = tk.Label(hero_text, text="Consultando el estado real de UWF…", font=f["hero"],
                                   fg=TEXT, bg=CARD, anchor="w", justify="left")
        self.hero_value.pack(fill="x")
        hero_text.bind("<Configure>", lambda e: self.hero_value.configure(wraplength=max(e.width - 8, 100)))

        # Aviso de reinicio (solo visible si procede)
        self.banner = tk.Frame(body, highlightthickness=1, padx=12, pady=8)
        self.banner_icon = StatusIcon(self.banner, 20, CARD)
        self.banner_icon.pack(side="left", padx=(0, 10))
        self.banner_text = tk.Label(self.banner, text="", font=f["body_bold"], anchor="w", justify="left")
        self.banner_text.pack(side="left", fill="x", expand=True)
        self.banner.bind("<Configure>", lambda e: self.banner_text.configure(wraplength=max(e.width - 60, 100)))
        self._banner_anchor = tk.Frame(body, bg=BG, height=10)
        self._banner_anchor.pack(fill="x")

        # Tarjetas de estado
        grid = tk.Frame(body, bg=BG)
        grid.pack(fill="x")
        self.cards: dict[str, StatusCard] = {}
        layout = [("filter", "Filtro UWF"), ("volume", "Protección de C:"), ("feature", "Característica UWF"),
                  ("overlay", "Superposición"), ("reboot", "Reinicio"), ("compat", "Compatibilidad")]
        for i, (key, caption) in enumerate(layout):
            card = StatusCard(grid, caption, f)
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=(0 if i % 3 == 0 else 10, 0),
                      pady=(0, 10))
            self.cards[key] = card
        for c in range(3):
            grid.columnconfigure(c, weight=1, uniform="cards")
        self.cards["compat"].set(Item("Compatibilidad", "Sin comprobar · pulse «Buscar compatibilidad»",
                                      "unknown"))

        # Acciones
        actions = self._card(body, "Acciones")
        actions.pack(fill="x")
        row = tk.Frame(actions.body, bg=CARD)  # type: ignore[attr-defined]
        row.pack(fill="x")
        row.columnconfigure((0, 1), weight=1, uniform="main")
        self.btn_enable = ttk.Button(row, text="Activar congelación y protección",
                                     style="Primary.TButton", command=self.on_enable)
        self.btn_enable.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.btn_disable = ttk.Button(row, text="Desactivar congelación", style="Danger.TButton",
                                      command=self.on_disable)
        self.btn_disable.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        row2 = tk.Frame(actions.body, bg=CARD)  # type: ignore[attr-defined]
        row2.pack(fill="x", pady=(10, 0))
        self.btn_compat = ttk.Button(row2, text="Buscar compatibilidad", style="Secondary.TButton",
                                     command=self.on_compat)
        self.btn_compat.pack(side="left")
        self.btn_refresh = ttk.Button(row2, text="Actualizar estado  (F5)", style="Secondary.TButton",
                                      command=self.refresh)
        self.btn_refresh.pack(side="left", padx=8)
        self.btn_logs = ttk.Button(row2, text="Abrir carpeta de registros", style="Secondary.TButton",
                                   command=self.open_logs)
        self.btn_logs.pack(side="right")

        # Actividad
        activity = self._card(body, "Actividad")
        activity.pack(fill="both", expand=True, pady=(10, 0))
        holder = tk.Frame(activity.body, bg=CARD)  # type: ignore[attr-defined]
        holder.pack(fill="both", expand=True)
        self.messages = tk.Text(holder, height=6, wrap="word", state="disabled", font=f["mono"],
                                relief="flat", bg="#FAFBFD", fg=TEXT, padx=8, pady=6,
                                highlightthickness=1, highlightbackground=BORDER)
        scroll = ttk.Scrollbar(holder, command=self.messages.yview)
        self.messages.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.messages.pack(side="left", fill="both", expand=True)
        for tag, color in (("time", MUTED), ("ok", LEVELS["ok"][1]), ("warn", LEVELS["warn"][1]),
                           ("error", LEVELS["bad"][1]), ("muted", MUTED), ("info", TEXT)):
            self.messages.tag_configure(tag, foreground=color)

        self._busy_buttons = (self.btn_enable, self.btn_disable, self.btn_compat, self.btn_refresh)

    # ---------- utilidades ----------
    def _drain_queue(self) -> None:
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        self._drain_id = self.after(50, self._drain_queue)

    def destroy(self) -> None:
        try:
            self.after_cancel(self._drain_id)
        except (AttributeError, tk.TclError):
            pass
        super().destroy()

    def say(self, text: str, level: str = "info") -> None:
        self.messages.configure(state="normal")
        self.messages.insert("end", time.strftime("%H:%M:%S  "), "time")
        self.messages.insert("end", text + "\n", level)
        self.messages.see("end")
        self.messages.configure(state="disabled")

    def set_busy(self, busy: bool, text: str = "Listo") -> None:
        for b in self._busy_buttons:
            b.state(["disabled"] if busy else ["!disabled"])
        self.status_text.configure(text=text)
        if busy:
            self.progress.pack(side="left", padx=(0, 10), before=self.status_text)
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()
        self.configure(cursor="watch" if busy else "")

    def show_status(self, st: UwfStatus) -> None:
        self.last_status = st
        items = describe(st)
        for key in ("filter", "volume", "feature", "overlay", "reboot"):
            self.cards[key].set(items[key])
        head = headline(st)
        color = LEVELS[head.level][1]
        self.hero_icon.set(head.level)
        self.hero_value.configure(text=head.value, fg=color)

        if st.is_admin:
            self.admin_badge.configure(text="ADMINISTRADOR", fg="#BFF0CF", bg="#1D4A3A")
        else:
            self.admin_badge.configure(text="SIN PRIVILEGIOS DE ADMINISTRADOR", fg="#FFE2B8", bg="#5A3A12")

        rp = st.reboot_pending
        if rp is True:
            self._show_banner("Reinicio pendiente: los cambios se aplicarán cuando reinicie Windows. "
                              "La aplicación no reinicia automáticamente.", "warn")
        elif rp is None and st.query_ok:
            self._show_banner("Posible cambio pendiente de reinicio: no se pudo verificar todo el estado.",
                              "unknown")
        else:
            self.banner.pack_forget()

        win = items["system"].value
        self.checked_text.configure(text=f"{win} · {st.edition_id or 'edición desconocida'} · "
                                         f"comprobado {time.strftime('%H:%M:%S')}")
        for err in st.errors:
            self.say(f"Aviso: {err}", "warn")

    def _show_banner(self, text: str, level: str) -> None:
        _, color, soft = LEVELS[level]
        self.banner.configure(bg=soft, highlightbackground=color)
        self.banner_icon.configure(bg=soft)
        self.banner_icon.set(level)
        self.banner_text.configure(text=text, fg=color, bg=soft)
        self.banner.pack(fill="x", pady=(0, 10), after=self._banner_anchor)

    def _start(self, task, on_result, message: str) -> None:
        if self.controller.busy:
            self.say("Ya hay una operación en curso.", "warn")
            return
        self.set_busy(True, message)
        self.say(message, "muted")

        def done(result, error) -> None:
            self.set_busy(False)
            if error is not None:
                self.say(f"ERROR inesperado: {error}", "error")
                messagebox.showerror("UWF Manager", f"Error inesperado:\n{error}", parent=self)
            else:
                on_result(result)

        self.controller.run_async(task, done)

    # ---------- acciones ----------
    def refresh(self) -> None:
        def shown(st: UwfStatus) -> None:
            self.show_status(st)
            self.say("Estado actualizado.", "ok" if st.query_ok else "warn")
        self._start(self.query.read, shown, "Consultando el estado real de UWF…")

    def on_compat(self) -> None:
        def task():
            st = self.query.read()
            return st, evaluate(st)

        def shown(result) -> None:
            st, report = result
            self.show_status(st)
            verdict, level = report.verdict
            self.cards["compat"].set(Item("Compatibilidad", verdict.split(":")[0], level))
            self.say(f"Compatibilidad: {verdict}", {"ok": "ok", "bad": "error"}.get(level, "warn"))
            if self.compat_dialog is not None and self.compat_dialog.winfo_exists():
                self.compat_dialog.destroy()
            self.compat_dialog = CompatDialog(self, report)
        self._start(task, shown, "Comprobando la compatibilidad del equipo…")

    def open_logs(self) -> None:
        folder = log_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            else:
                self.say(f"Registros en: {folder}")
        except OSError as exc:
            self.say(f"No se pudo abrir la carpeta de registros: {exc}", "error")

    def _ensure_admin(self) -> bool:
        if system.is_admin():
            return True
        if messagebox.askyesno("Privilegios de administrador",
                               "Esta operación requiere privilegios de administrador.\n"
                               "¿Reiniciar la aplicación solicitando elevación (UAC)?", parent=self):
            res = system.relaunch_as_admin()
            self.say(res.message, "warn")
            if res.started:
                self.destroy()
            elif not res.cancelled:
                messagebox.showerror("UWF Manager", res.message, parent=self)
        return False

    def _show_operation(self, res: OperationResult) -> None:
        self.say(res.title, "info")
        for line in res.lines():
            level = ("error" if line.startswith("[ERROR") or line.startswith("Secuencia detenida")
                     else "muted" if line.startswith("[OMITIDO") else "ok" if line.startswith("[OK") else "info")
            self.say("   " + line, level)
        if res.status:
            self.show_status(res.status)
        if res.reboot_required:
            messagebox.showwarning("Reinicio necesario",
                                   "Es necesario reiniciar Windows para aplicar los cambios.\n"
                                   "Reinícielo cuando lo desee; la aplicación no lo hará automáticamente.",
                                   parent=self)
        elif not res.ok:
            messagebox.showerror("UWF Manager", res.summary, parent=self)

    def on_enable(self) -> None:
        if not self._ensure_admin():
            return
        if not messagebox.askokcancel(
                "Activar congelación",
                "Tras reiniciar con la congelación activa, Windows descartará en cada reinicio "
                "los cambios hechos en C:.\n\nGuarde sus archivos importantes antes de continuar.\n\n"
                "¿Continuar?", icon="warning", parent=self):
            return
        self._start(self.ops.enable_freeze, self._show_operation, "Activando congelación…")

    def on_disable(self) -> None:
        if not self._ensure_admin():
            return
        if not messagebox.askyesno(
                "Desactivar congelación",
                "Al desactivar UWF y reiniciar, los cambios que se realicen mientras el filtro "
                "esté deshabilitado podrán persistir en el sistema.\n\n"
                "La protección configurada de C: se conservará.\n\n¿Continuar?", icon="warning",
                parent=self):
            return
        self._start(self.ops.disable_freeze, self._show_operation, "Desactivando congelación…")

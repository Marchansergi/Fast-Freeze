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

from . import APP_NAME, __version__, system
from .compat import CompatReport, Level, evaluate
from .controller import Controller
from .logs import log_dir
from .operations import OperationResult, Operations
from .presentation import Item, describe, headline
from .profile import APPLY_TEXT, SUMMARY, Assessment, Phase
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
    "neutral": ("–", "#6B7280", "#EEF0F3"),
}
BANNER_PHASES = (Phase.MAINTENANCE_REBOOT, Phase.CONTINUE, Phase.FEATURE_REBOOT)
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
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FastFreeze.App")
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
        elif level == "neutral":
            self.create_line(n * .3, n / 2, n * .7, n / 2, fill="white", width=w, capstyle="round")
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
        inner = tk.Frame(self, bg=CARD, padx=12, pady=8)
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
        self.title("Compatibilidad del equipo · Fast Freeze")
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


class RebootDialog(tk.Toplevel):
    """«Reiniciar ahora» / «Más tarde». Nunca reinicia sin que el usuario lo elija."""

    def __init__(self, app: "App", message: str) -> None:
        super().__init__(app)
        f = app.fonts
        self.choice = "later"
        self.title("Reinicio necesario · Fast Freeze")
        self.configure(bg=BG, padx=20, pady=18)
        self.transient(app)
        self.resizable(False, False)
        app.apply_icon(self)
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x")
        icon = StatusIcon(top, 30, BG)
        icon.set("warn")
        icon.pack(side="left", anchor="n", padx=(0, 12))
        text = tk.Frame(top, bg=BG)
        text.pack(side="left", fill="x")
        tk.Label(text, text="Es necesario reiniciar Windows", font=f["section"], fg=TEXT, bg=BG,
                 anchor="w").pack(fill="x")
        tk.Label(text, text=message, font=f["body"], fg=TEXT, bg=BG, anchor="w", justify="left",
                 wraplength=460).pack(fill="x", pady=(6, 0))
        tk.Label(text, text="Guarde su trabajo antes de reiniciar. Si elige «Más tarde», el paso quedará "
                            "pendiente y la aplicación se lo recordará.", font=f["small"], fg=MUTED, bg=BG,
                 anchor="w", justify="left", wraplength=460).pack(fill="x", pady=(8, 0))
        buttons = tk.Frame(self, bg=BG)
        buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(buttons, text="Reiniciar ahora", style="Primary.TButton",
                   command=lambda: self._close("now")).pack(side="right")
        later = ttk.Button(buttons, text="Más tarde", style="Secondary.TButton",
                           command=lambda: self._close("later"))
        later.pack(side="right", padx=(0, 8))
        self.protocol("WM_DELETE_WINDOW", lambda: self._close("later"))
        self.bind("<Escape>", lambda e: self._close("later"))
        self.update_idletasks()
        x = app.winfo_rootx() + max((app.winfo_width() - self.winfo_reqwidth()) // 2, 0)
        y = app.winfo_rooty() + max((app.winfo_height() - self.winfo_reqheight()) // 3, 0)
        self.geometry(f"+{x}+{y}")
        later.focus_set()  # la opción por defecto es la segura
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _close(self, choice: str) -> None:
        self.choice = choice
        self.destroy()


class App(tk.Tk):
    def __init__(self, ops: Operations, query: UwfQuery) -> None:
        super().__init__()
        self.ops, self.query = ops, query
        self._ui_queue: queue.Queue = queue.Queue()
        self.controller = Controller(self._ui_queue.put)  # el hilo de trabajo nunca toca Tk
        self.compat_dialog: CompatDialog | None = None
        self.last_status: UwfStatus | None = None
        self.last_assessment: Assessment | None = None

        self.title(APP_NAME)
        self.configure(bg=BG)
        self.minsize(900, 680)
        self.geometry("980x760")
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
        header = tk.Frame(outer, bg=CARD)
        header.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(header, text=title.upper(), font=self.fonts["caption"], fg=MUTED, bg=CARD,
                 anchor="w").pack(side="left")
        body = tk.Frame(outer, bg=CARD)
        body.pack(fill="both", expand=True, padx=14, pady=(6, 12))
        outer.header = header  # type: ignore[attr-defined]
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
        tk.Label(titles, text=APP_NAME, font=f["title"], fg="white", bg=NAVY).pack(anchor="w")
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
        hero = tk.Frame(body, bg=CARD, highlightthickness=1, highlightbackground=BORDER, padx=18, pady=10)
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
        # La superposición se muestra con detalle en «Configuración recomendada».
        layout = [("filter", "Filtro UWF"), ("volume", "Protección de C:"), ("feature", "Característica UWF"),
                  ("reboot", "Reinicio"), ("compat", "Compatibilidad")]
        for i, (key, caption) in enumerate(layout):
            card = StatusCard(grid, caption, f)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0), pady=(0, 10))
            self.cards[key] = card
        for c in range(len(layout)):
            grid.columnconfigure(c, weight=1, uniform="cards")
        self.cards["compat"].set(Item("Compatibilidad", "Sin comprobar", "unknown"))

        # Acciones y configuración recomendada, lado a lado
        columns = tk.Frame(body, bg=BG)
        columns.pack(fill="x")
        columns.columnconfigure((0, 1), weight=1, uniform="cols")
        actions = self._card(columns, "Acciones")
        actions.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        a = actions.body  # type: ignore[attr-defined]
        self.btn_enable = ttk.Button(a, text="Activar congelación y protección",
                                     style="Primary.TButton", command=self.on_enable)
        self.btn_enable.pack(fill="x")
        self.btn_disable = ttk.Button(a, text="Desactivar congelación", style="Danger.TButton",
                                      command=self.on_disable)
        self.btn_disable.pack(fill="x", pady=(8, 0))
        row2 = tk.Frame(a, bg=CARD)
        row2.pack(fill="x", pady=(12, 0))
        row2.columnconfigure((0, 1), weight=1, uniform="sec")
        self.btn_compat = ttk.Button(row2, text="Buscar compatibilidad", style="Secondary.TButton",
                                     command=self.on_compat)
        self.btn_compat.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.btn_refresh = ttk.Button(row2, text="Actualizar estado (F5)", style="Secondary.TButton",
                                      command=self.refresh)
        self.btn_refresh.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self._build_profile(columns)
        # Actividad
        activity = self._card(body, "Actividad")
        activity.pack(fill="both", expand=True, pady=(10, 0))
        self.btn_logs = ttk.Button(activity.header, text="Abrir carpeta de registros",  # type: ignore[attr-defined]
                                   style="Secondary.TButton", command=self.open_logs)
        self.btn_logs.pack(side="right")
        holder = tk.Frame(activity.body, bg=CARD)  # type: ignore[attr-defined]
        holder.pack(fill="both", expand=True)
        self.messages = tk.Text(holder, height=4, wrap="word", state="disabled", font=f["mono"],
                                relief="flat", bg="#FAFBFD", fg=TEXT, padx=8, pady=6,
                                highlightthickness=1, highlightbackground=BORDER)
        scroll = ttk.Scrollbar(holder, command=self.messages.yview)
        self.messages.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.messages.pack(side="left", fill="both", expand=True)
        for tag, color in (("time", MUTED), ("ok", LEVELS["ok"][1]), ("warn", LEVELS["warn"][1]),
                           ("error", LEVELS["bad"][1]), ("muted", MUTED), ("info", TEXT)):
            self.messages.tag_configure(tag, foreground=color)

        self._busy_buttons = (self.btn_enable, self.btn_disable, self.btn_compat, self.btn_refresh,
                              self.btn_profile)
        self._profile_can_apply = True

    def _build_profile(self, parent: tk.Frame) -> None:
        f = self.fonts
        card = self._card(parent, "Configuración recomendada")
        card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        b = card.body  # type: ignore[attr-defined]
        status = tk.Frame(b, bg=CARD)
        status.pack(fill="x")
        self.profile_icon = StatusIcon(status, 18, CARD)
        self.profile_icon.set("unknown")
        self.profile_icon.pack(side="left", anchor="n", pady=1)
        self.profile_status = tk.Label(status, text="Consultando…", font=f["body_bold"], fg=TEXT, bg=CARD,
                                       anchor="w", justify="left")
        self.profile_status.pack(side="left", fill="x", expand=True, padx=(8, 0))
        status.bind("<Configure>", lambda e: self.profile_status.configure(wraplength=max(e.width - 30, 80)))

        table = tk.Frame(b, bg=CARD)
        table.pack(fill="x", pady=(8, 0))
        table.columnconfigure(0, weight=1)
        for col, title in ((1, "AHORA"), (2, "TRAS REINICIAR")):
            tk.Label(table, text=title, font=f["caption"], fg=MUTED, bg=CARD).grid(row=0, column=col, padx=6)
        self.profile_cells = []
        for i, (name, value) in enumerate(SUMMARY, start=1):
            tk.Label(table, text=f"{name}: {value}", font=f["body"], fg=TEXT, bg=CARD, anchor="w",
                     ).grid(row=i, column=0, sticky="w", pady=1)
            cells = []
            for col in (1, 2):
                cell = tk.Frame(table, bg=CARD)
                cell.grid(row=i, column=col, sticky="w", padx=6)
                icon = StatusIcon(cell, 12, CARD)
                icon.set("unknown")
                icon.pack(side="left")
                lab = tk.Label(cell, text="?", font=f["small"], fg=MUTED, bg=CARD)
                lab.pack(side="left", padx=(4, 0))
                cells.append((icon, lab))
            self.profile_cells.append(cells)

        self.btn_profile = ttk.Button(b, text=APPLY_TEXT, style="Primary.TButton", command=self.on_profile)
        self.btn_profile.pack(fill="x", pady=(10, 0))
        tk.Label(b, text="La reserva de 4096 MB no limita los datos nuevos: con el acceso al espacio libre se "
                         "usa el espacio libre del disco, que sigue siendo el límite.",
                 font=f["small"], fg=MUTED, bg=CARD, anchor="w", justify="left", wraplength=400,
                 ).pack(fill="x", pady=(6, 0))

    def show_profile(self, a: Assessment) -> None:
        self.last_assessment = a
        color = LEVELS[a.level][1]
        self.profile_icon.set(a.level)
        # En las fases a medias el detalle va en el aviso superior; aquí basta la fase.
        text = f"{a.phase.value.capitalize()}." if a.phase in BANNER_PHASES else a.message
        self.profile_status.configure(text=text, fg=color)
        values = {True: ("Sí", "ok"), False: ("No", "warn"), None: ("?", "unknown")}
        for i, cells in enumerate(self.profile_cells):
            row = a.rows[i] if i < len(a.rows) else None
            for (icon, lab), value in zip(cells, (row.current, row.next) if row else (None, None)):
                text, level = values[value]
                icon.set(level)
                lab.configure(text=text, fg=LEVELS[level][1])
        self.btn_profile.configure(text=a.button_text)
        self._profile_can_apply = a.can_apply
        if not a.can_apply:
            self.btn_profile.state(["disabled"])

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
        if not busy and not self._profile_can_apply:
            self.btn_profile.state(["disabled"])
        self.status_text.configure(text=text)
        if busy:
            self.progress.pack(side="left", padx=(0, 10), before=self.status_text)
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()
        self.configure(cursor="watch" if busy else "")

    def show_status(self, st: UwfStatus, assessment: Assessment | None = None) -> None:
        self.last_status = st
        if assessment is not None:
            self.show_profile(assessment)
        items = describe(st)
        for key in ("filter", "volume", "feature", "reboot"):
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
        a = assessment
        if a is not None and a.phase in BANNER_PHASES:
            self._show_banner("Configuración recomendada a medias: " + a.message, "warn")
        elif rp is True:
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
                messagebox.showerror(APP_NAME, f"Error inesperado:\n{error}", parent=self)
            else:
                on_result(result)

        self.controller.run_async(task, done)

    # ---------- acciones ----------
    def refresh(self) -> None:
        def shown(result) -> None:
            st, a = result
            self.show_status(st, a)
            self.say("Estado actualizado.", "ok" if st.query_ok else "warn")
        self._start(self.ops.assess_profile, shown, "Consultando el estado real de UWF…")

    def on_compat(self) -> None:
        def task():
            st, a = self.ops.assess_profile()
            return st, a, evaluate(st)

        def shown(result) -> None:
            st, a, report = result
            self.show_status(st, a)
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
                messagebox.showerror(APP_NAME, res.message, parent=self)
        return False

    def _with_assessment(self, op, *args):
        """Ejecuta una operación (en el hilo de trabajo) y añade la fase del perfil al resultado."""
        res = op(*args)
        if res.assessment is None and res.status is not None:
            res.assessment = self.ops.assess_profile(res.status)[1]
        return res

    def _show_operation(self, res: OperationResult, info_when_ok: bool = False) -> None:
        self.say(res.title, "info")
        for line in res.lines():
            level = ("error" if line.startswith("[ERROR") or line.startswith("Secuencia detenida")
                     else "warn" if "AVISO" in line or "sin verificar" in line
                     else "muted" if line.startswith("[OMITIDO") else "ok" if line.startswith("[OK") else "info")
            self.say("   " + line, level)
        if res.status:
            self.show_status(res.status, res.assessment)
        if res.reboot_required:
            if self.ask_reboot(res.summary):
                self._restart()
            else:
                pending = res.assessment.message if res.assessment else res.summary
                self.say(f"Reinicio pospuesto. Pendiente: {pending}", "warn")
        elif not res.ok:
            messagebox.showerror(APP_NAME, res.summary + "\n\nLos detalles técnicos están en el registro "
                                 "(botón «Abrir carpeta de registros»).", parent=self)
        elif info_when_ok:
            messagebox.showinfo(APP_NAME, res.summary, parent=self)

    def ask_reboot(self, message: str) -> bool:
        """Diálogo «Reiniciar ahora» / «Más tarde». Devuelve True si el usuario elige reiniciar."""
        dialog = RebootDialog(self, message)
        self.wait_window(dialog)
        return dialog.choice == "now"

    def _restart(self) -> None:
        def shown(result) -> None:
            ok, message = result
            self.say(message, "ok" if ok else "error")
            if not ok:
                messagebox.showerror(APP_NAME, f"No se pudo reiniciar:\n{message}", parent=self)
        self._start(self.ops.restart_now, shown, "Solicitando el reinicio de Windows…")

    def on_profile(self) -> None:
        if not self._ensure_admin():
            return
        if not messagebox.askokcancel(
                APPLY_TEXT,
                "Se configurará UWF con: overlay en disco con reserva de 4096 MB, acceso al espacio libre, "
                "overlay no persistente, C: protegida y filtro activo.\n\n"
                "Con UWF activo, Windows descarta al reiniciar los cambios hechos en C: durante la sesión. "
                "Guarde sus archivos importantes en otra unidad.\n\n"
                "Puede necesitar uno o dos reinicios; usted decide cuándo.\n\n¿Continuar?",
                icon="warning", parent=self):
            return
        self._start(lambda: self._with_assessment(self.ops.apply_profile, False), self._after_profile,
                    "Aplicando la configuración recomendada…")

    def _after_profile(self, res: OperationResult) -> None:
        if res.needs_confirmation:
            if messagebox.askyesno("Superposición persistente", res.needs_confirmation, icon="warning",
                                   parent=self):
                self._start(lambda: self._with_assessment(self.ops.apply_profile, True), self._after_profile,
                            "Aplicando la configuración recomendada…")
            else:
                self.say("Cancelado: no se ha cambiado nada.", "warn")
            return
        self._show_operation(res, info_when_ok=True)

    def on_enable(self) -> None:
        if not self._ensure_admin():
            return
        if not messagebox.askokcancel(
                "Activar congelación",
                "Tras reiniciar con la congelación activa, Windows descartará en cada reinicio "
                "los cambios hechos en C:.\n\nGuarde sus archivos importantes antes de continuar.\n\n"
                "¿Continuar?", icon="warning", parent=self):
            return
        self._start(lambda: self._with_assessment(self.ops.enable_freeze), self._show_operation,
                    "Activando congelación…")

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
        self._start(lambda: self._with_assessment(self.ops.disable_freeze), self._show_operation,
                    "Desactivando congelación…")

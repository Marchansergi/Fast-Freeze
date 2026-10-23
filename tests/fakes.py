"""Windows simulado: ningún test toca el sistema real."""
from __future__ import annotations

import json
import ntpath
import subprocess

from uwf_manager.runner import CommandResult, CommandRunner


def exe(argv) -> str:
    return ntpath.basename(argv[0]).lower()


class FakeWindows:
    """Simula PowerShell/CIM, DISM, uwfmgr, shutdown y el Registro con un estado en memoria.

    Reglas modeladas: los cambios de uwfmgr afectan a la próxima sesión; `overlay set-type DISK`
    falla si el filtro está activo en la sesión actual; lo escrito en el Registro durante una
    sesión protegida se pierde al reiniciar salvo que se confirme con `registry commit`.
    """

    def __init__(self, *, feature="Enabled", edition="IoTEnterpriseS", build=26100,
                 filter_cur=False, filter_next=False, c_cur=False, c_next=False,
                 overlay_cur=(1, 2048), overlay_next=(1, 2048),
                 pass_cur=False, pass_next=False, persist_cur=False, persist_next=False,
                 wmi_flags=True, wmi=None, dism_rc=0, fail=None, ps_output=None, is64=True,
                 c_free=50 * 1024**3):
        self.feature, self.edition, self.build = feature, edition, build
        self.filter_cur, self.filter_next = filter_cur, filter_next
        self.c_cur, self.c_next = c_cur, c_next
        self.overlay_cur, self.overlay_next = overlay_cur, overlay_next
        self.pass_cur, self.pass_next = pass_cur, pass_next
        self.persist_cur, self.persist_next = persist_cur, persist_next
        self.wmi_flags = wmi_flags  # False: WMI no expone passthrough/persistencia
        self.wmi = (feature == "Enabled") if wmi is None else wmi
        self.dism_rc = dism_rc
        self.is64, self.c_free = is64, c_free
        self.fail = fail or {}  # {"filter enable": código | "timeout" | "notfound" | "denied"}
        self.ps_output = ps_output  # fuerza la salida de la consulta
        self.calls: list[tuple[str, ...]] = []
        self.reg_value: str | None = None      # lo que ve la sesión actual
        self.reg_persisted: str | None = None  # lo que sobrevive al reinicio
        self.reset_persistent_scheduled = False
        self.restarted = 0

    # ---- consulta ----
    def _overlay_json(self, session, ov, passthrough, persistent):
        d = {"session": session, "size": ov[1], "type": ov[0],
             "props": ["CurrentSession", "MaximumSize", "Type"]}
        if self.wmi_flags:
            d.update({"x_FreeSpacePassthrough": passthrough, "x_PersistentOverlay": persistent})
        return d

    def _json(self) -> str:
        d = {"caption": "Microsoft Windows 11 IoT Enterprise LTSC", "version": "10.0.26100",
             "build": self.build, "edition": self.edition, "feature": self.feature,
             "errors": [], "wmi": self.wmi, "is64": self.is64, "c_free": self.c_free}
        if self.wmi:
            d["filter"] = [{"current": self.filter_cur, "next": self.filter_next}]
            d["volumes"] = [{"drive": "C:", "protected": self.c_cur, "session": True},
                            {"drive": "C:", "protected": self.c_next, "session": False}]
            d["overlay"] = [self._overlay_json(True, self.overlay_cur, self.pass_cur, self.persist_cur),
                            self._overlay_json(False, self.overlay_next, self.pass_next, self.persist_next)]
        return json.dumps(d)

    # ---- ejecución ----
    def run(self, argv, **kwargs):
        argv = tuple(argv)
        self.calls.append(argv)
        name = exe(argv)
        ok = lambda out=b"ok": subprocess.CompletedProcess(argv, 0, out, b"")
        if name == "powershell.exe":
            out = self.ps_output if self.ps_output is not None else self._json()
            return ok(out.encode())
        key = " ".join(argv[1:3]) if name == "uwfmgr.exe" else name.removesuffix(".exe")
        if key in self.fail:
            f = self.fail[key]
            if f == "timeout":
                raise subprocess.TimeoutExpired(argv, 5)
            if f == "notfound":
                raise FileNotFoundError(argv[0])
            if f == "denied":
                raise PermissionError("Access is denied")
            return subprocess.CompletedProcess(argv, f, b"", b"fallo simulado")
        if name == "dism.exe":
            if self.dism_rc in (0, 3010):
                self.feature = "EnablePending" if self.dism_rc == 3010 else "Enabled"
                self.wmi = self.dism_rc == 0
            return subprocess.CompletedProcess(argv, self.dism_rc, b"", b"")
        if name == "shutdown.exe":
            self.restarted += 1
            return ok()
        if name == "uwfmgr.exe":
            a = [x.lower() for x in argv[1:]]
            if a[:2] == ["overlay", "set-size"]:
                self.overlay_next = (self.overlay_next[0], int(a[2]))
            elif a[:2] == ["overlay", "set-type"]:
                if a[2] == "disk" and self.filter_cur:
                    return subprocess.CompletedProcess(argv, 1, b"", b"UWF debe estar deshabilitado")
                self.overlay_next = (1 if a[2] == "disk" else 0, self.overlay_next[1])
            elif a[:2] == ["overlay", "set-passthrough"]:
                self.pass_next = a[2] == "on"
            elif a[:2] == ["overlay", "set-persistent"]:
                self.persist_next = a[2] == "on"
            elif a[:2] == ["overlay", "reset-persistentstate"]:
                self.reset_persistent_scheduled = a[2] == "on"
            elif a[:2] == ["volume", "protect"]:
                self.c_next = True
            elif a[:2] == ["filter", "enable"]:
                self.filter_next = True
            elif a[:2] == ["filter", "disable"]:
                self.filter_next = False
            elif a[:2] == ["registry", "commit"]:
                self.reg_persisted = self.reg_value
            elif a[:2] == ["registry", "commit-delete"]:
                self.reg_persisted = None
            elif "get-config" in a or a[-1] in ("get-consumption", "get-available-space"):
                return ok(b"config")
            else:
                raise AssertionError(f"comando no previsto: {argv}")
            return ok()
        raise AssertionError(f"proceso no previsto: {argv}")

    def runner(self) -> CommandRunner:
        return CommandRunner(run=self.run)

    def reboot(self):
        self.filter_cur, self.c_cur, self.overlay_cur = self.filter_next, self.c_next, self.overlay_next
        self.pass_cur, self.persist_cur = self.pass_next, self.persist_next
        self.reset_persistent_scheduled = False
        self.reg_value = self.reg_persisted
        if self.feature == "EnablePending":
            self.feature, self.wmi = "Enabled", True


class FakeRegistry:
    """Registro de Windows simulado, enlazado a FakeWindows para modelar la protección UWF."""

    def __init__(self, win: FakeWindows) -> None:
        self.win = win

    def read(self):
        return self.win.reg_value

    def write(self, value):
        self.win.reg_value = value
        if not self.win.filter_cur:
            self.win.reg_persisted = value

    def delete(self):
        self.win.reg_value = None
        if not self.win.filter_cur:
            self.win.reg_persisted = None

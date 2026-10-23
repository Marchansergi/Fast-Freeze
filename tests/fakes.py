"""Windows simulado: ningún test toca el sistema real."""
from __future__ import annotations

import json
import subprocess

from uwf_manager.runner import CommandResult, CommandRunner


class FakeWindows:
    """Simula PowerShell/CIM, DISM y uwfmgr con un estado en memoria."""

    def __init__(self, *, feature="Enabled", edition="IoTEnterpriseS", build=26100,
                 filter_cur=False, filter_next=False, c_cur=False, c_next=False,
                 overlay_cur=(1, 2048), overlay_next=(1, 2048), wmi=None,
                 dism_rc=0, fail=None, ps_output=None, is64=True, c_free=50 * 1024**3):
        self.feature, self.edition, self.build = feature, edition, build
        self.filter_cur, self.filter_next = filter_cur, filter_next
        self.c_cur, self.c_next = c_cur, c_next
        self.overlay_cur, self.overlay_next = overlay_cur, overlay_next
        self.wmi = (feature == "Enabled") if wmi is None else wmi
        self.dism_rc = dism_rc
        self.is64, self.c_free = is64, c_free
        self.fail = fail or {}  # {"filter enable": CommandResult-kwargs | "timeout" | "notfound"}
        self.ps_output = ps_output  # fuerza la salida de la consulta
        self.calls: list[tuple[str, ...]] = []

    def _json(self) -> str:
        d = {"caption": "Microsoft Windows 11 IoT Enterprise LTSC", "version": "10.0.26100",
             "build": self.build, "edition": self.edition, "feature": self.feature,
             "errors": [], "wmi": self.wmi, "is64": self.is64, "c_free": self.c_free}
        if self.wmi:
            d["filter"] = [{"current": self.filter_cur, "next": self.filter_next}]
            d["volumes"] = [{"drive": "C:", "protected": self.c_cur, "session": True},
                            {"drive": "C:", "protected": self.c_next, "session": False}]
            d["overlay"] = [{"session": True, "size": self.overlay_cur[1], "type": self.overlay_cur[0]},
                            {"session": False, "size": self.overlay_next[1], "type": self.overlay_next[0]}]
        return json.dumps(d)

    def run(self, argv, **kwargs):
        argv = tuple(argv)
        self.calls.append(argv)
        exe = argv[0].lower()
        if exe == "powershell.exe":
            out = self.ps_output if self.ps_output is not None else self._json()
            return subprocess.CompletedProcess(argv, 0, out.encode(), b"")
        key = " ".join(argv[1:3]) if exe == "uwfmgr.exe" else "dism"
        if key in self.fail:
            f = self.fail[key]
            if f == "timeout":
                raise subprocess.TimeoutExpired(argv, 5)
            if f == "notfound":
                raise FileNotFoundError(argv[0])
            if f == "denied":
                raise PermissionError("Access is denied")
            return subprocess.CompletedProcess(argv, f, b"", b"fallo simulado")
        if exe == "dism.exe":
            if self.dism_rc in (0, 3010):
                self.feature = "EnablePending" if self.dism_rc == 3010 else "Enabled"
                self.wmi = self.dism_rc == 0
            return subprocess.CompletedProcess(argv, self.dism_rc, b"", b"")
        if exe == "uwfmgr.exe":
            a = list(argv[1:])
            if a[:2] == ["overlay", "set-size"]:
                self.overlay_next = (self.overlay_next[0], int(a[2]))
            elif a[:2] == ["overlay", "set-type"]:
                self.overlay_next = (1 if a[2] == "disk" else 0, self.overlay_next[1])
            elif a[:2] == ["volume", "protect"]:
                self.c_next = True
            elif a[:2] == ["filter", "enable"]:
                self.filter_next = True
            elif a[:2] == ["filter", "disable"]:
                self.filter_next = False
            elif a[:1] == ["get-config"]:
                return subprocess.CompletedProcess(argv, 0, b"config", b"")
            else:
                raise AssertionError(f"comando no previsto: {argv}")
            return subprocess.CompletedProcess(argv, 0, b"ok", b"")
        raise AssertionError(f"proceso no previsto: {argv}")

    def runner(self) -> CommandRunner:
        return CommandRunner(run=self.run)

    def reboot(self):
        self.filter_cur, self.c_cur, self.overlay_cur = self.filter_next, self.c_next, self.overlay_next
        if self.feature == "EnablePending":
            self.feature, self.wmi = "Enabled", True

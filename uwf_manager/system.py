"""Detección del entorno: privilegios, ejecutables y elevación UAC."""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from typing import Callable

ERROR_CANCELLED = 1223


def is_windows() -> bool:
    return sys.platform == "win32"


def is_admin() -> bool:
    if not is_windows():
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def find_executable(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    root = os.environ.get("SystemRoot")
    if root:
        candidate = os.path.join(root, "System32", name)
        if os.path.isfile(candidate):
            return candidate
    return None


@dataclass(frozen=True)
class ElevationResult:
    started: bool
    cancelled: bool = False
    message: str = ""


def _shell_execute_runas(exe: str, params: str) -> tuple[int, int]:
    import ctypes
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return int(ret), ctypes.GetLastError()


def relaunch_as_admin(shell_execute: Callable[[str, str], tuple[int, int]] = _shell_execute_runas
                      ) -> ElevationResult:
    """Pide elevación UAC lanzando de nuevo la aplicación. No cierra el proceso actual."""
    if not is_windows() and shell_execute is _shell_execute_runas:
        return ElevationResult(False, message="La elevación UAC solo existe en Windows.")
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, subprocess_list2cmdline(sys.argv[1:])
    else:
        exe = sys.executable
        params = subprocess_list2cmdline(["-m", "uwf_manager", *sys.argv[1:]])
    try:
        ret, last_error = shell_execute(exe, params)
    except Exception as exc:
        return ElevationResult(False, message=f"No se pudo solicitar la elevación: {exc}")
    if ret > 32:
        return ElevationResult(True, message="Se solicitó la elevación; se abrirá una nueva ventana.")
    if last_error == ERROR_CANCELLED or ret == 5:
        return ElevationResult(False, cancelled=True,
                               message="Elevación cancelada: la aplicación sigue sin permisos de administrador.")
    return ElevationResult(False, message=f"No se pudo elevar los privilegios (código {ret}).")


def subprocess_list2cmdline(args: list[str]) -> str:
    import subprocess
    return subprocess.list2cmdline(args)

"""Detección del entorno: privilegios, ejecutables y elevación UAC."""
from __future__ import annotations

import ntpath
import os
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


def system_dir() -> str:
    """Carpeta System32 real (GetSystemDirectoryW); no depende del PATH ni de la carpeta actual."""
    if is_windows():
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.kernel32.GetSystemDirectoryW(buf, 260):
                return buf.value
        except Exception:
            pass
    root = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    return ntpath.join(root, "System32")


def system32(name: str) -> str:
    """Ruta absoluta de una herramienta de Windows. Evita ejecutar copias suplantadas
    que estén en la carpeta del programa, en la carpeta actual o en el PATH."""
    return ntpath.join(system_dir(), name)


def find_executable(name: str) -> str | None:
    """Ruta de la herramienta en System32 si existe; nunca busca en el PATH."""
    candidate = system32(name)
    return candidate if os.path.isfile(candidate) else None


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

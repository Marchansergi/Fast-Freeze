"""Indicador de progreso del perfil recomendado que sobrevive a los reinicios.

Es un único valor del Registro. Si se escribe mientras UWF protege la sesión, se hace
persistente con `uwfmgr registry commit` (solo ese valor; no se añaden exclusiones).
El indicador es solo una pista: el paso pendiente se deduce siempre del estado real de UWF.
"""
from __future__ import annotations

from typing import Protocol

from . import commands
from .errors import classify, explain, succeeded
from .logs import get_logger
from .runner import CommandRunner

MAINTENANCE = "maintenance"  # fase 1 hecha: falta reiniciar con el filtro desactivado
FEATURE = "feature"          # se instaló la característica: falta reiniciar
VALID = (MAINTENANCE, FEATURE)


class RegistryBackend(Protocol):
    def read(self) -> str | None: ...
    def write(self, value: str) -> None: ...
    def delete(self) -> None: ...


class WinRegistry:
    """HKLM\\SOFTWARE\\UWFManager\\RecommendedProfilePhase (vista de 64 bits)."""

    _SUBKEY = r"SOFTWARE\UWFManager"

    def _open(self, write: bool):
        import winreg
        access = (winreg.KEY_SET_VALUE if write else winreg.KEY_READ) | winreg.KEY_WOW64_64KEY
        if write:
            return winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, self._SUBKEY, 0, access)
        return winreg.OpenKeyEx(winreg.HKEY_LOCAL_MACHINE, self._SUBKEY, 0, access)

    def read(self) -> str | None:
        import winreg
        try:
            with self._open(False) as key:
                value, kind = winreg.QueryValueEx(key, commands.PROFILE_VALUE)
                return value if kind == winreg.REG_SZ else None
        except OSError:
            return None

    def write(self, value: str) -> None:
        import winreg
        with self._open(True) as key:
            winreg.SetValueEx(key, commands.PROFILE_VALUE, 0, winreg.REG_SZ, value)

    def delete(self) -> None:
        import winreg
        try:
            with self._open(True) as key:
                winreg.DeleteValue(key, commands.PROFILE_VALUE)
        except FileNotFoundError:
            pass


class ProgressStore:
    def __init__(self, runner: CommandRunner, backend: RegistryBackend | None = None) -> None:
        self.runner = runner
        self.backend = backend

    def _backend(self) -> RegistryBackend | None:
        if self.backend is None:
            try:
                import winreg  # noqa: F401  (solo existe en Windows)
                self.backend = WinRegistry()
            except ImportError:
                return None
        return self.backend

    def read(self) -> str | None:
        backend = self._backend()
        try:
            value = backend.read() if backend else None
        except Exception:
            value = None
        return value if value in VALID else None

    def write(self, phase: str, session_protected: bool) -> str | None:
        """Guarda la fase. Devuelve None si queda persistente, o un aviso si puede perderse."""
        backend = self._backend()
        if backend is None:
            return "No hay Registro de Windows disponible para guardar el progreso."
        try:
            backend.write(phase)
        except Exception as exc:
            return f"No se pudo guardar el progreso en el Registro: {exc}"
        return self._commit(commands.registry_commit, session_protected)

    def clear(self, session_protected: bool) -> str | None:
        backend = self._backend()
        if backend is None:
            return None
        try:
            if backend.read() is None:
                return None
            backend.delete()
        except Exception as exc:
            return f"No se pudo borrar el indicador de progreso: {exc}"
        return self._commit(commands.registry_commit_delete, session_protected)

    def _commit(self, build, session_protected: bool) -> str | None:
        if not session_protected:
            return None  # sin UWF activo, el Registro se conserva por sí solo
        res = self.runner.run(build(commands.PROFILE_KEY, commands.PROFILE_VALUE), timeout=30)
        kind = classify(res)
        get_logger().info("PROGRESO commit -> %s", kind.value)
        if succeeded(kind):
            return None
        return ("No se pudo hacer persistente el indicador de progreso; tras reiniciar, la aplicación "
                "deducirá el paso pendiente del estado real de UWF. " + explain(kind, res))

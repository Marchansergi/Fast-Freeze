"""Ejecución centralizada de procesos externos (sin shell, con timeout)."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Sequence

from .logs import get_logger

DEFAULT_TIMEOUT = 120


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    not_found: bool = False
    error: str | None = None  # excepción del SO (permisos, elevación requerida...)
    winerror: int | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not (self.timed_out or self.not_found or self.error)

    @property
    def exit_code(self) -> int | None:
        """Código de salida como entero sin signo de 32 bits."""
        return None if self.returncode is None else self.returncode & 0xFFFFFFFF

    @property
    def output(self) -> str:
        return "\n".join(p.strip() for p in (self.stdout, self.stderr) if p and p.strip())

    def describe(self) -> str:
        return " ".join(self.args)


def _decode(data: bytes | None) -> str:
    if not data:
        return ""
    if sys.platform == "win32":
        for enc in ("utf-8", "oem"):
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
    return data.decode("utf-8", errors="replace")


class CommandRunner:
    """Único punto por el que la aplicación lanza procesos."""

    def __init__(self, default_timeout: int = DEFAULT_TIMEOUT,
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self.default_timeout = default_timeout
        self._run = run

    def run(self, args: Sequence[str], timeout: int | None = None) -> CommandResult:
        if isinstance(args, str) or not args or not all(isinstance(a, str) for a in args):
            raise TypeError("args debe ser una lista no vacía de cadenas")
        argv = tuple(args)
        log = get_logger()
        log.info("EJECUTAR %s", " ".join(argv))
        kwargs: dict = dict(capture_output=True, timeout=timeout or self.default_timeout,
                            shell=False, stdin=subprocess.DEVNULL)
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            proc = self._run(list(argv), **kwargs)
            result = CommandResult(argv, proc.returncode, _decode(proc.stdout), _decode(proc.stderr))
        except subprocess.TimeoutExpired as exc:
            result = CommandResult(argv, None, _decode(exc.stdout), _decode(exc.stderr),
                                   timed_out=True, error=f"Tiempo de espera agotado ({exc.timeout}s)")
        except FileNotFoundError as exc:
            result = CommandResult(argv, None, not_found=True, error=str(exc))
        except OSError as exc:  # PermissionError, WinError 740 (requiere elevación), ...
            result = CommandResult(argv, None, error=str(exc), winerror=getattr(exc, "winerror", None))
        log.info("RESULTADO rc=%s timeout=%s no_encontrado=%s error=%s salida=%r",
                 result.returncode, result.timed_out, result.not_found, result.error,
                 result.output[:500])
        return result

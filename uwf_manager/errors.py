"""Clasificación de fallos de comandos externos y mensajes en español."""
from __future__ import annotations

from enum import Enum

from .runner import CommandResult


class ErrorKind(Enum):
    OK = "ok"
    REBOOT_REQUIRED = "reboot_required"  # éxito, pero hay que reiniciar
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    FEATURE_UNAVAILABLE = "feature_unavailable"
    FAILED = "failed"


_REBOOT_CODES = {3010, 1641}
_ACCESS_CODES = {5, 740}
_FEATURE_CODES = {50, 0x800F080C, 0x800F0950}
_ACCESS_MARKERS = ("access is denied", "acceso denegado", "0x80070005", "elevation", "elevación")


def classify(result: CommandResult) -> ErrorKind:
    if result.not_found:
        return ErrorKind.NOT_FOUND
    if result.timed_out:
        return ErrorKind.TIMEOUT
    if result.winerror in _ACCESS_CODES or (result.error and isinstance(result.error, str)
                                            and "denied" in result.error.lower()):
        return ErrorKind.PERMISSION
    code = result.exit_code
    if code is None:
        return ErrorKind.FAILED
    if code == 0:
        return ErrorKind.OK
    if code in _REBOOT_CODES:
        return ErrorKind.REBOOT_REQUIRED
    text = result.output.lower()
    if code in _ACCESS_CODES or any(m in text for m in _ACCESS_MARKERS):
        return ErrorKind.PERMISSION
    if code in _FEATURE_CODES:
        return ErrorKind.FEATURE_UNAVAILABLE
    return ErrorKind.FAILED


def succeeded(kind: ErrorKind) -> bool:
    return kind in (ErrorKind.OK, ErrorKind.REBOOT_REQUIRED)


def explain(kind: ErrorKind, result: CommandResult) -> str:
    detail = result.output or result.error or ""
    detail = f" Detalle: {detail[:300]}" if detail else ""
    code = f" (código {result.exit_code})" if result.exit_code is not None else ""
    msgs = {
        ErrorKind.NOT_FOUND: "No se encontró el programa necesario.",
        ErrorKind.TIMEOUT: "El comando tardó demasiado y se canceló.",
        ErrorKind.PERMISSION: "Permisos insuficientes: ejecute la aplicación como administrador.",
        ErrorKind.FEATURE_UNAVAILABLE: "La característica no está disponible en esta edición de Windows.",
        ErrorKind.FAILED: f"El comando falló{code}.",
        ErrorKind.REBOOT_REQUIRED: "Operación correcta; es necesario reiniciar.",
        ErrorKind.OK: "Correcto.",
    }
    return msgs[kind] + detail

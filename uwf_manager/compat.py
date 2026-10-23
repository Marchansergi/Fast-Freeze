"""Comprobación de compatibilidad del equipo. Solo lectura: no modifica nada."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .commands import OVERLAY_SIZE_MB
from .state import UwfStatus

MB = 1024 * 1024


class Level(Enum):
    PASS = "CORRECTO"
    WARN = "AVISO"
    FAIL = "NO CUMPLE"
    UNKNOWN = "DESCONOCIDO"


@dataclass(frozen=True)
class Check:
    name: str
    level: Level
    detail: str


@dataclass
class CompatReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def verdict(self) -> tuple[str, str]:
        """(texto, nivel) del resultado global."""
        levels = {c.level for c in self.checks}
        critical = {c.level for c in self.checks if c.name in _CRITICAL}
        if Level.FAIL in levels:
            return "NO COMPATIBLE: este equipo no puede usar UWF", "bad"
        if Level.UNKNOWN in critical:
            return "NO SE PUEDE DETERMINAR: faltan datos para confirmar la compatibilidad", "unknown"
        if Level.WARN in levels or Level.UNKNOWN in levels:
            return "COMPATIBLE CON AVISOS: revise los puntos marcados", "warn"
        return "COMPATIBLE: este equipo puede usar UWF", "ok"

    def as_text(self) -> str:
        lines = [f"Compatibilidad UWF — {self.verdict[0]}", ""]
        lines += [f"[{c.level.value}] {c.name}: {c.detail}" for c in self.checks]
        return "\n".join(lines)


_CRITICAL = {"Versión de Windows", "Edición de Windows", "Característica UWF"}


def evaluate(st: UwfStatus) -> CompatReport:
    r = CompatReport()
    add = lambda name, level, detail: r.checks.append(Check(name, level, detail))

    if not st.query_ok:
        add("Consulta del sistema", Level.UNKNOWN,
            "No se pudo leer la información de Windows. " + "; ".join(st.errors[:2]))

    b = st.windows_build
    if b is None:
        add("Versión de Windows", Level.UNKNOWN, "No se pudo leer la versión.")
    elif b >= 22000:
        add("Versión de Windows", Level.PASS, f"Windows 11 (compilación {b}).")
    elif b >= 10240:
        add("Versión de Windows", Level.PASS, f"Windows 10 (compilación {b}). UWF existe en Windows 10.")
    else:
        add("Versión de Windows", Level.FAIL, f"Compilación {b}: anterior a Windows 10.")

    ed = st.edition_id
    if st.edition_supported is True:
        add("Edición de Windows", Level.PASS, f"{ed}: incluye UWF.")
    elif st.edition_supported is False:
        add("Edición de Windows", Level.FAIL,
            f"{ed}: UWF solo está en las ediciones Enterprise, Education e IoT Enterprise.")
    else:
        add("Edición de Windows", Level.UNKNOWN, "No se pudo leer la edición.")

    if st.is_64bit is True:
        add("Arquitectura", Level.PASS, "64 bits.")
    elif st.is_64bit is False:
        add("Arquitectura", Level.WARN, "32 bits: esta aplicación no se ha probado en 32 bits.")
    else:
        add("Arquitectura", Level.UNKNOWN, "No se pudo leer la arquitectura.")

    if st.is_admin:
        add("Privilegios de administrador", Level.PASS, "La aplicación se ejecuta como administrador.")
    else:
        add("Privilegios de administrador", Level.WARN,
            "Sin privilegios: hacen falta para activar o desactivar la congelación.")

    fs = st.feature_state
    if fs == "Enabled":
        add("Característica UWF", Level.PASS, "Instalada.")
    elif fs == "Disabled":
        add("Característica UWF", Level.PASS, "Disponible; se instalará al pulsar «Activar».")
    elif fs == "EnablePending":
        add("Característica UWF", Level.WARN, "Instalándose: reinicie Windows para completarla.")
    elif fs == "NotPresent":
        add("Característica UWF", Level.FAIL, "Esta instalación de Windows no incluye UWF.")
    elif st.wmi_available:
        add("Característica UWF", Level.PASS, "UWF responde (instalada).")
    else:
        why = "" if st.is_admin else " Hace falta ejecutar como administrador para comprobarlo."
        add("Característica UWF", Level.UNKNOWN, "No se pudo comprobar." + why)

    if st.uwfmgr_path:
        add("Herramienta uwfmgr.exe", Level.PASS, st.uwfmgr_path)
    elif st.feature_installed:
        add("Herramienta uwfmgr.exe", Level.FAIL, "La característica figura instalada pero falta uwfmgr.exe.")
    elif fs == "NotPresent":
        pass  # sin la característica no habrá uwfmgr.exe; ya se indica arriba
    else:
        add("Herramienta uwfmgr.exe", Level.PASS, "Se instala junto con la característica UWF.")

    if st.feature_installed:
        if st.wmi_available:
            add("Servicio UWF", Level.PASS, "Responde a las consultas de configuración.")
        else:
            add("Servicio UWF", Level.WARN, "No responde; suele resolverse reiniciando Windows.")

    free = st.c_free_bytes
    need = OVERLAY_SIZE_MB * MB
    if free is None:
        add("Espacio libre en C:", Level.UNKNOWN, "No se pudo leer el espacio libre.")
    else:
        gb = free / (1024 * MB)
        if free >= 2 * need:
            add("Espacio libre en C:", Level.PASS, f"{gb:.1f} GB libres.")
        else:
            add("Espacio libre en C:", Level.WARN,
                f"Solo {gb:.1f} GB libres; la superposición en disco de {OVERLAY_SIZE_MB} MB "
                "usa espacio de C: y podría fallar o llenarse.")
    return r

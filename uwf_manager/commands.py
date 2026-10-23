"""Únicos comandos que la aplicación puede lanzar para modificar el sistema.

Todas las herramientas se invocan con su ruta absoluta en System32.
"""
from __future__ import annotations

from .state import FEATURE_NAME, TARGET_VOLUME
from .system import system32

OVERLAY_SIZE_MB = 2048  # «Activar congelación»; uwfmgr overlay set-size usa megabytes
OVERLAY_TYPE = "disk"

# Perfil recomendado («Aplicar configuración recomendada»)
PROFILE_SIZE_MB = 4096
PROFILE_KEY = r"HKLM\SOFTWARE\UWFManager"  # indicador de progreso del perfil (un único valor)
PROFILE_VALUE = "RecommendedProfilePhase"


def uwfmgr(*args: str) -> list[str]:
    return [system32("uwfmgr.exe"), *args]


def enable_feature() -> list[str]:
    # DISM devuelve 3010 si hace falta reiniciar, lo que facilita distinguirlo; /NoRestart evita reiniciar.
    return [system32("dism.exe"), "/Online", "/Enable-Feature", f"/FeatureName:{FEATURE_NAME}", "/All",
            "/NoRestart"]


def overlay_set_size(size_mb: int = OVERLAY_SIZE_MB) -> list[str]:
    return uwfmgr("overlay", "set-size", str(size_mb))


def overlay_set_type(kind: str = OVERLAY_TYPE) -> list[str]:
    return uwfmgr("overlay", "set-type", kind)


def overlay_set_passthrough_on() -> list[str]:
    return uwfmgr("overlay", "set-passthrough", "ON")


def overlay_set_persistent_off() -> list[str]:
    return uwfmgr("overlay", "set-persistent", "OFF")


def overlay_reset_persistent_state() -> list[str]:
    return uwfmgr("overlay", "reset-persistentstate", "ON")


def volume_protect() -> list[str]:
    return uwfmgr("volume", "protect", TARGET_VOLUME)


def filter_enable() -> list[str]:
    return uwfmgr("filter", "enable")


def filter_disable() -> list[str]:
    return uwfmgr("filter", "disable")


def registry_commit(key: str, value: str) -> list[str]:
    """Hace persistente un único valor del Registro escrito durante una sesión protegida."""
    return uwfmgr("registry", "commit", key, value)


def registry_commit_delete(key: str, value: str) -> list[str]:
    return uwfmgr("registry", "commit-delete", key, value)


def restart_now() -> list[str]:
    """Solo se usa cuando el usuario pulsa «Reiniciar ahora»."""
    return [system32("shutdown.exe"), "/r", "/t", "0"]


READ_ONLY_REPORT = (
    ("get-config",), ("overlay", "get-config"), ("overlay", "get-consumption"),
    ("overlay", "get-available-space"), ("volume", "get-config", TARGET_VOLUME),
)

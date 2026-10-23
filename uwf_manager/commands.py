"""Únicos comandos que la aplicación puede lanzar para modificar el sistema."""
from __future__ import annotations

from .state import FEATURE_NAME, TARGET_VOLUME

OVERLAY_SIZE_MB = 2048  # uwfmgr overlay set-size usa megabytes
OVERLAY_TYPE = "disk"


def enable_feature() -> list[str]:
    # DISM devuelve 3010 si hace falta reiniciar, lo que facilita distinguirlo; /NoRestart evita reiniciar.
    return ["dism.exe", "/Online", "/Enable-Feature", f"/FeatureName:{FEATURE_NAME}", "/All", "/NoRestart"]


def overlay_set_size() -> list[str]:
    return ["uwfmgr.exe", "overlay", "set-size", str(OVERLAY_SIZE_MB)]


def overlay_set_type() -> list[str]:
    return ["uwfmgr.exe", "overlay", "set-type", OVERLAY_TYPE]


def volume_protect() -> list[str]:
    return ["uwfmgr.exe", "volume", "protect", TARGET_VOLUME]


def filter_enable() -> list[str]:
    return ["uwfmgr.exe", "filter", "enable"]


def filter_disable() -> list[str]:
    return ["uwfmgr.exe", "filter", "disable"]

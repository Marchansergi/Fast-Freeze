"""Textos de estado para la interfaz (sin dependencias gráficas)."""
from __future__ import annotations

from dataclasses import dataclass

from .state import TARGET_VOLUME, UwfStatus

UNKNOWN = "Estado desconocido: no se pudo verificar"


@dataclass(frozen=True)
class Item:
    caption: str
    value: str
    level: str  # ok | warn | bad | unknown
    full: str | None = None  # texto completo cuando «título: valor» no se lee bien

    @property
    def text(self) -> str:
        return self.full or f"{self.caption}: {self.value}"


def describe(st: UwfStatus) -> dict[str, Item]:
    out: dict[str, Item] = {}

    if st.feature_installed is None:
        out["feature"] = Item("Característica UWF", UNKNOWN, "unknown")
    elif st.feature_installed:
        out["feature"] = Item("Característica UWF", "INSTALADA", "ok")
    elif st.feature_pending:
        out["feature"] = Item("Característica UWF", "PENDIENTE DE REINICIO", "warn")
    elif st.feature_state == "NotPresent":
        out["feature"] = Item("Característica UWF", "NO DISPONIBLE EN ESTA EDICIÓN", "bad")
    else:
        out["feature"] = Item("Característica UWF", "NO INSTALADA", "warn")

    if st.filter_current is None:
        out["filter"] = Item("UWF", UNKNOWN, "unknown")
    else:
        value = "ACTIVO" if st.filter_current else "DESACTIVADO"
        if st.filter_next is not None and st.filter_next != st.filter_current:
            value += f" (tras reiniciar: {'ACTIVO' if st.filter_next else 'DESACTIVADO'})"
        out["filter"] = Item("UWF", value, "ok" if st.filter_current else "warn")

    vol = f"Protección {TARGET_VOLUME}"
    cur, nxt = st.c_current, st.c_next
    if nxt is True and cur is True:
        out["volume"] = Item(vol, "CONFIGURADA (activa en esta sesión)", "ok")
    elif nxt is True:
        out["volume"] = Item(vol, "CONFIGURADA (se aplicará tras reiniciar)", "warn")
    elif cur is True and nxt is False:
        out["volume"] = Item(vol, "ACTIVA ahora; se quitará al reiniciar", "warn")
    elif nxt is False and cur in (False, None):
        out["volume"] = Item(vol, "NO CONFIGURADA", "warn")
    else:
        out["volume"] = Item(vol, UNKNOWN, "unknown")

    rp = st.reboot_pending
    if rp is True:
        out["reboot"] = Item("Reinicio", "PENDIENTE", "warn", "Reinicio pendiente")
    elif rp is False:
        out["reboot"] = Item("Reinicio", "Sin cambios pendientes", "ok", "Sin cambios pendientes de reinicio")
    else:
        out["reboot"] = Item("Reinicio", "Posible cambio pendiente (no se puede determinar)", "unknown",
                             "Posible cambio pendiente de reinicio (no se puede determinar)")

    ov = st.overlay_next
    if ov:
        size = f"{ov.size_mb} MB" if ov.size_mb is not None else "? MB"
        out["overlay"] = Item("Superposición (próximo inicio)", f"{ov.type or '?'} · {size}", "ok")
    else:
        out["overlay"] = Item("Superposición", UNKNOWN, "unknown")

    win = st.windows_caption or "Windows (versión desconocida)"
    build = f" · compilación {st.windows_build}" if st.windows_build else ""
    out["system"] = Item("Sistema", f"{win}{build}", "ok" if st.query_ok else "unknown")
    return out


def headline(st: UwfStatus) -> Item:
    """Resumen principal: ¿está el equipo congelado ahora mismo?"""
    if st.filter_current is True and st.c_current is True:
        return Item("Estado del equipo", "CONGELADO · los cambios en C: se descartan al reiniciar", "ok")
    if st.filter_current is False or st.c_current is False:
        if st.filter_next is True and st.c_next is True:
            return Item("Estado del equipo", "SIN CONGELAR · se congelará al reiniciar", "warn")
        return Item("Estado del equipo", "SIN CONGELAR · los cambios se conservan", "warn")
    return Item("Estado del equipo", "DESCONOCIDO · no se pudo verificar", "unknown")

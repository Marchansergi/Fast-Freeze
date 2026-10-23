"""Textos de estado para la interfaz (sin dependencias gráficas)."""
from __future__ import annotations

from .state import TARGET_VOLUME, UwfStatus

UNKNOWN = "Estado desconocido: no se pudo verificar"


def _yes_no(v: bool | None, yes: str, no: str) -> str:
    return UNKNOWN if v is None else (yes if v else no)


def describe(st: UwfStatus) -> dict[str, tuple[str, str]]:
    """Devuelve {clave: (texto, nivel)}; nivel ∈ ok | warn | bad | unknown."""
    out: dict[str, tuple[str, str]] = {}

    if st.feature_installed is None:
        out["feature"] = ("Característica UWF: " + UNKNOWN, "unknown")
    elif st.feature_installed:
        out["feature"] = ("Característica UWF: INSTALADA", "ok")
    else:
        txt = "PENDIENTE DE REINICIO" if st.feature_pending else "NO INSTALADA"
        out["feature"] = (f"Característica UWF: {txt}", "warn")

    if st.filter_current is None:
        out["filter"] = ("UWF: " + UNKNOWN, "unknown")
    else:
        text = "UWF: ACTIVO" if st.filter_current else "UWF: DESACTIVADO"
        if st.filter_next is not None and st.filter_next != st.filter_current:
            text += f" (tras reiniciar: {'ACTIVO' if st.filter_next else 'DESACTIVADO'})"
        out["filter"] = (text, "ok" if st.filter_current else "warn")

    vol = f"Protección {TARGET_VOLUME}:"
    cur, nxt = st.c_current, st.c_next
    if cur is None and nxt is None:
        out["volume"] = (f"{vol} {UNKNOWN}", "unknown")
    elif nxt is True and cur is True:
        out["volume"] = (f"{vol} CONFIGURADA (activa en esta sesión)", "ok")
    elif nxt is True:
        out["volume"] = (f"{vol} CONFIGURADA (se aplicará tras reiniciar)", "warn")
    elif cur is True and nxt is False:
        out["volume"] = (f"{vol} ACTIVA ahora; se quitará al reiniciar", "warn")
    elif nxt is False and cur in (False, None):
        out["volume"] = (f"{vol} NO CONFIGURADA", "warn")
    else:
        out["volume"] = (f"{vol} {UNKNOWN}", "unknown")

    rp = st.reboot_pending
    if rp is True:
        out["reboot"] = ("Reinicio pendiente", "warn")
    elif rp is False:
        out["reboot"] = ("Sin cambios pendientes de reinicio", "ok")
    else:
        out["reboot"] = ("Posible cambio pendiente de reinicio (no se puede determinar)", "unknown")

    ov = st.overlay_next
    out["overlay"] = (("Superposición (próxima sesión): "
                       f"{ov.type or '?'} / {ov.size_mb if ov.size_mb is not None else '?'} MB")
                      if ov else "Superposición: " + UNKNOWN, "ok" if ov else "unknown")

    win = st.windows_caption or "Windows (versión desconocida)"
    admin = "administrador" if st.is_admin else "SIN privilegios de administrador"
    out["system"] = (f"{win} · {st.edition_id or 'edición desconocida'} · {admin}",
                     "ok" if st.is_admin else "warn")
    return out

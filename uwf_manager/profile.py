"""Perfil recomendado de UWF: valores y evaluación de en qué fase se encuentra.

La fase se deduce del estado real (sesión actual y siguiente). El indicador guardado en el
Registro solo sirve para distinguir casos que el estado no puede distinguir por sí solo
(p. ej. «UWF desactivado porque estamos en la fase de mantenimiento»).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from . import progress
from .commands import PROFILE_SIZE_MB
from .state import TARGET_VOLUME, OverlayInfo, UwfStatus

APPLY_TEXT = "Aplicar configuración recomendada"
CONTINUE_TEXT = "Continuar configuración recomendada"

SUMMARY = (
    ("Overlay", "disco"),
    ("Reserva", f"{PROFILE_SIZE_MB} MB"),
    ("Acceso al espacio libre", "activado"),
    ("Persistencia del overlay", "desactivada"),
    ("Volumen protegido", TARGET_VOLUME),
    ("Restauración al reiniciar", "activada"),
)


class Phase(Enum):
    APPLIED = "aplicada"
    UNVERIFIED = "sin verificar"
    PENDING_REBOOT = "pendiente de reinicio"
    MAINTENANCE_REBOOT = "fase 1: reinicio de mantenimiento pendiente"
    CONTINUE = "fase 2 pendiente"
    FEATURE_REBOOT = "instalación pendiente de reinicio"
    NOT_APPLIED = "no aplicada"
    NOT_AVAILABLE = "no disponible"
    UNKNOWN = "desconocida"


@dataclass(frozen=True)
class Row:
    label: str
    current: bool | None
    next: bool | None


@dataclass(frozen=True)
class Assessment:
    phase: Phase
    message: str
    level: str  # ok | warn | bad | unknown | neutral
    rows: tuple[Row, ...] = ()

    @property
    def button_text(self) -> str:
        return CONTINUE_TEXT if self.phase is Phase.CONTINUE else APPLY_TEXT

    @property
    def can_apply(self) -> bool:
        return self.phase is not Phase.NOT_AVAILABLE


def _ov(o: OverlayInfo | None, attr: str, expected) -> bool | None:
    value = getattr(o, attr) if o is not None else None
    return None if value is None else value == expected


def rows(st: UwfStatus) -> tuple[Row, ...]:
    cur, nxt = st.overlay_current, st.overlay_next
    return (
        Row("Overlay en disco", _ov(cur, "type", "DISK"), _ov(nxt, "type", "DISK")),
        Row(f"Reserva de {PROFILE_SIZE_MB} MB", _ov(cur, "size_mb", PROFILE_SIZE_MB),
            _ov(nxt, "size_mb", PROFILE_SIZE_MB)),
        Row("Acceso al espacio libre", _ov(cur, "passthrough", True), _ov(nxt, "passthrough", True)),
        Row("Overlay no persistente", _ov(cur, "persistent", False), _ov(nxt, "persistent", False)),
        Row(f"{TARGET_VOLUME} protegido", st.c_current, st.c_next),
        Row("Filtro UWF activo", st.filter_current, st.filter_next),
    )


def assess(st: UwfStatus, marker: str | None) -> Assessment:
    if not st.query_ok:
        return Assessment(Phase.UNKNOWN, "No se pudo comprobar el estado de UWF.", "unknown")
    if st.edition_supported is False or st.feature_state == "NotPresent":
        return Assessment(Phase.NOT_AVAILABLE,
                          f"Este equipo no admite UWF (edición {st.edition_id or 'desconocida'}).", "bad")
    if st.feature_pending:
        return Assessment(Phase.FEATURE_REBOOT, "Falta reiniciar Windows para terminar de instalar UWF.", "warn")
    if st.feature_installed is False:
        return Assessment(Phase.NOT_APPLIED, "No aplicada. UWF no está instalado: el botón lo instalará.",
                          "neutral")
    if st.feature_installed is None or not st.wmi_available:
        if marker == progress.FEATURE:
            return Assessment(Phase.FEATURE_REBOOT, "Falta reiniciar Windows para terminar de instalar UWF.",
                              "warn")
        return Assessment(Phase.UNKNOWN, "No se pudo comprobar la configuración de UWF.", "unknown")

    r = rows(st)
    cur = [x.current for x in r]
    nxt = [x.next for x in r]
    if all(v is True for v in cur + nxt):
        return Assessment(Phase.APPLIED, "Aplicada y activa: los cambios de cada sesión se descartan al "
                                         "reiniciar.", "ok", r)
    if False not in nxt:
        if False in cur:
            extra = _unknown_note(r)
            return Assessment(Phase.PENDING_REBOOT, "Configurada para el próximo inicio. Falta reiniciar "
                                                    "para que se active." + extra, "warn", r)
        return Assessment(Phase.UNVERIFIED, "Parece aplicada, pero no se pudo verificar todo." +
                          _unknown_note(r), "unknown", r)
    if marker == progress.MAINTENANCE:
        if st.filter_current is True and st.filter_next is False:
            return Assessment(Phase.MAINTENANCE_REBOOT,
                              "Fase 1 de 2 hecha. Al reiniciar, Windows arrancará SIN protección UWF "
                              f"(mantenimiento); después pulse «{CONTINUE_TEXT}».", "warn", r)
        if st.filter_current is False:
            return Assessment(Phase.CONTINUE, "Fase 2 de 2 pendiente. UWF está desactivado en esta sesión: "
                                              f"pulse «{CONTINUE_TEXT}».", "warn", r)
    if marker == progress.FEATURE:
        return Assessment(Phase.CONTINUE, f"UWF ya está instalado. Pulse «{CONTINUE_TEXT}».", "warn", r)
    return Assessment(Phase.NOT_APPLIED, "No aplicada.", "neutral", r)


def _unknown_note(r: tuple[Row, ...]) -> str:
    unknown = [x.label for x in r if x.current is None or x.next is None]
    return f" No se pudo verificar: {', '.join(unknown).lower()}." if unknown else ""

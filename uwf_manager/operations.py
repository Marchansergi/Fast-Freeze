"""Lógica de activación y desactivación de la congelación, por fases y verificada."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import commands
from .errors import ErrorKind, classify, explain, succeeded
from .logs import get_logger
from .runner import CommandResult, CommandRunner
from .state import TARGET_VOLUME, OverlayInfo, UwfQuery, UwfStatus

EXPECTED_OVERLAY = OverlayInfo("DISK", commands.OVERLAY_SIZE_MB)


@dataclass
class Step:
    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False
    verified: bool | None = None  # None = no se pudo verificar


@dataclass
class OperationResult:
    title: str
    steps: list[Step] = field(default_factory=list)
    status: UwfStatus | None = None
    reboot_required: bool = False
    stopped: bool = False  # secuencia detenida antes de completarse
    summary: str = ""

    @property
    def ok(self) -> bool:
        return not self.stopped and all(s.ok for s in self.steps)

    @property
    def verified(self) -> bool:
        return self.ok and all(s.verified is not False and (s.skipped or s.verified) for s in self.steps)

    def lines(self) -> list[str]:
        out = []
        for s in self.steps:
            mark = "OMITIDO" if s.skipped else ("OK" if s.ok else "ERROR")
            if s.ok and not s.skipped and s.verified is None:
                mark = "OK (sin verificar)"
            out.append(f"[{mark}] {s.name}" + (f": {s.detail}" if s.detail else ""))
        out.append(self.summary)
        return out


class Operations:
    def __init__(self, runner: CommandRunner, query: UwfQuery) -> None:
        self.runner = runner
        self.query = query
        self.log = get_logger()

    # ---- utilidades ----
    def _fail(self, res: OperationResult, name: str, detail: str, status: UwfStatus | None = None) -> OperationResult:
        res.steps.append(Step(name, False, detail))
        res.stopped = True
        res.summary = f"Secuencia detenida: {detail}"
        res.status = status or res.status
        self.log.error("%s: %s", res.title, res.summary)
        return res

    def _finish(self, res: OperationResult, summary: str) -> OperationResult:
        res.status = self.query.read()
        res.reboot_required = res.reboot_required or res.status.reboot_pending is True
        res.summary = summary
        self.log.info("%s: %s | reinicio=%s", res.title, summary, res.reboot_required)
        return res

    def _step(self, res: OperationResult, name: str, args: list[str],
              verify: Callable[[UwfStatus], bool | None]) -> tuple[bool, UwfStatus | None, ErrorKind]:
        """Ejecuta un comando, comprueba el estado posterior y registra el paso."""
        result: CommandResult = self.runner.run(args)
        kind = classify(result)
        self.log.info("PASO %s -> %s rc=%s", name, kind.value, result.returncode)
        if not succeeded(kind):
            self._fail(res, name, explain(kind, result))
            return False, None, kind
        status = self.query.read()
        verdict = verify(status)
        self.log.info("VERIFICACION %s -> %s", name, verdict)
        if verdict is False:
            self._fail(res, name, "El comando terminó sin error, pero la comprobación posterior "
                                  "no confirma el cambio.", status)
            return False, status, kind
        res.steps.append(Step(name, True, "reinicio requerido" if kind is ErrorKind.REBOOT_REQUIRED else "",
                              verified=verdict))
        res.status = status
        return True, status, kind

    # ---- activar ----
    def enable_freeze(self) -> OperationResult:
        res = OperationResult("Activar congelación y protección")
        self.log.info("OPERACION %s", res.title)
        st = self.query.read()
        res.status = st

        # A. comprobaciones previas
        if not st.is_admin:
            return self._fail(res, "Permisos", "Se requieren privilegios de administrador.", st)
        if st.edition_supported is False:
            return self._fail(res, "Edición de Windows",
                              f"La edición «{st.edition_id}» no admite UWF (requiere Enterprise, Education o IoT Enterprise).", st)
        if st.edition_supported is None:
            res.steps.append(Step("Edición de Windows", True, "no se pudo determinar; se continúa", verified=None))
        if st.is_windows_11 is False:
            res.steps.append(Step("Versión de Windows", True,
                                  "no es Windows 11 (compilación < 22000); no está verificado", verified=None))

        # B. característica opcional
        if st.feature_pending:
            res.reboot_required = True
            return self._finish_stop(res, "La característica UWF está habilitándose y necesita un reinicio. "
                                          "Reinicie Windows y vuelva a pulsar el botón.")
        if st.feature_installed is None:
            return self._fail(res, "Característica UWF", "No se pudo verificar si UWF está instalado.", st)
        if st.feature_installed is False:
            ok, st2, kind = self._step(res, "Habilitar característica UWF", commands.enable_feature(),
                                       lambda s: None)
            if not ok:
                return res
            st2 = st2 or self.query.read()
            if kind is ErrorKind.REBOOT_REQUIRED or not st2.wmi_available:
                res.reboot_required = True
                return self._finish_stop(res, "La característica UWF se ha habilitado, pero hay que reiniciar "
                                              "Windows para completarla. UWF todavía NO está operativo; "
                                              "vuelva a pulsar el botón tras reiniciar.")
            st = st2
        else:
            res.steps.append(Step("Habilitar característica UWF", True, "ya habilitada", skipped=True))

        if not st.wmi_available:
            return self._fail(res, "Estado de UWF", "UWF no responde; no se puede configurar.", st)
        if not st.uwfmgr_path:
            return self._fail(res, "uwfmgr.exe", "No se encontró uwfmgr.exe.", st)

        # C. superposición
        if st.overlay_next == EXPECTED_OVERLAY:
            res.steps.append(Step("Superposición DISK 2048 MB", True, "ya configurada", skipped=True, verified=True))
        else:
            for name, args in (("Tamaño de superposición 2048 MB", commands.overlay_set_size()),
                               ("Tipo de superposición DISK", commands.overlay_set_type())):
                ok, st, _ = self._step(res, name, args, _verify_overlay_part)
                if not ok:
                    return res
            if st and st.overlay_next is not None and st.overlay_next != EXPECTED_OVERLAY:
                return self._fail(res, "Superposición", "La configuración resultante no coincide con DISK/2048 MB.", st)

        # D. protección de C:
        if st.c_next is True:
            res.steps.append(Step(f"Proteger {TARGET_VOLUME}", True, "ya configurada", skipped=True, verified=True))
        else:
            ok, st, _ = self._step(res, f"Proteger {TARGET_VOLUME}", commands.volume_protect(),
                                   lambda s: s.c_next if s.wmi_available else None)
            if not ok:
                return res

        # E. activar el filtro
        if st.filter_next is True:
            res.steps.append(Step("Habilitar filtro", True, "ya programado/activo", skipped=True, verified=True))
        else:
            ok, st, _ = self._step(res, "Habilitar filtro", commands.filter_enable(),
                                   lambda s: s.filter_next)
            if not ok:
                return res

        # F. resultado
        final = self.query.read()
        res.status = final
        res.reboot_required = final.reboot_pending is True
        if final.filter_next is True and final.c_next is True:
            msg = ("Configuración completada. La congelación se activará tras reiniciar Windows."
                   if final.filter_current is not True else
                   "Configuración completada; el filtro ya estaba activo en esta sesión.")
        else:
            res.stopped = True
            msg = "No se pudo confirmar que la configuración final esté completa."
        res.summary = msg + (" Reinicie cuando lo desee (no se reinicia automáticamente)." if res.reboot_required else "")
        self.log.info("%s: %s", res.title, res.summary)
        return res

    def _finish_stop(self, res: OperationResult, message: str) -> OperationResult:
        res.stopped = False
        res.status = self.query.read()
        res.summary = message
        self.log.info("%s: %s", res.title, message)
        return res

    # ---- desactivar ----
    def disable_freeze(self) -> OperationResult:
        res = OperationResult("Desactivar congelación")
        self.log.info("OPERACION %s", res.title)
        st = self.query.read()
        res.status = st
        if not st.is_admin:
            return self._fail(res, "Permisos", "Se requieren privilegios de administrador.", st)
        if not st.uwfmgr_path:
            return self._fail(res, "uwfmgr.exe", "No se encontró uwfmgr.exe.", st)
        if st.feature_installed is not True or not st.wmi_available:
            return self._fail(res, "Estado de UWF",
                              "UWF no está instalado o no responde; no hay nada que desactivar.", st)
        if st.filter_current is None or st.filter_next is None:
            return self._fail(res, "Estado del filtro", "No se pudo verificar el estado del filtro.", st)
        if st.filter_current is False and st.filter_next is False:
            res.steps.append(Step("Deshabilitar filtro", True, "ya está desactivado", skipped=True, verified=True))
            return self._finish(res, "UWF ya estaba desactivado; no se ejecutó ninguna operación.")

        protected_before = st.c_next

        def verify(s: UwfStatus) -> bool | None:
            return None if s.filter_next is None else s.filter_next is False

        ok, st2, _ = self._step(res, "Deshabilitar filtro", commands.filter_disable(), verify)
        if not ok:
            return res
        if protected_before is True and st2 and st2.c_next is not True:
            return self._fail(res, f"Protección de {TARGET_VOLUME}",
                              "La configuración de protección de C: ya no figura como conservada.", st2)
        res.steps.append(Step(f"Conservar protección de {TARGET_VOLUME}", True,
                              "se mantiene configurada" if protected_before else "no estaba configurada",
                              verified=None if st2 is None or st2.c_next is None else True))
        final = self.query.read()
        res.status = final
        res.reboot_required = final.reboot_pending is True
        res.summary = ("Filtro deshabilitado para el próximo inicio. "
                       + ("Reinicie Windows para completar el cambio (no se reinicia automáticamente)."
                          if res.reboot_required else "No hay reinicio pendiente."))
        self.log.info("%s: %s", res.title, res.summary)
        return res


def _verify_overlay_part(s: UwfStatus) -> bool | None:
    return None if s.overlay_next is None else True

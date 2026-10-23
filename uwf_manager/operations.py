"""Lógica de activación y desactivación de la congelación, por fases y verificada."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import commands, progress
from .errors import ErrorKind, classify, explain, succeeded
from .logs import get_logger
from .profile import CONTINUE_TEXT, Assessment, Phase, assess
from .progress import ProgressStore
from .runner import CommandResult, CommandRunner
from .state import TARGET_VOLUME, UwfQuery, UwfStatus


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
    needs_confirmation: str | None = None  # pregunta que la interfaz debe hacer antes de seguir
    assessment: Assessment | None = None   # fase del perfil recomendado al terminar

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
    def __init__(self, runner: CommandRunner, query: UwfQuery, store: ProgressStore | None = None) -> None:
        self.runner = runner
        self.query = query
        self.store = store or ProgressStore(runner)
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
        st = self._ensure_feature(res, st, "vuelva a pulsar el botón tras reiniciar")
        if st is None:
            return res

        # C. superposición (si ya es DISK se conserva, p. ej. la del perfil recomendado)
        if st.overlay_next is not None and st.overlay_next.type == "DISK":
            res.steps.append(Step("Superposición DISK", True, "ya configurada; se conserva", skipped=True,
                                  verified=True))
        elif st.filter_current is not False:
            return self._fail(res, "Superposición", "No se puede cambiar la superposición a DISK mientras UWF "
                                                    "está activo en esta sesión. Use «Aplicar configuración "
                                                    "recomendada», que lo hace en dos fases.", st)
        else:
            for name, args in (("Tamaño de superposición 2048 MB", commands.overlay_set_size()),
                               ("Tipo de superposición DISK", commands.overlay_set_type())):
                ok, st, _ = self._step(res, name, args, _verify_overlay_part)
                if not ok:
                    return res
            if st and st.overlay_next is not None and st.overlay_next.type not in (None, "DISK"):
                return self._fail(res, "Superposición", "La superposición resultante no es DISK.", st)

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

    def _ensure_feature(self, res: OperationResult, st: UwfStatus, retry_hint: str,
                        on_reboot=None) -> UwfStatus | None:
        """Instala la característica si falta. Devuelve el estado o None si hay que parar."""
        if st.feature_pending:
            res.reboot_required = True
            if on_reboot:
                on_reboot(res)
            self._finish_stop(res, "La característica UWF está habilitándose y necesita un reinicio. "
                                   f"Reinicie Windows y {retry_hint}.")
            return None
        if st.feature_installed is None:
            self._fail(res, "Característica UWF", "No se pudo verificar si UWF está instalado.", st)
            return None
        if st.feature_installed is False:
            ok, st2, kind = self._step(res, "Habilitar característica UWF", commands.enable_feature(),
                                       lambda s: None)
            if not ok:
                return None
            st2 = st2 or self.query.read()
            if kind is ErrorKind.REBOOT_REQUIRED or not st2.wmi_available:
                res.reboot_required = True
                if on_reboot:
                    on_reboot(res)
                self._finish_stop(res, "La característica UWF se ha habilitado, pero hay que reiniciar "
                                       "Windows para completarla. UWF todavía NO está operativo; "
                                       f"{retry_hint}.")
                return None
            st = st2
        else:
            res.steps.append(Step("Habilitar característica UWF", True, "ya habilitada", skipped=True))
        if not st.wmi_available:
            self._fail(res, "Estado de UWF", "UWF no responde; no se puede configurar.", st)
            return None
        if not st.uwfmgr_path:
            self._fail(res, "uwfmgr.exe", "No se encontró uwfmgr.exe en System32.", st)
            return None
        return st

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


    # ---- perfil recomendado ----
    def assess_profile(self, st: UwfStatus | None = None) -> tuple[UwfStatus, Assessment]:
        st = st or self.query.read()
        return st, assess(st, self.store.read())

    def apply_profile(self, allow_discard_persistent: bool = False) -> OperationResult:
        """Aplica el perfil recomendado por fases. Idempotente; nunca reinicia."""
        res = OperationResult("Aplicar configuración recomendada")
        self.log.info("OPERACION %s", res.title)
        st = self.query.read()
        res.status = st

        if not st.is_admin:
            return self._fail(res, "Permisos", "Se requieren privilegios de administrador.", st)
        if st.edition_supported is False or st.feature_state == "NotPresent":
            return self._fail(res, "Edición de Windows",
                              f"La edición «{st.edition_id}» no incluye UWF (requiere Enterprise, Education "
                              "o IoT Enterprise).", st)

        def remember_feature(r: OperationResult) -> None:
            self._note(r, "Guardar progreso", self.store.write(progress.FEATURE, session_protected=False))

        st = self._ensure_feature(res, st, f"vuelva a abrir la aplicación y pulse «{CONTINUE_TEXT}»",
                                  on_reboot=remember_feature)
        if st is None:
            res.assessment = self.assess_profile(res.status)[1] if res.status else None
            return res

        ov_now, ov_next = st.overlay_current, st.overlay_next
        if None in (st.filter_current, st.filter_next, st.c_next) or ov_next is None or ov_next.type is None:
            return self._fail(res, "Estado de UWF", "No se pudo verificar la configuración actual de UWF; "
                                                    "no se modifica nada.", st)

        start = assess(st, self.store.read())
        if start.phase in (Phase.APPLIED, Phase.PENDING_REBOOT) and not _missing(st):
            return self._profile_done(res, st, changed=False)

        persistent_now = ov_now.persistent if ov_now else None
        # Solo puede haber cambios acumulados si la sesión actual es persistente (o no se sabe).
        accumulated = persistent_now is True or (persistent_now is None and ov_next.persistent is True)
        if accumulated and not allow_discard_persistent:
            res.stopped = True
            res.needs_confirmation = (
                "La superposición está configurada como PERSISTENTE y puede contener cambios acumulados "
                "de sesiones anteriores.\n\nAl aplicar el perfil recomendado (no persistente), esos "
                "cambios acumulados se descartarán en el próximo reinicio, además de los cambios "
                "temporales habituales.\n\n¿Desea continuar?")
            res.summary = "Pendiente de confirmación: la superposición actual es persistente."
            return res

        protected_before = st.c_next

        # Caso B: hay que pasar a DISK con UWF activo en esta sesión -> fase 1 de mantenimiento.
        if ov_next.type != "DISK" and st.filter_current:
            if st.filter_next:
                ok, st2, _ = self._step(res, "Desactivar UWF para el próximo inicio (mantenimiento)",
                                        commands.filter_disable(),
                                        lambda s: None if s.filter_next is None else s.filter_next is False)
                if not ok:
                    return res
                st = st2 or st
            else:
                res.steps.append(Step("Desactivar UWF para el próximo inicio", True, "ya programado",
                                      skipped=True, verified=True))
            if protected_before and st.c_next is not True:
                return self._fail(res, f"Protección de {TARGET_VOLUME}",
                                  "La protección de C: ya no figura como configurada.", st)
            self._note(res, "Guardar progreso (fase 1 de 2)",
                       self.store.write(progress.MAINTENANCE, session_protected=True))
            res.status = self.query.read()
            res.assessment = assess(res.status, self.store.read())
            res.reboot_required = True
            res.summary = ("Fase 1 de 2 hecha. Para cambiar la superposición a disco, UWF debe estar "
                           "desactivado: tras reiniciar, Windows arrancará SIN la protección habitual de "
                           "UWF (sesión de mantenimiento). Después abra la aplicación y pulse "
                           f"«{CONTINUE_TEXT}». La protección de C: se conserva configurada.")
            self.log.info("%s: %s", res.title, res.summary)
            return res

        # Casos A, C y fase 2: aplicar lo que falte, en orden, verificando cada paso.
        def check(attr, expected):
            return lambda s: (None if s.overlay_next is None or getattr(s.overlay_next, attr) is None
                              else getattr(s.overlay_next, attr) == expected)

        plan = []
        if ov_next.type != "DISK":
            plan.append(("Superposición en disco", commands.overlay_set_type("DISK"), check("type", "DISK")))
        if ov_next.size_mb != commands.PROFILE_SIZE_MB:
            plan.append((f"Reserva de {commands.PROFILE_SIZE_MB} MB",
                         commands.overlay_set_size(commands.PROFILE_SIZE_MB),
                         check("size_mb", commands.PROFILE_SIZE_MB)))
        if ov_next.passthrough is not True:
            plan.append(("Acceso al espacio libre", commands.overlay_set_passthrough_on(),
                         check("passthrough", True)))
        if ov_next.persistent is not False:
            plan.append(("Overlay no persistente", commands.overlay_set_persistent_off(),
                         check("persistent", False)))
        if st.c_next is not True:
            plan.append((f"Proteger {TARGET_VOLUME}", commands.volume_protect(),
                         lambda s: s.c_next if s.wmi_available else None))
        if st.filter_next is not True:
            plan.append(("Activar UWF para el próximo inicio", commands.filter_enable(),
                         lambda s: s.filter_next))

        if persistent_now is True:  # confirmado por el usuario
            r = self.runner.run(commands.overlay_reset_persistent_state())
            kind = classify(r)
            self._note(res, "Restablecer la superposición persistente al reiniciar",
                       None if succeeded(kind) else
                       "no se pudo programar (" + explain(kind, r) + "). Al quedar no persistente, el "
                       "contenido acumulado debería descartarse igualmente al reiniciar; compruébelo.")

        for name, args, verify in plan:
            ok, st2, _ = self._step(res, name, args, verify)
            if not ok:
                return res
            st = st2 or st
            if protected_before and st.c_next is False:
                return self._fail(res, f"Protección de {TARGET_VOLUME}",
                                  "La protección de C: ya no figura como configurada.", st)
        return self._profile_done(res, st, changed=bool(plan))

    def _profile_done(self, res: OperationResult, st: UwfStatus, changed: bool) -> OperationResult:
        final = self.query.read()
        a = assess(final, None)  # tras aplicar, el indicador de fase ya no hace falta
        if a.phase in (Phase.APPLIED, Phase.PENDING_REBOOT, Phase.UNVERIFIED):
            self._note(res, "Borrar indicador de progreso",
                       self.store.clear(session_protected=final.filter_current is True), quiet=True)
        res.status, res.assessment = final, a
        res.reboot_required = a.phase is Phase.PENDING_REBOOT
        if a.phase is Phase.APPLIED:
            res.summary = ("La configuración recomendada ya estaba aplicada; no se ha cambiado nada."
                           if not changed else "Configuración recomendada aplicada y activa.")
        elif a.phase is Phase.PENDING_REBOOT:
            res.summary = (("La configuración recomendada ya está programada; " if not changed else
                            "Configuración recomendada programada; ")
                           + "falta reiniciar para activarla. No se ha reiniciado el equipo.")
        elif a.phase is Phase.UNVERIFIED:
            res.summary = "Comandos aplicados, pero no se pudo verificar todo. " + a.message
        else:
            res.stopped = True
            res.summary = "No se pudo confirmar la configuración final: " + a.message
        try:
            self.query.raw_report()  # detalles técnicos al registro (texto posiblemente traducido)
        except Exception:
            pass
        self.log.info("%s: %s", res.title, res.summary)
        return res

    def _note(self, res: OperationResult, name: str, warning: str | None, quiet: bool = False) -> None:
        """Paso auxiliar que no detiene la secuencia; si falla, se muestra como aviso."""
        if warning:
            res.steps.append(Step(name, True, "AVISO: " + warning, verified=False))
        elif not quiet:
            res.steps.append(Step(name, True, verified=True))

    # ---- reinicio (solo a petición explícita del usuario) ----
    def restart_now(self) -> tuple[bool, str]:
        r = self.runner.run(commands.restart_now(), timeout=30)
        kind = classify(r)
        self.log.info("REINICIO solicitado por el usuario -> %s", kind.value)
        return (True, "Reiniciando Windows…") if succeeded(kind) else (False, explain(kind, r))


def _missing(st: UwfStatus) -> bool:
    """¿Falta por configurar para el próximo inicio algo verificable o desconocido?"""
    ov = st.overlay_next
    return not (ov and ov.type == "DISK" and ov.size_mb == commands.PROFILE_SIZE_MB and ov.passthrough is True
                and ov.persistent is False and st.c_next is True and st.filter_next is True)


def _verify_overlay_part(s: UwfStatus) -> bool | None:
    return None if s.overlay_next is None else True

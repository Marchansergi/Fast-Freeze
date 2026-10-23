"""«Aplicar configuración recomendada»: todos los casos con un Windows simulado."""
import pytest

from tests.fakes import FakeRegistry, FakeWindows, exe
from uwf_manager import progress, system
from uwf_manager.operations import Operations
from uwf_manager.profile import APPLY_TEXT, CONTINUE_TEXT, Phase, assess
from uwf_manager.progress import ProgressStore
from uwf_manager.state import UwfQuery

DISK, RAM = 1, 0
READ_ONLY = ("get-config", "get-consumption", "get-available-space")


@pytest.fixture(autouse=True)
def admin(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(system, "find_executable", lambda name: r"C:\Windows\System32\uwfmgr.exe")


def ops_for(fake):
    r = fake.runner()
    return Operations(r, UwfQuery(r), ProgressStore(r, FakeRegistry(fake)))


def changes(fake):
    """Comandos uwfmgr que modifican algo (sin las consultas de solo lectura)."""
    out = []
    for c in fake.calls:
        if exe(c) == "uwfmgr.exe" and not any(q in c for q in READ_ONLY):
            out.append(" ".join(c[1:]))
    return out


def phase(fake):
    return ops_for(fake).assess_profile()[1]


def applied_fake(**kw):
    base = dict(filter_cur=True, filter_next=True, c_cur=True, c_next=True,
                overlay_cur=(DISK, 4096), overlay_next=(DISK, 4096),
                pass_cur=True, pass_next=True, persist_cur=False, persist_next=False)
    base.update(kw)
    return FakeWindows(**base)


FULL_PLAN = ["overlay set-type DISK", "overlay set-size 4096", "overlay set-passthrough ON",
             "overlay set-persistent OFF", "volume protect C:", "filter enable"]
NOT_PERSISTENT_YET = dict(persist_next=True)  # persistente solo para el próximo inicio: sin acumulados


def test_case_c_uwf_disabled_applies_profile_directly():
    f = FakeWindows(overlay_cur=(RAM, 1024), overlay_next=(RAM, 1024), **NOT_PERSISTENT_YET)
    res = ops_for(f).apply_profile()
    assert res.ok and res.reboot_required and res.needs_confirmation is None
    assert changes(f) == FULL_PLAN
    assert res.assessment.phase is Phase.PENDING_REBOOT
    assert "falta reiniciar" in res.summary and f.restarted == 0
    f.reboot()
    assert phase(f).phase is Phase.APPLIED


def test_case_a_uwf_enabled_with_disk_keeps_filter_on():
    f = FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True)  # DISK 2048
    res = ops_for(f).apply_profile()
    assert res.ok and res.reboot_required
    assert changes(f) == ["overlay set-size 4096", "overlay set-passthrough ON"]  # ya no persistente
    assert f.filter_next is True  # no se desactiva UWF si no hace falta
    f.reboot()
    assert phase(f).phase is Phase.APPLIED


def test_case_b_ram_with_uwf_enabled_needs_maintenance_reboot():
    f = FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True,
                    overlay_cur=(RAM, 1024), overlay_next=(RAM, 1024))
    res = ops_for(f).apply_profile()
    assert res.ok and res.reboot_required
    assert changes(f) == ["filter disable", "registry commit HKLM\\SOFTWARE\\UWFManager RecommendedProfilePhase"]
    assert "set-type" not in " ".join(changes(f))  # nunca con UWF activo en la sesión
    assert f.c_next is True and f.reg_persisted == progress.MAINTENANCE
    assert "SIN la protección" in res.summary and "Fase 1 de 2" in res.summary
    assert res.assessment.phase is Phase.MAINTENANCE_REBOOT


def test_case_b_resume_after_first_reboot_and_second_reboot():
    f = FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True,
                    overlay_cur=(RAM, 1024), overlay_next=(RAM, 1024))
    ops_for(f).apply_profile()
    f.reboot()  # sesión de mantenimiento: UWF desactivado
    a = phase(f)
    assert a.phase is Phase.CONTINUE and a.button_text == CONTINUE_TEXT
    assert f.filter_cur is False and f.c_next is True
    f.calls.clear()
    res = ops_for(f).apply_profile()
    assert res.ok and res.reboot_required and res.assessment.phase is Phase.PENDING_REBOOT
    assert changes(f) == ["overlay set-type DISK", "overlay set-size 4096", "overlay set-passthrough ON",
                          "filter enable"]  # C: ya protegida y overlay ya no persistente: se omiten
    assert f.reg_persisted is None  # fase terminada: indicador borrado
    f.reboot()
    a = phase(f)
    assert a.phase is Phase.APPLIED and a.button_text == APPLY_TEXT
    assert all(r.current and r.next for r in a.rows)


def test_c_protection_kept_in_every_step():
    f = FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True, overlay_next=(RAM, 1024),
                    overlay_cur=(RAM, 1024))
    seen = []
    original = f.run

    def spy(argv, **kw):
        out = original(argv, **kw)
        seen.append(f.c_next)
        return out
    f.run = spy
    ops = ops_for(f)
    ops.apply_profile()
    f.reboot()
    ops.apply_profile()
    f.reboot()
    assert all(seen) and f.c_cur is True
    assert not any("unprotect" in " ".join(c) for c in f.calls)


def test_already_applied_no_changes():
    f = applied_fake()
    res = ops_for(f).apply_profile()
    assert res.ok and not res.reboot_required
    assert changes(f) == []
    assert "ya estaba aplicada" in res.summary
    assert res.assessment.phase is Phase.APPLIED


def test_pending_reboot_detected_separately():
    f = applied_fake(filter_cur=False, overlay_cur=(RAM, 1024), pass_cur=False)
    a = phase(f)
    assert a.phase is Phase.PENDING_REBOOT
    rows = {r.label: r for r in a.rows}
    assert rows["Overlay en disco"].current is False and rows["Overlay en disco"].next is True
    res = ops_for(f).apply_profile()
    assert changes(f) == [] and res.reboot_required and "ya está programada" in res.summary


def test_feature_not_available():
    f = FakeWindows(feature="NotPresent", edition="Professional", wmi=False)
    res = ops_for(f).apply_profile()
    assert not res.ok and "no incluye UWF" in res.summary
    assert not any(exe(c) in ("uwfmgr.exe", "dism.exe") for c in f.calls)
    assert phase(f).phase is Phase.NOT_AVAILABLE and not phase(f).can_apply


def test_feature_install_needs_reboot_then_continue():
    f = FakeWindows(feature="Disabled", dism_rc=3010)
    res = ops_for(f).apply_profile()
    assert res.reboot_required and changes(f) == []  # nada de overlay sin UWF disponible
    assert f.reg_persisted == progress.FEATURE
    assert phase(f).phase is Phase.FEATURE_REBOOT
    f.reboot()
    assert phase(f).phase is Phase.CONTINUE
    res = ops_for(f).apply_profile()
    assert res.ok and res.assessment.phase is Phase.PENDING_REBOOT and f.reg_persisted is None


def test_no_admin_blocks(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: False)
    f = FakeWindows()
    res = ops_for(f).apply_profile()
    assert not res.ok and "administrador" in res.summary and changes(f) == []


def test_uac_cancel_does_not_start():
    r = system.relaunch_as_admin(lambda exe_, params: (5, system.ERROR_CANCELLED))
    assert r.cancelled and not r.started


@pytest.mark.parametrize("key", ["overlay set-size", "overlay set-passthrough", "overlay set-persistent",
                                 "volume protect"])
def test_intermediate_failure_stops_before_enabling(key):
    f = FakeWindows(fail={key: 1}, **NOT_PERSISTENT_YET)
    res = ops_for(f).apply_profile()
    assert not res.ok and res.stopped and "ERROR" in "\n".join(res.lines())
    assert "filter enable" not in changes(f) and f.filter_next is False


def test_filter_enable_failure_is_not_success():
    f = FakeWindows(fail={"filter enable": 1})
    res = ops_for(f).apply_profile()
    assert not res.ok and f.filter_next is False


def test_persistent_overlay_requires_confirmation():
    f = applied_fake(persist_cur=True, persist_next=True)
    res = ops_for(f).apply_profile()
    assert res.needs_confirmation and "PERSISTENTE" in res.needs_confirmation
    assert not res.ok and changes(f) == []
    res = ops_for(f).apply_profile(allow_discard_persistent=True)
    assert res.ok and res.reboot_required
    assert changes(f) == ["overlay reset-persistentstate ON", "overlay set-persistent OFF"]
    f.reboot()
    assert phase(f).phase is Phase.APPLIED and f.persist_cur is False


def test_reset_persistent_not_run_on_non_persistent_devices():
    f = FakeWindows(**NOT_PERSISTENT_YET)
    res = ops_for(f).apply_profile()
    assert res.needs_confirmation is None  # nada acumulado todavía: no se pregunta
    assert "overlay set-persistent OFF" in changes(f)
    assert not any("reset-persistentstate" in c for c in changes(f))


def test_reboot_postponed_keeps_phase_and_does_not_repeat():
    f = FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True,
                    overlay_cur=(RAM, 1024), overlay_next=(RAM, 1024))
    ops_for(f).apply_profile()
    f.calls.clear()  # «Más tarde»: el usuario vuelve a pulsar sin reiniciar
    res = ops_for(f).apply_profile()
    assert "filter disable" not in changes(f)
    assert res.assessment.phase is Phase.MAINTENANCE_REBOOT and f.restarted == 0


def test_lost_marker_still_recoverable_from_real_state():
    f = FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True,
                    overlay_cur=(RAM, 1024), overlay_next=(RAM, 1024), fail={"registry commit": 1})
    res = ops_for(f).apply_profile()
    assert any("AVISO" in s.detail for s in res.steps)  # se avisa, no se oculta
    f.reboot()
    assert f.reg_value is None and phase(f).phase is Phase.NOT_APPLIED
    res = ops_for(f).apply_profile()  # sigue funcionando: UWF desactivado -> caso C
    assert res.ok and res.assessment.phase is Phase.PENDING_REBOOT


def test_unverifiable_flags_never_green():
    f = applied_fake(wmi_flags=False)
    a = phase(f)
    assert a.phase is Phase.UNVERIFIED and a.level != "ok"
    assert "acceso al espacio libre" in a.message
    res = ops_for(f).apply_profile()
    assert res.ok and res.assessment.phase is Phase.UNVERIFIED
    assert "no se pudo verificar" in res.summary.lower()


def test_unknown_state_changes_nothing():
    f = FakeWindows(ps_output="basura")
    res = ops_for(f).apply_profile()
    assert not res.ok and changes(f) == []
    assert phase(f).phase is Phase.UNKNOWN


def test_flows_never_restart_and_restart_is_explicit():
    f = FakeWindows(filter_cur=True, filter_next=True, overlay_next=(RAM, 1), overlay_cur=(RAM, 1))
    ops = ops_for(f)
    ops.apply_profile(); ops.enable_freeze(); ops.disable_freeze()
    assert f.restarted == 0
    ok, _ = ops.restart_now()
    assert ok and f.restarted == 1


def test_activate_button_keeps_profile_overlay():
    f = applied_fake(filter_cur=False, filter_next=False)
    res = ops_for(f).enable_freeze()
    assert res.ok and "overlay set-size 2048" not in changes(f)
    assert f.overlay_next == (DISK, 4096)


def test_activate_button_refuses_type_change_with_uwf_on():
    f = FakeWindows(filter_cur=True, filter_next=False, overlay_next=(RAM, 1024), overlay_cur=(RAM, 1024))
    res = ops_for(f).enable_freeze()
    assert not res.ok and "dos fases" in res.summary
    assert not any("set-type" in c for c in changes(f))


def test_assess_marker_ignored_when_state_disagrees():
    f = applied_fake()
    f.reg_value = progress.MAINTENANCE  # indicador obsoleto
    assert phase(f).phase is Phase.APPLIED


def test_commands_use_absolute_system32_paths():
    f = FakeWindows(overlay_next=(RAM, 1), overlay_cur=(RAM, 1))
    ops_for(f).apply_profile()
    assert f.calls and all(c[0].lower().startswith("c:\\windows\\system32\\") for c in f.calls)


def test_persistent_flag_not_confused_with_reset_flag():
    import json
    from uwf_manager.state import UwfStatus, parse_status
    data = json.loads(FakeWindows()._json())
    for ov in data["overlay"]:
        ov.pop("x_PersistentOverlay")
        ov["x_ResetPersistentState"] = True
        ov["x_IsPersistent"] = False
    st = parse_status(json.dumps(data), UwfStatus())
    assert st.overlay_next.persistent is False and st.overlay_current.persistent is False

import threading
import time

import pytest

from tests.fakes import FakeWindows
from uwf_manager import system
from uwf_manager.controller import Controller
from uwf_manager.errors import ErrorKind, classify
from uwf_manager.operations import Operations
from uwf_manager.presentation import describe
from uwf_manager.runner import CommandResult, CommandRunner
from uwf_manager.state import UwfQuery

@pytest.fixture(autouse=True)
def admin(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(system, "find_executable", lambda name: r"C:\Windows\System32\uwfmgr.exe")


def make(fake):
    r = fake.runner()
    return Operations(r, UwfQuery(r)), UwfQuery(r)


def uwf_calls(fake):
    return [" ".join(c[1:]) for c in fake.calls if c[0].lower() == "uwfmgr.exe"]


# --- 1-3 estado ---
def test_installed_filter_active():
    f = FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True)
    st = make(f)[1].read()
    d = describe(st)
    assert d["filter"].text == "UWF: ACTIVO"
    assert "CONFIGURADA" in d["volume"].text
    assert st.reboot_pending is False


def test_installed_filter_disabled():
    st = make(FakeWindows())[1].read()
    assert describe(st)["filter"].text == "UWF: DESACTIVADO"
    assert "NO CONFIGURADA" in describe(st)["volume"].text


def test_not_installed():
    st = make(FakeWindows(feature="Disabled"))[1].read()
    assert st.feature_installed is False
    assert "NO INSTALADA" in describe(st)["feature"].text
    assert st.reboot_pending is False


# --- 4 reinicio tras habilitar característica ---
def test_enable_feature_requires_reboot_and_stops():
    f = FakeWindows(feature="Disabled", dism_rc=3010)
    ops, _ = make(f)
    res = ops.enable_freeze()
    assert res.reboot_required and "NO está operativo" in res.summary
    assert uwf_calls(f) == []  # no se ejecutó uwfmgr antes de que UWF exista
    f.reboot()
    res = ops.enable_freeze()
    assert f.filter_next and f.c_next and res.ok


def test_full_enable_sequence_and_commands():
    f = FakeWindows(overlay_next=(0, 1024))
    ops, _ = make(f)
    res = ops.enable_freeze()
    assert res.ok and res.reboot_required
    assert uwf_calls(f) == ["overlay set-size 2048", "overlay set-type disk",
                            "volume protect C:", "filter enable"]
    assert describe(res.status)["filter"].text.startswith("UWF: DESACTIVADO")  # aún no activo
    assert "Reinicio pendiente" == describe(res.status)["reboot"].text


def test_enable_is_idempotent():
    f = FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True)
    ops, _ = make(f)
    res = ops.enable_freeze()
    assert res.ok and uwf_calls(f) == []
    assert not res.reboot_required


# --- 5 permisos ---
def test_no_admin_blocks_changes(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: False)
    f = FakeWindows()
    ops, _ = make(f)
    for res in (ops.enable_freeze(), ops.disable_freeze()):
        assert not res.ok and "administrador" in res.summary
    assert uwf_calls(f) == [] and not any(c[0].lower() == "dism.exe" for c in f.calls)


def test_permission_error_from_command():
    f = FakeWindows(fail={"filter enable": "denied"})
    res = make(f)[0].enable_freeze()
    assert not res.ok and "Permisos insuficientes" in res.summary


# --- 6 uwfmgr inexistente ---
def test_uwfmgr_missing(monkeypatch):
    monkeypatch.setattr(system, "find_executable", lambda name: None)
    f = FakeWindows()
    res = make(f)[0].enable_freeze()
    assert not res.ok and "uwfmgr.exe" in res.summary and uwf_calls(f) == []


def test_command_not_found_is_error():
    f = FakeWindows(overlay_next=(0, 1024), fail={"overlay set-size": "notfound"})
    res = make(f)[0].enable_freeze()
    assert not res.ok and "No se encontró" in res.summary


# --- 7-10 fallos ---
@pytest.mark.parametrize("key,stopped_before", [
    ("overlay set-size", "volume protect C:"),
    ("overlay set-type", "volume protect C:"),
    ("volume protect", "filter enable"),
    ("filter enable", None),
])
def test_enable_step_failures(key, stopped_before):
    f = FakeWindows(overlay_next=(0, 1024), fail={key: 1})
    res = make(f)[0].enable_freeze()
    assert not res.ok and res.stopped
    assert "ERROR" in "\n".join(res.lines())
    assert stopped_before not in uwf_calls(f)
    assert not f.filter_next


def test_disable_failure_not_reported_as_success():
    f = FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True,
                    fail={"filter disable": 1})
    res = make(f)[0].disable_freeze()
    assert not res.ok and f.filter_next is True


def test_command_ok_but_state_unchanged_is_failure():
    class Liar(FakeWindows):
        def run(self, argv, **kw):
            if tuple(argv[1:3]) == ("filter", "enable"):
                return __import__("subprocess").CompletedProcess(argv, 0, b"ok", b"")
            return super().run(argv, **kw)
    f = Liar(c_next=True)
    res = make(f)[0].enable_freeze()
    assert not res.ok and "no confirma" in res.summary


# --- 11 cambio pendiente ---
def test_pending_reboot_detected_and_cleared():
    f = FakeWindows(filter_next=True, c_next=True)
    st = make(f)[1].read()
    assert st.reboot_pending is True and describe(st)["reboot"].text == "Reinicio pendiente"
    f.reboot()
    assert make(f)[1].read().reboot_pending is False


# --- 12 protección conservada ---
def test_disable_keeps_c_protection():
    f = FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True)
    ops, _ = make(f)
    res = ops.disable_freeze()
    assert res.ok and res.reboot_required
    assert uwf_calls(f) == ["filter disable"]
    assert f.c_next is True and f.filter_next is False


def test_disable_when_already_disabled_is_noop():
    f = FakeWindows()
    res = make(f)[0].disable_freeze()
    assert res.ok and uwf_calls(f) == []


# --- 13 estado desconocido ---
@pytest.mark.parametrize("out", ["no es json", "[1,2]", "{}", ""])
def test_unexpected_output_is_unknown(out):
    st = make(FakeWindows(ps_output=out))[1].read()
    d = describe(st)
    assert st.filter_current is None
    assert "Estado desconocido" in d["filter"].text
    assert st.reboot_pending is None
    assert "no se puede determinar" in d["reboot"].text


def test_operations_refuse_when_state_unknown():
    f = FakeWindows(ps_output="basura")
    ops, _ = make(f)
    assert not ops.enable_freeze().ok
    assert not ops.disable_freeze().ok
    assert uwf_calls(f) == []


# --- 14 cancelación UAC ---
def test_uac_cancelled():
    r = system.relaunch_as_admin(lambda exe, params: (5, system.ERROR_CANCELLED))
    assert not r.started and r.cancelled
    r = system.relaunch_as_admin(lambda exe, params: (42, 0))
    assert r.started
    r = system.relaunch_as_admin(lambda exe, params: (2, 2))
    assert not r.started and not r.cancelled


# --- 15 timeout ---
def test_timeout():
    f = FakeWindows(fail={"filter enable": "timeout"})
    res = make(f)[0].enable_freeze()
    assert not res.ok and "tardó demasiado" in res.summary
    r = FakeWindows(fail={"dism": "timeout"}).runner().run(["dism.exe"])
    assert r.timed_out and classify(r) is ErrorKind.TIMEOUT


# --- transversales ---
def test_never_runs_destructive_commands():
    for f, op in ((FakeWindows(overlay_next=(0, 1)), "enable_freeze"),
                  (FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True), "disable_freeze"),
                  (FakeWindows(feature="Disabled", dism_rc=3010), "enable_freeze")):
        getattr(make(f)[0], op)()
        for call in f.calls:
            joined = " ".join(call)
            assert "unprotect" not in joined and "reset-settings" not in joined
            assert "shutdown" not in joined.lower() and "/Disable-Feature" not in joined
            assert "/NoRestart" in joined or call[0].lower() != "dism.exe"


def test_runner_rejects_string_and_no_shell():
    seen = {}
    def fake_run(argv, **kw):
        seen.update(kw)
        import subprocess
        return subprocess.CompletedProcess(argv, 0, b"", b"")
    r = CommandRunner(run=fake_run)
    with pytest.raises(TypeError):
        r.run("uwfmgr filter enable")
    r.run(["uwfmgr.exe", "get-config"])
    assert seen["shell"] is False and seen["timeout"]


def test_exit_code_classification():
    mk = lambda rc, out="": CommandResult(("x",), rc, out)
    assert classify(mk(0)) is ErrorKind.OK
    assert classify(mk(3010)) is ErrorKind.REBOOT_REQUIRED
    assert classify(mk(5)) is ErrorKind.PERMISSION
    assert classify(mk(1, "Acceso denegado")) is ErrorKind.PERMISSION
    assert classify(mk(-2146498548)) is ErrorKind.FEATURE_UNAVAILABLE
    assert classify(mk(1)) is ErrorKind.FAILED


def test_unsupported_edition_blocks():
    f = FakeWindows(feature="Disabled", edition="Professional")
    res = make(f)[0].enable_freeze()
    assert not res.ok and not any(c[0].lower() == "dism.exe" for c in f.calls)


def test_ui_not_blocked_and_single_operation():
    c = Controller(lambda fn: fn())
    gate, done = threading.Event(), []
    t0 = time.monotonic()
    assert c.run_async(lambda: gate.wait(5), lambda r, e: done.append((r, e)))
    assert time.monotonic() - t0 < 0.5  # run_async vuelve de inmediato
    assert c.busy and not c.run_async(lambda: 1, lambda r, e: None)  # sin ejecución simultánea
    gate.set()
    for _ in range(100):
        if done:
            break
        time.sleep(0.02)
    assert done == [(True, None)] and not c.busy


def test_controller_reports_exceptions():
    c = Controller(lambda fn: fn())
    done = []
    c.run_async(lambda: 1 / 0, lambda r, e: done.append(e))
    for _ in range(100):
        if done:
            break
        time.sleep(0.02)
    assert isinstance(done[0], ZeroDivisionError)


def test_no_auto_reboot_code():
    import pathlib
    src = "".join(p.read_text(encoding="utf-8") for p in pathlib.Path("uwf_manager").glob("*.py"))
    for bad in ("shutdown", "Restart-Computer", "unprotect", "reset-settings", "shell=True"):
        assert bad not in src, bad


# --- compatibilidad ---
from uwf_manager.compat import Level, evaluate


def _levels(fake):
    st = make(fake)[1].read()
    return {c.name: c.level for c in evaluate(st).checks}, evaluate(st).verdict


def test_compat_ltsc_is_compatible():
    levels, verdict = _levels(FakeWindows())
    assert verdict[1] == "ok" and set(levels.values()) == {Level.PASS}


def test_compat_windows10_enterprise():
    levels, verdict = _levels(FakeWindows(build=19045, edition="Enterprise", feature="Disabled"))
    assert levels["Versión de Windows"] is Level.PASS and verdict[1] == "ok"


def test_compat_pro_is_not_compatible():
    levels, verdict = _levels(FakeWindows(edition="Professional", feature="NotPresent"))
    assert levels["Edición de Windows"] is Level.FAIL and verdict[1] == "bad"


def test_compat_unknown_without_admin(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: False)
    f = FakeWindows(feature="Disabled")
    f.feature = None  # sin elevación no se puede leer la característica
    levels, verdict = _levels(f)
    assert levels["Característica UWF"] is Level.UNKNOWN and verdict[1] == "unknown"


def test_compat_low_disk_and_32bit_warn():
    levels, verdict = _levels(FakeWindows(c_free=1024**3, is64=False))
    assert levels["Espacio libre en C:"] is Level.WARN and levels["Arquitectura"] is Level.WARN
    assert verdict[1] == "warn"


def test_compat_garbage_output():
    levels, verdict = _levels(FakeWindows(ps_output="basura"))
    assert verdict[1] in ("unknown", "bad") and "COMPATIBLE:" not in verdict[0]


def test_compat_is_read_only():
    f = FakeWindows(feature="Disabled")
    evaluate(make(f)[1].read())
    assert all(c[0].lower() == "powershell.exe" for c in f.calls)


def test_powershell_uses_encoded_command():
    import base64
    from uwf_manager.state import POWERSHELL, _PS_SCRIPT
    assert POWERSHELL[-2] == "-EncodedCommand"
    assert base64.b64decode(POWERSHELL[-1]).decode("utf-16-le") == _PS_SCRIPT

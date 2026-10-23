"""Prueba de la ventana real con un Windows simulado. Se omite si no hay Tkinter o pantalla."""
import time

import pytest

tk = pytest.importorskip("tkinter")

from tests.fakes import FakeRegistry, FakeWindows, exe
from uwf_manager import system
from uwf_manager.operations import Operations
from uwf_manager.progress import ProgressStore
from uwf_manager.state import UwfQuery


def build(monkeypatch, fake):
    from uwf_manager import gui
    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(system, "find_executable", lambda n: r"C:\Windows\System32\uwfmgr.exe")
    runner = fake.runner()
    query = UwfQuery(runner)
    try:
        window = gui.App(Operations(runner, query, ProgressStore(runner, FakeRegistry(fake))), query)
    except tk.TclError as exc:
        pytest.skip(f"sin pantalla: {exc}")
    window.fake = fake
    return window


@pytest.fixture
def app(monkeypatch):
    window = build(monkeypatch, FakeWindows(filter_next=True, c_next=True))
    yield window
    window.destroy()


@pytest.fixture
def ram_app(monkeypatch):
    from uwf_manager import gui
    monkeypatch.setattr(gui.messagebox, "askokcancel", lambda *a, **k: True)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    window = build(monkeypatch, FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True,
                                            overlay_cur=(0, 1024), overlay_next=(0, 1024)))
    yield window
    window.destroy()


def pump(app, until, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if until():
            return
        time.sleep(0.02)
    raise AssertionError("la interfaz no se actualizó a tiempo")


def test_window_shows_real_state(app):
    pump(app, lambda: app.last_status is not None)
    assert app.title() == "Fast Freeze"
    assert app.cards["reboot"].value.cget("text") == "PENDIENTE"
    assert "DESACTIVADO" in app.cards["filter"].value.cget("text")
    assert "SIN CONGELAR" in app.hero_value.cget("text")
    assert app.banner.winfo_manager() == "pack"  # aviso de reinicio visible
    assert app.btn_enable.cget("text") == "Activar congelación y protección"
    assert app.btn_disable.cget("text") == "Desactivar congelación"
    assert not app.btn_enable.instate(["disabled"])


def test_compatibility_button(app):
    pump(app, lambda: not app.controller.busy and app.last_status is not None)
    app.btn_compat.invoke()
    assert app.btn_compat.instate(["disabled"]) or app.compat_dialog is not None
    pump(app, lambda: app.compat_dialog is not None)
    assert app.compat_dialog.report.verdict[0].startswith("COMPATIBLE")
    assert "COMPATIBLE" in app.cards["compat"].value.cget("text")
    # la comprobación es de solo lectura
    assert all(exe(c) == "powershell.exe" for c in app.fake.calls)


def test_buttons_disabled_while_busy(app):
    pump(app, lambda: not app.controller.busy)
    app.refresh()
    assert app.btn_enable.instate(["disabled"]) and app.btn_compat.instate(["disabled"])
    pump(app, lambda: not app.controller.busy and not app.btn_enable.instate(["disabled"]))


def test_profile_button_later_does_not_restart(ram_app):
    asked = []
    ram_app.ask_reboot = lambda msg: asked.append(msg) or False  # «Más tarde»
    pump(ram_app, lambda: ram_app.last_assessment is not None)
    assert ram_app.btn_profile.cget("text") == "Aplicar configuración recomendada"
    ram_app.btn_profile.invoke()
    pump(ram_app, lambda: asked and not ram_app.controller.busy)
    assert "Fase 1 de 2" in asked[0]
    assert ram_app.fake.restarted == 0
    assert ram_app.last_assessment.phase.name == "MAINTENANCE_REBOOT"
    assert ram_app.banner.winfo_manager() == "pack"
    assert "Fase 1" in ram_app.banner_text.cget("text")


def test_profile_button_restart_now(ram_app):
    ram_app.ask_reboot = lambda msg: True  # «Reiniciar ahora»
    pump(ram_app, lambda: ram_app.last_assessment is not None)
    ram_app.btn_profile.invoke()
    pump(ram_app, lambda: ram_app.fake.restarted == 1 and not ram_app.controller.busy)


def test_continue_button_after_maintenance_reboot(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(system, "find_executable", lambda n: r"C:\Windows\System32\uwfmgr.exe")
    fake = FakeWindows(filter_cur=True, filter_next=True, c_cur=True, c_next=True,
                       overlay_cur=(0, 1024), overlay_next=(0, 1024))
    r = fake.runner()
    Operations(r, UwfQuery(r), ProgressStore(r, FakeRegistry(fake))).apply_profile()
    fake.reboot()
    window = build(monkeypatch, fake)
    try:
        pump(window, lambda: window.last_assessment is not None)
        assert window.btn_profile.cget("text") == "Continuar configuración recomendada"
        assert "Fase 2" in window.banner_text.cget("text")
    finally:
        window.destroy()


def test_profile_panel_shows_now_and_after_reboot(app):
    pump(app, lambda: app.last_assessment is not None)
    (now_icon, now_lab), (next_icon, next_lab) = app.profile_cells[5]  # filtro UWF
    assert now_lab.cget("text") == "No" and next_lab.cget("text") == "Sí"

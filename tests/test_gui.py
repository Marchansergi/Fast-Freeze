"""Prueba de la ventana real con un Windows simulado. Se omite si no hay Tkinter o pantalla."""
import time

import pytest

tk = pytest.importorskip("tkinter")

from tests.fakes import FakeWindows
from uwf_manager import system
from uwf_manager.operations import Operations
from uwf_manager.state import UwfQuery


@pytest.fixture
def app(monkeypatch):
    from uwf_manager import gui
    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(system, "find_executable", lambda n: r"C:\Windows\System32\uwfmgr.exe")
    fake = FakeWindows(filter_next=True, c_next=True)
    runner = fake.runner()
    query = UwfQuery(runner)
    try:
        window = gui.App(Operations(runner, query), query)
    except tk.TclError as exc:
        pytest.skip(f"sin pantalla: {exc}")
    window.fake = fake
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
    assert app.title() == "UWF Manager"
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
    assert all(c[0].lower() == "powershell.exe" for c in app.fake.calls)


def test_buttons_disabled_while_busy(app):
    pump(app, lambda: not app.controller.busy)
    app.refresh()
    assert app.btn_enable.instate(["disabled"]) and app.btn_compat.instate(["disabled"])
    pump(app, lambda: not app.controller.busy and not app.btn_enable.instate(["disabled"]))

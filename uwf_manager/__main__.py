"""Punto de entrada: `python -m uwf_manager` (GUI), `--status` o `--compat` (consola, solo lectura)."""
from __future__ import annotations

import sys
from pathlib import Path

from .compat import evaluate
from .logs import setup_logging
from .operations import Operations
from .presentation import describe
from .runner import CommandRunner
from .state import UwfQuery


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    setup_logging()
    runner = CommandRunner()
    query = UwfQuery(runner)
    if "--status" in argv or "--compat" in argv:  # solo lectura
        st = query.read()
        if "--compat" in argv:
            print(evaluate(st).as_text())
        else:
            for item in describe(st).values():
                print(item.text)
        for err in st.errors:
            print("Aviso:", err)
        return 0
    from .gui import App, prepare_windows_process  # import tardío: la consola no necesita Tkinter
    prepare_windows_process()
    app = App(Operations(runner, query), query)
    if "--smoke-test" in argv:  # usado en CI: abre la ventana, lee el estado y se cierra
        _smoke_test(app, Path(argv[argv.index("--smoke-test") + 1]))
    app.mainloop()
    return 0


def _smoke_test(app, out: Path) -> None:
    from .gui import ASSETS

    def check() -> None:
        if app.last_status is None:
            app.after(200, check)
            return
        lines = [item.text for item in describe(app.last_status).values()]
        lines.append(f"Icono incluido: {(ASSETS / 'app.ico').is_file()}")
        out.write_text("\n".join(lines), encoding="utf-8")
        app.destroy()
    app.after(200, check)
    app.after(60_000, app.destroy)


if __name__ == "__main__":
    raise SystemExit(main())

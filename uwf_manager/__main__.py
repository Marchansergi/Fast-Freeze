"""Punto de entrada: `python -m uwf_manager` (GUI) o `--status` (consulta en consola)."""
from __future__ import annotations

import sys

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
    if "--status" in argv:  # solo lectura
        st = query.read()
        for text, _ in describe(st).values():
            print(text)
        for err in st.errors:
            print("Aviso:", err)
        return 0
    from .gui import App  # import tardío: la consola no necesita Tkinter
    App(Operations(runner, query), query).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

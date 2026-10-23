"""Ejecución de tareas en un hilo de trabajo para no bloquear la interfaz."""
from __future__ import annotations

import threading
from typing import Callable

from .logs import get_logger


class Controller:
    """Permite una sola tarea simultánea. `dispatch` lleva el callback al hilo de la UI."""

    def __init__(self, dispatch: Callable[[Callable[[], None]], None]) -> None:
        self._dispatch = dispatch
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def run_async(self, task: Callable[[], object], on_done: Callable[[object, BaseException | None], None]) -> bool:
        """Lanza `task`; devuelve False (sin ejecutar nada) si ya hay otra en curso."""
        if not self._lock.acquire(blocking=False):
            return False

        def work() -> None:
            result: object = None
            error: BaseException | None = None
            try:
                result = task()
            except BaseException as exc:  # se muestra en la interfaz, no se oculta
                error = exc
                get_logger().exception("Excepción en tarea")
            finally:
                self._lock.release()
            self._dispatch(lambda: on_done(result, error))

        threading.Thread(target=work, daemon=True, name="uwf-worker").start()
        return True

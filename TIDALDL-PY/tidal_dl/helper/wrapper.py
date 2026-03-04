"""Logger wrapper with optional debug traceback output."""

import traceback
from collections.abc import Callable
from typing import Any


class LoggerWrapped:
    """Wraps a print callable to provide standard logging-style methods.

    Attributes:
        fn_print (Callable): The function used to emit messages.
        debug_mode (bool): When True, full tracebacks are printed for exceptions.
    """

    def __init__(self, fn_print: Callable, debug: bool = False) -> None:
        self.fn_print: Callable = fn_print
        self.debug_mode: bool = debug

    def debug(self, value: Any) -> None:
        if self.debug_mode:
            self.fn_print(value)

    def warning(self, value: Any) -> None:
        self.fn_print(value)

    def info(self, value: Any) -> None:
        self.fn_print(value)

    def error(self, value: Any) -> None:
        self.fn_print(value)

    def critical(self, value: Any) -> None:
        self.fn_print(value)

    def exception(self, value: Any) -> None:
        self.fn_print(value)

        if self.debug_mode:
            tb = traceback.format_exc()

            if tb and tb.strip() != "NoneType: None":
                self.fn_print(tb)

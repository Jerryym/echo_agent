from enum import Enum
from html import escape

from PySide6.QtCore import QObject, Signal


class LogLevel(str, Enum):
    TRACE = "trace"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


LEVEL_COLORS = {
    LogLevel.ERROR: "#d32f2f",
    LogLevel.WARN: "#f9a825",
    LogLevel.TRACE: "#2e7d32",
}
DEFAULT_COLOR = "#000000"


class ConsoleLogger(QObject):
    """
    统一日志输出：发出信号后由 LogPanel 自动追加
    """
    logged = Signal(str, str)  # level, message

    def log(self, message: str, level: LogLevel | str = LogLevel.INFO) -> None:
        if not isinstance(level, LogLevel):
            level = LogLevel(level)
        self.logged.emit(level.value, message)

    def trace(self, message: str) -> None:
        self.log(message, LogLevel.TRACE)

    def info(self, message: str) -> None:
        self.log(message, LogLevel.INFO)

    def warn(self, message: str) -> None:
        self.log(message, LogLevel.WARN)

    def error(self, message: str) -> None:
        self.log(message, LogLevel.ERROR)


def level_color(level: str) -> str:
    try:
        return LEVEL_COLORS.get(LogLevel(level), DEFAULT_COLOR)
    except ValueError:
        return DEFAULT_COLOR


def format_log_html(level: str, message: str) -> str:
    color = level_color(level)
    return (
        f'<span style="color:{color}">'
        f"[{level.upper()}] {escape(message)}"
        f"</span>"
    )


logger = ConsoleLogger()

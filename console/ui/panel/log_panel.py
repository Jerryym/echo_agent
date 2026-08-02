from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTextEdit,
)

from manager.console_logger import format_log_html


class LogPanel(QWidget):
    """
    日志面板
    """
    def __init__(self):
        super().__init__()
        self.setObjectName("log_panel")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        self.viewer = QTextEdit()
        self.viewer.setObjectName("log_viewer")
        self.viewer.setReadOnly(True)
        layout.addWidget(self.viewer)

    def append(self, level: str, text: str) -> None:
        """
        按日志等级追加彩色行
        """
        self.viewer.append(format_log_html(level, text))

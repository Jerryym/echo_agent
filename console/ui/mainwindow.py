from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QSplitter,
)

from PySide6.QtCore import Qt


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self._init_window()
        self._init_ui()

    def _init_window(self):
        self.setWindowTitle("Echo Agent Console")
        self.resize(1600, 900)

    def _init_ui(self):
        root = QWidget()
        layout = QHBoxLayout(root)

        splitter = QSplitter(Qt.Horizontal)

        splitter.addWidget(self._placeholder("Session"))
        splitter.addWidget(self._placeholder("Chat"))
        splitter.addWidget(self._placeholder("Log"))

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 3)

        layout.addWidget(splitter)

        self.setCentralWidget(root)

    def _placeholder(self, text: str) -> QWidget:
        widget = QWidget()
        widget.setObjectName(text.lower())
        return widget
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

# 保证 console/ 作为导入根（case / manager / ui）
_CONSOLE_ROOT = Path(__file__).resolve().parent
if str(_CONSOLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONSOLE_ROOT))

from ui import MainWindow


def create_app() -> QApplication:
    app = QApplication(sys.argv)
    app.setApplicationName("Echo Agent Console")
    app.setApplicationVersion("0.1.0")
    load_qss(app)
    return app


def load_qss(app: QApplication):
    """
    加载QSS
    """
    qss_path = Path(__file__).parent / "ui" / "theme" / "dark.qss"
    with open(qss_path, "r", encoding="utf-8") as f:
        app.setStyleSheet(f.read())


def main():
    app = create_app()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QListWidget,
    QListWidgetItem,
)

from manager.session_manager import SessionManager
from model.session import SessionInfo


class SessionPanel(QWidget):
    """
    会话面板
    """
    session_created = Signal(SessionInfo)
    session_changed = Signal(SessionInfo)

    def __init__(self, manager: SessionManager, parent: QWidget | None = None):
        super().__init__(parent)

        self.manager = manager
        self.setObjectName("session_panel")

        self._init_ui()
        self._bind_events()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self.new_button = QPushButton("+ 新建会话")
        self.session_list = QListWidget()

        layout.addWidget(self.new_button)
        layout.addWidget(self.session_list)

    def _bind_events(self):
        self.new_button.clicked.connect(self.create_session)
        self.session_list.currentItemChanged.connect(self.on_session_changed)

    def create_session(self):
        session = self.manager.create()
        item = self._create_item(session)
        self.session_list.addItem(item)
        self.session_list.setCurrentItem(item)

        self.session_created.emit(session)

    def on_session_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        """
        会话切换
        """
        if current is None:
            return

        session_id = current.data(Qt.UserRole)
        self.manager.switch_session(session_id)

        session = self.manager.current_session
        if session is not None:
            self.session_changed.emit(session)

    def _create_item(self, session: SessionInfo) -> QListWidgetItem:
        """
        创建会话项
        """
        index = self.session_list.count() + 1
        display_name = f"session_{index}"
        session.title = display_name

        item = QListWidgetItem(display_name)
        # 保存 session id
        item.setData(Qt.UserRole, session.id)
        return item

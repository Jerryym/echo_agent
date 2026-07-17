from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTextBrowser,
    QSizePolicy,
)

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QResizeEvent, QShowEvent


class ChatMessage(QWidget):
    """
    聊天消息组件
    """
    def __init__(self, role: str, content: str, tokens: int | None = None):
        super().__init__()

        self.setObjectName("chat_message")

        self.role = role
        self.content = content
        self.tokens = tokens

        if self.role == "Assistant":
            self.max_width = 800
        else:
            self.max_width = 500
        self.setMaximumWidth(self.max_width)
        # Maximum：水平只占内容所需宽度，不拉满 max_width
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # role
        role_label = QLabel(self.role)
        role_label.setObjectName("message_role")
        if self.role == "User":
            role_label.setAlignment(Qt.AlignRight)
        layout.addWidget(role_label)

        # content
        self.content_browser = QTextBrowser()
        self.content_browser.setObjectName("message_content")
        self.content_browser.setMarkdown(self.content)
        self.content_browser.setOpenExternalLinks(True)
        self.content_browser.setReadOnly(True)
        self.content_browser.setFrameShape(QTextBrowser.NoFrame)
        self.content_browser.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)
        self.content_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        document = self.content_browser.document()
        document.setDocumentMargin(0)
        layout.addWidget(self.content_browser)

        # token
        if self.role == "Assistant" and self.tokens is not None:
            token_label = QLabel(f"tokens: {self.tokens}")
            token_label.setObjectName("message_meta")
            token_label.setAlignment(Qt.AlignRight)
            layout.addWidget(token_label)

        self._update_content_size()

    def _content_max_width(self) -> int:
        return self.max_width - 24  # 左右 layout margin 各 12

    def _update_content_size(self, available_width: int | None = None) -> None:
        """按内容 ideal width 收缩，避免短消息右侧大片留白。"""
        document = self.content_browser.document()
        max_w = self._content_max_width()

        document.setTextWidth(-1)
        ideal = int(document.idealWidth()) + 2
        width = max(1, min(ideal, max_w))
        if available_width is not None and available_width > 0:
            width = min(width, available_width)

        document.setTextWidth(width)
        height = int(document.size().height()) + 4
        self.content_browser.setFixedSize(QSize(width, height))

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._update_content_size()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        available = event.size().width() - 24
        self._update_content_size(available if available > 0 else None)

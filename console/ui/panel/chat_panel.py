from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QScrollArea,
    QTextEdit,
    QPushButton,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
)

from model.session import ChatMessageData, SessionInfo
from ui.widget.chat_message import ChatMessage
from ui.widget.hitl_form import HITLForm


class ChatPanel(QWidget):
    """
    聊天面板
    """
    message_sent = Signal(str)
    hitl_submitted = Signal(dict)
    hitl_cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("chat_panel")
        self._current_session: SessionInfo | None = None
        self._init_ui()
        self._bind_events()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # session header
        header = QHBoxLayout()
        self.title_label = QLabel("无会话")
        self.title_label.setObjectName("session_title")
        self.session_id_label = QLabel("")
        self.session_id_label.setObjectName("session_id")
        header.addWidget(self.title_label)
        header.addStretch()
        header.addWidget(self.session_id_label)
        layout.addLayout(header)

        # message container
        self.message_layout = QVBoxLayout()
        self.message_layout.setSpacing(10)
        self.message_layout.addStretch(1)
        message_widget = QWidget()
        message_widget.setLayout(self.message_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(message_widget)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # HITL form（输入框上方）
        self.hitl_form = HITLForm()

        # input：高度与发送按钮一致
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)
        input_layout.setAlignment(Qt.AlignVCenter)

        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("chat_send_button")
        button_height = max(36, self.send_button.sizeHint().height())
        self.send_button.setFixedHeight(button_height)

        self.input = QTextEdit()
        self.input.setObjectName("chat_input")
        self.input.setPlaceholderText("输入消息… Enter 发送，Ctrl+Enter 换行")
        self.input.setFixedHeight(button_height)
        self.input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input.installEventFilter(self)

        input_layout.addWidget(self.input, 1)
        input_layout.addWidget(self.send_button, 0)

        layout.addWidget(scroll, 1)
        layout.addWidget(self.hitl_form, 0)
        layout.addLayout(input_layout, 0)

    def _bind_events(self):
        self.send_button.clicked.connect(self._on_send)
        self.hitl_form.submitted.connect(self._on_hitl_submitted)
        self.hitl_form.cancelled.connect(self._on_hitl_cancelled)

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.KeyPress:
            key_event: QKeyEvent = event
            if key_event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if key_event.modifiers() & Qt.ControlModifier:
                    self.input.insertPlainText("\n")
                    return True
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    def _on_send(self) -> None:
        if not self.input.isEnabled():
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.message_sent.emit(text)
        self.input.clear()

    def _on_hitl_submitted(self, result: dict) -> None:
        # 保持输入禁用，等 MainWindow 跑完 resume 再决定是否恢复
        self.hitl_submitted.emit(result)

    def _on_hitl_cancelled(self) -> None:
        self._set_chat_input_enabled(True)
        self.hitl_cancelled.emit()

    def set_busy(self, busy: bool) -> None:
        """Agent 运行中禁用输入，避免重复发送。"""
        self._set_chat_input_enabled(not busy)

    def _set_chat_input_enabled(self, enabled: bool) -> None:
        self.input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)

    def show_hitl(self, request: dict) -> None:
        """
        弹出 HITL 表单并禁用聊天输入
        """
        self.hitl_form.show_request(request)
        self._set_chat_input_enabled(False)

    def hide_hitl(self) -> None:
        """
        关闭 HITL 表单并恢复聊天输入
        """
        self.hitl_form.hide_form()
        self._set_chat_input_enabled(True)

    def set_session(self, session: SessionInfo | None) -> None:
        """
        切换会话：更新标题，并加载该会话消息
        """
        self.hide_hitl()
        self._current_session = session

        if session is None:
            self.title_label.setText("无会话")
            self.session_id_label.setText("")
            self.clear_messages()
            return

        title = session.title or "未命名会话"
        self.title_label.setText(title)
        self.session_id_label.setText(str(session.id))
        self.load_messages(session.messages)

    def clear_messages(self) -> None:
        """清空消息区（保留底部 stretch）。"""
        while self.message_layout.count() > 1:
            item = self.message_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def load_messages(self, messages: list[ChatMessageData]) -> None:
        """按会话历史重绘消息（不写回 session）。"""
        self.clear_messages()
        for msg in messages:
            if msg.role == "User":
                self._render_message("User", msg.content, None, "right")
            else:
                self._render_message("Assistant", msg.content, msg.tokens, "left")

    def add_user_message(self, text: str) -> None:
        """
        添加用户消息（写入当前会话并渲染）
        """
        if self._current_session is not None:
            self._current_session.messages.append(
                ChatMessageData(role="User", content=text)
            )
        self._render_message("User", text, None, "right")

    def add_assistant_message(self, text: str, tokens: int) -> None:
        """
        添加AI消息（写入当前会话并渲染）
        """
        if self._current_session is not None:
            self._current_session.messages.append(
                ChatMessageData(role="Assistant", content=text, tokens=tokens)
            )
        self._render_message("Assistant", text, tokens, "left")

    def _render_message(
        self,
        role: str,
        text: str,
        tokens: int | None,
        align: str,
    ) -> None:
        message = ChatMessage(role, text, tokens)
        self._add_message(message, align)

    def _add_message(self, message: QWidget, align: str) -> None:
        """
        添加消息并控制左右对齐
        """
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        # User 靠右时缩小右边距，避免气泡离右边缘过远
        if align == "right":
            row_layout.setContentsMargins(10, 5, 4, 5)
            row_layout.addStretch()
            row_layout.addWidget(message, 0)
        else:
            row_layout.setContentsMargins(10, 5, 10, 5)
            row_layout.addWidget(message, 0)
            row_layout.addStretch()

        self.message_layout.insertWidget(self.message_layout.count() - 1, row_widget)

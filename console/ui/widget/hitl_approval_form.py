from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
)


class HITLApprovalForm(QWidget):
    """
    HITLType.APPROVAL：仅说明 + 批准 / 拒绝（不展示 tool_calls）
    """
    submitted = Signal(dict)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("hitl_approval_form")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignTop)

        self.description_label = QLabel()
        self.description_label.setObjectName("hitl_description")
        self.description_label.setWordWrap(True)
        self.description_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.description_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.description_label, 0)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(6)
        buttons.addStretch()
        self.reject_button = QPushButton("拒绝")
        self.approve_button = QPushButton("批准")
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.approve_button)
        layout.addLayout(buttons, 0)

        self.approve_button.clicked.connect(
            lambda: self.submitted.emit({"approved": True})
        )
        self.reject_button.clicked.connect(
            lambda: self.submitted.emit({"approved": False})
        )

    def load(self, description: str) -> None:
        self.description_label.setText(description or "请审批该操作")
        self.adjustSize()

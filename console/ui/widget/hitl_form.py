from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QSizePolicy

from ui.widget.hitl_approval_form import HITLApprovalForm
from ui.widget.hitl_input_form import HITLInputForm


class HITLForm(QWidget):
    """
    HITL 表单容器：按 type 切换 INPUT / APPROVAL
    """
    submitted = Signal(dict)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("hitl_form")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._request: dict | None = None
        self._init_ui()
        self._bind_events()
        self.hide()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.input_form = HITLInputForm()
        self.approval_form = HITLApprovalForm()
        self.stack.addWidget(self.input_form)
        self.stack.addWidget(self.approval_form)
        layout.addWidget(self.stack, 0)

    def _bind_events(self):
        self.input_form.submitted.connect(self._on_submitted)
        self.input_form.cancelled.connect(self._on_cancelled)
        self.approval_form.submitted.connect(self._on_submitted)
        self.approval_form.cancelled.connect(self._on_cancelled)

    def show_request(self, request: dict) -> None:
        """
        根据 interrupt request 展示对应表单
        request: {id, type, description, payload}
        """
        self._request = request
        hitl_type = request.get("type")
        description = request.get("description", "")
        payload = request.get("payload") or {}

        if hitl_type == "input":
            fields = payload.get("fields") or {}
            tool_calls = payload.get("tool_calls") or []
            self.input_form.load(description, fields, tool_calls)
            self.stack.setCurrentWidget(self.input_form)
        elif hitl_type == "approval":
            self.approval_form.load(description)
            self.stack.setCurrentWidget(self.approval_form)
        else:
            raise ValueError(f"unsupported HITL type: {hitl_type!r}")

        self.adjustSize()
        self.show()

    def hide_form(self) -> None:
        self._request = None
        self.hide()

    def _on_submitted(self, result: dict) -> None:
        self.submitted.emit(result)
        self.hide_form()

    def _on_cancelled(self) -> None:
        self.cancelled.emit()
        self.hide_form()

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFormLayout,
    QSizePolicy,
)


class HITLInputForm(QWidget):
    """
    HITLType.INPUT：按 fields 动态补参
    """
    submitted = Signal(dict)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("hitl_input_form")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._fields: dict[str, QLineEdit] = {}
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

        self.form_layout = QFormLayout()
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_layout.setHorizontalSpacing(8)
        self.form_layout.setVerticalSpacing(4)
        layout.addLayout(self.form_layout, 0)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(6)
        buttons.addStretch()
        self.cancel_button = QPushButton("取消")
        self.submit_button = QPushButton("提交")
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.submit_button)
        layout.addLayout(buttons, 0)

        self.submit_button.clicked.connect(self._on_submit)
        self.cancel_button.clicked.connect(self.cancelled.emit)

    def load(self, description: str, fields: list[dict]) -> None:
        self.description_label.setText(description or "请补充缺失参数")
        self._clear_fields()

        for field in fields:
            name = field.get("name", "")
            if not name:
                continue
            desc = field.get("description") or name
            edit = QLineEdit()
            edit.setPlaceholderText(desc)
            self.form_layout.addRow(QLabel(name), edit)
            self._fields[name] = edit

        self.adjustSize()

    def _clear_fields(self) -> None:
        while self.form_layout.rowCount() > 0:
            self.form_layout.removeRow(0)
        self._fields.clear()

    def _on_submit(self) -> None:
        values = {
            name: edit.text().strip()
            for name, edit in self._fields.items()
        }
        self.submitted.emit({"values": values})

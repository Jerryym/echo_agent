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
    HITLType.INPUT：按 tool_call_id 分组动态补参
    """
    submitted = Signal(dict)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("hitl_input_form")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        # tool_call_id -> param_name -> QLineEdit
        self._fields: dict[str, dict[str, QLineEdit]] = {}
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

        self.fields_container = QVBoxLayout()
        self.fields_container.setContentsMargins(0, 0, 0, 0)
        self.fields_container.setSpacing(6)
        layout.addLayout(self.fields_container, 0)

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

    def load(
        self,
        description: str,
        fields: dict[str, list[dict]] | list[dict],
        tool_calls: list[dict] | None = None,
    ) -> None:
        self.description_label.setText(description or "请补充缺失参数")
        self._clear_fields()

        fields_by_call = self._normalize_fields(fields)
        tool_name_by_id = {
            tc.get("tool_call_id"): tc.get("name") or tc.get("tool_call_id")
            for tc in (tool_calls or [])
            if tc.get("tool_call_id")
        }

        for tool_call_id, call_fields in fields_by_call.items():
            title = tool_name_by_id.get(tool_call_id) or tool_call_id
            section_label = QLabel(f"{title} ({tool_call_id})")
            section_label.setObjectName("hitl_tool_section")
            self.fields_container.addWidget(section_label)

            form_layout = QFormLayout()
            form_layout.setContentsMargins(0, 0, 0, 0)
            form_layout.setHorizontalSpacing(8)
            form_layout.setVerticalSpacing(4)
            self.fields_container.addLayout(form_layout)

            editors: dict[str, QLineEdit] = {}
            for field in call_fields:
                name = field.get("name", "")
                if not name:
                    continue
                desc = field.get("description") or name
                edit = QLineEdit()
                edit.setPlaceholderText(desc)
                form_layout.addRow(QLabel(name), edit)
                editors[name] = edit
            self._fields[tool_call_id] = editors

        self.adjustSize()

    @staticmethod
    def _normalize_fields(fields: dict[str, list[dict]] | list[dict]) -> dict[str, list[dict]]:
        """兼容旧扁平 list；新协议为 {tool_call_id: [field, ...]}。"""
        if isinstance(fields, dict):
            return {
                tool_call_id: list(call_fields or [])
                for tool_call_id, call_fields in fields.items()
            }
        # 旧协议：无法区分 tool_call，归到占位 key（仅兜底）
        return {"_default": list(fields or [])}

    def _clear_fields(self) -> None:
        while self.fields_container.count() > 0:
            item = self.fields_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                continue
            layout = item.layout()
            if layout is not None:
                while layout.count() > 0:
                    child = layout.takeAt(0)
                    child_widget = child.widget()
                    if child_widget is not None:
                        child_widget.deleteLater()
                layout.deleteLater()
        self._fields.clear()

    def _on_submit(self) -> None:
        values = {
            tool_call_id: {
                name: edit.text().strip()
                for name, edit in editors.items()
            }
            for tool_call_id, editors in self._fields.items()
        }
        self.submitted.emit({"values": values})

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QComboBox,
)

from manager.case_registry import CaseRegistry


class ControlBar(QWidget):
    case_changed = Signal(str)

    def __init__(self, case_registry: CaseRegistry):
        super().__init__()
        self.case_registry = case_registry
        self.setObjectName("control_bar")
        self.setFixedHeight(40)
        self._init_ui()
        self._bind_events()
        self._sync_strategy_from_case()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Strategy"))

        # strategy：由 Test Case 控制，只读展示
        self.strategy_box = QComboBox()
        self.strategy_box.setObjectName("strategy_box")
        self.strategy_box.addItems(
            [
                "None",
                "ReAct",
                "Plan Execute",
            ]
        )
        self.strategy_box.setEnabled(False)
        self.strategy_box.setMinimumWidth(120)
        layout.addWidget(self.strategy_box)

        layout.addSpacing(16)
        layout.addWidget(QLabel("Test Case"))

        self.case_box = QComboBox()
        self.case_box.setObjectName("case_box")
        self.case_box.setMinimumWidth(180)
        for case in self.case_registry.list_cases():
            self.case_box.addItem(case.title, case.name)
        layout.addWidget(self.case_box)

        layout.addStretch()

    def _bind_events(self):
        self.case_box.currentIndexChanged.connect(self._on_case_changed)

    def _on_case_changed(self, _index: int) -> None:
        name = self.current_case_name()
        if name:
            self._sync_strategy_from_case()
            self.case_changed.emit(name)

    def _sync_strategy_from_case(self) -> None:
        name = self.current_case_name()
        if not name:
            return
        handler = self.case_registry.get(name).handler
        strategy = getattr(handler, "strategy", "None") if handler else "None"
        self.sync_strategy(strategy)

    def sync_strategy(self, strategy: str) -> None:
        idx = self.strategy_box.findText(strategy)
        if idx >= 0:
            self.strategy_box.setCurrentIndex(idx)

    def current_case_name(self) -> str | None:
        return self.case_box.currentData()

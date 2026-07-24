"""Adapter 侧协议/运行时辅助类型（不进入 core）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeOptions:
    """CreateAgent 可选运行时选项；缺省为进程内 Memory checkpointer。"""

    checkpointer_kind: str = "memory"
    checkpointer_uri: str | None = None


@dataclass
class AgentInvokeResult:
    """Invoke / Resume 归一化结果。"""

    output: str = ""
    interrupted: bool = False
    interrupt_payload: dict[str, Any] | None = None


@dataclass
class AgentEvent:
    """流式事件（Adapter 映射后的最小集合）。"""

    type: str
    data: dict[str, Any] = field(default_factory=dict)

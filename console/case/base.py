from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from echo_agent.core.llm import LLMConfig


@dataclass
class CaseResult:
    """Case 执行结果。"""
    reply: str | None = None
    pending_hitl: dict | None = None
    debug: str | None = None


class BaseCase:
    """Console 测例基类。"""

    name: str = ""
    title: str = ""
    strategy: str = "None"

    def create_runtime(self, llm_config: LLMConfig | None) -> Any:
        raise NotImplementedError

    def on_message(self, runtime: Any, session_id: str, text: str) -> CaseResult:
        raise NotImplementedError

    def on_hitl(self, runtime: Any, session_id: str, values: dict) -> CaseResult:
        return CaseResult(reply="当前 Case 不支持 HITL resume")

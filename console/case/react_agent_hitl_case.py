from __future__ import annotations

from echo_agent import Agent, LLMConfig, UserInput

from case.base import BaseCase, CaseResult
from case.common import extract_reply, get_pending_interrupt
from case.react_agent_case import build_react_agent


# 写操作需人工审批；测 APPROVAL 时用参数齐全的话术，避免先进 INPUT
APPROVAL_REQUIRED_TOOLS = {
    "create_refund",
}


class ReactAgentHITLCase(BaseCase):
    """ReAct Agent（含 HITL：补参 / 审批）。"""

    name = "react_agent_hitl"
    title = "ReAct（有HITL）"
    strategy = "ReAct"

    def create_runtime(self, llm_config: LLMConfig | None) -> Agent:
        if llm_config is None:
            raise ValueError("ReAct HITL Case 需要 llm_config")
        return build_react_agent(
            "console_react_hitl",
            llm_config,
            approval_required=APPROVAL_REQUIRED_TOOLS,
        )

    def on_message(self, runtime: Agent, session_id: str, text: str) -> CaseResult:
        result = runtime.invoke(session_id, UserInput(text=text))
        return self._to_result(runtime, session_id, result)

    def on_hitl(self, runtime: Agent, session_id: str, values: dict) -> CaseResult:
        result = runtime.resume(session_id, values)
        return self._to_result(runtime, session_id, result)

    def _to_result(self, runtime: Agent, session_id: str, result) -> CaseResult:
        pending = get_pending_interrupt(runtime, session_id)
        if pending is not None:
            return CaseResult(
                pending_hitl=pending,
                debug=f"hitl pending type={pending.get('type')}",
            )
        reply = extract_reply(result)
        state = runtime.get_state(session_id)
        return CaseResult(reply=reply, debug=f"state={getattr(state, 'values', state)}")

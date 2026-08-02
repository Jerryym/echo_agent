"""ReAct + MCP + HITL（补参 / 审批）。"""

from __future__ import annotations

from echo_agent import LLMConfig, UserInput

from case.base import BaseCase, CaseResult
from case.common import extract_reply, get_pending_interrupt
from case.mcp_common import (
    APPROVAL_REQUIRED_TOOLS,
    MCPRuntimeHolder,
    run_async,
)


class ReactAgentHITLMCPCase(BaseCase):
    """ReAct Agent + MCP + HITL。

    固定启用：builtin(Fetch/Filesystem) + stdio(everything) + http(remote)。
    APPROVAL：create_refund / write_file / edit_file / move_file。
    """

    name = "react_agent_hitl_mcp"
    title = "ReAct MCP（有HITL）"
    strategy = "ReAct"

    def create_runtime(self, llm_config: LLMConfig | None) -> MCPRuntimeHolder:
        if llm_config is None:
            raise ValueError("ReAct HITL MCP Case 需要 llm_config")
        return MCPRuntimeHolder(
            name="console_react_hitl_mcp",
            llm_config=llm_config,
            approval_required=set(APPROVAL_REQUIRED_TOOLS),
        )

    def on_message(self, runtime: MCPRuntimeHolder, session_id: str, text: str) -> CaseResult:
        agent = runtime.ensure_agent()
        result = run_async(agent.ainvoke(session_id, UserInput(text=text)))
        return self._to_result(runtime, agent, session_id, result)

    def on_hitl(self, runtime: MCPRuntimeHolder, session_id: str, values: dict) -> CaseResult:
        agent = runtime.ensure_agent()
        result = run_async(agent.aresume(session_id, values))
        return self._to_result(runtime, agent, session_id, result)

    def _to_result(
        self,
        runtime: MCPRuntimeHolder,
        agent,
        session_id: str,
        result,
    ) -> CaseResult:
        pending = get_pending_interrupt(agent, session_id)
        if pending is not None:
            return CaseResult(
                pending_hitl=pending,
                debug=f"hitl pending type={pending.get('type')}",
            )
        reply = extract_reply(result)
        state = agent.get_state(session_id)
        tools = ",".join(runtime.tool_names) if runtime.tool_names else ""
        return CaseResult(
            reply=reply,
            debug=f"tools=[{tools}] state={getattr(state, 'values', state)}",
        )

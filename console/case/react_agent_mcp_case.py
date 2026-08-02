"""ReAct + MCP（builtin / stdio / http），无 HITL 审批侧重。"""

from __future__ import annotations

from echo_agent import LLMConfig, UserInput

from case.base import BaseCase, CaseResult
from case.common import extract_reply, get_pending_interrupt
from case.mcp_common import MCPRuntimeHolder, run_async


class ReactAgentMCPCase(BaseCase):
    """ReAct Agent + MCP 工具（异步轨）。

    固定启用：builtin(Fetch/Filesystem) + stdio(everything) + http(remote)。
    http 默认 http://localhost:8000/mcp，需先启动 tests/mcp_server.py。
    """

    name = "react_agent_mcp"
    title = "ReAct MCP（无HITL）"
    strategy = "ReAct"

    def create_runtime(self, llm_config: LLMConfig | None) -> MCPRuntimeHolder:
        if llm_config is None:
            raise ValueError("ReAct MCP Case 需要 llm_config")
        return MCPRuntimeHolder(
            name="console_react_mcp",
            llm_config=llm_config,
            approval_required=None,
        )

    def on_message(self, runtime: MCPRuntimeHolder, session_id: str, text: str) -> CaseResult:
        agent = runtime.ensure_agent()
        result = run_async(agent.ainvoke(session_id, UserInput(text=text)))
        pending = get_pending_interrupt(agent, session_id)
        if pending is not None:
            return CaseResult(
                pending_hitl=pending,
                debug=f"unexpected hitl in no-HITL mcp case: {pending}",
            )
        reply = extract_reply(result)
        state = agent.get_state(session_id)
        tools = ",".join(runtime.tool_names) if runtime.tool_names else ""
        return CaseResult(
            reply=reply,
            debug=f"tools=[{tools}] state={getattr(state, 'values', state)}",
        )

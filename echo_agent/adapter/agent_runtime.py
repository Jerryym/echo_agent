"""Adapter 侧 AgentRuntime：Create / Invoke / Stream / Resume（含默认 ReAct 组装）。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from echo_agent import Agent, AgentConfig, UserInput

from .events import iter_agent_events, to_invoke_result
from .react_agent import build_default_react_agent
from .schema import AgentEvent, AgentInvokeResult, RuntimeOptions


class AgentRuntime:
    """
    Runtime Adapter 入口（非 core）。

    - 持有 agent_id → Agent
    - CreateAgent 时在本层固定组装默认 ReAct Agent
    - 转发 invoke / stream / resume 到现有 Agent API
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def get_agent(self, agent_id: str) -> Agent:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"agent not found: {agent_id}")
        return agent

    async def create_agent(
        self,
        config: AgentConfig,
        runtime_options: RuntimeOptions | None = None,
    ) -> str:
        agent = await build_default_react_agent(config, runtime_options=runtime_options)
        agent_id = str(uuid.uuid4())
        self._agents[agent_id] = agent
        return agent_id

    async def invoke(
        self,
        agent_id: str,
        session_id: str,
        input: UserInput,
    ) -> AgentInvokeResult:
        self._require_session_id(session_id)
        agent = self.get_agent(agent_id)
        result = await agent.ainvoke(session_id, input)
        return to_invoke_result(agent, session_id, result)

    async def stream(
        self,
        agent_id: str,
        session_id: str,
        input: UserInput,
    ) -> AsyncIterator[AgentEvent]:
        self._require_session_id(session_id)
        agent = self.get_agent(agent_id)
        stream = await agent.astream(session_id, input)
        async for event in iter_agent_events(agent, session_id, stream):
            yield event

    async def resume(
        self,
        agent_id: str,
        session_id: str,
        values: dict[str, Any],
    ) -> AgentInvokeResult:
        self._require_session_id(session_id)
        agent = self.get_agent(agent_id)
        result = await agent.aresume(session_id, values)
        return to_invoke_result(agent, session_id, result)

    async def stream_resume(
        self,
        agent_id: str,
        session_id: str,
        values: dict[str, Any],
    ) -> AsyncIterator[AgentEvent]:
        self._require_session_id(session_id)
        agent = self.get_agent(agent_id)
        stream = await agent.astream_resume(session_id, values)
        async for event in iter_agent_events(agent, session_id, stream):
            yield event

    @staticmethod
    def _require_session_id(session_id: str) -> None:
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id is required")

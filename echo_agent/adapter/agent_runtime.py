"""Adapter 侧 AgentRuntime：Create / Invoke / Stream / Resume。"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeAlias

from echo_agent import Agent, AgentConfig, UserInput

from .events import iter_agent_events, to_invoke_result
from .schema import AgentEvent, AgentInvokeResult, RuntimeOptions

AgentFactory: TypeAlias = Callable[
    [AgentConfig, RuntimeOptions | None],
    Agent | Awaitable[Agent],
]


class AgentRuntime:
    """
    Runtime Adapter 入口（非 core）。

    - 持有 agent_id → Agent
    - CreateAgent 时必须调用集成方注入的 factory
    - 转发 invoke / stream / resume 到现有 Agent API
    """
    def __init__(self, factory: AgentFactory) -> None:
        if factory is None:
            raise TypeError("factory is required")
        self._agent_map: dict[str, Agent] = {}
        self._factory = factory

    def get_agent(self, agent_id: str) -> Agent:
        """
        根据ID获取对应智能体
        """
        agent = self._agent_map.get(agent_id)
        if agent is None:
            raise KeyError(f"agent not found: {agent_id}")
        return agent

    async def create_agent(
        self,
        config: AgentConfig,
        runtime_options: RuntimeOptions | None = None,
    ) -> str:
        """
        创建智能体
        """
        result = self._factory(config, runtime_options)
        agent = await result if inspect.isawaitable(result) else result
        if not isinstance(agent, Agent):
            raise TypeError(
                f"agent factory must return Agent, got {type(agent).__name__}"
            )
        agent_id = str(uuid.uuid4())
        self._agent_map[agent_id] = agent
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

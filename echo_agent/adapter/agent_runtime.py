"""Adapter 侧 AgentRuntime：Create / Delete / Invoke / Stream / Resume / Cancel。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias

from echo_agent import Agent, AgentConfig, UserInput
from echo_agent.common.network import HttpRequest
from echo_agent.core.model.agent import AgentMode

from .events import iter_agent_events, to_invoke_result
from .schema import AgentEvent, AgentInvokeResult, RuntimeOptions

AgentFactory: TypeAlias = Callable[
    [AgentConfig, RuntimeOptions | None],
    Agent | Awaitable[Agent],
]

_STREAM_DONE = object()


class AgentLimitExceededError(Exception):
    """进程内 Agent 数量达到 max_agents 上限。"""


@dataclass
class _ActiveRun:
    """单 session 上正在进行的当轮执行。"""

    task: asyncio.Task[Any]
    pre_checkpoint_id: str | None


class AgentRuntime:
    """
    Runtime Adapter 入口（非 core）。

    - 持有 agent_id → Agent（id 与 Agent.agent_id / Application 登记一致）
    - CreateAgent 时必须调用集成方注入的 factory
    - 转发 invoke / stream / resume 到现有 Agent API
    - 当轮执行登记为 asyncio.Task；新请求会先 Cancel 同 session 上的当轮再开跑
    """

    def __init__(
        self,
        factory: AgentFactory,
        *,
        max_agents: int | None = None,
    ) -> None:
        if factory is None:
            raise TypeError("factory is required")
        if max_agents is not None and max_agents <= 0:
            raise ValueError("max_agents must be a positive int when set")
        self._agent_map: dict[str, Agent] = {}
        self._factory = factory
        self._max_agents = max_agents
        # (agent_id, session_id) → 当轮 ActiveRun
        self._active_runs: dict[tuple[str, str], _ActiveRun] = {}
        # 串行化 Cancel / 开跑，避免重叠请求撞 session already running
        self._schedule_lock = asyncio.Lock()

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
        if self._max_agents is not None and len(self._agent_map) >= self._max_agents:
            raise AgentLimitExceededError(
                f"max_agents limit reached: {self._max_agents}"
            )
        result = self._factory(config, runtime_options)
        agent = await result if inspect.isawaitable(result) else result
        if not isinstance(agent, Agent):
            raise TypeError(
                f"agent factory must return Agent, got {type(agent).__name__}"
            )
        if getattr(agent, "_compiled_graph", None) is None:
            raise TypeError(
                "agent factory must call Agent.compile() before returning"
            )
        agent_id = (agent.agent_id or "").strip()
        if not agent_id:
            raise TypeError("agent factory must set Agent.agent_id")
        if agent_id in self._agent_map:
            raise ValueError(f"agent already exists: {agent_id}")
        self._agent_map[agent_id] = agent
        return agent_id

    async def delete_agent(self, agent_id: str) -> None:
        """移除并丢弃 agent 实例（宿主业务结束时调用）。"""
        agent_id = (agent_id or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        if agent_id not in self._agent_map:
            raise KeyError(f"agent not found: {agent_id}")
        # 先中止该 agent 上未结束的当轮，再移除实例
        for aid, sid in [k for k in list(self._active_runs) if k[0] == agent_id]:
            await self.cancel(aid, sid)
        agent = self._agent_map.pop(agent_id)
        close = getattr(agent, "aclose", None) or getattr(agent, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def cancel(self, agent_id: str, session_id: str) -> bool:
        """
        中止指定 session 上正在进行的当轮执行。

        Returns:
            True：找到活跃 turn 并已取消（含 checkpoint 回滚尝试）；
            False：当时无活跃 turn（幂等成功）。

        Raises:
            KeyError: agent_id 不存在
            ValueError: agent_id / session_id 为空
        """
        agent_id = (agent_id or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        self._require_session_id(session_id)
        agent = self.get_agent(agent_id)

        async with self._schedule_lock:
            return await self._cancel_locked(agent, agent_id, session_id)

    async def _cancel_locked(
        self,
        agent: Agent,
        agent_id: str,
        session_id: str,
    ) -> bool:
        """Cancel 当轮（调用方须已持有 _schedule_lock）。"""
        key = (agent_id, session_id)
        run = self._active_runs.get(key)
        if run is None:
            return False

        run.task.cancel()
        try:
            await run.task
        except asyncio.CancelledError:
            pass

        current = self._active_runs.get(key)
        if current is run:
            self._active_runs.pop(key, None)

        await self._call_restore_checkpoint(agent, session_id, run.pre_checkpoint_id)
        return True

    async def invoke(
        self,
        agent_id: str,
        session_id: str,
        input: UserInput,
        agent_mode: AgentMode = AgentMode.AGENT,
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentInvokeResult:
        self._require_session_id(session_id)
        agent = self.get_agent(agent_id)

        async def _runner() -> AgentInvokeResult:
            result = await agent.ainvoke(
                session_id,
                input,
                agent_mode=agent_mode,
                http_request=http_request,
                metadata=metadata,
            )
            return to_invoke_result(agent, session_id, result)

        return await self._run_unary(agent_id, session_id, agent, _runner)

    async def stream(
        self,
        agent_id: str,
        session_id: str,
        input: UserInput,
        agent_mode: AgentMode = AgentMode.AGENT,
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        self._require_session_id(session_id)
        agent = self.get_agent(agent_id)

        async def _producer(queue: asyncio.Queue[Any]) -> None:
            try:
                stream = await agent.astream(
                    session_id,
                    input,
                    agent_mode=agent_mode,
                    http_request=http_request,
                    metadata=metadata,
                )
                async for event in iter_agent_events(agent, session_id, stream):
                    await queue.put(event)
            finally:
                # 取消路径下 finally 内 await 可能再次被 cancel；用 nowait 保证收尾
                queue.put_nowait(_STREAM_DONE)

        async for event in self._run_stream(agent_id, session_id, agent, _producer):
            yield event

    async def resume(
        self,
        agent_id: str,
        session_id: str,
        values: dict[str, Any],
        agent_mode: AgentMode = AgentMode.AGENT,
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentInvokeResult:
        self._require_session_id(session_id)
        agent = self.get_agent(agent_id)

        async def _runner() -> AgentInvokeResult:
            result = await agent.aresume(
                session_id,
                values,
                agent_mode=agent_mode,
                http_request=http_request,
                metadata=metadata,
            )
            return to_invoke_result(agent, session_id, result)

        return await self._run_unary(agent_id, session_id, agent, _runner)

    async def stream_resume(
        self,
        agent_id: str,
        session_id: str,
        values: dict[str, Any],
        agent_mode: AgentMode = AgentMode.AGENT,
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        self._require_session_id(session_id)
        agent = self.get_agent(agent_id)

        async def _producer(queue: asyncio.Queue[Any]) -> None:
            try:
                stream = await agent.astream_resume(
                    session_id,
                    values,
                    agent_mode=agent_mode,
                    http_request=http_request,
                    metadata=metadata,
                )
                async for event in iter_agent_events(agent, session_id, stream):
                    await queue.put(event)
            finally:
                queue.put_nowait(_STREAM_DONE)

        async for event in self._run_stream(agent_id, session_id, agent, _producer):
            yield event

    async def _run_unary(
        self,
        agent_id: str,
        session_id: str,
        agent: Agent,
        runner: Callable[[], Awaitable[AgentInvokeResult]],
    ) -> AgentInvokeResult:
        """将单次 ainvoke/aresume 放入 Task 并登记，供 Cancel 取消。"""
        async with self._schedule_lock:
            await self._cancel_locked(agent, agent_id, session_id)
            pre_checkpoint_id = self._read_pre_checkpoint_id(agent, session_id)
            task = asyncio.create_task(runner())
            self._begin_run(agent_id, session_id, task, pre_checkpoint_id)
        try:
            return await task
        finally:
            await self._finish_run(
                agent_id,
                session_id,
                agent,
                task=task,
                restore_if_cancelled=True,
            )

    async def _run_stream(
        self,
        agent_id: str,
        session_id: str,
        agent: Agent,
        producer: Callable[[asyncio.Queue[Any]], Awaitable[None]],
    ) -> AsyncIterator[AgentEvent]:
        """将 astream 消费放入 Task + Queue，供 Cancel 取消生产者。"""
        async with self._schedule_lock:
            await self._cancel_locked(agent, agent_id, session_id)
            pre_checkpoint_id = self._read_pre_checkpoint_id(agent, session_id)
            queue: asyncio.Queue[Any] = asyncio.Queue()
            task = asyncio.create_task(producer(queue))
            self._begin_run(agent_id, session_id, task, pre_checkpoint_id)
        completed_ok = False
        try:
            while True:
                item = await queue.get()
                if item is _STREAM_DONE:
                    break
                yield item
            await task
            completed_ok = True
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await self._finish_run(
                agent_id,
                session_id,
                agent,
                task=task,
                restore_if_cancelled=not completed_ok,
            )

    async def _finish_run(
        self,
        agent_id: str,
        session_id: str,
        agent: Agent,
        *,
        task: asyncio.Task[Any],
        restore_if_cancelled: bool,
    ) -> None:
        """结束登记；若本端清理且任务已取消，则回滚 checkpoint。"""
        run = self._end_run(agent_id, session_id, task=task)
        if run is None:
            return
        if restore_if_cancelled and task.cancelled():
            await self._call_restore_checkpoint(
                agent, session_id, run.pre_checkpoint_id
            )

    @staticmethod
    async def _call_restore_checkpoint(
        agent: Agent,
        session_id: str,
        pre_checkpoint_id: str | None,
    ) -> None:
        restore = getattr(agent, "restore_checkpoint", None)
        if not callable(restore):
            return
        result = restore(session_id, pre_checkpoint_id)
        if inspect.isawaitable(result):
            await result

    def _begin_run(
        self,
        agent_id: str,
        session_id: str,
        task: asyncio.Task[Any],
        pre_checkpoint_id: str | None,
    ) -> None:
        """登记当轮执行。调用方须已 Cancel 同 session 并持有 _schedule_lock。"""
        key = (agent_id, session_id)
        if key in self._active_runs:
            raise RuntimeError(f"session already running: {session_id}")
        self._active_runs[key] = _ActiveRun(
            task=task,
            pre_checkpoint_id=pre_checkpoint_id,
        )

    def _end_run(
        self,
        agent_id: str,
        session_id: str,
        *,
        task: asyncio.Task[Any] | None = None,
    ) -> _ActiveRun | None:
        """结束并移除当轮登记；task 非空时仅当仍是同一 Task 才移除。"""
        key = (agent_id, session_id)
        run = self._active_runs.get(key)
        if run is None:
            return None
        if task is not None and run.task is not task:
            return None
        return self._active_runs.pop(key, None)

    @staticmethod
    def _read_pre_checkpoint_id(agent: Agent, session_id: str) -> str | None:
        """读取当前 tip 的 checkpoint_id；全新 thread 可能为 None。"""
        snap = agent.get_state(session_id)
        config = getattr(snap, "config", None) or {}
        if not isinstance(config, dict):
            return None
        configurable = config.get("configurable") or {}
        if not isinstance(configurable, dict):
            return None
        checkpoint_id = configurable.get("checkpoint_id")
        if checkpoint_id is None or checkpoint_id == "":
            return None
        return str(checkpoint_id)

    @staticmethod
    def _require_session_id(session_id: str) -> None:
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id is required")

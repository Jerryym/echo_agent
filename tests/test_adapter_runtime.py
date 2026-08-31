"""AgentRuntime：agent_id 与 Agent 对齐；同 session 新请求抢占当轮。"""

from __future__ import annotations

import asyncio

from echo_agent import Agent, UserInput
from echo_agent.adapter.agent_runtime import AgentRuntime
from echo_agent.adapter.schema import AgentInvokeResult


def _stub_agent(*, agent_id: str) -> Agent:
    agent = Agent.__new__(Agent)
    agent._agent_config = type("Cfg", (), {"id": agent_id})()
    agent._compiled_graph = object()
    return agent


def test_create_agent_returns_agent_agent_id():
    expected = "ak-from-factory"

    async def _factory(config, runtime_options=None):
        del config, runtime_options
        return _stub_agent(agent_id=expected)

    async def _run():
        runtime = AgentRuntime(factory=_factory)
        agent_id = await runtime.create_agent(config=None)  # type: ignore[arg-type]
        assert agent_id == expected
        assert runtime.get_agent(expected) is not None

    asyncio.run(_run())


def test_create_agent_duplicate_id_raises():
    async def _factory(config, runtime_options=None):
        del config, runtime_options
        return _stub_agent(agent_id="ak-dup")

    async def _run():
        runtime = AgentRuntime(factory=_factory)
        await runtime.create_agent(config=None)  # type: ignore[arg-type]
        try:
            await runtime.create_agent(config=None)  # type: ignore[arg-type]
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "already exists" in str(exc)

    asyncio.run(_run())


def test_invoke_preempts_in_flight_same_session():
    started = asyncio.Event()
    cancelled = asyncio.Event()
    restore_ids: list[str | None] = []
    invoke_n = 0

    class _FakeAgent:
        async def ainvoke(self, session_id, input, **kwargs):
            del kwargs
            nonlocal invoke_n
            invoke_n += 1
            n = invoke_n
            if n == 1:
                started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            return {"response": f"ok-{input.text}"}

        def get_state(self, session_id):
            del session_id

            class _State:
                interrupts = ()
                tasks = ()
                config = {}

            return _State()

        def restore_checkpoint(self, session_id, checkpoint_id):
            del session_id
            restore_ids.append(checkpoint_id)

    async def _factory(config, runtime_options=None):
        del config, runtime_options
        return _FakeAgent()

    async def _run():
        runtime = AgentRuntime(factory=_factory)
        fake = _FakeAgent()
        runtime._agent_map["aid"] = fake  # type: ignore[assignment]

        first = asyncio.create_task(
            runtime.invoke("aid", "sid", UserInput(text="one"))
        )
        await started.wait()
        second = await runtime.invoke("aid", "sid", UserInput(text="two"))
        assert cancelled.is_set()
        assert restore_ids  # 抢占路径回滚当轮
        assert second.output == "ok-two"
        assert isinstance(second, AgentInvokeResult)
        with_exc = await asyncio.gather(first, return_exceptions=True)
        assert isinstance(with_exc[0], asyncio.CancelledError)

    asyncio.run(_run())

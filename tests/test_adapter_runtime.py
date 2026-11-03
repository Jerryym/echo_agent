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

        def cancel_current_turn(self, session_id):
            del session_id
            restore_ids.append("cancelled")

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


def test_concurrent_creation_reserves_capacity_and_releases_on_cancel():
    from echo_agent.adapter.agent_runtime import AgentLimitExceededError

    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def factory(config, options):
            entered.set()
            await release.wait()
            return _stub_agent(agent_id="reserved")

        runtime = AgentRuntime(factory, max_agents=1)
        first = asyncio.create_task(runtime.create_agent(None))
        await entered.wait()
        try:
            await runtime.create_agent(None)
        except AgentLimitExceededError:
            pass
        else:
            raise AssertionError("concurrent creation exceeded capacity")
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        release.set()
        assert await runtime.create_agent(None) == "reserved"

    asyncio.run(run())


def test_delete_rejects_request_already_waiting_to_start():
    from unittest.mock import MagicMock

    async def run():
        runtime = AgentRuntime(lambda *_: None)
        agent = MagicMock()
        agent.aclose = None
        runtime._agent_map["aid"] = agent
        await runtime._schedule_lock.acquire()
        deleting = asyncio.create_task(runtime.delete_agent("aid"))
        await asyncio.sleep(0)
        invoked = False

        async def runner():
            nonlocal invoked
            invoked = True
            return AgentInvokeResult(output="unexpected")

        pending = asyncio.create_task(runtime._run_unary("aid", "new", agent, runner))
        await asyncio.sleep(0)
        runtime._schedule_lock.release()
        await deleting
        result = await asyncio.gather(pending, return_exceptions=True)
        assert isinstance(result[0], KeyError)
        assert not invoked
        assert not runtime._active_runs
        agent.close.assert_called_once()

    asyncio.run(run())


def test_old_sse_cleanup_preserves_replacement_run():
    from unittest.mock import AsyncMock, MagicMock
    from echo_agent.adapter.agent_runtime import _STREAM_DONE
    from echo_agent.adapter.http.sse import iter_sse
    from echo_agent.adapter.schema import AgentEvent

    async def run():
        runtime = AgentRuntime(lambda *_: None)
        agent = MagicMock()
        runtime._agent_map["aid"] = agent
        started = asyncio.Event()
        release = asyncio.Event()

        async def producer(queue):
            try:
                await queue.put(AgentEvent(type="message", data={}))
                await asyncio.Event().wait()
            finally:
                queue.put_nowait(_STREAM_DONE)

        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)
        events = runtime._run_stream("aid", "sid", agent, producer)
        sse = iter_sse(request, runtime, "aid", "sid", events, operation="Stream")
        await anext(sse)

        async def runner():
            started.set()
            await release.wait()
            return AgentInvokeResult(output="replacement")

        replacement = asyncio.create_task(runtime._run_unary("aid", "sid", agent, runner))
        await started.wait()
        remaining = [frame async for frame in sse]
        assert any("cancelled" in frame for frame in remaining)
        assert not replacement.done()
        release.set()
        assert (await replacement).output == "replacement"
        assert not runtime._active_runs

    asyncio.run(run())

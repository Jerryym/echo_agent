"""交互用量增量累计回归，不使用外部模型。"""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime

from echo_agent import Agent, AgentConfig, BaseContext, BaseState, LLMConfig, Node, UserInput
from echo_agent.core.agent.agent_session import AgentSession
from echo_agent.core.graph import END_NODE, START_NODE, GraphCompileOptions, GraphSchema
from echo_agent.core.llm.llm_result import LLMResult
from echo_agent.core.model.agent import AgentResult
from echo_agent.core.model.session import SessionState
from echo_agent.core.model.token_usage import TokenUsage
from echo_agent.core.strategy.react.node.reason_node import ReasonNode
from echo_agent.core.strategy.react.schema import ReActContext, ReActState
from echo_agent.utils import update_agent_reasoning, update_agent_result, update_token_usage


def config() -> LLMConfig:
    return LLMConfig(base_url="http://localhost/v1", api_key="offline", model_name="mock")


class _UsageNode(Node):
    def run(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict[str, object]:
        del state
        update_agent_result(runtime.context, "上下文已压缩", TokenUsage(input_tokens=20, output_tokens=5))
        update_agent_result(runtime.context, "reply", TokenUsage(input_tokens=10, output_tokens=2))
        return {"response": "reply"}

    async def arun(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict[str, object]:
        return self.run(state, runtime)


class TokenUsageAccountingTests(unittest.TestCase):
    def test_increment_and_content_are_independent(self) -> None:
        context = BaseContext(session_state=SessionState(), agent_result=AgentResult())
        usage = TokenUsage(input_tokens=10, output_tokens=3, cache_hit=4, reasoning_tokens=2)
        update_token_usage(context, usage)
        update_agent_reasoning(context, "assessment")
        self.assertEqual(context.agent_result.token_usage, usage)
        self.assertEqual(context.session_state.token_usage, usage)
        self.assertEqual(context.agent_result.reasoning, ["assessment"])
        self.assertIsNot(context.agent_result.token_usage, context.session_state.token_usage)
        update_agent_result(context, "reply", usage)
        self.assertEqual(context.session_state.token_usage, usage.add(usage))
        self.assertEqual(context.agent_result.token_usage, usage.add(usage))

    def test_completion_does_not_readd_turn_usage(self) -> None:
        for asynchronous in (False, True):
            agent = Agent(AgentConfig(name="accounting", llm_config=config()), GraphSchema(state_schema=BaseState), GraphCompileOptions(checkpointer=InMemorySaver()))
            agent.add_node(_UsageNode("usage"))
            agent.add_edge(START_NODE, "usage")
            agent.add_edge("usage", END_NODE)
            agent.compile()
            for index in range(2):
                output = asyncio.run(agent.ainvoke("s", UserInput(text="hello"))) if asynchronous else agent.invoke("s", UserInput(text="hello"))
                self.assertEqual(output.token_usage.total_tokens, 37)
                self.assertEqual(agent.get_sesion("s").state.token_usage.total_tokens, 37 * (index + 1))

    def test_wait_resume_cancel_failure_preserve_spent_usage(self) -> None:
        for terminal in ("cancel", "fail"):
            session = AgentSession("s", 256_000, config())
            turn = session.start_turn(UserInput(text="hello"))
            context = BaseContext(session_state=session.state, agent_result=turn.result)
            update_token_usage(context, TokenUsage(input_tokens=10))
            session.wait_turn()
            resumed = BaseContext(session_state=session.state, agent_result=turn.result)
            update_token_usage(resumed, TokenUsage(output_tokens=4))
            if terminal == "cancel":
                session.cancel_turn()
            else:
                session.fail_turn("test failure")
            self.assertEqual(session.state.token_usage.total_tokens, 14)
            self.assertEqual(session.turns[0].result.token_usage.total_tokens, 14)
            self.assertIsNone(session.current_turn)

    def test_reason_validation_failure_keeps_usage_sync_and_async(self) -> None:
        for asynchronous in (False, True):
            for structured in ({}, {"assessment": "", "next_action": "", "tool_list": [], "task_status": "completed"}, {"assessment": "done", "next_action": "", "tool_list": [], "task_status": "completed"}):
                node = ReasonNode("reason", config())
                response = LLMResult(text="", structured=structured, token_usage=TokenUsage(input_tokens=20, output_tokens=3))
                node._llm_client.invoke_structured = Mock(return_value=response)
                node._llm_client.ainvoke_structured = AsyncMock(return_value=response)
                context = ReActContext(session_state=SessionState(), agent_result=AgentResult())
                state = ReActState()
                runtime = Runtime(context=context)
                kwargs = {"prompt": "prompt", "user_input": "input"}
                if asynchronous:
                    result = asyncio.run(node._ainvoke_reason_result(state, kwargs, runtime))
                else:
                    result = node._invoke_reason_result(state, kwargs, runtime)
                self.assertEqual(context.agent_result.token_usage.total_tokens, 23)
                self.assertEqual(context.session_state.token_usage.total_tokens, 23)
                self.assertEqual(state.steps[0].token_usage.total_tokens, 23)
                if structured.get("assessment"):
                    self.assertIsNotNone(result)
                    self.assertEqual(context.agent_result.reasoning, ["done"])
                else:
                    self.assertIsNone(result)
                    self.assertEqual(context.agent_result.reasoning, [])


if __name__ == "__main__":
    unittest.main()

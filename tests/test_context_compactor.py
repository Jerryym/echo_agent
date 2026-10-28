"""会话压缩的用户消息保留和目标容量回归，无需模型服务。"""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from echo_agent.core.llm import ContextBudgetGateway
from echo_agent.core.llm.llm_result import LLMResult
from echo_agent.core.model.context import CompactedContext, ContextState
from echo_agent.core.model.message import Message, Role
from echo_agent.core.model.token_usage import TokenUsage
from echo_agent.core.model.tool import ToolCall
from echo_agent.core.runtime.context import ContextCompactor


def compactor() -> ContextCompactor:
    instance = ContextCompactor.__new__(ContextCompactor)
    instance._retain_recent_tokens = 32_000
    instance._prompt = "summarize"
    instance._user_input = "Preserve older user requirements in the summary."
    instance._llm_client = Mock()
    return instance


def response(goal: str) -> LLMResult:
    return LLMResult(text="", structured={"goal": goal}, token_usage=TokenUsage(input_tokens=10, output_tokens=2))


def context() -> ContextState:
    return ContextState(
        messages=[Message(role=Role.USER, content="old preference " * 500), Message(role=Role.USER, content="current request")],
        context_window=600,
        auto_compact_threshold=500,
    )


class ContextCompactorTests(unittest.TestCase):
    def test_old_user_messages_are_compressed_sync_and_async(self) -> None:
        for asynchronous in (False, True):
            instance = compactor()
            instance._llm_client.invoke_structured = Mock(return_value=response("task"))
            instance._llm_client.ainvoke_structured = AsyncMock(return_value=response("task"))
            original = context()
            snapshot = original.model_dump_json()
            candidate, usage = asyncio.run(instance.acompress(original)) if asynchronous else instance.compress(original)
            self.assertEqual(original.model_dump_json(), snapshot)
            self.assertEqual(candidate.messages[-1].content, "current request")
            self.assertEqual(sum(m.role == Role.USER for m in candidate.messages), 1)
            self.assertLess(ContextBudgetGateway.calculate_tokens(candidate.messages), original.auto_compact_threshold)
            self.assertEqual(usage.total_tokens, 12)

    def test_oversized_summary_retries_and_accumulates_usage(self) -> None:
        for asynchronous in (False, True):
            instance = compactor()
            instance._llm_client.invoke_structured = Mock(side_effect=[response("large " * 1000), response("short")])
            instance._llm_client.ainvoke_structured = AsyncMock(side_effect=[response("large " * 1000), response("short")])
            original = context()
            candidate, usage = asyncio.run(instance.acompress(original)) if asynchronous else instance.compress(original)
            self.assertLess(ContextBudgetGateway.calculate_tokens(candidate.messages), 500)
            self.assertEqual(usage.total_tokens, 24)

    def test_exhaustion_never_returns_oversized_candidate(self) -> None:
        for asynchronous in (False, True):
            instance = compactor()
            instance._llm_client.invoke_structured = Mock(return_value=response("large " * 1000))
            instance._llm_client.ainvoke_structured = AsyncMock(return_value=response("large " * 1000))
            original = context()
            snapshot = original.model_dump_json()
            with self.assertRaisesRegex(ValueError, "did not reach"):
                if asynchronous:
                    asyncio.run(instance.acompress(original))
                else:
                    instance.compress(original)
            call = instance._llm_client.ainvoke_structured if asynchronous else instance._llm_client.invoke_structured
            self.assertEqual(call.call_count, 3)
            self.assertEqual(original.model_dump_json(), snapshot)

    def test_impossible_protected_input_fails_before_model(self) -> None:
        instance = compactor()
        original = ContextState(messages=[Message(role=Role.USER, content="huge " * 1000)], auto_compact_threshold=100)
        with self.assertRaisesRegex(ValueError, "Protected messages"):
            instance.compress(original)
        instance._llm_client.invoke_structured.assert_not_called()

    def test_tool_groups_and_pending_tail_are_not_split(self) -> None:
        instance = compactor()
        call = Message(role=Role.ASSISTANT, tool_calls=[ToolCall(name="echo", tool_call_id="c1")])
        result = Message(role=Role.TOOL, tool_call_id="c1", content="value")
        latest = Message(role=Role.USER, content="latest")
        selected = instance._select_messages([call, result, latest], 0)
        self.assertIsNotNone(selected)
        source, retained = selected
        self.assertEqual(source, [call, result])
        self.assertEqual(retained, [latest])
        pending = Message(role=Role.ASSISTANT, tool_calls=[ToolCall(name="echo", tool_call_id="c2")])
        source, retained = instance._select_messages([call, result, latest, pending], 0)
        self.assertEqual(source, [call, result])
        self.assertEqual(retained, [latest, pending])

    def test_old_summary_is_replaced_and_below_target_noop_is_safe(self) -> None:
        instance = compactor()
        old = Message(role=Role.SYSTEM, content=instance.SUMMARY_PREFIX + "old")
        source, retained = instance._select_messages([old, Message(role=Role.USER, content="latest")])
        self.assertEqual(source, [old])
        self.assertEqual(len(retained), 1)
        original = ContextState(messages=[Message(role=Role.USER, content="latest")])
        candidate, usage = instance.compress(original)
        self.assertEqual(candidate, original)
        self.assertIsNot(candidate, original)
        self.assertEqual(usage.total_tokens, 0)
        instance._llm_client.invoke_structured.assert_not_called()


if __name__ == "__main__":
    unittest.main()

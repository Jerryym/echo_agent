"""结构化工具输出重试回归；不访问模型服务。"""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

import httpx
from openai import BadRequestError
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from echo_agent.core.llm.exception import LLMResponseDecodeError
from echo_agent.core.llm.llm_client import LLMClient
from echo_agent.core.llm.llm_config import LLMConfig
from echo_agent.core.llm.llm_result import LLMResult
from echo_agent.core.llm.structured_output import create_structured_output_tool
from echo_agent.core.model.message import Message, Role


class Output(BaseModel):
    answer: int


def response(text: str = "", arguments: str | None = None) -> ChatCompletion:
    tool_name = create_structured_output_tool(Output).name
    return ChatCompletion.model_validate({
        "id": "test", "created": 0, "model": "test", "object": "chat.completion",
        "choices": [{
            "index": 0, "finish_reason": "tool_calls" if arguments is not None else "stop",
            "message": {
                "role": "assistant", "content": text,
                "tool_calls": [] if arguments is None else [{
                    "id": "call_test", "type": "function",
                    "function": {"name": tool_name, "arguments": arguments},
                }],
            },
        }],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    })


def thinking_error() -> BadRequestError:
    return BadRequestError(
        "Thinking mode does not support this tool_choice",
        response=httpx.Response(400, request=httpx.Request("POST", "https://unused.invalid")),
        body=None,
    )


class StructuredRetryTests(unittest.TestCase):
    def test_structured_tool_retries(self) -> None:
        dsml = response('<｜｜DSML｜｜ calls><｜｜DSML｜｜ invoke name="read_skill_resource">')
        invalid = response(arguments='{"answer":"invalid"}')
        good = response(arguments='{"answer":42}')
        scenarios = [
            ([dsml, good], False),
            ([invalid, good], False),
            ([response(arguments="not JSON"), good], False),
            ([thinking_error(), dsml, good], False),
            ([dsml, thinking_error(), good], False),
            ([dsml, dsml], True),
            ([thinking_error(), dsml, dsml], True),
        ]
        for asynchronous in (False, True):
            for tool_replies, fails in scenarios:
                with self.subTest(asynchronous=asynchronous, replies=len(tool_replies), fails=fails):
                    client = LLMClient.__new__(LLMClient)
                    client._config = LLMConfig(base_url="https://unused.invalid", api_key="unused", model_name="test")
                    replies = [response("invalid JSON"), response("invalid JSON"), *tool_replies]
                    call = AsyncMock(side_effect=replies) if asynchronous else Mock(side_effect=replies)
                    messages = [Message(role=Role.USER, content="original")]
                    client._invoke_model = call
                    client._ainvoke_model = call

                    def invoke() -> LLMResult:
                        if asynchronous:
                            return asyncio.run(client._astructured_output(Output, messages))
                        return client._structured_output(Output, messages)

                    if fails:
                        with self.assertRaises(LLMResponseDecodeError):
                            invoke()
                    else:
                        result = invoke()
                        self.assertEqual(result.structured, {"answer": 42})
                        count = sum(isinstance(reply, ChatCompletion) for reply in replies)
                        self.assertEqual(result.token_usage.input_tokens, count * 2)
                    self.assertEqual(call.call_count, len(replies))
                    self.assertEqual(len(messages), 1)
                    tool_calls = call.call_args_list[2:]
                    for index, reply in enumerate(tool_replies):
                        if isinstance(reply, BadRequestError):
                            self.assertTrue(tool_calls[index + 1].kwargs["disable_thinking"])
                    retry = call.call_args
                    retry_messages = retry.args[0] if retry.args else retry.kwargs["messages"]
                    self.assertIn("DSML", retry_messages[-1].content)


if __name__ == "__main__":
    unittest.main()

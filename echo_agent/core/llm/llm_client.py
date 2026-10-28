from collections.abc import AsyncIterator, Iterator, Sequence
import json
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from openai import AsyncOpenAI, BadRequestError, OpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionMessageParam,
)
from openai.types.responses import Response, ResponseInputParam, ResponseStreamEvent

from ...common import get_logger
from ...utils import MessageAdapter, ToolAdapter
from ..model.input import UserInput
from ..model.message import Message, Role
from ..model.token_usage import TokenUsage
from ..model.tool import ToolCall
from .context_budget_gateway import ContextBudgetGateway
from .exception import (
    LLMException,
    LLMInitializeError,
    LLMInvokeError,
    LLMResponseDecodeError,
)
from .llm_config import LLMConfig
from .llm_result import LLMResult
from .structured_output import (
    StructuredOutputSchema,
    create_structured_output_tool,
    validate_structured_output,
)

logger = get_logger("llm")


class LLMClient:
    """
    LLM客户端：提供LLM调用接口，支持同步和异步调用，支持结构化输出，支持流式输出
    """
    def __init__(self, config: LLMConfig) -> None:
        try:
            self._config = config
            self._client = OpenAI(
                api_key=config.api_key, base_url=config.base_url,
                timeout=config.timeout,
                max_retries=config.max_retries,
                default_headers=config.default_headers or None,
            )
            self._async_client = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=config.timeout,
                max_retries=config.max_retries,
                default_headers=config.default_headers or None,
            )
        except Exception as exc:
            raise LLMInitializeError(message="LLM client initialize failed", detail=str(exc)) from exc

    def invoke(
        self, 
        prompt: str, 
        user_input: UserInput | dict[str, Any] | str,
        history: Sequence[Message] | None = None,
        tool_list: list[BaseTool | dict[str, Any]] | None = None,
        config: RunnableConfig | None = None,
    ) -> LLMResult:
        try:
            messages = self._build_messages(prompt, user_input, history)
            self._log_context_usage(messages, tool_list)
            return self._parse_response(self._invoke_model(messages, tool_list))
        except LLMException:
            raise
        except Exception as exc:
            raise LLMInvokeError(message="LLM invoke failed", detail=str(exc)) from exc

    async def ainvoke(
        self, 
        prompt: str, 
        user_input: UserInput | dict[str, Any] | str,
        history: Sequence[Message] | None = None,
        tool_list: list[BaseTool | dict[str, Any]] | None = None,
        config: RunnableConfig | None = None,
    ) -> LLMResult:
        try:
            messages = self._build_messages(prompt, user_input, history)
            self._log_context_usage(messages, tool_list)
            return self._parse_response(await self._ainvoke_model(messages, tool_list))
        except LLMException:
            raise
        except Exception as exc:
            raise LLMInvokeError(message="LLM async invoke failed", detail=str(exc)) from exc

    def invoke_structured(
        self, 
        schema: StructuredOutputSchema, 
        prompt: str,
        user_input: UserInput | dict[str, Any] | str,
        history: Sequence[Message] | None = None,
        config: RunnableConfig | None = None,
    ) -> LLMResult:
        try:
            messages = self._build_messages(prompt, user_input, history)
            self._log_context_usage(messages)
            return self._structured_output(schema, self._build_structured_output_instruction(messages))
        except LLMException:
            raise
        except Exception as exc:
            raise LLMInvokeError(message="LLM structured invoke failed", detail=str(exc)) from exc

    async def ainvoke_structured(
        self, 
        schema: StructuredOutputSchema, 
        prompt: str,
        user_input: UserInput | dict[str, Any] | str,
        history: Sequence[Message] | None = None,
        config: RunnableConfig | None = None,
    ) -> LLMResult:
        try:
            messages = self._build_messages(prompt, user_input, history)
            self._log_context_usage(messages)
            return await self._astructured_output(schema, self._build_structured_output_instruction(messages))
        except LLMException:
            raise
        except Exception as exc:
            raise LLMInvokeError(message="LLM structured invoke failed", detail=str(exc)) from exc

    def stream(
        self, 
        prompt: str, 
        user_input: UserInput | dict[str, Any] | str,
        history: Sequence[Message] | None = None,
        tool_list: list[BaseTool | dict[str, Any]] | None = None,
        config: RunnableConfig | None = None,
    ) -> Iterator[LLMResult]:
        try:
            messages = self._build_messages(prompt, user_input, history)
            self._log_context_usage(messages, tool_list)
            pending: dict[int, dict[str, str]] = {}
            completed = False
            for item in self._stream_model(messages, tool_list):
                if isinstance(item, ChatCompletionChunk):
                    result = self._build_chat_stream_result(item, pending)
                else:
                    if item.type == "response.completed":
                        completed = True
                    result = self._build_responses_stream_result(item)
                if result is not None:
                    yield result
            if pending or (self._config.use_responses_api and not completed):
                raise LLMResponseDecodeError(message="Stream ended without completing")
        except LLMException:
            raise
        except Exception as exc:
            raise LLMInvokeError(message="LLM stream invoke failed", detail=str(exc)) from exc

    async def astream(
        self, 
        prompt: str, 
        user_input: UserInput | dict[str, Any] | str,
        history: Sequence[Message] | None = None,
        tool_list: list[BaseTool | dict[str, Any]] | None = None,
        config: RunnableConfig | None = None,
    ) -> AsyncIterator[LLMResult]:
        try:
            messages = self._build_messages(prompt, user_input, history)
            self._log_context_usage(messages, tool_list)
            pending: dict[int, dict[str, str]] = {}
            completed = False
            async for item in self._astream_model(messages, tool_list):
                if isinstance(item, ChatCompletionChunk):
                    result = self._build_chat_stream_result(item, pending)
                else:
                    if item.type == "response.completed":
                        completed = True
                    result = self._build_responses_stream_result(item)
                if result is not None:
                    yield result
            if pending or (self._config.use_responses_api and not completed):
                raise LLMResponseDecodeError(message="Stream ended without completing")
        except LLMException:
            raise
        except Exception as exc:
            raise LLMInvokeError(message="LLM async stream invoke failed", detail=str(exc)) from exc

    def _build_messages(self, prompt: str, user_input: UserInput | dict[str, Any] | str, history: Sequence[Message] | None = None) -> list[Message]:
        """构建消息列表"""
        messages = [Message(role=Role.SYSTEM, content=prompt), *(history or [])]
        if isinstance(user_input, UserInput):
            content: str | list[str | dict[str, Any]] = user_input.text
            if user_input.attachments:
                parts: list[str | dict[str, Any]] = [{"type": "text", "text": user_input.text}]
                for attachment in user_input.attachments:
                    if attachment.format == "url":
                        parts.append({
                            "type": "text", 
                            "text": f"[{attachment.type}] {attachment.data}"
                        })
                    else:
                        mime_types = {"image": "image/jpeg", "audio": "audio/wav", "file": "application/pdf"}
                        parts.append({
                            "type": attachment.type,
                            "base64": attachment.data,
                            "mime_type": mime_types[attachment.type]
                        })
                content = parts
            messages.append(Message(role=Role.USER, content=content))
        elif isinstance(user_input, str):
            messages.append(Message(role=Role.USER, content=user_input))
        else:
            messages.append(Message(role=Role.USER, content=json.dumps(user_input, ensure_ascii=False, default=str)))
        return messages

    def _log_context_usage(self, messages: list[Message], tools: list[BaseTool | dict[str, Any]] | None = None) -> None:
        """记录本次请求的上下文用量"""
        usage = ContextBudgetGateway.calculate_total_tokens(messages, tools=tools)
        logger.info("context usage = %s", usage)

    def _check_context_budget(self, messages: list[Message], tools: list[BaseTool | dict[str, Any]] | None = None) -> bool:
        tokens = ContextBudgetGateway.calculate_total_tokens(messages=messages, tools=tools)
        return ContextBudgetGateway.is_over_budget(
            tokens=tokens, 
            budget=self._config.context_window - self._config.max_tokens
        )

    def _chat_messages(self, messages: list[Message]) -> list[ChatCompletionMessageParam]:
        return MessageAdapter.to_openai_messages(messages)

    def _build_response_input(self, messages: list[Message]) -> ResponseInputParam:
        return MessageAdapter.to_openai_response_input(messages)

    def _chat_tools(self, tools: list[BaseTool | dict[str, Any]] | None) -> list[dict[str, Any]]:
        return ToolAdapter.to_openai_chat_tools(tools)

    def _build_response_tools(self, tools: list[BaseTool | dict[str, Any]] | None) -> list[dict[str, Any]]:
        return ToolAdapter.to_openai_response_tools(tools, self._config.builtin_tools)

    def _reasoning_effort(self, disable_thinking: bool = False) -> str | None:
        if disable_thinking:
            return "none"
        return self._config.reasoning.effort if self._config.reasoning is not None else None

    def _build_chat_kwargs(
        self, 
        messages: list[Message],
        tools: list[BaseTool | dict[str, Any]] | None = None,
        json_mode: bool = False, tool_choice: dict[str, Any] | str | None = None,
        disable_thinking: bool = False
    ) -> dict[str, Any]:
        """构建 Chat API 参数"""
        if self._check_context_budget(messages, tools):
            logger.warning("LLM context budget exceeded; compaction is not yet integrated")

        kwargs: dict[str, Any] = {
            "model": self._config.model_name, 
            "messages": self._chat_messages(messages),
            "max_completion_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
        }
        converted_tools = self._chat_tools(tools)
        if converted_tools:
            kwargs.update(tools=converted_tools, parallel_tool_calls=self._config.parallel_tool_calls)
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        effort = self._reasoning_effort(disable_thinking)
        if effort is not None:
            kwargs["reasoning_effort"] = effort
        if self._config.extra_body:
            kwargs["extra_body"] = self._config.extra_body
        return kwargs

    def _responses_kwargs(
        self, 
        messages: list[Message],
        tools: list[BaseTool | dict[str, Any]] | None = None,
        json_mode: bool = False,
        tool_choice: dict[str, Any] | str | None = None,
        disable_thinking: bool = False
    ) -> dict[str, Any]:
        """构建 Responses API 参数"""
        if self._check_context_budget(messages, tools):
            logger.warning("LLM context budget exceeded; compaction is not yet integrated")

        kwargs: dict[str, Any] = {
            "model": self._config.model_name, 
            "input": self._build_response_input(messages),
            "max_output_tokens": self._config.max_tokens,
            "truncation": "disabled",
            "store": False,
            "temperature": self._config.temperature,
        }
        converted_tools = self._build_response_tools(tools)
        if converted_tools:
            kwargs.update(tools=converted_tools, parallel_tool_calls=self._config.parallel_tool_calls)
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if json_mode:
            kwargs["text"] = {"format": {"type": "json_object"}}
        effort = self._reasoning_effort(disable_thinking)
        if effort is not None:
            kwargs["reasoning"] = {"effort": effort}
        if self._config.extra_body:
            kwargs["extra_body"] = self._config.extra_body
        return kwargs

    def _invoke_model(
        self, 
        messages: list[Message],
        tools: list[BaseTool | dict[str, Any]] | None = None,
        json_mode: bool = False, 
        tool_choice: dict[str, Any] | str | None = None,
        disable_thinking: bool = False
    ) -> ChatCompletion | Response:
        if self._config.use_responses_api:
            return self._client.responses.create(**cast(Any, self._responses_kwargs(
                messages, tools, json_mode, tool_choice, disable_thinking)))
        return self._client.chat.completions.create(**cast(Any, self._build_chat_kwargs(
            messages, tools, json_mode, tool_choice, disable_thinking)))

    async def _ainvoke_model(
        self, 
        messages: list[Message],
        tools: list[BaseTool | dict[str, Any]] | None = None,
        json_mode: bool = False, 
        tool_choice: dict[str, Any] | str | None = None,
        disable_thinking: bool = False
    ) -> ChatCompletion | Response:
        if self._config.use_responses_api:
            return await self._async_client.responses.create(**cast(Any, self._responses_kwargs(
                messages, tools, json_mode, tool_choice, disable_thinking)))
        return await self._async_client.chat.completions.create(**cast(Any, self._build_chat_kwargs(
            messages, tools, json_mode, tool_choice, disable_thinking)))

    def _stream_model(self, messages: list[Message], tools: list[BaseTool | dict[str, Any]] | None = None) -> Iterator[ChatCompletionChunk | ResponseStreamEvent]:
        if self._config.use_responses_api:
            kwargs = self._responses_kwargs(messages, tools)
            kwargs["stream"] = True
            stream = self._client.responses.create(**cast(Any, kwargs))
            with stream:
                for event in stream:
                    yield event
        else:
            kwargs = self._build_chat_kwargs(messages, tools)
            kwargs.update(stream=True, stream_options={"include_usage": True})
            stream = self._client.chat.completions.create(**cast(Any, kwargs))
            with stream:
                for chunk in stream:
                    yield chunk

    async def _astream_model(self, messages: list[Message], tools: list[BaseTool | dict[str, Any]] | None = None) -> AsyncIterator[ChatCompletionChunk | ResponseStreamEvent]:
        if self._config.use_responses_api:
            kwargs = self._responses_kwargs(messages, tools)
            kwargs["stream"] = True
            stream = await self._async_client.responses.create(**cast(Any, kwargs))
            async with stream:
                async for event in stream:
                    yield event
        else:
            kwargs = self._build_chat_kwargs(messages, tools)
            kwargs.update(stream=True, stream_options={"include_usage": True})
            stream = await self._async_client.chat.completions.create(**cast(Any, kwargs))
            async with stream:
                async for chunk in stream:
                    yield chunk

    @staticmethod
    def _chat_usage(response: ChatCompletion) -> TokenUsage:
        usage = response.usage
        if usage is None:
            return TokenUsage()
        prompt = usage.prompt_tokens_details
        completion = usage.completion_tokens_details
        return TokenUsage(
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cache_hit=(prompt.cached_tokens or 0) if prompt else 0,
            reasoning_tokens=(completion.reasoning_tokens or 0) if completion else 0
        )

    @staticmethod
    def _response_usage(response: Response) -> TokenUsage:
        usage = response.usage
        if usage is None:
            return TokenUsage()
        return TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_hit=usage.input_tokens_details.cached_tokens,
            reasoning_tokens=usage.output_tokens_details.reasoning_tokens
        )

    @staticmethod
    def _extract_usage(response: ChatCompletion | Response) -> TokenUsage:
        """提取token usage信息"""
        if isinstance(response, ChatCompletion):
            return LLMClient._chat_usage(response)
        return LLMClient._response_usage(response)

    def _parse_response(self, response: ChatCompletion | Response) -> LLMResult:
        if isinstance(response, ChatCompletion):
            if not response.choices:
                raise LLMResponseDecodeError(message="Chat Completion response has no choices")
            
            choice = response.choices[0]
            message = MessageAdapter.from_openai_message(choice.message)
            extra = choice.message.model_extra or {}
            reasoning = extra.get("reasoning_content")
            return LLMResult(
                text=message.content if isinstance(message.content, str) else "",
                reasoning=reasoning if isinstance(reasoning, str) else None,
                tool_calls=message.tool_calls, raw=response.model_dump(mode="json"),
                response_metadata={
                    "id": response.id,
                    "model": response.model,
                    "finish_reason": choice.finish_reason,
                },
                token_usage=self._chat_usage(response)
            )
        
        if response.status in ("failed", "incomplete"):
            raise LLMResponseDecodeError(message="Responses request did not complete", detail=str(response.status))
        
        text_parts: list[str] = []
        thinking: list[str] = []
        calls: list[ToolCall] = []
        for item in response.output:
            if item.type == "message":
                for part in item.content:
                    if part.type == "output_text":
                        text_parts.append(part.text)
            elif item.type == "function_call":
                calls.append(ToolCall(
                    name=item.name,
                    args=self._load_json_object(item.arguments),
                    tool_call_id=item.call_id
                ))
            elif item.type == "reasoning":
                thinking.extend(part.text for part in item.summary if part.type == "summary_text")
        return LLMResult(
            text="".join(text_parts), reasoning="\n".join(thinking) or None,
            tool_calls=calls, raw=response.model_dump(mode="json"),
            response_metadata={
                "id": response.id,
                "model": response.model,
                "status": response.status,
            },
            token_usage=self._response_usage(response)
        )

    @staticmethod
    def _normalize_json_text(text: str) -> str:
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:].lstrip()
        elif text.startswith("```"):
            text = text[3:].lstrip()
        if text.endswith("```"):
            text = text[:-3].rstrip()
        return text

    def _load_json_object(self, text: str) -> dict[str, Any]:
        """加载 JSON 对象"""
        try:
            payload: Any = json.loads(self._normalize_json_text(text))
        except (ValueError, TypeError) as exc:
            raise LLMResponseDecodeError(message="Invalid JSON output", detail=str(exc)) from exc
        if not isinstance(payload, dict):
            raise LLMResponseDecodeError(message="Structured output must be a JSON object")
        return cast(dict[str, Any], payload)

    def _parse_structured(self, schema: StructuredOutputSchema, response: ChatCompletion | Response) -> LLMResult:
        """解析结构化输出"""
        result = self._parse_response(response)
        try:
            result.structured = validate_structured_output(schema, self._load_json_object(result.text))
        except LLMException:
            raise
        except Exception as exc:
            raise LLMResponseDecodeError(message="Structured output validation failed", detail=str(exc)) from exc
        return result

    def _parse_structured_tool(self, schema: StructuredOutputSchema, tool_name: str, response: ChatCompletion | Response) -> LLMResult:
        """解析结构化工具输出"""
        try:
            result = self._parse_response(response)
        except ValueError as exc:
            raise LLMResponseDecodeError(message="Structured tool response invalid", detail=str(exc)) from exc
        for call in result.tool_calls or []:
            if call.name == tool_name:
                try:
                    result.structured = validate_structured_output(schema, call.args)
                except Exception as exc:
                    raise LLMResponseDecodeError(message="Structured tool arguments invalid", detail=str(exc)) from exc
                return result
        raise LLMResponseDecodeError(message="Structured tool call not found")

    @staticmethod
    def _build_structured_retry_messages(messages: list[Message]) -> list[Message]:
        """构建结构化重试消息"""
        return [*messages, Message(role=Role.USER, content="The structured result was invalid. Regenerate the result and strictly follow the provided schema.")]

    @staticmethod
    def _build_structured_output_instruction(messages: list[Message]) -> list[Message]:
        """构建结构化输出指令"""
        return [*messages, Message(role=Role.USER, content="Generate the result strictly according to the provided structured output schema. Do not return a normal conversational response.")]

    def _build_structured_tool_choice(self, name: str) -> dict[str, Any]:
        """构建结构化工具选择"""
        if self._config.use_responses_api:
            return {"type": "function", "name": name}
        return {"type": "function", "function": {"name": name}}

    @staticmethod
    def _should_retry_structured_tool(error: Exception) -> bool:
        """是否重试结构化工具"""
        if isinstance(error, BadRequestError):
            body = str(error).lower()
            return any(value in body for value in ("thinking", "reasoning", "tool_choice"))
        return False

    def _structured_output(self, schema: StructuredOutputSchema, messages: list[Message]) -> LLMResult:
        """结构化输出（同步）"""
        last_error: Exception | None = None
        total_usage = TokenUsage()

        for attempt in range(2):
            current = (
                messages
                if attempt == 0
                else self._build_structured_retry_messages(messages)
            )
            try:
                response = self._invoke_model(current, json_mode=True)
                total_usage = total_usage.add(self._extract_usage(response)) # 更新token用量
                # 解析结果
                result = self._parse_structured(schema, response)
                result.token_usage = total_usage
                return result
            except LLMResponseDecodeError as exc:
                last_error = exc
                logger.warning("JSON mode parsing failed: %s", exc)
            except BadRequestError as exc:
                last_error = exc
                break
        logger.warning("Native structured output failed; falling back to tool: %s", last_error)

        # 创建结构化输出工具
        tool = create_structured_output_tool(schema)
        disabled = False
        decode_retries = 0
        current = messages
        while True:
            try:
                response = self._invoke_model(
                    messages=current,
                    tools=[tool],
                    tool_choice=self._build_structured_tool_choice(tool.name),
                    disable_thinking=disabled,
                )
                total_usage = total_usage.add(self._extract_usage(response))
                # 解析结果
                result = self._parse_structured_tool(schema, tool.name, response)
                result.token_usage = total_usage
                return result
            except LLMResponseDecodeError as exc:
                if decode_retries >= 1:
                    raise
                decode_retries += 1
                current = [
                    *self._build_structured_retry_messages(messages),
                    Message(
                        role=Role.USER,
                        content=f"Call the provided {tool.name} tool using a native function call. Do not write tool calls as text or DSML.",
                    ),
                ]
                logger.warning("Retry structured tool after invalid output: %s", exc)
            except Exception as exc:
                if disabled or not self._should_retry_structured_tool(exc):
                    raise
                disabled = True
                logger.warning("Retry structured tool with thinking disabled: %s", exc)
    
    async def _astructured_output(self, schema: StructuredOutputSchema, messages: list[Message]) -> LLMResult:
        """结构化输出（异步）"""
        last_error: Exception | None = None
        total_usage = TokenUsage()

        for attempt in range(2):
            current = (
                messages
                if attempt == 0
                else self._build_structured_retry_messages(messages)
            )
            try:
                response = await self._ainvoke_model(current, json_mode=True)
                total_usage = total_usage.add(self._extract_usage(response))
                # 解析结果
                result = self._parse_structured(schema, response)
                result.token_usage = total_usage
                return result
            except LLMResponseDecodeError as exc:
                last_error = exc
                logger.warning("JSON mode parsing failed: %s", exc)
            except BadRequestError as exc:
                last_error = exc
                break
        logger.warning("Native structured output failed; falling back to tool: %s", last_error,)
        
        # 创建结构化输出工具
        tool = create_structured_output_tool(schema)
        disabled = False
        decode_retries = 0
        current = messages
        while True:
            try:
                response = await self._ainvoke_model(
                    current,
                    tools=[tool],
                    tool_choice=self._build_structured_tool_choice(tool.name),
                    disable_thinking=disabled,
                )
                total_usage = total_usage.add(self._extract_usage(response))
                # 解析结果
                result = self._parse_structured_tool(schema, tool.name,response,)
                result.token_usage = total_usage
                return result
            except LLMResponseDecodeError as exc:
                if decode_retries >= 1:
                    raise
                decode_retries += 1
                current = [
                    *self._build_structured_retry_messages(messages),
                    Message(
                        role=Role.USER,
                        content=f"Call the provided {tool.name} tool using a native function call. Do not write tool calls as text or DSML.",
                    ),
                ]
                logger.warning("Retry structured tool after invalid output: %s", exc)
            except Exception as exc:
                if disabled or not self._should_retry_structured_tool(exc):
                    raise
                disabled = True
                logger.warning("Retry structured tool with thinking disabled: %s", exc)


    def _build_chat_stream_result(self, chunk: ChatCompletionChunk, pending: dict[int, dict[str, str]]) -> LLMResult | None:
        """构建 Chat 流结果"""
        text = ""
        reasoning: str | None = None
        calls: list[ToolCall] = []
        finish: str | None = None
        if chunk.choices:
            choice = chunk.choices[0]
            finish = choice.finish_reason
            delta = choice.delta
            text = delta.content or ""
            extra = delta.model_extra or {}
            value = extra.get("reasoning_content")
            reasoning = value if isinstance(value, str) else None
            for part in delta.tool_calls or []:
                current = pending.setdefault(part.index, {"id": "", "name": "", "arguments": ""})
                if part.id:
                    current["id"] = part.id
                if part.function:
                    if part.function.name:
                        current["name"] += part.function.name
                    if part.function.arguments:
                        current["arguments"] += part.function.arguments
            if finish is not None and pending:
                if finish != "tool_calls":
                    raise LLMResponseDecodeError(message="Incomplete tool calls at stream termination")
                for index in sorted(pending):
                    entry = pending[index]
                    calls.append(ToolCall(
                        name=entry["name"], 
                        tool_call_id=entry["id"],
                        args=self._load_json_object(entry["arguments"]),
                    ))
                pending.clear()
        usage = TokenUsage()
        if chunk.usage is not None:
            details_in = chunk.usage.prompt_tokens_details
            details_out = chunk.usage.completion_tokens_details
            usage = TokenUsage(
                input_tokens=chunk.usage.prompt_tokens,
                output_tokens=chunk.usage.completion_tokens,
                cache_hit=(details_in.cached_tokens or 0) if details_in else 0,
                reasoning_tokens=(details_out.reasoning_tokens or 0) if details_out else 0
            )
        if not text and not reasoning and not calls and chunk.usage is None:
            return None
        return LLMResult(
            text=text, reasoning=reasoning, tool_calls=calls,
            raw=chunk.model_dump(mode="json"),
            response_metadata={
                "id": chunk.id, 
                "model": chunk.model, 
                "finish_reason": finish
            },
            token_usage=usage
        )

    def _build_responses_stream_result(self, event: ResponseStreamEvent) -> LLMResult | None:
        """构建 Responses 流结果"""
        if event.type == "response.output_text.delta":
            return LLMResult(text=event.delta, token_usage=TokenUsage())
        if event.type == "response.reasoning_summary_text.delta":
            return LLMResult(reasoning=event.delta, token_usage=TokenUsage())
        if event.type == "response.output_item.done" and event.item.type == "function_call":
            call = event.item
            return LLMResult(tool_calls=[ToolCall(
                name=call.name, 
                tool_call_id=call.call_id,
                args=self._load_json_object(call.arguments),
            )],
                             token_usage=TokenUsage())
        if event.type == "response.completed":
            return LLMResult(
                raw=event.response.model_dump(mode="json"),
                response_metadata={
                    "id": event.response.id,
                    "status": event.response.status,
                },
                token_usage=self._response_usage(event.response)
            )
        if event.type in ("response.failed", "response.incomplete"):
            raise LLMResponseDecodeError(message="Responses stream failed or incomplete")
        return None

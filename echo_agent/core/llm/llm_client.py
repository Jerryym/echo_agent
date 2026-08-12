import json
from typing import Any, Literal, Optional, Sequence

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from ...common import get_logger
from ...prompt import PromptAssembler, PromptLoader
from ...utils import MessageAdapter
from ..graph.schema import BaseContext
from ..model.agent_resources import AgentResources
from ..model.input import UserInput
from ..model.message import Message
from ..model.token_usage import TokenUsage
from ..model.tool import ToolCall
from .exception import (
    LLMException,
    LLMInitializeError,
    LLMInvokeError,
    LLMResponseDecodeError,
)
from .llm_config import LLMConfig
from .llm_result import LLMResult

logger = get_logger("llm")


class LLMClient:
    """
    大模型客户端

    参数:
        config: 模型配置
        model: 模型实例
    """
    def __init__(self, config: LLMConfig):
        try:
            self._config = config
            self._model = self._initialize_model()
        except Exception as e:
            raise LLMInitializeError(
                message="LLM model initialize failed",
                detail=str(e)
            )

    def invoke(
        self, 
        prompt: str, 
        user_input: UserInput | dict | str, 
        history: Optional[Sequence[Message]] = None, 
        tool_list: Optional[list[dict[str, Any]]] = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
        config: RunnableConfig | None = None,
    ):
        """
        调用模型

        参数:
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_list: 工具列表
            context: Runtime Context（含 active_skills）
            agent_resources: Agent 静态资源（system_prompt / skill_list；可空）
            config: 配置
        """
        try:
            # 构建 Messages
            messages = self._build_messages(
                prompt=prompt,
                user_input=user_input,
                history=history or [],
                tool_list=tool_list,
                context=context,
                agent_resources=agent_resources,
            )
            # 配置模型
            model = self._configure_model(tool_list=tool_list)
            # 调用模型
            response = model.invoke(messages, config=config)
            # 解析响应
            return self._parse_response(response)
        except LLMException:
            raise
        except Exception as e:
            raise LLMInvokeError(message="LLM invoke failed", detail=str(e))

    async def ainvoke(
        self,
        prompt: str,
        user_input: UserInput | dict | str,
        history: Optional[Sequence[Message]] = None,
        tool_list: Optional[list[dict[str, Any]]] = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
        config: RunnableConfig | None = None,
    ):
        """
        调用模型（异步）
        
        参数:
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_list: 工具列表
            context: Runtime Context（含 active_skills）
            agent_resources: Agent 静态资源（system_prompt / skill_list；可空）
            config: 配置
        """
        try:
            # 构建 Messages
            messages = self._build_messages(
                prompt=prompt,
                user_input=user_input,
                history=history or [],
                tool_list=tool_list,
                context=context,
                agent_resources=agent_resources,
            )
            # 配置模型
            model = self._configure_model(tool_list=tool_list)
            # 调用模型
            response = await model.ainvoke(messages, config=config)
            # 解析响应
            return self._parse_response(response)
        except LLMException:
            raise
        except Exception as e:
            raise LLMInvokeError(message="LLM async invoke failed", detail=str(e))

    def invoke_structured(
        self,
        schema: type[BaseModel] | dict[str, Any],
        prompt: str,
        user_input: UserInput | dict | str,
        history: Optional[Sequence[Message]] = None,
        *,
        method: Literal["json_schema", "function_calling", "json_mode"] = "json_schema",
        strict: bool | None = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
        config: RunnableConfig | None = None
    ):
        """
        结构化输出调用模型

        ⚠️ 注意：本方法不支持工具调用，若需要工具调用请使用 invoke / stream 方法

        参数:
            schema: 输出 schema（Pydantic 类或 JSON Schema dict）
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            method: 结构化输出方式
            strict: 是否严格匹配 schema
            context: Runtime Context（含 active_skills）
            agent_resources: Agent 静态资源（system_prompt / skill_list；可空）
            config: 配置
        """
        try:
            # 构建 Messages
            messages = self._build_messages(
                prompt=prompt,
                user_input=user_input,
                history=history or [],
                context=context,
                agent_resources=agent_resources,
            )
            # 配置模型
            model = self._configure_model(
                structured=True,
                schema=schema,
                method=method,
                strict=strict,
            )
            # 调用模型
            response = model.invoke(messages, config=config)
            # 解析响应
            return self._parse_structured_response(response)
        except LLMException:
            raise
        except Exception as e:
            raise LLMInvokeError(
                message="LLM structured invoke failed",
                detail=str(e),
            )

    async def ainvoke_structured(
        self,
        schema: type[BaseModel] | dict[str, Any],
        prompt: str,
        user_input: UserInput | dict | str,
        history: Optional[Sequence[Message]] = None,
        *,
        method: Literal["json_schema", "function_calling", "json_mode"] = "json_schema",
        strict: bool | None = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
        config: RunnableConfig | None = None,
    ):
        """
        结构化输出调用模型（异步）

        ⚠️ 注意：本方法不支持工具调用，若需要工具调用请使用 ainvoke / astream 方法

        参数:
            schema: 输出 schema（Pydantic 类或 JSON Schema dict）
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            method: 结构化输出方式
            strict: 是否严格匹配 schema
            context: Runtime Context（含 active_skills）
            agent_resources: Agent 静态资源（system_prompt / skill_list；可空）
            config: 配置
        """
        try:
            # 构建 Messages
            messages = self._build_messages(
                prompt=prompt,
                user_input=user_input,
                history=history or [],
                context=context,
                agent_resources=agent_resources,
            )
            # 配置模型
            model = self._configure_model(
                structured=True,
                schema=schema,
                method=method,
                strict=strict,
            )
            # 调用模型
            response = await model.ainvoke(messages, config=config)
            # 解析响应
            return self._parse_structured_response(response)
        except LLMException:
            raise
        except Exception as e:
            raise LLMInvokeError(
                message="LLM async structured invoke failed",
                detail=str(e),
            )

    def stream(
        self, prompt: str, 
        user_input: UserInput | dict | str, 
        history: Optional[Sequence[Message]] = None, 
        tool_list: Optional[list[dict[str, Any]]] = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
        config: RunnableConfig | None = None,
    ):
        """
        流式调用模型

        参数:
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_list: 工具列表
            context: Runtime Context（含 active_skills）
            agent_resources: Agent 静态资源（system_prompt / skill_list；可空）
            config: 配置
        """
        try:
            # 构建 Messages
            messages = self._build_messages(
                prompt=prompt,
                user_input=user_input,
                history=history or [],
                tool_list=tool_list,
                context=context,
                agent_resources=agent_resources,
            )
            # 配置模型
            model = self._configure_model(tool_list=tool_list)
            # 解析响应
            for chunk in model.stream(messages, config=config):
                yield self._parse_response(chunk)
        except LLMException:
            raise
        except Exception as e:
            raise LLMInvokeError(
                message="LLM stream invoke failed",
                detail=str(e)
            )

    async def astream(
        self,
        prompt: str,
        user_input: UserInput | dict | str,
        history: Optional[Sequence[Message]] = None,
        tool_list: Optional[list[dict[str, Any]]] = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
        config: RunnableConfig | None = None,
    ):
        """
        流式调用模型（异步）

        参数:
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_list: 工具列表
            context: Runtime Context（含 active_skills）
            agent_resources: Agent 静态资源（system_prompt / skill_list；可空）
            config: 配置
        """
        try:
            # 构建 Messages
            messages = self._build_messages(
                prompt=prompt,
                user_input=user_input,
                history=history or [],
                tool_list=tool_list,
                context=context,
                agent_resources=agent_resources,
            )
            # 配置模型
            model = self._configure_model(tool_list=tool_list)
            # 解析响应
            async for chunk in model.astream(messages, config=config):
                yield self._parse_response(chunk)
        except LLMException:
            raise
        except Exception as e:
            raise LLMInvokeError(
                message="LLM async stream invoke failed",
                detail=str(e)
            )

    def _initialize_model(self):
        """初始化模型"""
        # Responses API 模型初始化
        if self._config.use_responses_api:
            logger.info("Initializing model with Responses API")
            return self._initialize_model_with_responses_api()

        # 非 Responses API 模型初始化
        logger.info("Initializing model with Completion API")
        model_kwargs: dict[str, Any] = {
            "model": self._config.model_name,
            "api_key": self._config.api_key,
            "model_provider": self._config.model_provider,
            "base_url": self._config.base_url,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "timeout": self._config.timeout,
            "max_retries": self._config.max_retries,
        }
        if self._config.extra_body:
            model_kwargs["extra_body"] = self._config.extra_body
        return init_chat_model(**model_kwargs)

    def _initialize_model_with_responses_api(self):
        """初始化 Responses API 模型"""
        if self._config.model_provider == "openai":
            model_kwargs: dict[str, Any] = {
                "model": self._config.model_name,
                "api_key": self._config.api_key,
                "base_url": self._config.base_url,
                "temperature": self._config.temperature,
                "max_tokens": self._config.max_tokens,
                "timeout": self._config.timeout,
                "max_retries": self._config.max_retries,
                "use_responses_api": self._config.use_responses_api,

            }
            # output_version
            if self._config.output_version:
                model_kwargs["output_version"] = self._config.output_version
            # extra_body
            if self._config.extra_body:
                model_kwargs["extra_body"] = self._config.extra_body
            # 初始化模型
            model = ChatOpenAI(**model_kwargs)
            # 绑定内置工具
            if self._config.builtin_tools:
                model = model.bind(tools=self._config.builtin_tools)
        else:
            raise LLMInitializeError(
                message="model provider not supported",
                detail=f"model provider {self._config.model_provider} not supported"
            )
        return model

    def _build_messages(
        self, 
        prompt: str, 
        user_input: UserInput | dict | str, 
        history: Optional[Sequence[Message]] = None, 
        tool_list: Optional[list[dict[str, Any]]] = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
    ):
        """
        构建 LangChain Messages
        """
        messages: list[BaseMessage] = []

        # 添加系统提示词（含 Runtime Context 注入的 Loaded Skills，不写入 history）
        system_prompt = self._build_prompt(
            prompt,
            tool_list=tool_list,
            context=context,
            agent_resources=agent_resources,
        )
        messages.append(SystemMessage(content=system_prompt))
        # 添加历史记录
        messages.extend(MessageAdapter.to_langchain_messages(history or []))
        # 添加用户输入
        if isinstance(user_input, UserInput):
            messages.append(MessageAdapter.to_human_message(user_input))
        elif isinstance(user_input, str):
            messages.append(HumanMessage(content=user_input))
        elif isinstance(user_input, dict):
            messages.append(HumanMessage(content=json.dumps(user_input, ensure_ascii=False, default=str)))
        
        return messages

    def _build_prompt(
        self,
        prompt: str,
        tool_list: list[dict[str, Any]] | None = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
    ):
        """
        构建提示词
        """
        if agent_resources is not None or context is not None:
            return PromptAssembler.assemble(
                agent_prompt=agent_resources.system_prompt if agent_resources else None,
                system_prompt=prompt,
                skill_list=agent_resources.skill_list if agent_resources else None,
                active_skills=context.active_skills if context else None,
            )

        system_prompts: list[str] = []

        # tool call policy prompt: 当工具列表不为空时，才添加工具调用策略提示词
        if tool_list:
            tool_call_policy_prompt = PromptLoader.load("prompt/tool_call_policy.md")
            if tool_call_policy_prompt:
                system_prompts.append(tool_call_policy_prompt)

        if prompt:
            system_prompts.append(prompt)

        return "\n\n".join(system_prompts)

    def _configure_model(
        self,
        *,
        structured: bool = False,
        schema: type[BaseModel] | dict[str, Any] | None = None,
        tool_list: list[dict[str, Any]] | None = None,
        method: Literal["json_schema", "function_calling", "json_mode"] = "json_schema",
        strict: bool | None = None,
    ):
        """
        配置模型
        """
        model = self._model

        # 结构化输出
        if structured:
            if schema is None: 
                raise LLMInvokeError(
                    message="schema is required when structured=True",
                )
            # 配置结构化输出
            kwargs = {
                "schema": schema,
                "method": method,
                "strict": strict,
                "include_raw": True,
            }
            return model.with_structured_output(**kwargs)

        # 绑定工具
        if tool_list:
            return model.bind_tools(tool_list, parallel_tool_calls=True)

        return model

    def _parse_response(self, response: AIMessage):
        """
        解析 LLM 响应
        """
        try:
            text, reasoning = self._normalize_content(response)
            usage_metadata = getattr(response, "usage_metadata", None) or {}
            return LLMResult(
                    text=text,
                    reasoning=reasoning,
                    tool_calls=self._normalize_tool_calls(getattr(response, "tool_calls", None)),
                    raw=response,
                    response_metadata=getattr(response, "response_metadata", None),
                    token_usage=TokenUsage(
                        input_tokens=usage_metadata.get("input_tokens", 0),
                        output_tokens=usage_metadata.get("output_tokens", 0),
                    )
                )
        except Exception as e:
            raise LLMResponseDecodeError(
                message="parse llm response failed",
                detail=str(e)
            )

    def _parse_structured_response(self, response) -> LLMResult:
        """
        解析 LLM 结构化输出
        """
        try:
            # 解析原始消息
            raw = response.get("raw")
            if raw is None:
                raise LLMResponseDecodeError(
                    message="structured response missing raw message",
                )
            # 解析结构化输出
            parsed = response["parsed"]
            if parsed is None:
                raise LLMResponseDecodeError(
                    message="structured response missing parsed message",
                )

            text, reasoning = self._normalize_content(raw)
            usage_metadata = getattr(response, "usage_metadata", None) or {}
            return LLMResult(
                text=text,
                reasoning=reasoning,
                raw=raw,
                structured=parsed,
                response_metadata=getattr(raw, "response_metadata", {}),
                token_usage=TokenUsage(
                    input_tokens=usage_metadata.get("input_tokens", 0),
                    output_tokens=usage_metadata.get("output_tokens", 0),
                )
            )
        except Exception as e:
            raise LLMResponseDecodeError(
                message="parse structured response failed",
                detail=str(e),
            )

    def _normalize_content(self, response: AIMessage | Any) -> tuple[str, str | None]:
        """
        规范化内容为 text / reasoning（对齐 LangChain ContentBlock）。

        优先使用 AIMessage.content_blocks；否则回退解析 content。
        reasoning 为空时返回 None。
        """
        blocks = getattr(response, "content_blocks", None)
        if blocks:
            text, reasoning = self._split_content_blocks(blocks)
            return text, reasoning or None

        content = getattr(response, "content", response)
        if content is None:
            return "", None
        if isinstance(content, str):
            return content, None
        if isinstance(content, list):
            text, reasoning = self._split_content_blocks(content)
            return text, reasoning or None
        return str(content), None

    def _split_content_blocks(self, blocks: Any) -> tuple[str, str]:
        """
        拆分 content block 列表为正文与 reasoning。
        """
        text_parts: list[str] = []
        reasoning_parts: list[str] = []

        for block in blocks:
            if isinstance(block, str):
                text_parts.append(block)
                continue

            block_type = None
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "text":
                    text_parts.append(block.get("text", "") or "")
                elif block_type in ("reasoning", "thinking"):
                    reasoning_parts.append(self._extract_reasoning_text(block))
                elif block_type in ("image", "audio", "video", "file"):
                    text_parts.append(f"\n[{str(block_type).upper()} OUTPUT]\n")
                elif block_type in ("tool_use", "tool_call", "input_json", "function_call"):
                    # 工具调用走 tool_calls 字段，不写入 text
                    continue
                else:
                    logger.warning("unsupported content block type discarded: %s", block_type)
            elif hasattr(block, "type"):
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    text_parts.append(getattr(block, "text", "") or "")
                elif block_type in ("reasoning", "thinking"):
                    reasoning_parts.append(self._extract_reasoning_text(block))
                else:
                    logger.warning("unsupported content block type discarded: %s", block_type)
            else:
                logger.warning("unsupported content block discarded: %r", type(block))

        text = "".join(text_parts)
        reasoning = "\n".join(part for part in reasoning_parts if part).strip()
        return text, reasoning

    @staticmethod
    def _extract_reasoning_text(block: Any) -> str:
        """从 reasoning / thinking block 提取文本。"""
        if isinstance(block, dict):
            reasoning = block.get("reasoning") or block.get("thinking") or ""
            if reasoning:
                return str(reasoning)
            summary = block.get("summary")
            if isinstance(summary, list):
                parts = []
                for item in summary:
                    if isinstance(item, dict):
                        parts.append(item.get("text", "") or "")
                    elif isinstance(item, str):
                        parts.append(item)
                return "".join(parts)
            return ""
        return (
            getattr(block, "reasoning", None)
            or getattr(block, "thinking", None)
            or ""
        )

    def _normalize_tool_calls(self, raw_tool_calls) -> list[ToolCall]:
        """
        规范化工具调用
        """
        if not raw_tool_calls:
            return []

        tool_calls = []
        for i, tc in enumerate(raw_tool_calls):
            if isinstance(tc, ToolCall):
                tool_calls.append(tc)
                continue
            if isinstance(tc, dict):
                tool_calls.append(ToolCall(
                    name=tc.get("name", ""),
                    args=tc.get("args") or tc.get("arguments") or {},
                    tool_call_id=tc.get("id") or tc.get("tool_call_id") or f"call_{i}",
                ))
            else:
                raise LLMResponseDecodeError(
                    message="invalid tool call",
                    detail=f"invalid tool call: {tc}",
                )
        return tool_calls

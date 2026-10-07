import json
from typing import Any, Awaitable, Callable, Optional, Sequence, TypeAlias, cast

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from ...common import get_logger
from ...prompt import PromptAssembler
from ...utils import ContextUsageCalculator, MessageAdapter
from ..graph.schema import BaseContext
from ..model.agent import AgentResources
from ..model.input import UserInput
from ..model.message import Message
from ..model.token_usage import TokenUsage
from ..model.tool import ToolCall
from ..runtime import RuntimeConfig
from .exception import (
    LLMException,
    LLMInitializeError,
    LLMInvokeError,
    LLMResponseDecodeError,
)
from .llm_config import LLMConfig
from .llm_result import LLMResult
from .structured_output import (
    JsonObject,
    StructuredOutputSchema,
    create_structured_output_tool,
    validate_structured_output,
)

logger = get_logger("llm")

BeforeModelHook: TypeAlias = Callable[[], Sequence[Message] | None]
AsyncBeforeModelHook: TypeAlias = Callable[[], Awaitable[Sequence[Message] | None]]


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
            raise LLMInitializeError(message="LLM model initialize failed", detail=str(e))

    def invoke(
        self, 
        prompt: str, 
        user_input: UserInput | dict | str, 
        history: Optional[Sequence[Message]] = None, 
        tool_informations: Optional[list[dict[str, str]]] = None,
        tool_list: Optional[list[dict[str, Any]]] = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
        config: RunnableConfig | None = None,
        before_model: BeforeModelHook | None = None
    ):
        """
        调用模型

        参数:
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_informations: 工具信息列表（name / description）
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
                tool_informations=tool_informations,
                tool_list=tool_list,
                context=context,
                agent_resources=agent_resources,
            )
            # Hook: before_model
            messages = self._before_model(
                messages=messages,
                before_model=before_model,
                prompt=prompt,
                user_input=user_input,
                tool_informations=tool_informations,
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
        tool_informations: Optional[list[dict[str, str]]] = None,
        tool_list: Optional[list[dict[str, Any]]] = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
        config: RunnableConfig | None = None,
        abefore_model: AsyncBeforeModelHook | None = None,
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
                tool_informations=tool_informations,
                tool_list=tool_list,
                context=context,
                agent_resources=agent_resources,
            )
            # Hook: before_model
            messages = await self._abefore_model(
                messages=messages,
                abefore_model=abefore_model,
                prompt=prompt,
                user_input=user_input,
                tool_informations=tool_informations,
                tool_list=tool_list,
                context=context,
                agent_resources=agent_resources,
            )
            # 配置模型
            model = self._configure_model(tool_list=tool_list)
            # 调用模型
            response = await model.ainvoke(messages, config=config)
            if not isinstance(response, AIMessage):
                raise LLMResponseDecodeError(message="structured response must be an AIMessage")
            # 解析响应
            return self._parse_response(response)
        except LLMException:
            raise
        except Exception as e:
            raise LLMInvokeError(message="LLM async invoke failed", detail=str(e))

    def invoke_structured(
        self,
        schema: StructuredOutputSchema,
        prompt: str,
        user_input: UserInput | dict | str,
        history: Optional[Sequence[Message]] = None,
        tool_informations: Optional[list[dict[str, str]]] = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
        config: RunnableConfig | None = None,
        before_model: BeforeModelHook | None = None
    ) -> LLMResult:
        """
        结构化输出调用模型

        先使用 LangChain 原生结构化输出；失败时回退到结构化输出工具。

        参数:
            schema: 输出 schema
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_informations: 工具信息列表（name / description）
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
                tool_informations=tool_informations,
                context=context,
                agent_resources=agent_resources,
            )
            # Hook: before_model
            messages = self._before_model(
                messages=messages,
                before_model=before_model,
                prompt=prompt,
                user_input=user_input,
                tool_informations=tool_informations,
                tool_list=None,
                context=context,
                agent_resources=agent_resources,
            )
            
            structured_messages = self._with_structured_output_instruction(messages)
            try: # 使用 LangChain 原生结构化输出
                return self._with_structured_output(schema, structured_messages, config)
            except Exception as native_error: # 回退到结构化输出工具
                logger.warning("native structured output failed, fallback to tool: %s", native_error)
                return self._invoke_with_structured_tool(schema, structured_messages, config)
        except LLMException:
            raise
        except Exception as e:
            raise LLMInvokeError(message="LLM structured invoke failed", detail=str(e))

    async def ainvoke_structured(
        self,
        schema: StructuredOutputSchema,
        prompt: str,
        user_input: UserInput | dict | str,
        history: Optional[Sequence[Message]] = None,
        tool_informations: Optional[list[dict[str, str]]] = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
        config: RunnableConfig | None = None,
        abefore_model: AsyncBeforeModelHook | None = None
    ) -> LLMResult:
        """
        结构化输出调用模型（异步）

        先使用 LangChain 原生结构化输出；失败时回退到结构化输出工具。

        参数:
            schema: 输出 schema
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_informations: 工具信息列表（name / description）
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
                tool_informations=tool_informations,
                context=context,
                agent_resources=agent_resources,
            )
            # Hook: before_model
            messages = await self._abefore_model(
                messages=messages,
                prompt=prompt,
                user_input=user_input,
                tool_informations=tool_informations,
                tool_list=None,
                context=context,
                agent_resources=agent_resources,
                abefore_model=abefore_model,
            )

            structured_messages = self._with_structured_output_instruction(messages)
            try: # 使用 LangChain 原生结构化输出
                return await self._awith_structured_output(schema, structured_messages, config)
            except Exception as native_error: # 回退到结构化输出工具
                logger.warning("native structured output failed, fallback to tool: %s", native_error)
                return await self._ainvoke_with_structured_tool(schema, structured_messages, config)
        except LLMException:
            raise
        except Exception as e:
            raise LLMInvokeError(message="LLM stream invoke failed", detail=str(e))

    def stream(
        self, prompt: str, 
        user_input: UserInput | dict | str, 
        history: Optional[Sequence[Message]] = None, 
        tool_informations: Optional[list[dict[str, str]]] = None,
        tool_list: Optional[list[dict[str, Any]]] = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
        config: RunnableConfig | None = None,
        before_model: BeforeModelHook | None = None
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
                tool_informations=tool_informations,
                tool_list=tool_list,
                context=context,
                agent_resources=agent_resources,
            )
            # Hook: before_model
            messages = self._before_model(
                messages=messages,
                before_model=before_model,
                prompt=prompt,
                user_input=user_input,
                tool_informations=tool_informations,
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
            raise LLMInvokeError(message="LLM stream invoke failed", detail=str(e))

    async def astream(
        self,
        prompt: str,
        user_input: UserInput | dict | str,
        history: Optional[Sequence[Message]] = None,
        tool_informations: Optional[list[dict[str, str]]] = None,
        tool_list: Optional[list[dict[str, Any]]] = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
        config: RunnableConfig | None = None,
        abefore_model: AsyncBeforeModelHook | None = None
    ):
        """
        流式调用模型（异步）

        参数:
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_informations: 工具信息列表（name / description）
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
                tool_informations=tool_informations,
                tool_list=tool_list,
                context=context,
                agent_resources=agent_resources,
            )
            # Hook: before_model
            messages = await self._abefore_model(
                messages=messages,
                abefore_model=abefore_model,
                prompt=prompt,
                user_input=user_input,
                tool_informations=tool_informations,
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
            "max_completion_tokens": self._config.max_tokens,
            "timeout": self._config.timeout,
            "max_retries": self._config.max_retries,
        }
        # extra_body
        if self._config.extra_body:
            model_kwargs["extra_body"] = self._config.extra_body
        # default_headers
        if self._config.default_headers:
            model_kwargs["default_headers"] = dict(self._config.default_headers)
        return init_chat_model(**model_kwargs)

    def _initialize_model_with_responses_api(self):
        """初始化 Responses API 模型"""
        if self._config.model_provider == "openai":
            model_kwargs: dict[str, Any] = {
                "model": self._config.model_name,
                "api_key": self._config.api_key,
                "base_url": self._config.base_url,
                "temperature": self._config.temperature,
                "max_completion_tokens": self._config.max_tokens,
                "timeout": self._config.timeout,
                "max_retries": self._config.max_retries,
                "use_responses_api": self._config.use_responses_api,
            }
            # output_version
            if self._config.output_version:
                model_kwargs["output_version"] = self._config.output_version
            # reasoning
            if self._config.reasoning:
                model_kwargs["reasoning"] = self._config.reasoning.model_dump(exclude_none=True)
            # extra_body
            if self._config.extra_body:
                model_kwargs["extra_body"] = self._config.extra_body
            # default_headers
            if self._config.default_headers:
                model_kwargs["default_headers"] = dict(self._config.default_headers)
            # 初始化模型
            model = ChatOpenAI(**model_kwargs)
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
        tool_informations: Optional[list[dict[str, str]]] = None,
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
            tool_informations=tool_informations,
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
        tool_informations: list[dict[str, str]] | None = None,
        tool_list: list[dict[str, Any]] | None = None,
        context: BaseContext | None = None,
        agent_resources: AgentResources | None = None,
    ):
        """
        构建提示词
        """
        runtime_config = RuntimeConfig.get_runtime_config()
        return PromptAssembler.assemble(
                agent_prompt=agent_resources.system_prompt if agent_resources else None,
                system_prompt=prompt,
                agent_mode=runtime_config.agent_mode,
                tool_informations=tool_informations,
                tool_list=tool_list,
                skill_frontmatter_list=agent_resources.skill_frontmatter_list if agent_resources else None,
                active_skills=context.active_skills if context else None,
            )
            
    def _configure_model(self, tool_list: list[dict[str, Any]] | None = None):
        """配置模型"""
        model = self._model
        # 绑定工具
        if tool_list:
            return model.bind(tools=tool_list, parallel_tool_calls=self._config.parallel_tool_calls)
        return model

# region Hooks
    def _before_model(
        self,
        messages: list[BaseMessage],
        prompt: str,
        user_input: UserInput | dict | str,
        tool_informations: list[dict[str, str]] | None,
        tool_list: list[dict[str, Any]] | None,
        context: BaseContext | None,
        agent_resources: AgentResources | None,
        before_model: BeforeModelHook | None,
    ) -> list[BaseMessage]:
        """Hook: before model"""
        # 获取当前上下文用量
        context_usage = ContextUsageCalculator.calculate(messages, tools=tool_list)
        logger.info("context usage = %s", context_usage)

        if before_model is None:
            return messages

        # 获取压缩上下文后的历史记录
        updated_history = before_model(messages, tools=tool_list)
        if updated_history is None:
            return messages

        # 重新构建消息
        updated_messages = self._build_messages(
            prompt=prompt,
            user_input=user_input,
            history=updated_history,
            tool_informations=tool_informations,
            tool_list=tool_list,
            context=context,
            agent_resources=agent_resources,
        )
        updated_context_usage = ContextUsageCalculator.calculate(updated_messages, tools=tool_list)
        logger.info("context compressed | before=%s after=%s", context_usage, updated_context_usage)
        return updated_messages

    async def _abefore_model(
        self,
        messages: list[BaseMessage],
        abefore_model: AsyncBeforeModelHook | None,
        prompt: str,
        user_input: UserInput | dict | str,
        tool_informations: list[dict[str, str]] | None,
        tool_list: list[dict[str, Any]] | None,
        context: BaseContext | None,
        agent_resources: AgentResources | None,
    ) -> list[Message]:
        """Hook: async before model"""
        # 获取当前上下文用量
        context_usage = ContextUsageCalculator.calculate(messages, tools=tool_list)
        logger.info("context usage = %s", context_usage)

        if abefore_model is None:
            return messages

        # 获取压缩上下文后的历史记录
        updated_history = await abefore_model(messages, tools=tool_list)
        if updated_history is None:
            return messages

        # 重新构建消息
        updated_messages = self._build_messages(
            prompt=prompt,
            user_input=user_input,
            history=updated_history,
            tool_informations=tool_informations,
            tool_list=tool_list,
            context=context,
            agent_resources=agent_resources,
        )
        updated_context_usage = ContextUsageCalculator.calculate(updated_messages, tools=tool_list)
        logger.info("context compressed | before=%s after=%s", context_usage, updated_context_usage)
        return updated_messages
# endregion

    def _parse_response(self, response: AIMessage):
        """解析 LLM 响应"""
        try:
            text, reasoning = self._normalize_content(response)
            usage_metadata = getattr(response, "usage_metadata", None) or {}
            input_token_details = usage_metadata.get("input_token_details", None) or {}
            output_token_details = usage_metadata.get("output_token_details", None) or {}
            return LLMResult(
                    text=text,
                    reasoning=reasoning,
                    tool_calls=self._normalize_tool_calls(getattr(response, "tool_calls", None)),
                    raw=response,
                    response_metadata=getattr(response, "response_metadata", None),
                    token_usage=TokenUsage(
                        input_tokens=usage_metadata.get("input_tokens", 0),
                        output_tokens=usage_metadata.get("output_tokens", 0),
                        cache_creation=input_token_details.get("cache_creation", 0) if input_token_details else 0,
                        cache_hit=input_token_details.get("cache_read", 0) if input_token_details else 0,
                        reasoning_tokens=output_token_details.get("reasoning", 0) if output_token_details else 0,
                    )
                )
        except Exception as e:
            raise LLMResponseDecodeError(message="parse llm response failed", detail=str(e))

    def _with_structured_output(self, schema: StructuredOutputSchema, messages: list[BaseMessage], config: RunnableConfig | None = None) -> LLMResult:
        """使用 LangChain 原生结构化输出（json_schema）"""
        model_with_structured = self._model.with_structured_output(
            schema,
            method="json_schema",
            include_raw=True,
            strict=True
        )

        try:
            result = model_with_structured.invoke(messages, config=config)
            return self._require_structured_output(schema, result)
        except LLMResponseDecodeError as error:
            logger.warning("native structured output parsing failed, retry generation: %s", error)

        # 解析失败重试
        retry_messages = [
            *messages,
            HumanMessage(
                content=(
                    "The structured result was invalid. Regenerate the result "
                    "and strictly follow the provided schema."
                )
            ),
        ]
        result = model_with_structured.invoke(retry_messages, config=config)
        return self._require_structured_output(schema, result)

    async def _awith_structured_output(self, schema: StructuredOutputSchema, messages: list[BaseMessage], config: RunnableConfig | None = None) -> LLMResult:
        """使用 LangChain 原生结构化输出（json_schema，异步）"""
        model_with_structured = self._model.with_structured_output(
            schema,
            method="json_schema",
            include_raw=True,
            strict=True
        )

        try:
            result = await model_with_structured.ainvoke(messages, config=config)
            return self._require_structured_output(schema, result)
        except LLMResponseDecodeError as error:
            logger.warning("native structured output parsing failed, retry generation: %s", error)

        # 解析失败重试
        retry_messages = [
            *messages,
            HumanMessage(
                content=(
                    "The structured result was invalid. Regenerate the result "
                    "and strictly follow the provided schema."
                )
            ),
        ]
        result = await model_with_structured.ainvoke(retry_messages, config=config)
        return self._require_structured_output(schema, result)

    def _require_structured_output(self, schema: StructuredOutputSchema, result: Any) -> LLMResult:
        """校验原生结构化输出并解析为 LLMResult"""
        if not isinstance(result, dict):
            raise LLMResponseDecodeError(message="native structured output failed", detail=str(result))
        if result.get("parsing_error"):
            try:
                return self._parse_structured_output(schema, result)
            except LLMResponseDecodeError:
                raise LLMResponseDecodeError(
                    message="native structured output failed",
                    detail=str(result.get("parsing_error")),
                ) from None
        return self._parse_structured_output(schema, result)

    def _invoke_with_structured_tool(self, schema: StructuredOutputSchema, messages: list[BaseMessage], config: RunnableConfig | None = None) -> LLMResult:
        """使用结构化输出工具构建结构化输出"""
        # 绑定结构化输出工具(不禁用思考模式)
        structured_output_tool, model = self._bind_structured_tool(schema)
        try:
            response = model.invoke(messages, config=config)
            return self._require_structured_tool_response(response, structured_output_tool)
        except LLMResponseDecodeError as error:
            logger.warning("structured output tool failed, retry with thinking disabled: %s", error)

        # 失败则重新绑定结构化输出工具(禁用思考模式)
        structured_output_tool, model = self._bind_structured_tool(schema, disable_thinking=True)
        response = model.invoke(messages, config=config)
        return self._require_structured_tool_response(response, structured_output_tool)

    async def _ainvoke_with_structured_tool(self, schema: StructuredOutputSchema, messages: list[BaseMessage], config: RunnableConfig | None = None) -> LLMResult:
        """使用结构化输出工具构建结构化输出（异步）"""
        # 绑定结构化输出工具(不禁用思考模式)
        structured_output_tool, model = self._bind_structured_tool(schema)
        try:
            response = await model.ainvoke(messages, config=config)
            return self._require_structured_tool_response(response, structured_output_tool)
        except LLMResponseDecodeError as error:
            logger.warning("structured output tool failed, retry with thinking disabled: %s", error)

        # 失败则重新绑定结构化输出工具(禁用思考模式)
        structured_output_tool, model = self._bind_structured_tool(schema, disable_thinking=True)
        response = await model.ainvoke(messages, config=config)
        return self._require_structured_tool_response(response, structured_output_tool)

    def _bind_structured_tool(self, schema: StructuredOutputSchema, disable_thinking: bool = False) -> tuple[BaseTool, Any]:
        """
        按 Responses API 或 Chat Completions 绑定结构化输出工具

        参数：
            schema: 结构化输出接哦古
            disable_thinking: 是否禁用思考模式
        """
        structured_output_tool = create_structured_output_tool(schema)
        model = self._model

        # 禁用思考模式
        if disable_thinking:
            model = self._disable_thinking(model)

        if self._config.use_responses_api:
            tool_choice: str | dict[str, Any] = "required"
        else:
            tool_choice = {
                "type": "function",
                "function": {
                    "name": structured_output_tool.name,
                },
            }

        return (
            structured_output_tool, 
            model.bind_tools(
                [structured_output_tool], 
                tool_choice=tool_choice
                )
            )

    def _require_structured_tool_response(self, response: Any, structured_output_tool: BaseTool) -> LLMResult:
        """校验工具调用响应并解析为 LLMResult"""
        if not isinstance(response, AIMessage):
            raise LLMResponseDecodeError(message="structured response must be an AIMessage")
        return self._parse_structured_response(response, structured_output_tool)

    def _parse_structured_output(self, schema: StructuredOutputSchema, result: dict[str, Any]) -> LLMResult:
        """解析 LangChain 原生结构化输出"""
        try:
            raw = result.get("raw")
            if not isinstance(raw, AIMessage):
                raise LLMResponseDecodeError(message="structured response must be an AIMessage")

            parsed = result.get("parsed")
            if isinstance(parsed, dict):
                payload = parsed
            elif hasattr(parsed, "model_dump"):
                dumped = parsed.model_dump(mode="json")
                if not isinstance(dumped, dict):
                    raise LLMResponseDecodeError(message="native structured output must be a JSON object")
                payload = dumped
            elif isinstance(parsed, str):
                payload = self._load_json_object(parsed)
            else:
                text, _ = self._normalize_content(raw)
                payload = self._load_json_object(text)

            structured = validate_structured_output(schema, payload)
            text, reasoning = self._normalize_content(raw)
            usage_metadata = raw.usage_metadata or {}
            input_token_details = usage_metadata.get("input_token_details", None) or {}
            output_token_details = usage_metadata.get("output_token_details", None) or {}
            return LLMResult(
                text=text,
                reasoning=reasoning,
                raw=raw,
                structured=structured,
                response_metadata=raw.response_metadata,
                token_usage=TokenUsage(
                    input_tokens=usage_metadata.get("input_tokens", 0),
                    output_tokens=usage_metadata.get("output_tokens", 0),
                    cache_creation=input_token_details.get("cache_creation", 0) if input_token_details else 0,
                    cache_hit=input_token_details.get("cache_read", 0) if input_token_details else 0,
                    reasoning_tokens=output_token_details.get("reasoning", 0) if output_token_details else 0,
                ),
            )
        except LLMResponseDecodeError:
            raise
        except Exception as e:
            raise LLMResponseDecodeError(
                message="parse structured output failed",
                detail=str(e),
            )

    def _parse_structured_response(self, response: AIMessage, structured_tool: BaseTool) -> LLMResult:
        """解析 LLM 结构化输出"""
        try:
            # 查找结构化输出工具调用
            structured_result: JsonObject | None = None
            for tool_call in response.tool_calls:
                if tool_call["name"] != structured_tool.name:
                    continue

                args = tool_call["args"]
                if not isinstance(args, dict):
                    raise LLMResponseDecodeError(message="structured output tool arguments must be a JSON object")

                result = structured_tool.invoke(args)
                if not isinstance(result, dict):
                    raise LLMResponseDecodeError(message="structured output tool result must be a JSON object")

                structured_result = cast(JsonObject, result)
                break

            if structured_result is None:
                raise LLMResponseDecodeError(message="structured output tool was not called")

            # 解析原始消息
            text, reasoning = self._normalize_content(response)
            # 解析 Token Usage
            usage_metadata = response.usage_metadata or {}
            input_token_details = (usage_metadata.get("input_token_details", None) or {})
            output_token_details = (usage_metadata.get("output_token_details", None) or {})

            return LLMResult(
                text=text,
                reasoning=reasoning,
                raw=response,
                structured=structured_result,
                response_metadata=response.response_metadata,
                token_usage=TokenUsage(
                    input_tokens=usage_metadata.get("input_tokens", 0),
                    output_tokens=usage_metadata.get("output_tokens", 0),
                    cache_creation=(input_token_details.get("cache_creation", 0) if input_token_details else 0),
                    cache_hit=(input_token_details.get("cache_read", 0) if input_token_details else 0),
                    reasoning_tokens=(output_token_details.get("reasoning", 0) if output_token_details else 0),
                ),
            )
        except LLMResponseDecodeError:
            raise
        except Exception as e:
            raise LLMResponseDecodeError(
                message="parse structured response failed",
                detail=str(e),
            )

    def _load_json_object(self, text: str) -> dict[str, Any]:
        """将归一化后的 JSON 文本解析为对象"""
        loaded = json.loads(self._normalize_json_text(text))
        if not isinstance(loaded, dict):
            raise LLMResponseDecodeError(message="native structured output must be a JSON object")
        return loaded

    def _normalize_content(self, response: AIMessage | Any) -> tuple[str, str | None]:
        """
        规范化内容为 text / reasoning（对齐 LangChain ContentBlock）

        优先使用 AIMessage.content_blocks；否则回退解析 content
        reasoning 为空时返回 None
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

    def _normalize_json_text(self, text: str) -> str:
        """归一化json文本"""
        text = text.strip()
        if text.startswith("```json"):
            text = text[len("```json"):].lstrip()
        elif text.startswith("```"):
            text = text[3:].lstrip()
        if text.endswith("```"):
            text = text[:-3].rstrip()
        return text

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
        """从 reasoning / thinking block 提取文本"""
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
        """规范化工具调用"""
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

    def _disable_thinking(self, model: Any) -> Any:
        """禁用思考模式"""
        if self._config.use_responses_api:
            return model.bind(
                reasoning={"effort": "none"},
            )

        extra_body = {
            **(self._config.extra_body or {}),
            "enable_thinking": False,
        }
        return model.bind(extra_body=extra_body)

    def _with_structured_output_instruction(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        return [
            *messages,
            HumanMessage(
                content=(
                    "Generate the result strictly according to the provided "
                    "structured output schema. Do not return a normal "
                    "conversational response."
                ),
            ),
        ]

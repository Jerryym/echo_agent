from collections.abc import AsyncIterator, Iterator
import json
from typing import Any, Mapping

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command

from ...common import get_logger
from ...common.network import HttpRequest
from ..capability.skill import SkillManager
from ..graph import BaseContext, BaseInput, GraphCompileOptions, RootGraph
from ..llm import LLMClient
from ..mcp import MCPClient
from ..model.agent import AgentMode, AgentResources, AgentResult, AgentState
from ..model.input import UserInput
from ..model.message import Message, Role, append_messages
from ..model.skill import SkillRuntimeContext
from ..runtime import RuntimeConfig
from ..runtime.algorithm import (
    ConversationCompressor,
    amaybe_compress_conversation,
    maybe_compress_conversation,
)
from ..tool import ToolDefinition, ToolRegistry
from ..tool.toolkit import create_load_skill_tool, create_read_skill_resource_tool
from ..tool.utils import to_tool_definition
from .agent_config import AgentConfig

logger = get_logger("agent")


class Agent:
    """
    Agent 类：用于定义 Agent 的运行实体，包括 AgentConfig、GraphCompileOptions、RootGraph 等。

    Attributes:
        agent_config: Agent 配置
        graph_compile_options: 图编译选项
        graph: RootGraph 根图
        compiled_graph: 编译后的图
        tool_registry: 工具注册器
        skill_manager: Skill 管理器
        mcp_client: MCP 客户端（由 AgentConfig.mcp_servers 在构造时内部创建；
            可选合并内置 Fetch / Filesystem，默认关闭）
    """
    def __init__(self, agent_config: AgentConfig, compile_options: GraphCompileOptions, graph: RootGraph):
        # 配置
        self._agent_config = agent_config
        self._graph_compile_options = compile_options

        # 图
        self._graph = graph
        self._compiled_graph = self._graph.compile(compile_options)

        self._tool_registry = ToolRegistry()
        self._skill_manager = SkillManager(agent_config.skill_list)
        self._mcp_client = (
            MCPClient(self._tool_registry, list(agent_config.mcp_servers))
            if agent_config.mcp_servers
            else None
        )
        self._agent_state_map: dict[str, AgentState] = {} # 会话ID -> 智能体状态
        self._active_skills_map: dict[str, dict[str, SkillRuntimeContext]] = {}
        self._pending_inputs: dict[str, UserInput | type[BaseInput]] = {}
        self._pending_results: dict[str, AgentResult] = {}
        self._conversation_compressor = ConversationCompressor(
            LLMClient(agent_config.llm_config)
        )

        # 智能体执行结果
        self._agent_results: dict[str, list[AgentResult]] = {}

        # 注册工具
        self._register_tools()

# region 属性
    @property
    def mcp_client(self) -> MCPClient | None:
        """Agent 持有的 MCPClient；mcp_servers 为空时为 None。"""
        return self._mcp_client

    @property
    def tool_registry(self) -> ToolRegistry:
        """Agent 持有的工具注册表（内置 toolkit + MCP 共用）。"""
        return self._tool_registry

    @property
    def skill_manager(self) -> SkillManager:
        """Agent 持有的 Skill 管理器。"""
        return self._skill_manager

    @property
    def agent_results(self) -> dict[str, list[AgentResult]]:
        """Agent 已完成轮次的执行结果。"""
        return self._agent_results
# endregion

    def invoke(
        self,
        session_id: str,
        input: UserInput | type[BaseInput],
        agent_mode: AgentMode = AgentMode.AGENT,
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentResult:
        """
        调用 Agent 执行

        Args:
            session_id: 会话 ID
            input: UserInput 用户输入 或 BaseInput 输入类型
            agent_mode: 智能体模式
            http_request: 本次出站 HTTP 配置（可空；鉴权头等，不经 metadata）
            metadata: 元数据, 智能体运行时需要的额外信息, 由调用方自行定义
        """
        graph_input = self._build_input(input)
        runnable_config = self._build_runnable_config(session_id, agent_mode, http_request, metadata)
        context = self._build_context(session_id, resume=False)
        self._expire_idle_skills_for_user_turn(context)
        self._pending_inputs[session_id] = input
        result = self._compiled_graph.invoke(graph_input, runnable_config, context=context)
        return self._generate_result(session_id, context, result)

    async def ainvoke(
        self,
        session_id: str,
        input: UserInput | type[BaseInput],
        agent_mode: AgentMode = AgentMode.AGENT,
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentResult:
        """
        调用 Agent 执行（异步）
        """
        graph_input = self._build_input(input)
        runnable_config = self._build_runnable_config(session_id, agent_mode, http_request, metadata)
        context = self._build_context(session_id, resume=False)
        self._expire_idle_skills_for_user_turn(context)
        self._pending_inputs[session_id] = input
        result = await self._compiled_graph.ainvoke(graph_input, runnable_config, context=context)
        return await self._agenerate_result(session_id, context, result)

    def stream(
        self,
        session_id: str,
        input: UserInput | type[BaseInput],
        agent_mode: AgentMode = AgentMode.AGENT,
        version: str = "v2",
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Iterator[AgentResult]:
        """
        流式调用 Agent 执行

        Args:
            session_id: 会话 ID
            input: UserInput 用户输入 或 BaseInput 输入类型
            version: 版本
            http_request: HTTP请求配置
            metadata: 元数据, 智能体运行时需要的额外信息, 由调用方自行定义
        """
        graph_input = self._build_input(input)
        runnable_config = self._build_runnable_config(session_id, agent_mode, http_request, metadata)
        context = self._build_context(session_id, http_request, resume=False)
        self._expire_idle_skills_for_user_turn(context)
        self._pending_inputs[session_id] = input
        return self._stream_iterator(graph_input, runnable_config, context, session_id, version)

    async def astream(
        self,
        session_id: str,
        input: UserInput | type[BaseInput],
        agent_mode: AgentMode = AgentMode.AGENT,
        version: str = "v2",
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[AgentResult]:
        """
        流式调用 Agent 执行（异步）
        """
        graph_input = self._build_input(input)
        runnable_config = self._build_runnable_config(session_id, agent_mode, http_request, metadata)
        context = self._build_context(session_id, http_request, resume=False)
        self._expire_idle_skills_for_user_turn(context)
        self._pending_inputs[session_id] = input
        return self._astream_iterator(graph_input, runnable_config, context, session_id, version)

    def resume(
        self,
        session_id: str,
        values: dict,
        agent_mode: AgentMode = AgentMode.AGENT,
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentResult:
        """
        恢复 Agent 执行

        Args:
            session_id: 会话 ID
            values: 输入
            http_request: HTTP请求配置
            metadata: 元数据, 智能体运行时需要的额外信息, 由调用方自行定义
        """
        runnable_config = self._build_runnable_config(session_id, agent_mode, http_request, metadata)
        context = self._build_context(session_id, http_request, resume=True)
        result = self._compiled_graph.invoke(Command(resume=values), runnable_config, context=context)
        return self._generate_result(session_id, context, result)

    async def aresume(
        self,
        session_id: str,
        values: dict,
        agent_mode: AgentMode = AgentMode.AGENT,
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentResult:
        """
        恢复 Agent 执行（异步）
        """
        runnable_config = self._build_runnable_config(session_id, agent_mode, http_request, metadata)
        context = self._build_context(session_id, http_request, resume=True)
        result = await self._compiled_graph.ainvoke(Command(resume=values), runnable_config, context=context)
        return await self._agenerate_result(session_id, context, result)

    def stream_resume(
        self,
        session_id: str,
        values: dict,
        version: str = "v2",
        agent_mode: AgentMode = AgentMode.AGENT,
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Iterator[AgentResult]:
        """
        流式恢复 Agent 执行

        Args:
            session_id: 会话 ID
            values: 输入
            version: 版本
            http_request: HTTP请求配置
            metadata: 元数据, 智能体运行时需要的额外信息, 由调用方自行定义
        """
        runnable_config = self._build_runnable_config(session_id, http_request, metadata)
        context = self._build_context(session_id, http_request, resume=True)
        return self._stream_iterator(Command(resume=values), runnable_config, context, session_id, version)

    async def astream_resume(
        self,
        session_id: str,
        values: dict,
        agent_mode: AgentMode = AgentMode.AGENT,
        version: str = "v2",
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[AgentResult]:
        """
        流式恢复 Agent 执行（异步）
        """
        runnable_config = self._build_runnable_config(session_id, agent_mode, http_request, metadata)
        context = self._build_context(session_id, http_request, resume=True)
        return self._astream_iterator(Command(resume=values), runnable_config, context, session_id, version)

    def get_state(self, session_id: str, checkpoint_id: str | None = None):
        """
        [Debug] 获取当前状态

        Args:
            session_id: 会话 ID
            checkpoint_id: 检查点 ID
        """
        configurable = {
            "thread_id": session_id,
        }

        if checkpoint_id:
            configurable["checkpoint_id"] = checkpoint_id

        runnable_config = RunnableConfig(configurable=configurable)
        return self._compiled_graph.get_state(runnable_config)

    def get_state_history(self, session_id: str):
        """
        [Debug] 获取状态历史

        Args:
            session_id: 会话 ID
        """
        configurable = {
            "thread_id": session_id,
        }
        runnable_config = RunnableConfig(configurable=configurable)
        return self._compiled_graph.get_state_history(runnable_config)

    def get_agent_results(self, session_id: str) -> list[AgentResult]:
        """获取指定会话已完成的各轮 AgentResult。"""
        return list(self._agent_results.get(session_id, []))

    def restore_checkpoint(
        self,
        session_id: str,
        checkpoint_id: str | None,
    ) -> None:
        """
        将 thread tip fork 回开跑前基线（Cancel 用）。

        LangGraph 的 update_state 不删除历史，只 fork 出新 tip，使后续
        无 checkpoint_id 的 get_state / invoke / astream 读到基线语义。

        Args:
            session_id: 会话 ID（= thread_id）
            checkpoint_id: 开跑前 tip 的 checkpoint_id；首轮无基线时为 None
        """
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id is required")

        # 当轮未完成，不写 conversation
        self._pending_inputs.pop(session_id, None)
        self._pending_results.pop(session_id, None)

        if checkpoint_id is None or not str(checkpoint_id).strip():
            self._restore_first_turn_baseline(session_id)
            return

        baseline = self.get_state(session_id, checkpoint_id=str(checkpoint_id))
        config = self._config_for_checkpoint(session_id, str(checkpoint_id), baseline)
        values = self._normalize_checkpoint_values(getattr(baseline, "values", None))
        # 不传 as_node：由 checkpoint 版本史推断。
        # - 完成态基线 → tip.next == ()
        # - HITL interrupt 基线 → tip.next 保留，可再次 Resume
        self._compiled_graph.update_state(config, values=values)

    def _restore_first_turn_baseline(self, session_id: str) -> None:
        """首轮无基线：若已有 tip（半成品），写成空完成态；否则 no-op。"""
        tip = self.get_state(session_id)
        tip_config = getattr(tip, "config", None) or {}
        tip_configurable = (
            tip_config.get("configurable") if isinstance(tip_config, dict) else None
        ) or {}
        if not tip_configurable.get("checkpoint_id"):
            return
        values = self._empty_state_values()
        config = RunnableConfig(configurable={"thread_id": session_id})
        self._compiled_graph.update_state(config, values=values)

    def _empty_state_values(self) -> dict[str, Any]:
        """用 state_schema 默认值构造空完成态；失败则 {}。"""
        schema = self._graph.state_schema
        if schema is None:
            return {}
        try:
            instance = schema()
        except Exception:
            return {}
        if hasattr(instance, "model_dump"):
            return instance.model_dump()
        if isinstance(instance, dict):
            return dict(instance)
        return {}

    @staticmethod
    def _normalize_checkpoint_values(values: Any) -> dict[str, Any]:
        """将 StateSnapshot.values 规范为 update_state 可用的 dict。"""
        if values is None:
            return {}
        if hasattr(values, "model_dump"):
            return values.model_dump()
        if isinstance(values, dict):
            out: dict[str, Any] = {}
            for key, value in values.items():
                if hasattr(value, "model_dump"):
                    out[key] = value.model_dump()
                else:
                    out[key] = value
            return out
        try:
            return dict(values)
        except Exception:
            return {}

    @staticmethod
    def _config_for_checkpoint(
        session_id: str,
        checkpoint_id: str,
        baseline: Any,
    ) -> RunnableConfig:
        """构造带 checkpoint_ns 的 config（get_state 按 id 取回时可能缺 ns）。"""
        checkpoint_ns = ""
        baseline_config = getattr(baseline, "config", None) or {}
        if isinstance(baseline_config, dict):
            configurable = baseline_config.get("configurable") or {}
            if isinstance(configurable, dict) and configurable.get("checkpoint_ns") is not None:
                checkpoint_ns = str(configurable.get("checkpoint_ns") or "")
        return RunnableConfig(
            configurable={
                "thread_id": session_id,
                "checkpoint_id": checkpoint_id,
                "checkpoint_ns": checkpoint_ns,
            }
        )

    def _register_tools(self) -> None:
        """
        注册工具。
        """
        self._register_builtin_toolkit()

    def _register_builtin_toolkit(self) -> None:
        """注册内置 skill 工具到 self._tool_registry。"""
        load_skill = create_load_skill_tool(self._skill_manager)
        read_skill = create_read_skill_resource_tool(self._skill_manager)

        self._tool_registry.register(to_tool_definition(load_skill), load_skill)
        self._tool_registry.register(to_tool_definition(read_skill), read_skill)

    async def register_mcp_tools(self) -> list[ToolDefinition]:
        """组装期异步注册 MCP 工具（写入 Agent 持有的同一 registry）。"""
        if self._mcp_client is None:
            return []
        return await self._mcp_client.register_tools()

    def _build_input(self, input: UserInput | type[BaseInput]) -> dict | BaseInput:
        """构建输入"""
        input_schema = self._graph.input_schema
        if input_schema is None:
            return {"input": input}
        if isinstance(input, input_schema):
            return input
        raise TypeError(f"输入类型错误，期望 {input_schema}，实际 {type(input)}")

    def _build_runnable_config(
        self,
        session_id: str,
        agent_mode: AgentMode = AgentMode.AGENT,
        http_request: HttpRequest | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RunnableConfig:
        """
        构建图级 RunnableConfig。
        """
        runtime = RuntimeConfig(
            thread_id=session_id,
            session_id=session_id,
            agent_mode=agent_mode,
            http_request=http_request,
            metadata=dict(metadata) if metadata else {},
        )
        return runtime.to_graph_runnable_config()

    def _build_context(self, session_id: str, http_request: HttpRequest | None = None, *, resume: bool = False) -> BaseContext:
        """
        构建上下文

        active_skills 使用会话级同一 dict；构造后校验引用，避免 Pydantic 拷贝
        导致 HITL resume 丢失已加载 skill。

        resume=True 时复用未完成的本轮 AgentResult；否则新建本轮结果。
        """
        agent_state = self._get_agent_state(session_id)
        if agent_state.session_id != session_id:
            raise ValueError("AgentState session_id does not match RunnableConfig thread_id")
        active_skills = self._get_active_skills(session_id)
        if resume and session_id in self._pending_results:
            agent_result = self._pending_results[session_id]
        else:
            agent_result = AgentResult()
            self._pending_results[session_id] = agent_result
        context = BaseContext(
            agent_state=agent_state,
            resources=AgentResources(
                system_prompt=self._agent_config.system_prompt,
                skill_list=self._agent_config.skill_list,
                skill_frontmatter_list=self._skill_manager.build_skill_frontmatter_list(http_request),
            ),
            active_skills=active_skills,
            agent_result=agent_result,
        )
        if context.active_skills is not active_skills:
            object.__setattr__(context, "active_skills", active_skills)
        if context.agent_result is not agent_result:
            object.__setattr__(context, "agent_result", agent_result)
        return context

    def _expire_idle_skills_for_user_turn(self, context: BaseContext) -> None:
        """按用户交互推进 skill idle；HITL resume 不调用。"""
        discarded = SkillManager.expire_idle(context)
        if discarded:
            logger.info("expired idle skills (user turn): %s", discarded)

    def _get_agent_state(self, session_id: str) -> AgentState:
        """
        获取智能体状态
        """
        return self._agent_state_map.setdefault(session_id, AgentState(session_id=session_id))

    def _get_active_skills(self, session_id: str) -> dict[str, SkillRuntimeContext]:
        """获取会话级已加载 Skill（同 dict 引用，供 load_skill 写回）。"""
        return self._active_skills_map.setdefault(session_id, {})

    @staticmethod
    def _extract_response_text(result: Any) -> str:
        """从 graph result / snapshot.values 提取 response 文本。"""
        if result is None:
            return ""
        if isinstance(result, dict):
            response = result.get("response")
        else:
            response = getattr(result, "response", None)
        if response is None:
            return ""
        return str(response)

    def _generate_result(
        self,
        session_id: str,
        context: BaseContext,
        result: Any = None,
        *,
        compress: bool = True,
    ) -> AgentResult:
        """
        生成结果
        """
        self._append_conversation(session_id, result)
        agent_result = context.agent_result or self._pending_results.get(session_id) or AgentResult()
        snapshot = self.get_state(session_id)

        if snapshot.next:
            agent_result.text = ""
            self._pending_results[session_id] = agent_result
            return agent_result.model_copy(deep=True)

        response_text = self._extract_response_text(result)
        if not response_text:
            snapshot = self.get_state(session_id)
            response_text = self._extract_response_text(getattr(snapshot, "values", None))
        if response_text:
            agent_result.text = response_text

        snapshot = self.get_state(session_id)
        if snapshot.next:
            self._pending_results[session_id] = agent_result
            return agent_result.model_copy(deep=True)

        self._update_token_usage(session_id, context)
        self._agent_results.setdefault(session_id, []).append(agent_result.model_copy(deep=True))
        self._pending_results.pop(session_id, None)
        if compress:
            self._compress_conversation(session_id)
        return agent_result.model_copy(deep=True)

    async def _agenerate_result(
        self,
        session_id: str,
        context: BaseContext,
        result: Any = None,
    ) -> AgentResult:
        """
        生成结果(异步)
        """
        agent_result = self._generate_result(session_id, context, result, compress=False)
        snapshot = self.get_state(session_id)
        if not snapshot.next:
            await self._acompress_conversation(session_id)
        return agent_result

    def _update_token_usage(self, session_id: str, context: BaseContext) -> None:
        """将本轮 token 用量累加到 AgentState"""
        if context.agent_result is None:
            return
        usage = context.agent_result.token_usage
        agent_state = self._get_agent_state(session_id)
        agent_state.token_usage = agent_state.token_usage.add(usage)
        logger.info(
            "token_usage | turn_input=%s turn_output=%s turn_total=%s | session_total=%s",
            usage.input_tokens,
            usage.output_tokens,
            usage.total_tokens,
            agent_state.token_usage.total_tokens,
        )

    def _compress_conversation(self, session_id: str) -> None:
        """交互结束后按需压缩会话历史（同步）。"""
        maybe_compress_conversation(
            self._get_agent_state(session_id),
            self._conversation_compressor,
            max_tokens=self._agent_config.conversation_max_tokens,
        )

    async def _acompress_conversation(self, session_id: str) -> None:
        """交互结束后按需压缩会话历史（异步）。"""
        await amaybe_compress_conversation(
            self._get_agent_state(session_id),
            self._conversation_compressor,
            max_tokens=self._agent_config.conversation_max_tokens,
        )

    def _stream_iterator(
        self,
        graph_input: dict | Command,
        runnable_config: RunnableConfig,
        context: BaseContext,
        session_id: str,
        version: str,
    ) -> Iterator[AgentResult]:
        for _ in self._compiled_graph.stream(
            graph_input,
            runnable_config,
            context=context,
            stream_mode="custom",
            subgraphs=True,
            version=version,
        ):
            if context.agent_result is not None:
                yield context.agent_result.model_copy(deep=True)
        final = self._generate_result(session_id, context)
        yield final

    async def _astream_iterator(
        self,
        graph_input: dict | Command,
        runnable_config: RunnableConfig,
        context: BaseContext,
        session_id: str,
        version: str,
    ) -> AsyncIterator[AgentResult]:
        async for _ in self._compiled_graph.astream(
            graph_input,
            runnable_config,
            context=context,
            stream_mode="custom",
            subgraphs=True,
            version=version,
        ):
            if context.agent_result is not None:
                yield context.agent_result.model_copy(deep=True)
        final = await self._agenerate_result(session_id, context)
        yield final

    def _append_conversation(self, session_id: str, result=None) -> None:
        """
        追加会话历史
        """
        snapshot = self.get_state(session_id)

        # Graph 处于 HITL 等中断状态
        if snapshot.next:
            return

        if result is None:
            result = snapshot.values

        pending_input = self._pending_inputs.get(session_id)
        if pending_input is None:
            return

        response = (
            result.get("response")
            if isinstance(result, dict)
            else getattr(result, "response", None)
        )
        if not response:
            return

        agent_state = self._get_agent_state(session_id)
        if agent_state.session_id != session_id:
            raise ValueError("AgentState session_id does not match RunnableConfig thread_id")

        conversation = agent_state.conversation
        conversation.messages = append_messages(
            conversation.messages,
            [
                Message(
                    role=Role.USER,
                    content=self._input_text(pending_input),
                ),
                Message(
                    role=Role.ASSISTANT,
                    content=str(response),
                ),
            ],
        )
        self._pending_inputs.pop(session_id, None)

    def _input_text(self,input: UserInput | type[BaseInput]) -> str:
        """将 Agent 输入转换为会话消息文本。"""
        value = getattr(input, "input", input)
        if isinstance(value, UserInput):
            return value.text
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

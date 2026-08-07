import json
from typing import Any, Mapping

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command

from ...common import get_logger
from ..capability.skill import SkillManager
from ..graph import BaseContext, BaseInput, RootGraph
from ..llm import LLMClient
from ..mcp import MCPClient
from ..model.agent_state import AgentState
from ..model.input import UserInput
from ..model.message import Message, Role
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
from ..trace import AgentTrace
from .agent_config import AgentConfig
from .runnable_metadata import METADATA_HTTP_HEADERS_KEY

logger = get_logger("agent")


class Agent:
    """
    Agent 类：用于定义 Agent 的运行实体，包括 AgentConfig、RuntimeConfig、RootGraph 等。

    Attributes:
        agent_config: Agent 配置
        runtime_config: Runtime 配置
        graph: RootGraph 根图
        compiled_graph: 编译后的图
        tool_registry: 工具注册器
        skill_manager: Skill 管理器
        mcp_client: MCP 客户端（由 AgentConfig.mcp_servers 在构造时内部创建；
            可选合并内置 Fetch / Filesystem，默认关闭）
    """
    def __init__(self, agent_config: AgentConfig, runtime_config: RuntimeConfig, graph: RootGraph):
        # 配置
        self._agent_config = agent_config
        self._runtime_config = runtime_config

        # 图
        self._graph = graph
        self._compiled_graph = self._graph.compile(runtime_config)

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
        self._conversation_compressor = ConversationCompressor(
            LLMClient(agent_config.llm_config)
        )
        
        # 注册工具
        self._register_tools()

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

    def invoke(
        self,
        session_id: str,
        input: UserInput | type[BaseInput],
        metadata: Mapping[str, Any] | None = None,
    ):
        """
        调用 Agent 执行

        Args:
            session_id: 会话 ID
            input: UserInput 用户输入 或 BaseInput 输入类型
            metadata: 元数据, 智能体运行时需要的额外信息, 由调用方自行定义
        """
        # 构建输入
        input_schema = self._graph.input_schema
        if input_schema is None: # 无输入类型时，直接使用UserInput
            graph_input = {"input": input}
        else: # 输入有类型时，使用input_schema进行类型检查，如果类型不匹配，则抛出TypeError
            if isinstance(input, input_schema):
                graph_input = input
            else:
                raise TypeError(f"输入类型错误，期望 {input_schema}，实际 {type(input)}")

        # 构建RunnableConfig
        runnable_config = self._build_runnable_config(session_id, metadata)
        context = self._build_context(session_id)
        self._expire_idle_skills_for_user_turn(context)
        self._pending_inputs[session_id] = input
        result = self._compiled_graph.invoke(graph_input, runnable_config, context=context)
        # 写回历史记录
        self._append_conversation(session_id, result)
        self._print_token_usage(session_id, context)
        self._compress_conversation(session_id)
        return result

    async def ainvoke(
        self,
        session_id: str,
        input: UserInput | type[BaseInput],
        metadata: Mapping[str, Any] | None = None,
    ):
        """
        调用 Agent 执行（异步）
        """
        # 构建输入
        input_schema = self._graph.input_schema
        if input_schema is None: # 无输入类型时，直接使用UserInput
            graph_input = {"input": input}
        else: # 输入有类型时，使用input_schema进行类型检查，如果类型不匹配，则抛出TypeError
            if isinstance(input, input_schema):
                graph_input = input
            else:
                raise TypeError(f"输入类型错误，期望 {input_schema}，实际 {type(input)}")

        # 构建RunnableConfig
        runnable_config = self._build_runnable_config(session_id, metadata)
        context = self._build_context(session_id)
        self._expire_idle_skills_for_user_turn(context)
        self._pending_inputs[session_id] = input
        result = await self._compiled_graph.ainvoke(graph_input, runnable_config, context=context)
        # 写回历史记录
        self._append_conversation(session_id, result)
        self._print_token_usage(session_id, context)
        await self._acompress_conversation(session_id)
        return result

    def stream(
        self,
        session_id: str,
        input: UserInput | type[BaseInput],
        version: str = "v2",
        metadata: Mapping[str, Any] | None = None,
    ):
        """
        流式调用 Agent 执行

        Args:
            session_id: 会话 ID
            input: UserInput 用户输入 或 BaseInput 输入类型
            version: 版本
            metadata: 元数据, 智能体运行时需要的额外信息, 由调用方自行定义
        """
        # 构建输入
        input_schema = self._graph.input_schema
        if input_schema is None: # 无输入类型时，直接使用UserInput
            graph_input = {"input": input}
        else: # 输入有类型时，使用input_schema进行类型检查，如果类型不匹配，则抛出TypeError
            if isinstance(input, input_schema):
                graph_input = input
            else:
                raise TypeError(f"输入类型错误，期望 {input_schema}，实际 {type(input)}")

        # 构建RunnableConfig
        runnable_config = self._build_runnable_config(session_id, metadata)
        context = self._build_context(session_id)
        self._expire_idle_skills_for_user_turn(context)
        self._pending_inputs[session_id] = input
        return self._stream_iterator(graph_input, runnable_config, context, session_id, version)

    async def astream(
        self,
        session_id: str,
        input: UserInput | type[BaseInput],
        version: str = "v2",
        metadata: Mapping[str, Any] | None = None,
    ):
        """
        流式调用 Agent 执行（异步）
        """
        # 构建输入
        input_schema = self._graph.input_schema
        if input_schema is None: # 无输入类型时，直接使用UserInput
            graph_input = {"input": input}
        else: # 输入有类型时，使用input_schema进行类型检查，如果类型不匹配，则抛出TypeError
            if isinstance(input, input_schema):
                graph_input = input
            else:
                raise TypeError(f"输入类型错误，期望 {input_schema}，实际 {type(input)}")

        # 构建RunnableConfig
        runnable_config = self._build_runnable_config(session_id, metadata)
        context = self._build_context(session_id)
        self._expire_idle_skills_for_user_turn(context)
        self._pending_inputs[session_id] = input
        return self._astream_iterator(graph_input, runnable_config, context, session_id, version)

    def resume(
        self,
        session_id: str,
        values: dict,
        metadata: Mapping[str, Any] | None = None,
    ):
        """
        恢复 Agent 执行

        Args:
            session_id: 会话 ID
            values: 输入
            metadata: 元数据, 智能体运行时需要的额外信息, 由调用方自行定义
        """
        runnable_config = self._build_runnable_config(session_id, metadata)
        context = self._build_context(session_id)
        result = self._compiled_graph.invoke(Command(resume=values), runnable_config, context=context)
        self._append_conversation(session_id, result)
        self._print_token_usage(session_id, context)
        self._compress_conversation(session_id)
        return result

    async def aresume(
        self,
        session_id: str,
        values: dict,
        metadata: Mapping[str, Any] | None = None,
    ):
        """
        恢复 Agent 执行（异步）
        """
        runnable_config = self._build_runnable_config(session_id, metadata)
        context = self._build_context(session_id)
        result = await self._compiled_graph.ainvoke(Command(resume=values), runnable_config, context=context)
        self._append_conversation(session_id, result)
        self._print_token_usage(session_id, context)
        await self._acompress_conversation(session_id)
        return result

    def stream_resume(
        self,
        session_id: str,
        values: dict,
        version: str = "v2",
        metadata: Mapping[str, Any] | None = None,
    ):
        """
        流式恢复 Agent 执行

        Args:
            session_id: 会话 ID
            values: 输入
            version: 版本
            metadata: 元数据, 智能体运行时需要的额外信息, 由调用方自行定义
        """
        runnable_config = self._build_runnable_config(session_id, metadata)
        context = self._build_context(session_id)
        return self._stream_iterator(Command(resume=values), runnable_config, context, session_id, version)

    async def astream_resume(
        self,
        session_id: str,
        values: dict,
        version: str = "v2",
        metadata: Mapping[str, Any] | None = None,
    ):
        """
        流式恢复 Agent 执行（异步）
        """
        runnable_config = self._build_runnable_config(session_id, metadata)
        context = self._build_context(session_id)
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

    def _build_runnable_config(
        self,
        session_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> RunnableConfig:
        """
        构建 RunnableConfig。

        metadata 经规范化后写入 configurable["metadata"]（包含默认键 http_headers, {"Authorization":"Bearer x"}）。
        """
        configurable: dict[str, Any] = {
            "thread_id": session_id,
            "metadata": self._normalize_invoke_metadata(metadata),
        }
        return RunnableConfig(configurable=configurable)

    def _build_context(self, session_id: str) -> BaseContext:
        """
        构建上下文

        active_skills 使用会话级同一 dict；构造后校验引用，避免 Pydantic 拷贝
        导致 HITL resume 丢失已加载 skill。
        """
        agent_state = self._get_agent_state(session_id)
        if agent_state.session_id != session_id:
            raise ValueError("AgentState session_id does not match RunnableConfig thread_id")
        active_skills = self._get_active_skills(session_id)
        context = BaseContext(
            agent_state=agent_state,
            agent_prompt=self._agent_config.system_prompt,
            skill_list=self._skill_manager.skill_frontmatter_list,
            active_skills=active_skills,
            trace=AgentTrace(
                session_id=session_id,
                token_usage=agent_state.token_usage.model_copy(),
            ),
        )
        if context.active_skills is not active_skills:
            object.__setattr__(context, "active_skills", active_skills)
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

    def _print_token_usage(self, session_id: str, context: BaseContext) -> None:
        """将会话级 token 用量写回 AgentState 并记录日志。"""
        if context.trace is None:
            return
        usage = context.trace.token_usage
        agent_state = self._get_agent_state(session_id)
        agent_state.token_usage = usage.model_copy()
        logger.info(
            "token_usage | input=%s output=%s total=%s",
            usage.input_tokens,
            usage.output_tokens,
            usage.total_tokens,
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

    def _stream_iterator(self, graph_input: dict | Command, runnable_config: RunnableConfig, context: BaseContext, session_id: str,version: str):
        yield from self._compiled_graph.stream(graph_input, runnable_config, context=context, stream_mode="messages", subgraphs=True, version=version)
        self._append_conversation(session_id)
        self._print_token_usage(session_id, context)
        self._compress_conversation(session_id)

    async def _astream_iterator(self, graph_input: dict | Command, runnable_config: RunnableConfig, context: BaseContext, session_id: str, version: str):
        async for event in self._compiled_graph.astream(graph_input, runnable_config, context=context, stream_mode="messages", subgraphs=True, version=version):
            yield event
        self._append_conversation(session_id)
        self._print_token_usage(session_id, context)
        await self._acompress_conversation(session_id)

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

        agent_state.conversation.append(
            Message(
                role=Role.USER,
                content=self._input_text(pending_input),
            ),
            Message(
                role=Role.ASSISTANT,
                content=str(response),
            ),
        )
        self._pending_inputs.pop(session_id, None)

    @staticmethod
    def _input_text(input: UserInput | type[BaseInput]) -> str:
        """将 Agent 输入转换为会话消息文本。"""
        value = getattr(input, "input", input)
        if isinstance(value, UserInput):
            return value.text
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

    def _normalize_invoke_metadata(self, metadata: Mapping[str, Any] | None) -> dict[str, Any]:
        """
        规范化调用 metadata，写入 configurable["metadata"]。

        - 其它键原样拷贝（不解释业务语义）
        - 保留键 http_headers：JSON 字符串或已是 dict → 统一为 dict[str, str]
        """
        if not metadata:
            return {}

        out: dict[str, Any] = dict(metadata)
        if METADATA_HTTP_HEADERS_KEY not in out:
            return out

        raw = out[METADATA_HTTP_HEADERS_KEY]
        if raw is None or raw == "":
            del out[METADATA_HTTP_HEADERS_KEY]
            return out

        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"metadata.{METADATA_HTTP_HEADERS_KEY} is not valid JSON: {exc}"
                ) from exc
        elif isinstance(raw, dict):
            parsed = raw
        else:
            raise ValueError(
                f"metadata.{METADATA_HTTP_HEADERS_KEY} must be a JSON object string "
                f"or dict[str, str], got {type(raw).__name__}"
            )

        if not isinstance(parsed, dict):
            raise ValueError(
                f"metadata.{METADATA_HTTP_HEADERS_KEY} must be a JSON object"
            )
        headers: dict[str, str] = {}
        for key, value in parsed.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(
                    f"metadata.{METADATA_HTTP_HEADERS_KEY} entries must be string keys "
                    "and string values"
                )
            headers[key] = value
        out[METADATA_HTTP_HEADERS_KEY] = headers
        return out

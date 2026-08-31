from collections.abc import AsyncIterator, Iterator
import json
from typing import Any, Callable, Mapping
from uuid import uuid4

from langchain_core.runnables.config import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from ...common import get_logger
from ...common.network import HttpRequest
from ..capability.skill import SkillManager
from ..graph import (
    BaseContext,
    BaseInput,
    Graph,
    GraphCompileOptions,
    GraphSchema,
    Node,
)
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
from ..tool.toolkit import (
    create_directory_tool,
    create_edit_file_tool,
    create_knowledge_base_query_tool,
    create_list_directory_tool,
    create_load_skill_tool,
    create_read_file_tool,
    create_read_skill_resource_tool,
    create_read_xls_tool,
    create_read_xlsx_tool,
    create_search_files_tool,
    create_write_file_tool,
    create_write_xls_tool,
    create_write_xlsx_tool,
)
from ..tool.utils import to_tool_definition
from .agent_config import AgentConfig
from .agent_session import AgentSession

logger = get_logger("agent")


class Agent:
    """
    Agent 类：用于定义 Agent 的运行实体，包括 AgentConfig、GraphSchema、GraphCompileOptions、Graph、CompiledStateGraph 等。

    Attributes:
        agent_config: Agent 配置
        graph_schema: 图模式
        graph_compile_options: 图编译选项
        graph: 图
        compiled_graph: 编译后的图
        tool_registry: 工具注册器
        skill_manager: Skill 管理器
        mcp_client: MCP 客户端
        agent_sessions: Agent Session 管理器
    """
    def __init__(self, agent_config: AgentConfig, graph_schema: GraphSchema, compile_options: GraphCompileOptions):
        # 配置
        self._agent_config = agent_config
        if agent_config.id is None:
            self._agent_config.id = self._generate_agent_id()
        self._graph_schema = graph_schema
        self._graph_compile_options = compile_options

        # 图
        self._graph: Graph = self._init_graph(graph_schema)
        self._compiled_graph: CompiledStateGraph | None = None

        # Agent Resources
        self._tool_registry = ToolRegistry()
        self._skill_manager = SkillManager(agent_config.skill_list)
        self._mcp_client = (
            MCPClient(self._tool_registry, list(agent_config.mcp_servers))
            if agent_config.mcp_servers
            else None
        )

        # Agent Session
        self._agent_sessions: dict[str, AgentSession] = {}

        # Conversation
        self._conversation_compressor = ConversationCompressor(
            LLMClient(agent_config.llm_config)
        )

        # 智能体执行结果
        # self._agent_results: dict[str, list[AgentResult]] = {}

        # 注册工具
        self._register_tools()

# region 属性
    @property
    def agent_config(self) -> AgentConfig:
        """Agent 配置"""
        return self._agent_config

    @property
    def agent_id(self) -> str:
        """Agent ID"""
        return self._agent_config.id

    @property
    def mcp_client(self) -> MCPClient | None:
        """MCPClient"""
        return self._mcp_client

    @property
    def tool_registry(self) -> ToolRegistry:
        """工具注册表"""
        return self._tool_registry

    @property
    def skill_manager(self) -> SkillManager:
        """Skill 管理器"""
        return self._skill_manager
# endregion

# region Build Graph API
    def add_node(self, node: Node) -> None:
        """添加节点"""
        self._graph.add_node(node)

    def add_subgraph(self, name: str, subgraph: CompiledStateGraph) -> None:
        """添加子图"""
        self._graph.add_subgraph(name, subgraph)

    def add_edge(self, from_node: str, to_node: str) -> None:
        """添加边"""
        self._graph.add_edge(from_node, to_node)

    def add_conditional_edge(self, from_node: str, condition: Callable[[Any], str], path_map: dict[str, str] | None = None) -> None:
        """"添加条件边"""
        self._graph.add_conditional_edges(
            from_node,
            condition,
            path_map,
        )

    def compile(self) -> None:
        """编译图"""
        builder = self._graph.build()
        self._compiled_graph = builder.compile(
            checkpointer=self._graph_compile_options.checkpointer,
            store=self._graph_compile_options.store,
        )
# endregion

# region Invoke and Stream
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
        context = self._build_context(session_id, input, http_request, resume=False)
        self._unload_idle_skills_for_user_turn(context)
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
        context = self._build_context(session_id, input, http_request, resume=False)
        self._unload_idle_skills_for_user_turn(context)
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
        context = self._build_context(session_id, input, http_request, resume=False)
        self._unload_idle_skills_for_user_turn(context)
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
        context = self._build_context(session_id, input, http_request, resume=False)
        self._unload_idle_skills_for_user_turn(context)
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
        runnable_config = self._build_runnable_config(session_id, agent_mode, http_request, metadata)
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
# endregion

# region Public Functions
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
        """获取指定会话所有的AgentResult"""
        session = self._agent_sessions.get(session_id)
        if session is None:
            return []
        return list(session.results)

    def restore_checkpoint(self, session_id: str, checkpoint_id: str | None) -> None:
        """
        将 thread tip fork 回开跑前基线（Cancel 用）。只 clear 当轮，
        不修改 conversation / token_usage。无 checkpoint_id 且已有
        会话消息时跳过空图基线，避免误伤已结算历史。

        LangGraph 的 update_state 不删除历史，只 fork 出新 tip，使后续
        无 checkpoint_id 的 get_state / invoke / astream 读到基线语义。

        Args:
            session_id: 会话 ID（= thread_id）
            checkpoint_id: 开跑前 tip 的 checkpoint_id；首轮无基线时为 None
        """
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id is required")

        # 当轮未完成：丢 turn，不改 conversation / token_usage
        session = self._get_session(session_id)
        session.clear_turn()

        if checkpoint_id is None or not str(checkpoint_id).strip():
            if session.state.conversation.messages:
                logger.warning(
                    "restore_checkpoint: skip empty-graph baseline "
                    "(conversation already has %s messages)",
                    len(session.state.conversation.messages),
                )
                return
            self._restore_first_turn_baseline(session_id)
            return

        baseline = self.get_state(session_id, checkpoint_id=str(checkpoint_id))
        config = self._config_for_checkpoint(session_id, str(checkpoint_id), baseline)
        values = self._normalize_checkpoint_values(getattr(baseline, "values", None))
        # 不传 as_node：由 checkpoint 版本史推断。
        # - 完成态基线 → tip.next == ()
        # - HITL interrupt 基线 → tip.next 保留，可再次 Resume
        self._compiled_graph.update_state(config, values=values)

    async def register_mcp_tools(self) -> list[ToolDefinition]:
        """注册MCP工具"""
        if self._mcp_client is None:
            return []
        return await self._mcp_client.register_tools()
    
# endregion

# region Private Functions
    def _init_graph(self, graph_schema: GraphSchema) -> Graph:
        """初始化图"""
        return Graph(graph_schema=graph_schema)
        
    def _generate_agent_id(self) -> str:
        """生成 Agent ID"""
        if self._agent_config.id is not None:
            return self._agent_config.id
        
        id = "ak-" + str(uuid4())
        return id

    def _register_tools(self) -> None:
        """注册工具"""
        self._register_builtin_toolkit()

    def _register_builtin_toolkit(self) -> None:
        """注册内部工具"""
        # 能力工具
        load_skill = create_load_skill_tool(self._skill_manager)
        read_skill = create_read_skill_resource_tool(self._skill_manager)
        # knowledge_base_query = create_knowledge_base_query_tool()
        self._tool_registry.register(to_tool_definition(load_skill), load_skill)
        self._tool_registry.register(to_tool_definition(read_skill), read_skill)
        # self._tool_registry.register(to_tool_definition(knowledge_base_query), knowledge_base_query)

        # 读写文件
        read_file = create_read_file_tool()
        write_file = create_write_file_tool()
        edit_file = create_edit_file_tool()
        search_files = create_search_files_tool()
        list_directory = create_list_directory_tool()
        create_directory = create_directory_tool()
        self._tool_registry.register(to_tool_definition(read_file), read_file)
        self._tool_registry.register(to_tool_definition(write_file), write_file)
        self._tool_registry.register(to_tool_definition(edit_file), edit_file)
        self._tool_registry.register(to_tool_definition(search_files), search_files)
        self._tool_registry.register(to_tool_definition(list_directory), list_directory)
        self._tool_registry.register(to_tool_definition(create_directory), create_directory)

        # 读写 XLS / XLSX
        read_xls = create_read_xls_tool()
        write_xls = create_write_xls_tool()
        read_xlsx = create_read_xlsx_tool()
        write_xlsx = create_write_xlsx_tool()
        self._tool_registry.register(to_tool_definition(read_xls), read_xls)
        self._tool_registry.register(to_tool_definition(write_xls), write_xls)
        self._tool_registry.register(to_tool_definition(read_xlsx), read_xlsx)
        self._tool_registry.register(to_tool_definition(write_xlsx), write_xlsx)

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
        构建图级 RunnableConfig
        """
        runtime = RuntimeConfig(
            agent_id=self.agent_config.id,
            thread_id=session_id,
            session_id=session_id,
            agent_mode=agent_mode,
            http_request=http_request,
            metadata=dict(metadata) if metadata else {},
        )
        return runtime.to_graph_runnable_config()
    
    def _build_context(self, session_id: str, input: UserInput | type[BaseInput] | None = None, http_request: HttpRequest | None = None, resume: bool = False) -> BaseContext:
        """
        构建上下文

        active_skills 使用会话级同一 dict；构造后校验引用，避免 Pydantic 拷贝
        导致 HITL resume 丢失已加载 skill。

        resume=True 时复用未完成的本轮 AgentResult；否则新建本轮结果。
        """
        session = self._get_session(session_id)
        # 获取当前会话状态
        agent_state = session.state
        if agent_state.session_id != session_id:
            raise ValueError("AgentState session_id does not match RunnableConfig thread_id")

        # 获取当前会话活动SKill
        active_skills = session.active_skills

        # 复用未完成的本轮 AgentResult
        if resume:
            turn = session.current_turn
            if turn is None:
                raise ValueError("Cannot resume without an active turn")
        else:
            if input is None:
                raise ValueError("input is required when starting a new turn")
            turn = session.start_turn(input)

        # 构建Context
        context = BaseContext(
            agent_state=agent_state,
            resources=AgentResources(
                system_prompt=self._agent_config.system_prompt,
                skill_list=self._agent_config.skill_list,
                skill_frontmatter_list=self._skill_manager.build_skill_frontmatter_list(http_request),
                kb_list=self._agent_config.kb_list,
            ),
            active_skills=active_skills,
            agent_result=turn.result,
        )

        if context.active_skills is not active_skills:
            object.__setattr__(context, "active_skills", active_skills)
        if context.agent_result is not turn.result:
            object.__setattr__(context, "agent_result", turn.result)
        return context

    def _get_session(self, session_id: str) -> AgentSession:
            """获取 Agent Session"""
            session = self._agent_sessions.get(session_id)
            if session is None:
                session = AgentSession(session_id)
                self._agent_sessions[session_id] = session
            return session
    
    def _get_agent_state(self, session_id: str) -> AgentState:
        """获取智能体状态"""
        return self._get_session(session_id).state
    
    def _get_active_skills(self, session_id: str) -> dict[str, SkillRuntimeContext]:
        """获取指定会话中已加载的Skill"""
        return self._get_session(session_id).active_skills

    def _unload_idle_skills_for_user_turn(self, context: BaseContext) -> None:
        """按用户交互推进 skill idle；HITL resume 不调用"""
        unloaded_skills = self._skill_manager.unload_idle_skills(context)
        if unloaded_skills:
            logger.info("unloaded idle skills (user turn): %s", unloaded_skills)

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

    def _generate_result(self, session_id: str, context: BaseContext, result: Any = None, compress: bool = True) -> AgentResult:
        """
        生成结果
        """
        session = self._get_session(session_id)
        turn = session.current_turn
        if turn is None:
            raise ValueError("Cannot generate result without an active turn")
        agent_result = turn.result

        snapshot = self.get_state(session_id)
        # Graph 处于 HITL 等中断状态，保留当前 Turn
        if snapshot.next:
            agent_result.text = ""
            return agent_result.model_copy(deep=True)

        response_text = self._extract_response_text(result)
        if not response_text:
            response_text = self._extract_response_text(getattr(snapshot, "values", None))
        if not response_text:
            response_text = agent_result.text or ""
        if response_text:
            agent_result.text = response_text

        self._append_conversation(session_id, result)

        # 更新 Token Usage
        self._update_token_usage(session_id, context)

        # 当前 Turn 完成，保存结果并清理当前 Turn
        final_result = agent_result.model_copy(deep=True)
        session.add_result(final_result)
        session.clear_turn()

        if compress:
            self._compress_conversation(session_id)

        return final_result

    async def _agenerate_result(self, session_id: str,  context: BaseContext, result: Any = None) -> AgentResult:
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

        # 获取当轮交互
        session = self._get_session(session_id)
        turn = session.current_turn
        if turn is None:
            return

        if result is None:
            result = snapshot.values

        assistant = self._extract_response_text(result)
        if not assistant:
            assistant = self._extract_response_text(getattr(snapshot, "values", None))
        if not assistant:
            assistant = (turn.result.text or "").strip()
        if not assistant:
            assistant = "本轮已结束，无最终回复。"

        agent_state = self._get_agent_state(session_id)
        if agent_state.session_id != session_id:
            raise ValueError("AgentState session_id does not match RunnableConfig thread_id")

        conversation = agent_state.conversation
        conversation.messages = append_messages(
            conversation.messages,
            [
                Message(
                    role=Role.USER,
                    content=self._input_text(turn.input),
                ),
                Message(
                    role=Role.ASSISTANT,
                    content=assistant,
                ),
            ],
        )

    def _input_text(self,input: UserInput | type[BaseInput]) -> str:
        """将 Agent 输入转换为会话消息文本。"""
        value = getattr(input, "input", input)
        if isinstance(value, UserInput):
            return value.text
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

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
# endregion

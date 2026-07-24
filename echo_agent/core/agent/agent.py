from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command

from ..capability.skill import SkillCatalog, setup_skills
from ..graph import BaseInput, RootGraph
from ..mcp import MCPClient
from ..model import UserInput
from ..runtime import RuntimeConfig
from ..tool import ToolRegistry
from .agent_config import AgentConfig


class Agent:
    """
    Agent 类：用于定义 Agent 的运行实体，包括 AgentConfig、RuntimeConfig、RootGraph 等。

    Attributes:
        agent_config: Agent 配置
        runtime_config: Runtime 配置
        graph: RootGraph 根图
        compiled_graph: 编译后的图
        mcp_client: MCP 客户端（由 AgentConfig.mcp_servers 在构造时内部创建；
            始终含内置 Fetch / Filesystem，并与额外 mcp_servers 合并）
        skill_catalog: Skill 只读映射（调用 setup_skills 后可用）
    """
    def __init__(self, agent_config: AgentConfig, runtime_config: RuntimeConfig, graph: RootGraph):
        self._agent_config = agent_config
        self._runtime_config = runtime_config
        self._graph = graph
        self._compiled_graph = self._graph.compile(runtime_config)
        self._mcp_client = (
            MCPClient(list(agent_config.mcp_servers))
            if agent_config.mcp_servers
            else None
        )
        self._skill_catalog: SkillCatalog | None = None

    @property
    def mcp_client(self) -> MCPClient | None:
        """Agent 持有的 MCPClient；mcp_servers 为空时为 None。"""
        return self._mcp_client

    @property
    def skill_catalog(self) -> SkillCatalog | None:
        """已解析的 Skill 只读映射；未调用 setup_skills 时为 None。"""
        return self._skill_catalog

    async def setup_skills(self, registry: ToolRegistry) -> str | None:
        """
        根据 AgentConfig.skill_list 组装 Skill 能力。

        - Resolve → 绑定 catalog（供 load_skill / read_skill_resource 与 LLMClient 注入 Skill Usage Prompt）
        - 注册 load_skill、read_skill_resource 到 ToolRegistry
        - 返回 Skill Usage Prompt（无 skill 时为 None）
        """
        catalog, skill_prompt = await setup_skills(
            self._agent_config.skill_list,
            registry,
        )
        self._skill_catalog = catalog
        return skill_prompt

    def invoke(self, session_id: str, input: UserInput | type[BaseInput]):
        """
        调用 Agent 执行

        Args:
            session_id: 会话 ID
            input: UserInput 用户输入 或 BaseInput 输入类型
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
        runnable_config = self._build_runnable_config(session_id)
        return self._compiled_graph.invoke(graph_input, runnable_config)

    async def ainvoke(self, session_id: str, input: UserInput | type[BaseInput]):
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
        runnable_config = self._build_runnable_config(session_id)
        return await self._compiled_graph.ainvoke(graph_input, runnable_config)

    def stream(self, session_id: str, input: UserInput | type[BaseInput], version: str = "v2"):
        """
        流式调用 Agent 执行

        Args:
            session_id: 会话 ID
            input: UserInput 用户输入 或 BaseInput 输入类型
            version: 版本
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
        runnable_config = self._build_runnable_config(session_id)
        return self._compiled_graph.stream(graph_input, runnable_config, stream_mode="messages", subgraphs=True, version=version)

    async def astream(self, session_id: str, input: UserInput | type[BaseInput], version: str = "v2"):
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
        runnable_config = self._build_runnable_config(session_id)
        # 返回 async iterator，由调用方 async for / await 消费
        return self._compiled_graph.astream(graph_input, runnable_config, stream_mode="messages", subgraphs=True, version=version)

    def resume(self, session_id: str, values: dict):
        """
        恢复 Agent 执行

        Args:
            session_id: 会话 ID
            values: 输入
        """
        runnable_config = self._build_runnable_config(session_id)
        return self._compiled_graph.invoke(Command(resume=values), runnable_config)

    async def aresume(self, session_id: str, values: dict):
        """
        恢复 Agent 执行（异步）
        """
        runnable_config = self._build_runnable_config(session_id)
        return await self._compiled_graph.ainvoke(Command(resume=values), runnable_config)

    def stream_resume(self, session_id: str, values: dict, version: str = "v2"):
        """
        流式恢复 Agent 执行

        Args:
            session_id: 会话 ID
            values: 输入
            version: 版本
        """
        runnable_config = self._build_runnable_config(session_id)
        return self._compiled_graph.stream(Command(resume=values), runnable_config, stream_mode="messages", subgraphs=True, version=version)

    async def astream_resume(self, session_id: str, values: dict, version: str = "v2"):
        """
        流式恢复 Agent 执行（异步）
        """
        runnable_config = self._build_runnable_config(session_id)
        return self._compiled_graph.astream(Command(resume=values), runnable_config, stream_mode="messages", subgraphs=True, version=version)

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

    def _build_runnable_config(self, session_id: str) -> RunnableConfig:
        """
        构建 RunnableConfig

        Args:
            session_id: 会话 ID
        """
        return RunnableConfig(
            configurable={
                "thread_id": session_id,
            }
        )

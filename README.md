# echo-agent

![](https://img.shields.io/github/license/Jerryym/echo_agent.svg) 

基于 LangChain / LangGraph 的 **Agent Harness Runtime**。

在执行框架之上提供围绕模型的运行控制层：管理模型可见的上下文、可用的能力，以及可持久化的执行状态。可作为独立 Python 库使用，也可作为 Agent / Workflow 平台的底层执行引擎。

```text
Application
  → Harness Runtime（上下文 / 能力 / 状态）
    → Execution Strategy（默认 ReAct）
      → LangGraph
```

版本：**v0.1.0**

## 要求

- Python >= 3.12
- 推荐使用 [uv](https://github.com/astral-sh/uv)

## 安装

```bash
uv sync
```

开发依赖（测试 MCP、console UI 等）：

```bash
uv sync --group dev
```

## 能力一览（v0.1.0）

| 能力 | 说明 |
|------|------|
| Agent / Graph / LLM / Tool | 统一入口、Workflow、模型调用与工具执行 |
| ReAct | 默认 Execution Strategy |
| HITL | 审批 / 补参中断与恢复 |
| MCP | Client 接入；内置 Fetch / Filesystem |
| Skill | 本地包；激活进 Runtime Context（详情不进 messages）；会话隔离；3 轮未触达自动 expire |
| Prompt | PromptAssembler：Agent / Policy / Loaded Skills |
| Context 治理 | Token 计量；会话裁剪；超阈值历史摘要 |

### 已知限制

- 工具集在策略组装期快照，运行期不随 Skill 动态裁剪
- Skill 冷启动 Catalog（name + description）尚未注入 Prompt
- Tool Result 压缩、Plan-and-Execute、Memory、Multi-Agent 未做

详见 [设计文档](docs/echo-agent%20v0.1.0%20设计文档.md)。

## 快速开始

```python
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, LLMConfig, RootGraph, UserInput
from echo_agent.core.graph import END_NODE, START_NODE, GraphCompileOptions
from echo_agent.core.strategy import StrategyFactory, StrategyType
from echo_agent.core.tool import ToolRegistry


class State(BaseState):
    pass


def build_agent(llm_config: LLMConfig) -> Agent:
    tool_registry = ToolRegistry()  # 可注册业务工具；内置 load_skill 等由 Agent 注册

    react = StrategyFactory.create_as_node(
        StrategyType.REACT,
        llm_config=llm_config,
        tool_registry=tool_registry,
    )

    graph = RootGraph(state_schema=State)
    graph.add_node(react)
    graph.add_edge(START_NODE, react.name)
    graph.add_edge(react.name, END_NODE)

    agent_config = AgentConfig(
        name="demo",
        description="demo agent",
        llm_config=llm_config,
        mcp_allowed_directories=str(Path.cwd()),
        # skill_list={"pdf": "/path/to/skills/pdf"},
    )
    compile_options = GraphCompileOptions(checkpointer=InMemorySaver())
    return Agent(agent_config, compile_options, graph)


agent = build_agent(LLMConfig(...))
# 若使用 MCP：await agent.register_mcp_tools()
result = agent.invoke("session-1", UserInput(text="你好"))
print(result.get("response") if isinstance(result, dict) else result)
```

更多可运行示例见 `tests/` 与 `console/`。

## 项目结构

```text
echo_agent/
├── common/          # 异常与调试
├── prompt/          # PromptLoader / PromptAssembler
└── core/
    ├── agent/       # Agent 入口与配置
    ├── graph/       # Workflow / Node / State / Context
    ├── strategy/    # ReAct（Plan-and-Execute 占位）
    ├── capability/  # Skill
    ├── tool/        # 注册与执行
    ├── mcp/         # MCP Client
    ├── llm/         # 模型客户端
    ├── runtime/     # RuntimeConfig、HITL、会话压缩
    ├── model/       # 统一数据模型
    └── trace/       # Token / AgentTrace
docs/                # 设计文档
tests/               # 集成与单元示例
console/             # 本地调试 UI（可选）
```

## 文档

| 文档 | 说明 |
|------|------|
| [v0.1.0 设计文档](docs/echo-agent%20v0.1.0%20设计文档.md) | 产品口径、交付范围与已知限制 |
| [Harness Runtime 优化设计](docs/runtime/echo-agent%20v0.1.0%20Harness%20Runtime%20优化设计文档.md) | Harness 原则与任务拆解 |
| [Runtime Adapter 快速接入](docs/runtime%20adapter/快速接入.md) | gRPC Adapter 接入 |
| [Skill v0.1.0](docs/capability/skill/skill%20v0.1.0%20设计文档.md) | Skill 能力设计 |
| [ReAct 测试案例](tests/docs/ReAct%20Agent%20测试案例文档.md) | ReAct 联调说明 |

## 版本规划

- [x] **v0.1.0**（当前）：Harness 雏形 + ReAct + MCP + HITL + Skill
- [ ] **v0.2.0**：工具动态治理、Plan-and-Execute、权限梯度等
- [ ] **v0.3.0**：Memory / Multi-Agent / Long-running Agent

## License

以仓库内声明为准。

## References

- [LangGraph](https://reference.langchain.com/python/langgraph)
- [LangGraph 文档](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangChain](https://reference.langchain.com/python/langchain)
- [LangChain 文档](https://docs.langchain.com/oss/python/langchain/overview)
- [MCP 文档](https://modelcontextprotocol.io/docs/2025-11-25/getting-started/intro)
- [智能体 Harness 工程指南](https://yeasy.gitbook.io/harness_engineering_guide)
- [Harness Engineering Guide](https://harness-guide.com/zh/)
- [Agent Harness Complete Guide](https://harness-engineering.ai/blog/agent-harness-complete-guide/)
- [What is Harness Engineering?](https://harness-engineering.ai/blog/what-is-harness-engineering/)
- [Agent Harness Architecture: How the System Works Under the Hood](https://harness-engineering.ai/blog/agent-harness-architecture-how-the-system-works-under-the-hood/)

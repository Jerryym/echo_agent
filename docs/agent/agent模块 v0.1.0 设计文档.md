# Agent 模块 v0.1.0 设计文档

## 1. 模块定位

Agent 模块用于定义 Echo-Agent 中智能体的运行实体与对外统一入口，是连接 Graph Runtime 与外部调用层的执行封装层。其核心职责包括：

* 定义 Agent 运行实体（Runtime Agent）
* 封装 LangGraph CompiledGraph 执行能力
* 提供统一调用入口（invoke / stream）
* 承载 Agent 配置与运行时上下文
* 作为 Graph Runtime 的上层执行包装

Agent 模块不负责：

* Graph 结构构建（Node / Edge / SubGraph 定义）
* Graph 执行逻辑编排
* Strategy 策略实现与决策逻辑
* KB / Skill 的执行实现
* Tool / MCP 调用执行逻辑
* LLM 底层适配与调用实现
* Memory / Checkpoint 管理机制

---

## 2. 设计原则

### 2.1 Graph Runtime 封装原则

Agent 基于 LangGraph CompiledGraph 构建运行实体，但不直接参与 Graph 构建与编排，即：Agent 只负责“运行图”，不负责“定义图”。系统结构如下：

```text
Graph (DSL / Node / Edge)
        ↓ compile()
CompiledGraph (LangGraph Runtime)
        ↓
Agent (Runtime Wrapper)
        ↓
invoke / stream
```

### 2.2 配置与运行分离原则

AgentConfig 仅用于描述 Agent 的能力声明与运行配置，不参与运行时逻辑决策。运行时所有行为均由 Graph Node 与 Runtime Context 决定。

```text
AgentConfig → 声明
Graph Runtime → 执行
```

---

## 3. 模块结构

```text
agent
├── __init__.py
│
├── agent.py
├── config.py
├── context.py
└── builder.py
```

---

## 4. AgentConfig 模型

AgentConfig 用于定义 Agent 的静态配置与能力声明。其职责是：**描述 Agent 可运行能力与基础运行参数**

```python
class AgentConfig(BaseModel):
    # identity
    name: str
    description: str | None = None

    # runtime core
    llm_config: LLMConfig
    system_prompt: str | None = None

    # strategy selector (deferred execution layer)
    strategy: str

    # capability declaration (not execution)
    kb_list: list[str] = []
    skill_list: list[str] = []
```

| 字段          | 语义                       |
| ------------- | -------------------------- |
| name          | Agent 标识                 |
| description   | Agent 描述信息             |
| llm_config    | LLM 运行配置               |
| system_prompt | LLM prompt 注入内容        |
| strategy      | 策略标识（仅声明，不执行） |
| kb_list       | 可访问知识库列表（声明）   |
| skill_list    | 可使用技能列表（声明）     |

> 📌**REMARK:**
> AgentConfig 仅描述能力边界，不参与运行时能力选择与执行。
> ❌ 不允许：AgentConfig 决定 KB/Skill 执行逻辑
> ✅ 允许：AgentConfig 声明 KB/Skill 可用范围

---

## 5. AgentContext 模型

AgentContext 用于描述 Agent 单次运行的上下文信息。其职责是：**承载运行级共享信息**

```python
class AgentContext(BaseModel):

    session_id: str
    user_id: str | None = None

    metadata: dict = {}
```

AgentContext 生命周期与单次 invoke / stream 调用绑定。

```text
invoke start → context create → graph execution → destroy
```

---

## 6. Agent 实体

Agent 是 Echo-Agent 的运行实体，用于封装 Graph 并提供统一执行入口。Agent 负责：

* 持有 AgentConfig
* 持有 Graph
* 提供统一执行接口
* 注入运行上下文
* 转发执行请求到 Graph Runtime


```python
class Agent:
    def __init__(
        self,
        config: AgentConfig,
        graph: Graph
    ):
        self.config = config
        self.graph = graph

    # invoke
    # Message → Graph Input → Graph.invoke → Output → Message
    async def invoke(
        self,
        message: Message,
        context: AgentContext | None = None
    ) -> Message:
        ...

    # stream
    # Message → Graph Stream → Event Stream → Output Stream
    async def stream(
        self,
        message: Message,
        context: AgentContext | None = None
    ):
        ...
```

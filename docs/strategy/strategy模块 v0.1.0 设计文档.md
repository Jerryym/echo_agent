# echo-agent v0.1.0 Strategy 模块设计

## 1. 模块定位

Strategy 模块用于封装 Agent 的推理策略。不同类型的智能体通常采用不同的推理流程，例如：

* ReAct
* Plan-Execute
* Reflection
* Supervisor
* Multi-Agent

这些推理流程本质上都是基于 LangGraph 构建的工作流（Graph）。Strategy 模块负责将这些常见推理流程封装为可复用的 Subgraph，并以统一接口提供给 Agent 使用。

Strategy 模块关注**如何思考（How to Think）**，而不是**思考什么（What to Think）**。因此，Strategy 不包含任何业务逻辑，而是提供通用的推理模式。

---

## 2. 模块职责

Strategy 模块主要负责：

* 封装通用 Agent 推理策略
* 基于 Graph 构建可复用 Subgraph
* 定义策略所需的 Prompt
* 定义策略运行所需的 Schema
* 为 Agent 提供统一的 Strategy 接口

Strategy 模块不负责：

* Agent 生命周期管理
* Runtime 能力管理
* Tool 管理
* Memory 管理
* Checkpoint 管理
* Store 管理
* 业务 Prompt
* Agent 配置管理

---

# 3. 模块关系

Strategy 在整个框架中的位置如下：

```text
                 Agent
                   │
          选择推理策略（Strategy）
                   │
        ┌──────────┴──────────┐
        │                     │
     ReAct               Plan-Execute
        │                     │
        └──────────┬──────────┘
                   │
               Subgraph
                   │
               Runtime
```

各模块职责如下：


| 模块     | 职责                |
| ---------- | --------------------- |
| Agent    | 选择并使用 Strategy |
| Runtime  | 提供运行时能力      |
| Graph    | 提供工作流构建能力  |
| Prompt   | 提供推理规则        |
| Strategy | 封装推理流程        |

其中：

* Strategy 基于 Graph 构建 Subgraph。
* Runtime 为 Strategy 提供运行环境。
* Agent 负责组合 Runtime 与 Strategy。

---

# 4. 生命周期

Strategy 生命周期依附于 Agent，Agent 初始化时完成 Strategy 构建。Strategy 在运行过程中保持无状态，其运行状态由 Runtime 管理。

```text
Agent 创建
      │
      ▼
创建 Strategy
      │
      ▼
构建 Subgraph
      │
      ▼
等待 Runtime 执行
```


---

# 5. 模块组成

一个 Strategy 由以下部分组成：

* Prompt
* Node
* Graph
* Schema

最终构建为一个可复用的 Subgraph。

```text
Strategy
│
├── Prompt
├── Node
├── Schema
└── Graph
        │
        ▼
    Compiled Subgraph
```

---

# 6. Schema

每个 Strategy 可以定义自身所需的数据结构。

包括：

* Input Schema
* State Schema
* Output Schema
* Context Schema

所有 Schema 均继承于框架提供的基础模型。

```text
BaseInput
    ▲
StrategyInput

BaseState
    ▲
StrategyState

BaseOutput
    ▲
StrategyOutput

BaseContext
    ▲
StrategyContext
```

不同 Strategy 可以扩展不同字段，而 Runtime 始终面向 Base Schema 工作。

---

# 7. Prompt

Strategy Prompt 用于定义推理模式，Prompt 应满足以下原则：

* 通用
* 与业务无关
* 不依赖具体 Tool
* 不依赖具体 Agent
* 不依赖 Runtime

例如：

ReAct Prompt：

* Thought
* Action
* Observation

Plan-Execute Prompt：

* Plan
* Execute
* Replan

Strategy Prompt 仅描述推理流程，不描述业务角色。

---

# 8. Graph

每个 Strategy 最终构建为一个 LangGraph Subgraph，Parent Graph 将 Strategy 作为普通 Node 使用，Strategy 内部结构对 Parent Graph 完全透明。

```text
Root Graph

START
   │
Runtime Init
   │
Strategy(Subgraph)
   │
Runtime Cleanup
   │
 END
```


---

# 9. BaseStrategy

所有 Strategy 均继承 BaseStrategy，BaseStrategy 提供统一接口，如下：

```python
class BaseStrategy(ABC):

    input_schema: type[BaseInput]
    state_schema: type[BaseState]
    output_schema: type[BaseOutput]
    context_schema: type[BaseContext]

    @abstractmethod
    def build(self):
        """构建 Strategy Subgraph"""

    @abstractmethod
    def as_node(self):
        """以 Node 形式加入 Parent Graph"""

    @abstractmethod
    def as_subgraph(self):
        """获取 Strategy Subgraph"""
```

其中：

* `build()` 负责构建 Strategy。
* `as_node()` 用于作为 Parent Graph 的节点使用。
* `as_subgraph()` 用于获取完整 Subgraph（预留扩展）。

---

# 10. Strategy Factory

Strategy 模块通过 Factory 创建具体策略。

```text
StrategyFactory
        │
        ▼
 StrategyType
        │
 ┌──────┴──────┐
 │             │
ReAct   PlanExecute
```

Agent 仅依赖 StrategyFactory，而不依赖具体 Strategy。

示例：

```python
strategy = StrategyFactory.create(
    StrategyType.REACT
)
```

---

# 11. v0.1.0 实现范围

v0.1.0 计划实现两种基础推理策略：


| Strategy     | 说明                                             |
| -------------- | -------------------------------------------------- |
| ReAct        | 基于 Thought → Action → Observation 的推理流程 |
| Plan-Execute | 基于 Plan → Execute 的规划执行流程              |

两种 Strategy 均遵循统一抽象，实现 BaseStrategy 接口，并作为可复用 Subgraph 提供给 Agent 使用。

---

## 12. 后续规划

Strategy 模块将保持统一抽象，后续新增策略无需修改 Agent 或 Runtime，仅需实现 `BaseStrategy` 接口并注册至 `StrategyFactory`。

后续计划支持但不属于 v0.1.0 范围的策略包括：

* Reflection
* ReAct + Reflection
* Supervisor
* Multi-Agent
* Tree Search
* Deep Research

这些策略均将复用当前 Strategy 模块的基础抽象，以 Subgraph 的形式集成到框架中。

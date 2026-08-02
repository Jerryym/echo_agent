# Runtime 模块 v0.1.1 设计文档

## 1. 版本说明


| 项目     | 内容                                                        |
| ---------- | ------------------------------------------------------------- |
| 版本     | v0.1.1                                                      |
| 状态     | 已实现（RuntimeConfig 已接入）；RuntimeContext 已定义未接入 |
| 依赖     | LangGraph`BaseCheckpointSaver` / `BaseStore`                |
| 上一版本 | v0.1.0                                                      |

> v0.1.0 中未变更的部分（模块定位、Config/Context 分离原则、LangGraph 对齐原则）仍适用，本文档仅描述 v0.1.1 相对 v0.1.0 的实现变更。概念性补充材料参见 [Runtime.md](Runtime.md)、[Persistence.md](Persistence.md)。

### 1.1 v0.1.1 变更摘要

v0.1.1 将 Runtime 从设计草案落地为 Agent / Graph 编译链中的实际组件，核心变化如下：


| 变更项                | v0.1.0（设计）               | v0.1.1（实现）                                         |
| ----------------------- | ------------------------------ | -------------------------------------------------------- |
| 模块文件              | `config.py` / `context.py`   | `runtime_config.py` / `runtime_context.py`             |
| `RuntimeConfig` 基类  | Pydantic`BaseModel`          | **`@dataclass`**                                       |
| `checkpointer`        | 必填                         | **可选**（默认 `None`）                                |
| `RuntimeContext`      | 含`thread_id` 可选、自动回退 | `thread_id` / `session_id` **均必填**                  |
| Agent 集成            | 设计描述                     | Agent 构造时持有`RuntimeConfig`，编译 RootGraph        |
| session 映射          | 经`RuntimeContext`           | Agent 直接将`session_id` → `RunnableConfig.thread_id` |
| `RuntimeContext` 使用 | 单次 invoke 绑定             | **尚未接入** Agent 调用链                              |

---

## 2. 模块定位（v0.1.1 补充）

Runtime 模块是 echo-agent 对 LangGraph Runtime **持久化能力** 的最小抽象层，v0.1.1 当前聚焦 **Persistence 子集**（checkpointer / store）。

**负责：**

- 定义构建期运行时能力配置（`RuntimeConfig`）
- 定义运行期上下文模型（`RuntimeContext`，v0.1.1 仅模型层）
- 为 `RootGraph.compile()` 提供 checkpointer / store 注入入口

**不负责：**

- Graph 结构定义与编译逻辑（Graph 模块）
- invoke / stream 调用封装（Agent 模块）
- thread_id / checkpoint_id 的运行时赋值（当前由 Agent 直接构建 `RunnableConfig`）
- Checkpointer / Store 的具体实现（调用方注入 LangGraph 实现）
- Interrupt / Resume / Human-in-the-loop 编排（Strategy 层语义，Runtime 未封装）

---

## 3. 设计原则（v0.1.1 补充）

### 3.1 构建期注入原则

`RuntimeConfig` 仅在 **Agent 构建 / RootGraph 编译** 阶段消费，不参与单次 invoke 的参数传递：

```text
RuntimeConfig（构建期）
    ↓
RootGraph.compile(runtime_config)
    ↓
CompiledStateGraph（含 checkpointer / store）
    ↓
Agent._compiled_graph
```

### 3.2 thread 由调用方标识原则

v0.1.1 中 LangGraph `thread_id` 由 Agent 在每次 invoke / stream 时通过 `session_id` 参数写入 `RunnableConfig`，**不经过 `RuntimeContext`**：

```python
RunnableConfig(configurable={"thread_id": session_id})
```

### 3.3 最小 Persistence 原则

v0.1.1 仅透传 LangGraph 原生 checkpointer / store，不封装 Thread 生命周期、Checkpoint 选择或 State History 遍历逻辑。Debug 场景下 Agent 直接调用 `CompiledStateGraph.get_state()` / `get_state_history()`。

---

## 4. 模块结构

```text
echo_agent/core/runtime/
├── __init__.py              # 导出 RuntimeConfig, RuntimeContext
├── runtime_config.py        # 构建期配置
└── runtime_context.py       # 运行期上下文（模型已定义，未接入）
```

对外导出：

```python
from echo_agent.core.runtime import RuntimeConfig, RuntimeContext
```

---

## 5. RuntimeConfig

### 5.1 模型定义

```python
@dataclass
class RuntimeConfig:
    checkpointer: BaseCheckpointSaver | None = None
    store: BaseStore | None = None
```

### 5.2 v0.1.0 → v0.1.1 变更


| 项             | v0.1.0              | v0.1.1           |
| ---------------- | --------------------- | ------------------ |
| 实现方式       | Pydantic`BaseModel` | `@dataclass`     |
| `checkpointer` | 必填                | 可选，默认`None` |
| `store`        | 可选                | 可选，默认`None` |

### 5.3 字段说明


| 字段           | 类型                         | 默认值 | 说明                                       |
| ---------------- | ------------------------------ | -------- | -------------------------------------------- |
| `checkpointer` | `BaseCheckpointSaver | None` | `None` | Graph State 持久化；注入 LangGraph compile |
| `store`        | `BaseStore | None`           | `None` | 跨 thread 数据存储；注入 LangGraph compile |

### 5.4 使用约束

- 不包含 `thread_id`、`checkpoint_id`、`session_id`
- 不参与运行时状态管理
- 生命周期与 Agent 实例绑定（构造时 compile 一次）

### 5.5 典型配置

```python
from langgraph.checkpoint.memory import InMemorySaver

runtime_config = RuntimeConfig(checkpointer=InMemorySaver())
```

测试与开发场景使用内存 Checkpointer；生产环境由调用方注入 Postgres / Redis 等 LangGraph 兼容实现。

### 5.6 编译注入路径

```python
# RootGraph.compile()
return self.build().compile(
    checkpointer=runtime_config.checkpointer,
    store=runtime_config.store,
)
```

`checkpointer=None` 时，CompiledGraph 不支持跨 Run 状态恢复；每次 invoke 独立运行。

---

## 6. RuntimeContext

### 6.1 模型定义

```python
class RuntimeContext(BaseModel):
    thread_id: str
    session_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.2 字段说明


| 字段         | 说明                             |
| -------------- | ---------------------------------- |
| `thread_id`  | LangGraph Persistence 作用域标识 |
| `session_id` | 业务会话标识                     |
| `metadata`   | 运行时扩展信息                   |

### 6.3 v0.1.0 → v0.1.1 变更


| 项          | v0.1.0 设计                | v0.1.1 实现              |
| ------------- | ---------------------------- | -------------------------- |
| `thread_id` | 可选，默认等于`session_id` | **必填**，无自动回退逻辑 |
| 接入 Agent  | 单次 invoke 绑定           | **未接入**               |

### 6.4 当前状态

`RuntimeContext` 已在模块中定义并导出，但 v0.1.1 **没有任何调用方** 实例化或传递该模型。Agent 直接使用 `session_id` 字符串参数。

预期 v0.1.2+ 接入方式：

```text
RuntimeContext(session_id, thread_id, metadata)
    ↓
Agent._build_runnable_config(context)
    ↓
RunnableConfig(configurable={thread_id, ...metadata})
```

---

## 7. 与上层模块的关系

### 7.1 Agent 模块

```text
Agent(agent_config, runtime_config, graph)
    ↓
graph.compile(runtime_config) → _compiled_graph
    ↓
invoke(session_id, input)
    ↓
RunnableConfig(configurable={"thread_id": session_id})
    ↓
_compiled_graph.invoke(graph_input, runnable_config)
```


| 阶段   | Runtime 参与方式                                          |
| -------- | ----------------------------------------------------------- |
| 构建期 | `RuntimeConfig` → `RootGraph.compile()`                  |
| 运行期 | `session_id` → `thread_id`（绕过 `RuntimeContext`）      |
| Debug  | `get_state(session_id)` / `get_state_history(session_id)` |

### 7.2 Graph 模块


| 类          | 与 Runtime 的关系                                   |
| ------------- | ----------------------------------------------------- |
| `RootGraph` | `compile(runtime_config)` 注入 checkpointer / store |
| `SubGraph`  | `compile()` 无 Runtime 参数；持久化依赖父图         |

Strategy 子图不单独持有 Checkpointer，同一 Agent session 的状态由 RootGraph 层统一管理。

### 7.3 Strategy 模块

Strategy 内部的 `ReActContext`（`max_steps` / `retry_max_count`）属于 **Graph Context Schema**，与 Runtime 模块的 `RuntimeContext` **无关**。二者命名相似但分属不同层次：


| 模型             | 层次                | 注入方式                        |
| ------------------ | --------------------- | --------------------------------- |
| `RuntimeContext` | Agent / Runtime 层  | 预期经 RunnableConfig（未接入） |
| `ReActContext`   | Strategy / Graph 层 | LangGraph`context_schema`       |

---

## 8. Persistence 语义（v0.1.1 实际行为）

### 8.1 Thread 与 session_id

v0.1.1 中 **`session_id` 等价于 `thread_id`**（1:1 映射，由 Agent 硬编码）。同一 `session_id` 的多轮 invoke 共享 Checkpoint 历史。

```text
session_id="react_test_session"
    ↓
thread_id="react_test_session"
    ↓
Checkpoint History（Run 1, Run 2, ...）
```

### 8.2 Checkpoint 读取

Agent Debug API 支持可选 `checkpoint_id` 回溯：

```python
agent.get_state(session_id)
agent.get_state(session_id, checkpoint_id="...")
agent.get_state_history(session_id)
```

底层均构建 `RunnableConfig(configurable={...})` 转发至 `CompiledStateGraph`。

### 8.3 store 字段

v0.1.1 已透传至 `RootGraph.compile(store=...)`，但当前测试与 Agent 代码 **未使用** Store 能力。

---

## 9. RuntimeConfig vs RuntimeContext


| 对比项          | RuntimeConfig                 | RuntimeContext                    |
| ----------------- | ------------------------------- | ----------------------------------- |
| 生命周期        | 构建期（Agent 构造）          | 运行期（单次 invoke，**未接入**） |
| 语义            | 系统持久化能力声明            | 执行实例上下文                    |
| 是否含 thread   | ❌                            | ✔（`thread_id` 必填）            |
| 是否含 session  | ❌                            | ✔（`session_id` 必填）           |
| 影响 checkpoint | ✔（编译期绑定 checkpointer） | 预期 ✔（经 thread_id，未实现）   |
| 当前使用状态    | **已接入**                    | **仅模型定义**                    |

---

## 10. 已知限制


| 限制                         | 说明                                                         |
| ------------------------------ | -------------------------------------------------------------- |
| `RuntimeContext` 未接入      | Agent 不使用该模型，session 管理分散在 Agent API             |
| `session_id` 即 `thread_id`  | 无法独立配置业务 session 与 persistence thread               |
| 无 Runtime 级 Interrupt 封装 | Human-in-the-loop 由 Strategy State 语义表达，非 Runtime API |
| `store` 未使用               | 字段已透传但无调用方配置                                     |
| `checkpointer=None` 静默降级 | 无 checkpointer 时不报错，但丢失多轮状态                     |
| 无统一 Runtime 入口          | Agent 直接操作 CompiledGraph，Runtime 模块仅提供数据模型     |

---

## 11. 后续版本候选（v0.1.2+）

- [ ]  Agent 接入 `RuntimeContext`，统一 session / thread / metadata 传递
- [ ]  `thread_id` 与 `session_id` 解耦（支持 1:N 或映射配置）
- [ ]  Runtime 级 Interrupt / Resume API 封装
- [ ]  Store 使用规范与 Strategy Memory 接入指南
- [ ]  `RuntimeConfig` 校验（如无 checkpointer 时 warn）
- [ ]  生产 Checkpointer 配置示例（PostgresSaver 等）

---

## 12. 验证结论

v0.1.1 已通过以下手动场景验证：

- `RuntimeConfig(checkpointer=InMemorySaver())` + Agent 多轮 invoke 状态连续
- `agent.get_state(session_id)` 读取当前 Checkpoint State
- `agent.get_state_history(session_id)` 读取状态变更历史
- 不同 `session_id` 对应独立 Thread，状态互不干扰
- `RootGraph.compile(runtime_config)` 正确透传 checkpointer 至 CompiledGraph

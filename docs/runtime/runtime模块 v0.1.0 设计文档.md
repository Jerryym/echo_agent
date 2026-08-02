# Runtime 模块 v0.1.0 设计文档

## 1. 模块定位

Runtime 模块是 echo-agent 对 LangGraph Runtime 的最小抽象封装层，位于 Agent 与 LangGraph 执行层之间，提供基础运行时配置与运行时上下文能力。其核心目标是：**为 Agent 提供统一、可控、可扩展的运行环境入口，同时隔离 LangGraph 原生运行时细节。**

---

## 2. 设计原则

### 2.1 最小运行闭环原则

v0.1 Runtime 仅保证：

> Agent 能够基于 LangGraph 完成一次带 checkpoint 的可持续运行

不引入额外运行时能力建模。

---

### 2.2 Config / Context 分离原则

Runtime 明确分离两类概念：

| 类型           | 语义               |
| -------------- | ------------------ |
| RuntimeConfig  | 系统级运行能力配置 |
| RuntimeContext | 单次运行实例上下文 |

---

### 2.3 LangGraph 对齐原则

Runtime 不重新实现 LangGraph Runtime 语义，仅做结构封装与上层解耦。

---

## 3. 模块结构

```text
runtime/
├── config.py
└── context.py
```

---

## 4. RuntimeConfig（运行时配置）

### 4.1 定义

RuntimeConfig 用于描述 Agent 在构建与执行时所依赖的运行时能力配置。

其生命周期属于：

> Agent 构建阶段（compile / initialization）

---

### 4.2 职责

RuntimeConfig 负责定义：

* checkpoint 持久化能力
* state 存储能力（预留）

不参与：

* session 管理
* thread 生命周期
* 单次运行状态

---

### 4.3 数据结构

```python
class RuntimeConfig(BaseModel):
    """
    Runtime 系统能力配置（构建期）
    """

    checkpointer: BaseCheckpointSaver
    store: BaseStore | None = None
```

---

### 4.4 字段说明

| 字段         | 类型                | 说明                                |
| ------------ | ------------------- | ----------------------------------- |
| checkpointer | BaseCheckpointSaver | LangGraph checkpoint 持久化实现     |
| store        | BaseStore           | 跨 thread 数据存储能力（v0.1 可选） |

---

### 4.5 设计约束

* 不包含 thread_id
* 不包含 checkpoint_id
* 不包含 session 信息
* 不参与运行时状态管理

---

## 5. RuntimeContext（运行时上下文）

### 5.1 定义

RuntimeContext 用于描述一次 Agent 执行实例的运行上下文。

其生命周期属于：

> 单次 graph.invoke / stream 调用周期

---

### 5.2 职责

RuntimeContext 负责：

* 标识本次运行所属 session
* 提供 thread 作用域信息
* 承载运行时附加 metadata

---

### 5.3 数据结构

```python
class RuntimeContext(BaseModel):
    """
    Runtime 执行上下文（运行期）
    """

    session_id: str
    thread_id: str | None = None

    metadata: dict = {}
```

---

### 5.4 字段说明

| 字段       | 类型 | 说明                                                    |
| ---------- | ---- | ------------------------------------------------------- |
| session_id | str  | 外部会话标识（通常来自前端）                            |
| thread_id  | str  | LangGraph persistence scope 标识（默认等于 session_id） |
| metadata   | dict | 运行时扩展信息                                          |

---

### 5.5 thread_id 解析规则

RuntimeContext 中 thread_id 遵循以下规则：

```text
if thread_id is None:
    thread_id = session_id
```

### 设计含义

* session_id 表示业务会话边界
* thread_id 表示 LangGraph 状态边界
* 默认情况下二者保持一致（1:1 映射）

---

### 5.6 设计约束

* 不负责 thread 生命周期管理
* 不包含 checkpoint 选择逻辑
* 不参与 persistence 实现
* 不引入 runtime routing 或分发逻辑

---

## 6. RuntimeConfig vs RuntimeContext

| 对比项              | RuntimeConfig | RuntimeContext |
| ------------------- | ------------- | -------------- |
| 生命周期            | 构建期        | 运行期         |
| 语义                | 系统能力配置  | 执行实例上下文 |
| 是否包含 thread     | ❌ | ✔（可选）      |
| 是否影响 checkpoint | ✔             | ✔（间接）      |
| 是否跨 session      | ✔             | ❌              |

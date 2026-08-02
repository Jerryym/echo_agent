# ReAct Strategy v0.1.0 设计文档

## 1. 版本说明

| 项目     | 内容                                                                                         |
| -------- | -------------------------------------------------------------------------------------------- |
| 版本     | v0.1.0                                                                                       |
| 状态     | 已实现，手动测试通过                                                                         |
| 所属模块 | Strategy（参见 `[strategy模块 v0.1.1 设计文档.md](../strategy模块%20v0.1.1%20设计文档.md)`） |
| 依赖     | Graph SubGraph、LLM v0.1.2、Tool v0.1.0                                                      |

本文档描述 ReAct 策略的专属设计，不重复 Strategy 模块抽象（BaseStrategy / Factory）的通用内容。

---

## 2. 设计目标

ReAct Strategy 实现 **Reason → Action → Observation → … → Final** 循环推理模式，目标如下：

| 目标                   | 实现方式                                                               |
| ---------------------- | ---------------------------------------------------------------------- |
| 推理与工具选择分离     | `ReasonNode` 评估状态；`ActionNode` 负责选工具                         |
| 工具选择与参数验证分离 | Action 两阶段：`invoke(tool_list)` + `invoke_structured(ActionResult)` |
| 工具执行隔离           | `ToolNode` + `ToolExecutor`，Strategy 不直接调用 handler               |
| 人机协作               | 参数缺失时进入 `human_in_the_loop`，写入 `ToolCall.missing_args`       |
| 可观测失败             | 非法工具 / 执行失败 / 步数超限 / 重试超限均有明确终止路径              |
| 最终回答独立生成       | `FinalNode` 基于 observations 生成自然语言响应                         |

---

## 3. 整体流程

### 3.1 子图结构

```text
START
  ↓
reason ──────────────────────────────┐
  ↓ (in_progress)                    │ (completed / failed /
action                                │  human_in_the_loop /
  ├─ tool_calls ─→ tool ─→ reason ────┘  step/retry limit)
  └─ else ───────→ final
                    ↓
                   END
```

### 3.2 节点职责

| Node         | 职责                       | LLM 调用                                                |
| ------------ | -------------------------- | ------------------------------------------------------- |
| `ReasonNode` | 评估任务状态、信息充分性   | `invoke_structured(ReasonResult)`                       |
| `ActionNode` | 选工具 + 验参数            | `invoke(tool_list)` + `invoke_structured(ActionResult)` |
| `ToolNode`   | 执行工具、写回 ToolMessage | 无                                                      |
| `FinalNode`  | 生成最终回答               | `invoke()`                                              |

### 3.3 单步循环时序

```text
1. ReasonNode
   输入：user input + messages + observations
   输出：reasoning, task_status (in_progress | completed)

2. ActionNode（task_status=in_progress 时）
   Step-1：选工具 → tool_calls
   Step-2：验参数 → ready | missing_parameters
   输出：tool_calls, messages(AIMessage+tool_calls), task_status

3. ToolNode（tool_calls 非空时）
   输出：tool_results, messages(ToolMessage)

4. 回到 ReasonNode，observations 来自 tool_results

5. FinalNode（终止条件触发时）
   输出：response, messages(AIMessage)
```

---

## 4. Schema 设计

### 4.1 ReActInput

```python
class ReActInput(BaseInput):
    input: UserInput | dict[str, Any] | str
    messages: Sequence[BaseMessage] = []
```

SubGraph 入口输入，从 Parent State 映射或直接传入。

### 4.2 ReActState

```python
class ReActState(BaseState):
    reasoning: str = ""
    task_status: Literal["in_progress", "human_in_the_loop", "completed", "failed"] = "in_progress"
    observations: list[str] = Field(default_factory=list)
    step_count: int = Field(default=0)
    retry_count: int = Field(default=0)
```

继承 `BaseState`，额外包含 `messages` / `tool_calls` / `tool_results` / `response` 等基类字段。

### 4.3 task_status 状态机

```text
                    ┌─────────────────┐
                    │   in_progress   │←──────────────────┐
                    └────────┬────────┘                   │
                             │                             │
              Reason: completed                            │
              Action: no tool_calls                        │
                             ↓                             │
                    ┌─────────────────┐                   │
                    │    completed    │                   │
                    └────────┬────────┘                   │
                             ↓                             │
                          final                           │
                                                          │
              Action: missing_parameters                  │
                             ↓                             │
                    ┌─────────────────┐                   │
                    │human_in_the_loop│                   │
                    └────────┬────────┘                   │
                             ↓                             │
                          final                           │
                                                          │
              Action: invalid tools                     │
              Reason: retry limit (tool error)            │
              Reason/Route: step/retry limit              │
                             ↓                             │
                    ┌─────────────────┐                   │
                    │     failed      │                   │
                    └────────┬────────┘                   │
                             ↓                             │
                          final                           │
                                                          │
              Action: ready → tool_calls                  │
                             ↓                             │
                          tool ────────────────────────────┘
```

| 状态                | 设置者                                                   | 含义                 |
| ------------------- | -------------------------------------------------------- | -------------------- |
| `in_progress`       | 初始 / Action ready                                      | 任务进行中，继续循环 |
| `completed`         | Reason / Action（无 tool_calls）                         | 任务完成，进入 Final |
| `human_in_the_loop` | Action（missing_parameters）                             | 需用户补充参数       |
| `failed`            | Action（非法工具）/ Reason（重试超限）/ 路由（步数超限） | 任务失败，进入 Final |

### 4.4 ReActOutput

```python
class ReActOutput(BaseOutput):
    response: str
    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
```

SubGraph 结束时提取，`to_parent_state()` 映射为 Parent State 的 `response` + `messages`。

### 4.5 ReActContext

```python
class ReActContext(BaseContext):
    max_steps: int = Field(default=10)
    retry_max_count: int = Field(default=3)
```

| 字段              | 消费者                          | 说明                             |
| ----------------- | ------------------------------- | -------------------------------- |
| `max_steps`       | `_reason_router`                | `step_count >= max_steps` 时终止 |
| `retry_max_count` | `ReasonNode._handle_tool_error` | 工具失败重试超限判定             |

> v0.1.0 中 `ReActStrategy._max_steps` / `_retry_max_count` 与 `ReActContext` 默认值重复，路由实际读取 Strategy 实例字段，Context 字段仅在 ReasonNode 工具错误处理中使用。

---

## 5. Node 设计

### 5.1 ReasonNode

**输入：**

```python
{
    "input": state.input,
    "messages": state.messages,
    "observations": state.observations + [tr.result for tr in state.tool_results],
}
```

**结构化输出** `ReasonResult`**：**

| 字段                 | 取值                      | 说明             |
| -------------------- | ------------------------- | ---------------- |
| `reasoning`          | str                       | 当前任务状态评估 |
| `information_status` | sufficient / insufficient | 信息是否充分     |
| `task_status`        | in_progress / completed   | 任务是否完成     |

**特殊逻辑 — 工具失败处理：**

- 若 `state.tool_results` 中存在 `success=False`，跳过 LLM 调用
- `retry_count += 1`；若 `retry_count >= context.retry_max_count`，设置 `task_status=failed`

**task_status 写入规则：**

- 仅当当前 `state.task_status == "in_progress"` 时，Reason 才可写入 `task_status`
- 避免覆盖 Action 设置的 `human_in_the_loop` / `failed`

### 5.2 ActionNode

Action 分为两阶段，对应两个独立 Prompt 和 LLM 调用模式。

#### Step-1：工具选择

```python
self._llm_client.invoke(
    prompt=tool_selection_prompt,
    user_input=input,
    history=state.messages,
    tool_list=self._tool_list,
)
```

- 无 tool_calls → `task_status=completed`，视为无需工具即可结束
- 有 tool_calls → 进入 Step-2

#### Step-2：参数验证

```python
self._llm_client.invoke_structured(
    prompt=tool_validation_prompt,
    user_input={
        "input": state.input,
        "reasoning": state.reasoning,
        "tool_calls": [tc.model_dump() for tc in tool_calls],
    },
    history=state.messages,
    schema=ActionResult,
    strict=True,
)
```

**结构化输出** `ActionResult`**：**

| 字段                 | 说明                              |
| -------------------- | --------------------------------- |
| `status`             | `ready` / `missing_parameters`    |
| `missing_parameters` | `{tool_call_id: [arg_name, ...]}` |

#### 结果处理

| 条件                        | 行为                                                           |
| --------------------------- | -------------------------------------------------------------- |
| 工具名不在 registry         | `task_status=failed`, `retry_count+=1`                         |
| `status=ready`              | `tool_calls` 写入 State，`messages` 追加 AIMessage(tool_calls) |
| `status=missing_parameters` | `task_status=human_in_the_loop`，`ToolCall.missing_args` 填充  |

### 5.3 ToolNode

定义于 Tool 模块，ReAct 中作为标准 Graph Node 注册。

- 读取 `state.tool_calls`
- 逐个 `ToolExecutor.execute()`
- 返回 `tool_results` + `ToolMessage` 列表

### 5.4 FinalNode

**输入：**

```python
{
    "input": state.input,
    "messages": state.messages,
    "reasoning": state.reasoning,
    "observations": state.observations,
}
```

**输出：**

```python
{
    "response": response.content,
    "messages": [AIMessage(content=response.content)],
}
```

支持透传 `RunnableConfig` 至 `LLMClient.invoke(..., config=config)`，便于 stream 场景。

---

## 6. 路由规则

### 6.1 _reason_router

| 条件                                 | 目标     |
| ------------------------------------ | -------- |
| `task_status == "completed"`         | `final`  |
| `task_status == "human_in_the_loop"` | `final`  |
| `task_status == "failed"`            | `final`  |
| `step_count >= max_steps`            | `final`  |
| `retry_count >= max_retry_count`     | `final`  |
| 否则                                 | `action` |

### 6.2 _action_router

| 条件                                                    | 目标    |
| ------------------------------------------------------- | ------- |
| `state.tool_calls` 非空                                 | `tool`  |
| `task_status in (completed, failed, human_in_the_loop)` | `final` |
| 否则                                                    | `final` |

---

## 7. Prompt 设计

Prompt 文件位于 `echo_agent/core/strategy/react/prompt/`，各 Node 职责边界如下：

| 文件                 | 使用者            | 核心约束                                  |
| -------------------- | ----------------- | ----------------------------------------- |
| `reasoning.md`       | ReasonNode        | 只推理，不选工具、不执行、不生成最终回答  |
| `tool_selection.md`  | ActionNode Step-1 | 只生成 tool_calls，不执行；允许参数不完整 |
| `tool_validation.md` | ActionNode Step-2 | 只验证参数完整性，不修改 tool_calls       |
| `final.md`           | FinalNode         | 只生成最终回答，不推理、不调用工具        |

`action-old.md` 为历史 Prompt，**不再使用**。

### 7.1 Prompt 分工原则

```text
Reason     → 「要不要继续？信息够吗？」
Action-1   → 「选什么工具？参数可以先不完整」
Action-2   → 「参数齐了吗？缺什么？」
Final      → 「基于已有信息回答用户」
```

Validation Prompt 明确禁止：选工具、改参数、填缺省值、判断是否需要人机交互（后者由 ActionNode 代码根据 `status` 决定）。

---

## 8. ReActStrategy 与 ReActNode

### 8.1 构造

```python
ReActStrategy(
    llm_config: LLMConfig,
    tool_registry: ToolRegistry,
)
```

内部创建 `ToolExecutor(tool_registry)`，ActionNode 接收 `tool_registry.get_tools()`。

### 8.2 build()

注册四节点与边（见 §3.1），返回未编译 `SubGraph(name="ReAct", ...)`。

### 8.3 两种接入方式

**方式一：子图节点（推荐，当前测试默认）**

```python
StrategyFactory.create_as_subgraph(StrategyType.REACT, ...)
→ RootGraph.add_subgraph("ReAct", compiled)
```

**方式二：包装 Node**

```python
StrategyFactory.create_as_node(StrategyType.REACT, ...)
→ ReActNode.run() → strategy.invoke(state, context)
```

`ReActNode` 通过 `to_strategy_input` / `to_parent_state` 完成 Parent State 映射。

---

## 9. 与外部模块的边界

| 模块       | ReAct 中的使用                                                        |
| ---------- | --------------------------------------------------------------------- |
| **LLM**    | Reason / Action 验证 / Final 分别使用 `invoke_structured` 与 `invoke` |
| **Tool**   | Action 绑定 schema；ToolNode 执行；`missing_args` 供人机协作          |
| **Graph**  | SubGraph 构建；条件边路由；State Patch 更新                           |
| **Model**  | `UserInput` 作为输入载体                                              |
| **Common** | `debug_print_messages` 调试消息历史                                   |

---

## 10. 已知限制

| 限制                             | 说明                                                                               |
| -------------------------------- | ---------------------------------------------------------------------------------- |
| `observations` 字段未自动填充    | ReasonNode 从 `tool_results` 构建 observations 输入，但不写回 `state.observations` |
| 步数上限硬编码                   | `_max_steps=10` 写在 `ReActStrategy`，未从外部配置                                 |
| `human_in_the_loop` 无恢复路径   | 进入该状态后直接 Final，未实现用户补参后继续循环                                   |
| Reason 忽略 `information_status` | 结构化输出含该字段，但代码未据此路由                                               |
| 无并行工具调用策略               | 多 tool_calls 由 ToolNode 串行执行                                                 |
| Plan 能力缺失                    | 无显式 Plan 阶段，依赖 Reason 隐式规划                                             |

---

## 11. 后续版本候选（v0.1.1+）

- [ ] `human_in_the_loop` 补参后续跑通（用户输入 → 继续 Action）
- [ ] `observations` 写回 State，支持持久化观察历史
- [ ] `information_status=insufficient` 驱动路由
- [ ] 步数 / 重试上限统一由 `ReActContext` 或构造参数注入
- [ ] 工具并行执行
- [ ] 去除 debug print，改用统一日志

---

## 12. 验证结论

v0.1.0 已通过 `tests/test_react_agent.py` 及 `tests/docs/ReAct Agent 测试案例文档.md` 中的场景验证：

- 单工具一次调用结束
- 多工具链式依赖执行
- 工具结果驱动下一步 Reason
- 任务完成判断与 Final 输出
- 多轮 Checkpoint 会话
- stream 模式 FinalNode token 输出

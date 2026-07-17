# ReAct Strategy v0.1.1 设计文档

## 1. 版本说明

| 项目     | 内容                                                                                         |
| -------- | -------------------------------------------------------------------------------------------- |
| 版本     | v0.1.1                                                                                       |
| 状态     | 已实现（含 HITL 补参 / 审批闭环）                                                            |
| 所属模块 | Strategy（参见 `[strategy模块 v0.1.1 设计文档.md](../strategy模块%20v0.1.1%20设计文档.md)`） |
| 依赖     | Graph SubGraph、LLM、Tool、Runtime HITLSubgraph                                              |
| 上一版本 | [v0.1.0](react%20v0.1.0%20设计文档.md)                                                       |

本文档描述 **当前代码实现** 的 ReAct 策略专属设计，不重复 Strategy 模块抽象（BaseStrategy / Factory）的通用内容。

### 1.1 相对 v0.1.0 的核心变更

| 变更项                         | v0.1.0                                              | v0.1.1（当前）                                                      |
| ------------------------------ | --------------------------------------------------- | ------------------------------------------------------------------- |
| Action 工具选择                | LLM `invoke(tool_list)`                             | 同左，Prompt 合并为单一 `action.md`                                 |
| Action 参数校验                | LLM `invoke_structured(ActionResult)`               | **代码侧**按 `ToolDefinition.required_parameters` 校验               |
| 人机协作                       | `human_in_the_loop` → Final，无恢复                 | 接入 `HITLSubgraph`：补参 / 审批后回到 Action 继续                  |
| 审批能力                       | 无                                                  | `ToolDefinition.requires_approval` → `HITLType.APPROVAL`            |
| 无 tool_calls                  | `task_status=completed` → Final                     | `task_status=no_tool_calls` → 回 Reason，靠 retry 上限终止          |
| Reason 结构化输出              | `reasoning` / `information_status` / `task_status`  | `thought` / `reasoning` / `task_status`（去掉 information_status）  |
| 子图节点                       | reason / action / tool / final                      | 新增 **HITL** 节点；Action 可通过 `Command(goto="HITL")` 直达      |
| `task_status`                  | 4 态                                                | 6 态：新增 `no_tool_calls`、`cancelled`                             |
| 工具定义注入                   | `tool_registry.get_tools()`                         | `tool_registry.list_definitions()`                                  |

---

## 2. 设计目标

ReAct Strategy 实现 **Reason → Action →（HITL）→ Tool → Observation → … → Final** 循环推理模式，目标如下：

| 目标                   | 实现方式                                                                 |
| ---------------------- | ------------------------------------------------------------------------ |
| 推理与工具选择分离     | `ReasonNode` 评估状态并产出能力意图；`ActionNode` 负责选工具与参数组装 |
| 参数校验确定性         | Action 用 Schema 代码校验必填参数，不再依赖 LLM 二次判断                 |
| 工具执行隔离           | `ToolNode` + `ToolExecutor`，Strategy 不直接调用 handler                 |
| 人机协作可恢复         | 缺参 → `HITLType.INPUT`；需审批 → `HITLType.APPROVAL`；恢复后回 Action   |
| 可观测失败             | 非法工具 / 执行失败 / 步数超限 / 重试超限 / 用户取消均有明确终止路径     |
| 最终回答独立生成       | `FinalNode` 基于 input / reasoning / observations 生成自然语言响应       |

---

## 3. 整体流程

### 3.1 子图结构

```text
START
  ↓
reason ──────────────────────────────────────────┐
  ↓ (继续)                                       │ (completed / cancelled /
action                                            │  failed / step|retry limit)
  ├─ Command(goto=HITL) 或 route=HITL ─→ HITL ─┐ │
  │                                              ↓ │
  │                                         action │
  ├─ tool_calls ─→ tool ─→ reason ────────────────┘
  └─ no tool_calls ─→ reason（带 no_tool_calls 观察）
                                              ↓
                                           final
                                              ↓
                                             END
```

固定边：

| 边                 | 说明                          |
| ------------------ | ----------------------------- |
| `START → reason`   | 入口                          |
| `HITL → action`    | HITL 完成后回到 Action 应用结果 |
| `tool → reason`    | 工具结果进入下一轮推理        |
| `final → END`      | 出口                          |

条件边：

| 源       | 路由函数           | 可能目标                    |
| -------- | ------------------ | --------------------------- |
| `reason` | `_reason_router`   | `action` / `final`          |
| `action` | `_action_router`   | `HITL` / `tool` / `reason`  |

> 缺参与审批路径优先由 Action 返回 `Command(update=..., goto="HITL")` 直接跳转；`_action_router` 在 `task_status=human_in_the_loop` 时作为兜底路由到 HITL。

### 3.2 节点职责

| Node           | 职责                                         | LLM 调用                          |
| -------------- | -------------------------------------------- | --------------------------------- |
| `ReasonNode`   | 评估任务状态、产出下一步能力意图             | `invoke_structured(ReasonStructuredOutput)` |
| `ActionNode`   | 选工具、代码验参、发起 HITL、应用 HITL 结果  | `invoke(tool_list)`（仅选工具）   |
| `HITL`         | Runtime `HITLSubgraph.as_node()`，中断等待人 | 无                                |
| `ToolNode`     | 执行工具、写回 ToolMessage                   | 无                                |
| `FinalNode`    | 生成最终回答                                 | `invoke()`                        |

### 3.3 单步循环时序

```text
1. ReasonNode
   输入：user input + messages + observations(+ tool_results 转观察)
   输出：reasoning, task_status (in_progress | completed)
   特例：tool_results 含失败 → 跳过 LLM，仅累加 retry_count；超限则 failed

2. ActionNode（reason 路由到 action）
   若 state.tool_calls 非空（HITL 回来）：
     - cancelled → task_status=cancelled
     - INPUT → 填参，必要时再 APPROVAL，否则 ready 写 messages
     - APPROVAL → 清空 HITL 字段，写 AIMessage(tool_calls)，继续执行
   否则：
     Step-1：LLM 选工具 → tool_calls
     Step-2：代码校验非法工具 / 缺参 / 是否需审批
     输出：tool_calls / hitl_request / task_status / messages

3. HITL（缺参或审批）
   读取 hitl_request → interrupt → 写回 hitl_response → 回到 action

4. ToolNode（tool_calls 就绪）
   输出：tool_results, messages(ToolMessage), tool_calls=[]

5. 回到 ReasonNode

6. FinalNode（终止条件触发）
   输出：response, messages(AIMessage)
```

---

## 4. Schema 设计

### 4.1 ReActInput

```python
class ReActInput(BaseInput):
    messages: Sequence[BaseMessage] = []
```

继承 `BaseInput.input`（`UserInput | dict | str`）。SubGraph 入口输入，从 Parent State 映射或直接传入。

### 4.2 ReActState

```python
class ReActState(BaseState):
    reasoning: str = ""
    task_status: Literal[
        "in_progress",
        "human_in_the_loop",
        "no_tool_calls",
        "completed",
        "cancelled",
        "failed",
    ] = "in_progress"
    observations: list[str] = Field(default_factory=list)
    step_count: int = Field(default=0)
    retry_count: int = Field(default=0)
```

继承 `BaseState`，额外包含基类字段：

| 字段            | 类型                         | 说明                    |
| --------------- | ---------------------------- | ----------------------- |
| `input`         | UserInput / dict / str / None | 用户输入               |
| `messages`      | list[BaseMessage]（add）     | 对话与工具消息历史      |
| `tool_calls`    | list[ToolCall]               | 待执行 / HITL 中的调用  |
| `tool_results`  | list[ToolResult]             | 最近一轮工具结果        |
| `hitl_request`  | HITLInput \| None            | 发给 HITL 的请求        |
| `hitl_response` | HITLOutput \| None           | HITL 返回结果           |
| `response`      | str \| None                  | 最终回答（由 Final 写） |

### 4.3 task_status 状态机

```text
                    ┌─────────────────┐
                    │   in_progress   │←──────────────────────────────────┐
                    └────────┬────────┘                                   │
                             │                                            │
              Reason: completed                                           │
                             ↓                                            │
                    ┌─────────────────┐                                   │
                    │    completed    │──→ final                          │
                    └─────────────────┘                                   │
                                                                          │
              Action: missing_params / approval                           │
                             ↓                                            │
                    ┌─────────────────┐     HITL 完成且通过               │
                    │human_in_the_loop│──────────────────→ action ────────┤
                    └────────┬────────┘                                   │
                             │ HITL cancelled                             │
                             ↓                                            │
                    ┌─────────────────┐                                   │
                    │    cancelled    │──→ final                          │
                    └─────────────────┘                                   │
                                                                          │
              Action: 无 tool_calls                                       │
                             ↓                                            │
                    ┌─────────────────┐                                   │
                    │  no_tool_calls  │──→ reason（retry+1）──────────────┤
                    └─────────────────┘                                   │
                                                                          │
              Action: invalid tools                                       │
              Reason: retry limit (tool error)                            │
              Route: step / retry limit                                   │
                             ↓                                            │
                    ┌─────────────────┐                                   │
                    │     failed      │──→ final                          │
                    └─────────────────┘                                   │
                                                                          │
              Action: ready → tool                                        │
                             ↓                                            │
                          tool ───────────────────────────────────────────┘
```

| 状态                | 设置者                                      | 含义                                       |
| ------------------- | ------------------------------------------- | ------------------------------------------ |
| `in_progress`       | 初始 / Action ready / HITL 恢复成功         | 任务进行中，继续循环                       |
| `completed`         | Reason（仅当当前已是 in_progress）          | 任务完成，进入 Final                       |
| `human_in_the_loop` | Action（缺参 / 需审批）                     | 等待 HITL；完成后回 Action                 |
| `no_tool_calls`     | Action（LLM 未产出 tool_calls）             | 回 Reason 再评估；同时 `retry_count+=1`    |
| `cancelled`         | Action（HITL `status=cancelled`）           | 用户取消，进入 Final                       |
| `failed`            | Action（非法工具）/ Reason（重试超限）等    | 任务失败，进入 Final                       |

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

| 字段              | 消费者                          | 说明                                         |
| ----------------- | ------------------------------- | -------------------------------------------- |
| `max_steps`       | 设计意图给路由使用              | **当前路由实际读 Strategy 实例** `_max_steps` |
| `retry_max_count` | `ReasonNode._handle_tool_error` | 工具失败重试超限判定                         |

> 与 v0.1.0 相同：`ReActStrategy._max_steps` / `_retry_max_count` 与 Context 默认值重复；`_reason_router` 读实例字段，Reason 工具错误处理读 Context。`to_strategy_context()` 当前始终返回空的 `ReActContext()`，未透传 Parent Context。

---

## 5. Node 设计

### 5.1 ReasonNode

**职责：** 判断任务是否完成、产出面向 Action 的能力意图（不提工具名 / 参数）。

**输入：**

```python
{
    "input": state.input,
    "messages": state.messages,
    "observations": state.observations + [
        # 由 tool_results 即时构建
        {"name", "success", "tool_call_id", "result"|"error"},
        ...
    ],
}
```

**结构化输出** `ReasonStructuredOutput`：

| 字段          | 说明                                                                 |
| ------------- | -------------------------------------------------------------------- |
| `thought`     | 调试 / 可观测用的思考过程；**不写入 State**，仅日志输出              |
| `reasoning`   | 面向 Action 的执行意图描述；禁止包含工具名与具体参数                 |
| `task_status` | `in_progress` / `completed`                                          |

**特殊逻辑 — 工具失败处理：**

- 若 `state.tool_results` 中存在 `success=False`，跳过 LLM 调用
- `retry_count += 1`；若 `context` 存在且 `retry_count >= context.retry_max_count`，设置 `task_status=failed`

**task_status 写入规则：**

- 仅当当前 `state.task_status == "in_progress"` 时，Reason 才可写入 `task_status`
- 避免覆盖 Action / HITL 设置的 `human_in_the_loop` / `no_tool_calls` / `failed` / `cancelled`

### 5.2 ActionNode

Action 不再使用 LLM 做参数完整性判定。流程为：**LLM 选工具 → 代码校验 → 可选 HITL → ready**。

#### 入口分支

| 条件                     | 行为                                                                 |
| ------------------------ | -------------------------------------------------------------------- |
| `state.tool_calls` 非空  | `_handle_existing_tool_calls`（通常来自 HITL 恢复，跳过重新选工具）  |
| 否则                     | LLM `invoke(action.md, tool_list=...)` 生成 tool_calls               |

#### 新生成 tool_calls 后的处理

| 条件                                      | 行为                                                                 |
| ----------------------------------------- | -------------------------------------------------------------------- |
| 无 tool_calls                             | `task_status=no_tool_calls`，`retry_count+=1`，写入 observations 提示 |
| 工具名不在定义列表                        | `task_status=failed`，`retry_count+=1`                               |
| 必填参数缺失（`None` / 空字符串）         | `Command(goto="HITL")`，`HITLType.INPUT`，标记 `missing_args`        |
| `definition.requires_approval == True`    | `Command(goto="HITL")`，`HITLType.APPROVAL`                          |
| 否则                                      | ready：写 `tool_calls` + `AIMessage(tool_calls)`，`step_count+=1`    |

#### HITL 恢复（`_handle_existing_tool_calls`）

| `hitl_response` / 请求类型 | 行为                                                                 |
| -------------------------- | -------------------------------------------------------------------- |
| `status=cancelled`         | `task_status=cancelled`，清空 tool_calls                             |
| `HITLType.INPUT`           | `_fill_tool_calls` 用 `result.values` 填缺参；若仍需审批则转 APPROVAL；否则 ready |
| `HITLType.APPROVAL`        | 清空 HITL 字段，写 AIMessage，保持 tool_calls，进入执行              |
| 无 hitl_response           | 原样保留 tool_calls，`task_status=in_progress`                       |

INPUT 的 HITL payload：

```python
{
    "fields": [{"name", "description"}, ...],  # InterruptField
    "tool_calls": [{"tool_call_id", "name", "missing_args"}, ...],
}
```

APPROVAL 的 HITL payload：

```python
{
    "tool_calls": [{"tool_call_id", "name", "args"}, ...],
}
```

#### 遗留类型

源码中仍保留未使用的 `ActionResult` Pydantic 模型（v0.1.0 LLM 验参残留），**当前运行路径不调用**。

### 5.3 HITL 节点

由 `HITLSubgraph().as_node()` 注册，节点名默认 `"HITL"`。

```text
HITLNode.run
  → 读 state.hitl_request
  → HITLSubgraph.invoke
      START --type--> input_flow | approval_flow → normalize_result → END
  → 写回 {"hitl_response": HITLOutput}
```

详细协议见 Runtime HITL 相关文档与 `tests/docs/HITL Subgraph 测试案例文档.md`。ReAct 只负责构造 `HITLInput` 与消费 `HITLOutput`。

### 5.4 ToolNode

定义于 Tool 模块，ReAct 中作为标准 Graph Node 注册。

- 读取 `state.tool_calls`
- 逐个 `ToolExecutor.execute()`（串行）
- 返回 `tool_results` + `ToolMessage` 列表，并清空 `tool_calls`

### 5.5 FinalNode

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

> Final 的 observations 仅含 State 中已持久化的列表。Reason 从 `tool_results` 即时构建的观察 **默认不会写回** `state.observations`（见 §10）。

---

## 6. 路由规则

### 6.1 `_reason_router`

| 条件                             | 目标     |
| -------------------------------- | -------- |
| `task_status == "completed"`     | `final`  |
| `task_status == "cancelled"`     | `final`  |
| `task_status == "failed"`        | `final`  |
| `step_count >= _max_steps`       | `final`  |
| `retry_count >= _retry_max_count`| `final`  |
| 否则                             | `action` |

说明：

- `no_tool_calls` / `human_in_the_loop` **不**在此特殊处理；前者会落到 `action`（再由 Action 或 retry 上限收敛），后者通常不会经 Reason 路由（HITL 边直接回 Action）。
- 步数 / 重试上限比较的是 Strategy 实例字段，不是 Context。

### 6.2 `_action_router`

| 条件                              | 目标     |
| --------------------------------- | -------- |
| `task_status == "human_in_the_loop"` | `HITL` |
| `state.tool_calls` 非空           | `tool`   |
| 否则                              | `reason` |

与 v0.1.0 差异：无 tool_calls 时不再进 Final，而是回 Reason；HITL 成为一等路由目标。

---

## 7. Prompt 设计

Prompt 文件位于 `echo_agent/core/strategy/react/prompt/`：

| 文件           | 使用者     | 核心约束                                               |
| -------------- | ---------- | ------------------------------------------------------ |
| `reasoning.md` | ReasonNode | 只推理业务下一步要做什么；不选工具、不验参、不生成最终回答 |
| `action.md`    | ActionNode | 只生成 tool_calls；缺参时省略参数，由运行时检测        |
| `final.md`     | FinalNode  | 只生成最终回答；不推理、不调用工具                     |

v0.1.0 的 `tool_selection.md` / `tool_validation.md` / `action-old.md` 已移除。

### 7.1 Prompt 分工原则

```text
Reason  → 「目标达成了吗？下一步需要什么能力？」
Action  → 「选什么工具？已知参数填上，未知参数省略」
HITL    → 「人补参 / 人审批」（代码驱动，无 Prompt）
Final   → 「基于已有信息回答用户」
```

Action Prompt 明确：不验证参数完整性、不执行工具、不生成面向用户的自然语言解释。

---

## 8. ReActStrategy 与 ReActNode

### 8.1 构造

```python
ReActStrategy(
    llm_config: LLMConfig,
    tool_registry: ToolRegistry,
)
```

内部创建 `ToolExecutor(tool_registry)`；ActionNode 接收 `tool_registry.list_definitions()`。

### 8.2 build()

注册五节点与边（见 §3.1），返回未编译 `SubGraph(name="ReAct", ...)`。

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

| 模块        | ReAct 中的使用                                                                 |
| ----------- | ------------------------------------------------------------------------------ |
| **LLM**     | Reason 用 `invoke_structured`；Action / Final 用 `invoke`                      |
| **Tool**    | Action 绑定 `ToolDefinition`；按 `required_parameters` / `requires_approval` 决策；ToolNode 执行 |
| **Runtime** | `HITLSubgraph` 作为节点；`HITLInput` / `HITLOutput` / `HITLType`；`InterruptField` |
| **Graph**   | SubGraph 构建；条件边；`Command(goto=...)`；State Patch                        |
| **Model**   | `UserInput` 作为输入载体；HITL 模型复用 Runtime/Model 层                       |
| **Common**  | `debug_print_messages` / `format_debug` 调试输出                               |

---

## 10. 已知限制

| 限制                                      | 说明                                                                 |
| ----------------------------------------- | -------------------------------------------------------------------- |
| `observations` 多数路径未写回 State       | Reason 从 `tool_results` 构建观察喂给 LLM，但不持久化；仅 `no_tool_calls` 会写入一条字符串观察 |
| 步数 / 重试上限双份配置                   | Strategy 实例字段与 `ReActContext` 并存，路由与错误处理读源不一致    |
| Context 未从 Parent 透传                  | `to_strategy_context()` 固定 `ReActContext()`                        |
| `ActionResult` 死代码                     | 旧 LLM 验参 Schema 仍留在 `action_node.py`，未被引用                 |
| APPROVAL 恢复分支变量问题                 | `_handle_existing_tool_calls` 在 APPROVAL 分支调用 `_build_tool_call_message(tool_calls)` 时，局部变量 `tool_calls` 可能未定义（应为 `state.tool_calls`） |
| 无并行工具调用策略                        | 多 tool_calls 由 ToolNode 串行执行                                   |
| Plan 能力缺失                             | 无显式 Plan 阶段，依赖 Reason 隐式规划                               |
| 大量 `print` 调试日志                     | 未接入统一日志框架                                                   |
| `thought` 未落 State                      | 仅控制台打印，不可被上游观测 / Checkpoint 查询                       |

---

## 11. 后续版本候选

- [ ] 修复 APPROVAL 恢复分支中的 `tool_calls` 未定义问题
- [ ] 删除未使用的 `ActionResult`
- [ ] `observations` 统一写回 State，并约定 reducer（追加而非覆盖）
- [ ] 步数 / 重试上限统一由 `ReActContext` 或构造参数注入，并透传 Parent Context
- [ ] `thought` 可选写入 State / 事件流，支撑 Console 可视化
- [ ] 工具并行执行
- [ ] 去除 debug print，改用统一日志
- [ ] `no_tool_calls` 与 Reason `completed` 的协作策略再收敛（避免仅靠 retry 耗尽）

---

## 12. 验证结论

与本版实现对齐的测试入口：

| 测试                         | 覆盖点                                           |
| ---------------------------- | ------------------------------------------------ |
| `tests/test_react_agent.py`  | 基础 ReAct：单/多工具、多轮、stream、Checkpoint  |
| `tests/test_react_agent_hitl.py` | HITL 补参（INPUT）与审批（APPROVAL）闭环     |
| `tests/docs/ReAct Agent 测试案例文档.md` | 业务场景案例说明                       |
| `tests/docs/HITL Subgraph 测试案例文档.md` | HITL 子图自身能力（不经 Strategy）     |

本版相对 v0.1.0 已落地的能力：

- 单工具 / 多工具链式执行与 Final 输出
- 代码侧缺参检测 → INPUT HITL → 填参后续跑
- `requires_approval` 工具 → APPROVAL HITL → 执行
- HITL 取消 → `cancelled` → Final
- 多轮 Checkpoint 会话与 stream 模式 FinalNode token 输出

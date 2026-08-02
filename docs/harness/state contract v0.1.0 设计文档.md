# State Contract v0.1.0 设计文档

## 1. 版本说明


| 项目     | 内容                                                                                                                                                    |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 版本     | v0.1.0                                                                                                                                                  |
| 状态     | 设计定稿，待实现                                                                                                                                        |
| 所属模块 | Harness Runtime · Task 1（参见[echo-agent v0.1.0 Harness Runtime 优化设计文档](../runtime/echo-agent%20v0.1.0%20Harness%20Runtime%20优化设计文档.md)） |
| 体现原则 | 原则 3（执行事实与运行环境分离）；原则 5（执行受控）                                                                                                    |
| 影响范围 | Graph Schema、ReAct Strategy（reason / action / final）                                                                                                 |
| 依赖     | LangGraph 1.2.5（state_schema / context_schema / checkpointer）                                                                                         |

本文档建立 echo-agent 的 State Contract（状态契约）：定义 State / Context / Store 三载体判定标准、字段分类与生命周期、字段登记表，并落地契约的第一个实例（observations 重构）。

---

## 2. 背景与现状

### 2.1 背景

优化文档问题 5：Agent State（BaseState / ReActState）字段职责未形成契约，Runtime 数据与 Execution 数据边界模糊，且已出现字段职责重叠实例（observations 与 tool_results）。本任务把原则 3 的边界落成代码级契约，回答四个问题：

1. 哪些数据属于 Agent State（需持久化的执行事实）
2. 哪些数据属于 Runtime Context（当前运行环境，可由 Runtime 服务重建）
3. 每个字段的生命周期与清理责任
4. 各 Execution Strategy 如何共享与扩展 State

**进入 State 的判定标准：下一节点执行必须依赖，且无法通过 Runtime 服务重建。**

### 2.2 当前问题


| 缺口                                            | 现象                                                                                                                                     | 后果                                                                                                 |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| 缺口 1：`tool_results` 成功路径无清理           | ToolNode 覆盖写入后，成功时无任何节点清空；下一轮若未产生工具调用，Reason 的`_build_observations` 会将上一轮结果重复转换                 | 同一结果重复进入推理输入，上下文膨胀                                                                 |
| 缺口 2：`observations` 持久化语义与设计意图不符 | 无 reducer（整体覆盖）；仅两条错误路径（Reason 工具失败重试、Action no_tool_calls）写入；成功结果从不落 State，靠`_build_input` 临时拼接 | 持久化部分只记异常，认知层对成功事实的感知依赖 tool_results 的临时转换——"同一份数据两处存储"的根源 |
| 缺口 3：字段写入方不唯一                        | `reasoning` 由 Reason 与 Action（非法工具路径）双写；`hitl_*` 字段清理分散在 Action 的 5+ 处                                             | 职责无法登记，新增字段只能模仿失控                                                                   |

---

## 3. 载体模型：State / Context / Store 三分类

原则 3 的"State / Runtime Context"二分，落到 LangGraph 机制上细化为三载体——运行期可变且跨 turn 存续的 Runtime 环境（如 Task 3 的 ACTIVE skills、Task 4 的 active_tools）需要独立落点：


| 载体        | LangGraph 机制                  | 语义                                   | 进入标准                                                | 持久化               |
| ------------- | --------------------------------- | ---------------------------------------- | --------------------------------------------------------- | ---------------------- |
| **State**   | `state_schema` + reducer        | 执行事实：发生了什么                   | 下一节点依赖，且无法由 Runtime 服务重建，且需要恢复语义 | checkpoint           |
| **Context** | `context_schema`，invoke 期传入 | 运行配置：run 开始前已确定             | run 内只读，跨 turn 由应用层重建供给（如`max_steps`）   | 否                   |
| **Store**   | `BaseStore`，按 namespace 隔离  | Runtime 环境：运行期可变、跨 turn 存续 | 可变，且需跨 turn 存续，且按 session 隔离               | 持久化（Store 自身） |

判定流程：**需要 checkpoint 恢复 → State；invoke 前已确定 → Context；运行期可变且跨 turn → Store。**

> 本任务只启用 State 与 Context 两类；Store 载体在 Task 3（Skill 生命周期）/ Task 4（Tool Scope）详细设计时启用，此处登记为契约的保留类别。

---

## 4. 字段分类与生命周期

### 4.1 五分类 + 例外类


| 分类                 | 职责                                         | 现有字段                                                               |
| ---------------------- | ---------------------------------------------- | ------------------------------------------------------------------------ |
| Conversation         | 对话上下文                                   | `messages`                                                             |
| Execution            | 执行流程控制                                 | `step_count` / `task_status` / `retry_count` / `reasoning`（策略特有） |
| Interaction          | 人机交互控制                                 | `hitl_request` / `hitl_response`                                       |
| Tool Execution       | 工具执行事实                                 | `tool_calls` / `tool_results`                                          |
| Input / Output       | 任务输入与最终输出                           | `input` / `response`                                                   |
| 认知留痕（例外登记） | 认知视图的覆盖式单条快照，供 checkpoint 审计 | `observations`（见 6.5）                                               |

### 4.2 生命周期三级定义


| 级别       | 定义                             | 清理责任                                                         |
| ------------ | ---------------------------------- | ------------------------------------------------------------------ |
| Session 级 | 跨用户任务存续                   | 不清理；`messages` 的视图裁剪归 Task 5（组装层），State 本体不动 |
| Task 级    | 单个用户任务的多轮循环内存续     | 任务结束自然失效；Session 内新任务启动时由入口重置               |
| Turn 级    | 节点间一跳：写入 → 消费 → 清理 | **谁消费谁清理**，写入方不负责                                   |

### 4.3 清理责任规则

- 统一规则：**谁消费谁清理**。`tool_calls` 由 Tool（执行后）与 Reason（错误重试）清理；`tool_results` 由 Reason（经 ObservationBuilder 消费后）清理；`hitl_*` 由 Action（执行路径）或 Reason（cancelled 路径）清理（见 6.5）。
- Turn 级字段禁止跨轮残留：每条图路径都必须有确定清理方。

---

## 5. 字段登记表（契约定稿）

所有字段登记六列：分类 / reducer 语义 / 生命周期 / 写入方（唯一主写）/ 读取方 / 清理方。**新增字段必须在 PR 中申明分类并登记本表。**


| 字段            | 分类                  | reducer                | 生命周期 | 写入方                                                       | 读取方                                        | 清理方                                       |
| ----------------- | ----------------------- | ------------------------ | ---------- | -------------------------------------------------------------- | ----------------------------------------------- | ---------------------------------------------- |
| `input`         | Input / Output        | 覆盖                   | Session  | 入口                                                         | Reason / Final                                | —                                           |
| `messages`      | Conversation          | `add_messages`（追加） | Session  | Action（AIMessage）/ Tool（ToolMessage）/ Final（AIMessage） | Reason / Action / Final                       | Task 5（组装层裁剪，不动 State）             |
| `tool_calls`    | Tool Execution        | 覆盖                   | Turn 级  | Action                                                       | Action（判已有）/ Tool                        | Tool（执行后）/ Reason（错误重试）           |
| `tool_results`  | Tool Execution        | 覆盖                   | Turn 级  | Tool                                                         | Reason（经 ObservationBuilder）               | Reason（消费后，缺口 1 闭合）                |
| `observations`  | 认知留痕（例外）      | 覆盖                   | Task 级  | Reason（经 ObservationBuilder）                              | trace / 审计（无 State 级读者）               | 下轮覆盖                                     |
| `hitl_request`  | Interaction           | 覆盖                   | Turn 级  | Action                                                       | HITL / Reason（经 builder，cancelled 路径）   | Action（执行路径）/ Reason（cancelled 路径） |
| `hitl_response` | Interaction           | 覆盖                   | Turn 级  | HITL Subgraph                                                | Action / Reason（经 builder，cancelled 路径） | 同上                                         |
| `reasoning`     | Execution（策略特有） | 覆盖                   | Task 级  | **Reason 独占**（Action 直写收编，见 6.5）                   | Action / Final                                | 下轮覆盖                                     |
| `task_status`   | Execution（策略特有） | 覆盖                   | Task 级  | Reason / Action                                              | 路由                                          | 任务结束                                     |
| `step_count`    | Execution（策略特有） | 覆盖                   | Task 级  | Action                                                       | Reason（路由）                                | 任务结束                                     |
| `retry_count`   | Execution（策略特有） | 覆盖                   | Task 级  | Reason / Action                                              | Reason（路由）                                | 任务结束                                     |
| `response`      | Input / Output        | 覆盖                   | Session  | Final                                                        | 出口                                          | —                                           |

> `retry_count` 语义（任务期总预算 vs 连续重试）属 ReAct 策略内部机制，本契约只登记分类与生命周期，不统一约定语义。

---

## 6. Observation 设计（契约第一个实例）

### 6.1 ReAct 原理锚点

ReAct（Yao et al., ICLR 2023）的轨迹由 Thought → Action → Observation 循环构成：Action 作用于外部环境，**Observation 是环境返回的反馈事实，模型只读 Observation、不生成 Observation**。生产实践的三条强共识：

1. Observation 是事实，不能由模型转述（paraphrase drift 导致后续动作错误）
2. Error-as-feedback：工具错误与成功结果走同一条路成为 Observation，是模型自我纠正的机制
3. Observation 不可遗漏：每个工具结果必须在下一次推理前进入上下文

echo-agent 是分解式 ReAct（Reason 为独立 LLM 调用、结构化输出），映射如下：


| 经典 ReAct             | echo-agent                                 | 数据载体                       |
| ------------------------ | -------------------------------------------- | -------------------------------- |
| Thought                | ReasonNode                                 | `reasoning` / `task_status`    |
| Action（决策）         | ActionNode                                 | `tool_calls`                   |
| Action（执行）/ 环境   | ToolNode                                   | `tool_results`（全量事实）     |
| **Observation**        | **ObservationBuilder（ReasonNode 内）**    | `observations`（认知视图快照） |
| Scratchpad（持久轨迹） | `messages`（AIMessage + ToolMessage 全量） | `add_messages`                 |

分解架构的工程必然：全量 tool_result 直接进入 Reason 输入即发生膨胀，故截断必须前置到进入 Reason 之前由 Harness 完成。**Observation 的三项职能：接收工具执行结果（含错误）→ 转换为结构化数据 → 截断取重要信息，供 Reason 下一轮推理。**

### 6.2 Observation 模型

```python
class ObservationMetadata(BaseModel):
    name: str                        # 工具名 / 事件名
    success: bool = True             # Reason 的错误检测改读此处
    tool_call_id: str | None = None  # 关联 ToolCall
    truncated: bool = False          # 是否发生截断
    original_length: int | None = None  # 截断前原始长度
    step: int = 0                    # 关联 step_count，供 trace

class Observation(BaseModel):
    content: str                     # 结构化序列化 + 截断后的文本
    metadata: ObservationMetadata
```

### 6.3 ObservationBuilder

**位置：ReasonNode 内，模型推理前调用。** 无状态服务类，不进 State（契约边界：State 不存能力/服务）。

```python
class ObservationBuilder:
    """执行事实 → 认知视图：Observation 的构建与截断管理。"""

    def __init__(self, max_content_length: int): ...

    def build_from_state(self, state: ReActState) -> list[Observation]:
        """按 State 瞬态信号合成当轮 Observation 集合：
        - state.tool_results 非空 → from_tool_results（tool）
        - state.hitl_request + hitl_response 存在 → from_hitl_response（human）
        - state.task_status == "no_tool_calls" / "failed" → from_system_event（system）
        - 首轮皆无 → 空列表（正常）"""

    def from_tool_results(self, results: list[ToolResult], *, step: int) -> list[Observation]: ...
    def from_hitl_response(self, request: HITLInput, response: HITLOutput, *, step: int) -> Observation: ...
    def from_system_event(self, name: str, content: str, *, step: int) -> Observation: ...
```

**截断策略（规则式，确定性、零成本、可从 tool_results 重建）三层：**


| 层 | 策略                 | 说明                                                                                                                           |
| ---- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| 1  | 结构化投影（优先）   | 对已知结构的 tool_result 按字段 allowlist 提取（status / id / 关键数据字段）；per-tool 策略可在`ToolDefinition.meta_data` 声明 |
| 2  | 首尾保留截断（兜底） | 无结构声明的长文本保留头尾，注入`[truncated, original_length: N]` 标记，模型可知数据被移除及原规模                             |
| 3  | 错误豁免             | error 内容不截断或走更高阈值——error-as-feedback 必须完整                                                                     |

截断阈值入 **`ReActContext.observation_max_length: int = 2000`**——静态运行配置，是 `context_schema` 的正确用法。

### 6.4 数据流与 State 更新

```text
ToolNode（完全不变：写 tool_results 全量 + ToolMessage + 清 tool_calls）
  │
ReasonNode 入口：observations = ObservationBuilder.build_from_state(state)
  │   （局部变量，作为本轮推理输入）
  ↓
ReasonNode 推理（错误检测改读 observations[*].metadata.success）
  │
ReasonNode 出口 Command update：
  ├─ observations: 本轮快照（覆盖写入 ReActState）
  ├─ tool_results: []（消费完毕清理——缺口 1 闭合）
  ├─ hitl_request / hitl_response: None（cancelled 路径消费后清理）
  └─ reasoning / task_status / retry_count ...
```

每轮 Reason 入口重新合成、出口覆盖快照，因此：

- 新任务首轮 Reason 不会读到上一任务残留（上一任务末轮快照被新快照覆盖，且 Reason 从不读 State 中的 observations）
- cancelled 路径（action → reason → final）的 human 观察能被 Reason 正常消费
- approve / 填充路径不写 human 观察：人工输入已物化在 `tool_calls` / AIMessage 中，属冗余

### 6.5 契约例外登记与收编清单

**例外登记**：`state.observations` 无 State 级读者（Reason 用入口局部产物，Final 不读），严格按 State 进入标准不达标。契约显式登记为例外条款：**认知视图的覆盖式单条留痕，供 checkpoint 审计与调试**。它是成本恒定的轻量留痕（覆盖刷新、不增长），区别于被否决的追加式累积（见 7.1）。

**收编清单：**


| # | 收编项                                                  | 变更                                                                                                                                                   |
| --- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 | Reason`_build_observations` / `_build_input` 的转换职责 | 删除，改为入口调用 ObservationBuilder；Reason 只读 builder 产物                                                                                        |
| 2 | Reason`_has_tool_error`                                 | 改读 builder 产物的`metadata.success`（顺序：build → 错误检测 → 推理）                                                                               |
| 3 | Action`_handle_no_tool_calls` 的 observations dict 写法 | 删除；`task_status=no_tool_calls` 信号足够 Reason 合成 system 观察                                                                                     |
| 4 | Action 非法工具路径直写`reasoning`                      | 收编为`task_status=failed` 单一信号；非法工具详情不入 State（诊断信息由日志 / 输出通道承载，trace 职能归属待单独讨论）；`reasoning` 归 Reason 独占写   |
| 5 | Final`_build_input` 的 `observations` 键                | 移除；`messages`（全量 ToolMessage）+ `reasoning` 已足                                                                                                 |
| 6 | HITL 字段清理                                           | cancelled 路径（含 APPROVAL 拒绝分支）不再由 Action 清理 hitl 字段，统一交 Reason 经 builder 消费后清理；执行路径（填充 / 批准）保持 Action 消费后清理 |

---

## 7. 边界约束（契约评审项）

### 7.1 五条禁令

1. State 保存数据，**不保存能力**——Tool / LLM / Manager 实例禁止进入
2. State 保存结果，**不保存服务**——ToolRegistry / SkillCatalog / MCP Client / ObservationBuilder 属于 Runtime
3. State 保存执行事实，**不保存 Runtime 配置**——静态配置入 Context（`context_schema`），运行期可变环境入 Store（Task 3/4 启用）
4. State **不承接 trace 职能**——模型视角轨迹入 messages，系统视角重放入 checkpoint；独立的 trace 通道设计待单独讨论
5. State **不做追加式累积**（`messages` 除外，其由 `add_messages` 契约管理）——瞬态字段覆盖 + 消费清理

> **禁令 4 / 5 的论证**（契约结论，trace 独立通道设计另行立项）：
>
> 1. **子系统分工**：State 服务执行推进，trace 服务诊断与计量（指南可观测性三支柱：日志 / 追踪 / 指标），混接使两子系统互相污染
> 2. **已有两个 trace 通道**：模型视角 trace → `messages`（追加，与模型输入对齐）；系统视角 trace → checkpointer 的 State History（恢复 / 重放 / time-travel）。字段级追加是第三份拷贝——恰是本契约要消除的双存储问题的翻版
> 3. **成本无界**：追加字段随步数线性膨胀，checkpoint 体积与序列化开销同步增长，且 Task 5 裁剪治理对象从 1 个变 3 个
> 4. **需要历史做决策时显式建模**（如循环检测的 `attempted_actions` 受限窗口），而非把瞬态字段改追加
> 5. **checkpoint 不能替代 trace**：checkpoint 是 super-step 快照（仅 state 变更时产生），盲区包括 LLM token / latency、节点内事件（参数校验拒绝、重试决策、prompt 组装）等不产生 state 变更的操作；且让 checkpoint 承接 trace 的唯一途径是把 trace 数据放进 State——违反本契约。契约收窄 State 与 checkpoint 的 trace 能力此消彼长，故 trace 必须有 State 之外的通道（设计待定）

### 7.2 新增字段流程

1. 按第 3 节判定载体（State / Context / Store）
2. State 字段需申明：分类（4.1）、reducer 语义、生命周期（4.2）、唯一写入方、读取方、清理方
3. 登记入第 5 节字段登记表后方可实现

---

## 8. 明确不做（Task 1 范围外）


| 项                                                  | 归属                         |
| ----------------------------------------------------- | ------------------------------ |
| Store 载体启用（ACTIVE skills / active_tools 落点） | Task 3 / Task 4              |
| Prompt 组装层与`messages` 视图裁剪                  | Task 2 / Task 5              |
| `llm_call` token usage 计量埋点                     | Task 5                       |
| `retry_count` 语义统一（总预算 vs 连续重试）        | ReAct 策略内部，本契约仅登记 |
| 跨轮历史显式建模（如循环检测`attempted_actions`）   | 后续版本按需申报             |

---

## 9. 影响面清单


| 文件                                         | 变更                                                                                            |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `core/graph/schema.py`                       | 契约注释（字段分类 / 生命周期登记）；字段无增删                                                 |
| `core/strategy/react/schema.py`              | `observations: list[dict]` → `list[Observation]`；`ReActContext` 新增 `observation_max_length` |
| `core/strategy/react/observation.py`（新增） | `Observation` / `ObservationMetadata` / `ObservationBuilder`                                    |
| `core/strategy/react/node/reason_node.py`    | 入口接 ObservationBuilder；出口写快照 + 清 tool_results / hitl；`_has_tool_error` 改读 metadata |
| `core/strategy/react/node/action_node.py`    | 收编项 3 / 4 / 6（不再写 observations / reasoning；cancelled 路径保留 hitl 字段）               |
| `core/strategy/react/node/final_node.py`     | 输入移除`observations` 键                                                                       |
| `core/tool/tool_node.py`                     | 无变更（保持通用）                                                                              |

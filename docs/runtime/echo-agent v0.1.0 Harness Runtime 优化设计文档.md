# echo-agent v0.1.0 Harness Runtime 优化设计文档

## 背景

echo-agent 当前已经完成 Agent Runtime 基础能力建设：

* 基于 LangGraph 的执行框架
* ReAct Agent 策略
* Tool 注册与执行
* MCP Client 接入
* HITL（Human In The Loop）
* Skill 初版机制
* Prompt 初版组合机制

当前版本已经能够完成完整 Agent 执行流程。

但是，在实际运行和测试过程中，逐渐暴露出工程化问题：

1. Skill 能力虽然支持动态加载，但 Skill 管理和运行时生命周期不完善。
2. Tool 虽然支持注册和绑定，但 Agent 可用 Tool 集合缺少动态治理机制。
3. Runtime Prompt 已支持组合和注入，但其生命周期与会话绑定、缺少单次调用级注入通道：Skill Catalog 随每次调用全量重发，load_skill 详情以 ToolMessage 永久驻留 messages，导致上下文污染。
4. 长任务执行过程中 Context 持续增长（实测：32 次 LLM 调用、总消耗 332,811 tokens、单次输入 ≈5.8k），需要上下文管理机制。
5. Agent State（BaseState / ReActState）字段职责未形成契约，Runtime 数据与 Execution 数据边界模糊，且已出现字段职责重叠的实例（observations 与 tool_results）。

以上五个问题并非五个孤立缺陷，而是**同一层缺失的五种症状**：上下文无人组装（问题 3、4）、能力无人收放（问题 1、2）、状态边界无人把守（问题 5）。当前 echo-agent 已具备 Agent Framework 能力，缺少的是 Agent Harness Runtime——围绕模型的运行控制层。因此，v0.1.0 发版前的主要目标不是增加更多智能体推理策略，而是补齐 Harness 层，使 echo-agent 从 `LangGraph + Strategy + Tool`（执行堆叠）演进为 `Application → Harness Runtime → Execution Strategy → LangGraph`（控制分层）：框架负责执行，Harness 负责控制，Strategy 负责推理模式。

---

## v0.1.0 目标调整

### 原目标

* ReAct Agent
* Plan-and-Execute Agent

### 调整后目标

> 完成基于 LangGraph 的 Agent Harness Runtime 初版，并以 ReAct 作为默认执行策略。

调整理由：

1. ReAct 已覆盖 Harness 的全部验证场景：Prompt 构建、Tool 调用、Skill 加载、Context 增长、State 更新、HITL、MCP 调用。以 ReAct 作为 Harness 的验证载体足够。
2. Plan-and-Execute 属于 Execution Strategy，不属于 Harness Runtime。在 Runtime 接口未稳定时同步推进，会放大上述五个问题，并被迫提前固化尚未设计好的接口。
3. Plan-and-Execute 更适合在 v0.2.0 作为 Harness 之上的第二个策略落地——用于验证 Harness 设计，而不是与 Harness 纠缠着一起诞生。

---

## Harness Runtime 定义

Harness Runtime 是位于 Application 和 Agent Framework 之间的运行控制层，职责：

* 控制 Agent 能看到的上下文
* 控制 Agent 可使用的能力
* 管理 Prompt 生命周期
* 管理 Tool 生命周期
* 管理 Skill 生命周期
* 管理 Runtime 状态
* 提供执行约束
* 提供运行可观测性（Token 计量、执行追踪）

上述职责在下文「设计原则」中收敛为五条设计原则。

---

## 设计原则

Harness Engineering 的核心主张：Harness 是大语言模型与真实执行环境之间的系统工程框架——它不替代模型推理，而是把模型的意图转化为可验证、可授权、可执行的操作，并将结果反馈给模型。Framework 解决"如何执行"，Harness 解决"如何控制"；其首要目标不是扩展智能体的能力，而是让智能体的行为可控、可见、可持续。

**引入原则**：引入 Harness Engineering 的目的是完善项目 Runtime，而非推翻 LangGraph 作为底层 Runtime Framework 与当前设计；相关参考资料（如《智能体 Harness 工程指南》）用于学习、借鉴，而非照搬。

本设计提炼五条原则：前三条为管理主线，第四条为反馈回路，第五条贯穿全局。

### 原则 1：上下文按调用组装，而非按历史堆积

Harness 的核心动作是"构造发给 LLM 的消息"，而不是维护越来越长的消息历史：

* 静态上下文缓存复用，动态上下文按需生成
* 生产参照：模块化提示词架构，保持缓存边界稳定（静态 / 动态分离）
* 消息历史是"完整真相"，模型输入是"当前视图"——两者分离，裁剪只发生在组装层
* 落实：Task 2、Task 5

### 原则 2：能力空间分层管理、渐进披露

能力分两层：Skills（高级指令层，教模型"怎么用"）→ Tools（底层能力层，让模型"能够用"）。Harness 管理两层之间的映射与暴露节奏：

* 指令层：Skill 是可版本化的能力包，动态发现与加载，生命周期 UNLOADED → ACTIVE → DISCARDED
* 能力层：元数据常驻（name + description）→ 按需激活 → 激活后收窄可见工具集
* 落实：Task 3（指令层激活）、Task 4（能力层暴露）

### 原则 3：执行事实与运行环境分离

* **State 记录过去**：发生了什么；可持久化；字段 reducer 语义与生命周期明确
* **Runtime Context 描述现在**：模型当前该看到什么、能做什么；可由 Runtime 服务重建，不持久化
* 进入 State 的唯一标准：下一节点执行必须依赖，且无法通过 Runtime 服务重建
* 落实：Task 1

### 原则 4：一切进入模型的内容都有预算，且可计量

* Token 预算分配：系统提示 / 消息历史 / 工具 schema / 用户输入 / 推理预留
* 可观测性（日志 / 追踪 / 指标）是 Harness 的反馈回路，不是附属功能——没有 per-call 计量，预算与压缩就没有触发依据
* 上下文重置（清空噪音、保留关键状态）作为压缩之外的兜底策略，列入 v0.2.0
* 落实：Task 5

### 原则 5：执行受控，行为可信

Harness 的主要目标不是扩展能力，而是约束风险：权限管理、操作校验、失败恢复，使智能体行为保持在安全边界内。

* 外部控制接口（暂停 / 恢复 / 干预）让执行可介入
* 现状：HITL 审批中断已实现，是本原则的雏形
* 规划：权限梯度（Free → Ask-first → Approve-once）列入 v0.2.0
* 落实：贯穿所有任务——任何新能力默认受控

### 原则间关系：Harness 最小闭环

```text
Application
  │
Harness Runtime（位于 LLM 与执行环境之间）
  ├─ 上下文管理主线（原则 1）：模型看到什么
  ├─ 能力管理主线  （原则 2）：模型能做什么
  ├─ 状态管理主线  （原则 3）：执行记住什么
  ├─ 预算观测回路  （原则 4）：计量驱动前三者
  └─ 执行约束      （原则 5）：贯穿所有主线（HITL / 权限）
  │
Execution Strategy（ReAct，可插拔）
  │
LangGraph（执行机制）
```

---

## 任务

### Task 1：State 优化

**体现原则 3（执行事实与运行环境分离）**——本任务把这条边界落成代码级契约。

#### 当前状态

项目中已完成对于 Agent Runtime 所需的 State 的基础抽象，因此，本阶段不是重新设计 LangGraph State，而是进一步明确各 State 中每个字段的职责、生命周期和使用范围。当前基类实现如下：

```python
class BaseState(BaseModel):
    """
    Graph 状态模型

    参数:
        input: 输入
        messages: 消息列表
        tool_calls: 工具调用列表
        tool_results: 工具执行结果列表
        hitl_request: HITL 请求
        hitl_response: HITL 响应
        response: 响应
    """
    input: UserInput | dict[str, Any] | str | None = None
    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    hitl_request: HITLInput | None = None
    hitl_response: HITLOutput | None = None
    response: str | None = None
```

#### 存在的问题

随着 Runtime 能力增加，State 中字段逐渐增多，在实际场景运行和测试中，逐渐暴露出以下问题：

**1. 字段职责重叠：认知层与执行层数据混杂**

`ReActState.observations: list[dict]` 与 `BaseState.tool_results: list[ToolResult]` 承载同一份工具执行数据：

* `tool_results` 是执行层事实——工具执行了什么、成功/失败、原始结果（tool_node 写入）
* `observations` 是认知层输入——Reason 节点据此判断任务状态（由 tool_results 转换拼入）

同一份数据两处存储，reducer 语义不一致（`tool_calls` 覆盖式 vs `messages` 追加式）；且 observations 为弱类型 `list[dict]`，下游节点大量字典取值，后续重构成本高。

**2. Runtime 数据与 Execution 数据边界模糊**

激活的 Skill、当前可用工具集等 Runtime 环境信息，目前通过进程级全局变量（`_active_catalog`）和构造期快照（strategy 组装时全量绑定 tool_list）隐式传递——既不在 State，也不在任何显式 Context 中：无法追踪、无法 checkpoint、无法按会话隔离。

**3. 字段清理责任不明**

Action 节点多处手动清空 hitl 字段；错误处理时手动清空 `tool_calls` / `tool_results`。字段生命周期（Session 级 / Turn 级 / 瞬态）没有约定，新增字段只能模仿现有模式，容易失控。

**4. 跨 Strategy 复用风险**

Plan-and-Execute 等后续策略需要 plan / current_step 等字段，若直接堆入同一 State，将出现策略特有字段污染。哪些字段全策略共享、哪些策略特有，目前没有约束。

#### 设计目标

建立 echo-agent State Contract，将原则 3 的边界落成字段级契约，回答四个问题：

1. 哪些数据属于 Agent State（需持久化的执行事实）
2. 哪些数据属于 Runtime Context（当前运行环境，可由 Runtime 服务重建）
3. 每个字段的生命周期与清理责任
4. 各 Execution Strategy 如何共享与扩展 State

**进入 State 的判定标准：下一节点执行必须依赖，且无法通过 Runtime 服务重建。**

#### State 字段分类

按职责与生命周期划分五类（现有字段对号入座）：

| 分类           | 职责               | 现有字段                                     | 生命周期                                      |
| -------------- | ------------------ | -------------------------------------------- | --------------------------------------------- |
| Conversation   | 对话上下文         | `messages`                                   | Session 级，受 Context Runtime 管理（Task 5） |
| Execution      | 执行流程控制       | `step_count` / `task_status` / `retry_count` | Turn 级                                       |
| Interaction    | 人机交互控制       | `hitl_request` / `hitl_response`             | 瞬态，消费后清理                              |
| Tool Execution | 工具执行事实       | `tool_calls` / `tool_results`                | Turn 级，追加                                 |
| Input / Output | 任务输入与最终输出 | `input` / `response`                         | Session 级                                    |

同时落地契约的第一个实例（observations 重构）：

* 保留 `tool_results` 作为执行层唯一事实源
* `observations` 重构为强类型认知层模型 `Observation(source, content, metadata)`，来源不限于 tool（可为 human / system）
* ToolResult → Observation 的转换职责从 Reason 节点剥离（独立转换节点或 Reason 前置步骤，实现期确定），Reason 只读 observations

#### 边界约束（三条原则）

1. State 保存数据，**不保存能力**——Tool / LLM / Manager 实例禁止进入
2. State 保存结果，**不保存服务**——ToolRegistry / SkillCatalog / MCP Client 属于 Runtime
3. State 保存执行事实，**不保存 Runtime 配置**——激活 Skill、可用工具集等放入 Runtime Context（落点见 Task 4：扩充 `BaseContext`，LangGraph `context_schema` 是其天然载体）

所有字段的 reducer 语义与生命周期在契约中显式登记，新增字段必须申明分类。

---

### Task 2：Prompt 优化

**体现原则 1（上下文按调用组装）**——Persistent / Runtime 双生命周期是该原则在 Prompt 层的落地。

#### 当前状态

Prompt 模块已具备组合、运行时注入与 Skill 集成能力：每次 LLM 调用时，`_build_prompt` 拼接 tool_call_policy + skill_usage + agent prompt，并经 `get_active_catalog()` 感知运行时。本阶段不是补齐组合能力，而是解决 Prompt 的生命周期管理。

#### 存在的问题

**1. 两条注入路径、两种生命周期同时失控**

* **Skill Catalog 每次调用全量重发**：作为 system prompt 组成部分前置到每次请求。虽未持久化进 `state.messages`，但成本等效——实测系统提示约 605 tokens × 51 次调用 ≈ 3 万 tokens，占输入 16.4%
* **load_skill 详情永久驻留**：SKILL.md 全文以 ToolMessage 进入 `state.messages`，后续每轮调用全程携带（见 Task 3）

**2. 组装逻辑硬编码**

拼接顺序、注入条件写死在 `LLMClient._build_prompt` 内部；`PromptLoader.load()` 每次调用直接读文件、无缓存；无注册、无版本、无分层管理。

#### 设计目标

Prompt 按生命周期分为两类：

* **Persistent Prompt**（Session 级）：基础 system prompt、Agent 行为约束、Tool Policy → 进入 system message，会话内稳定，可缓存
* **Runtime Prompt**（单次调用级）：Skill Catalog、当前可用工具信息、Runtime Context → 调用前按需注入，可裁剪、可去重，不随会话全量重发

#### 设计内容

1. **Prompt Registry**：分层注册（Runtime / Strategy / Agent / Runtime Context / Output，沿用已有分层表），支持版本管理
2. **PromptAssembler**：统一组装入口，每次调用前决定注入哪些 Runtime Prompt——skill 未激活不注入详情、catalog 仅在变更时更新；保持静态部分缓存边界稳定（静态 / 动态分离）
3. **Skill Prompt 分级**：Level 1 元数据名单常驻（name + description，轻量）；Level 2 详情按需（激活后由 Runtime Context 供给，不走消息，与 Task 3 联动）
4. **静态缓存**：文件读取缓存，消除每次 `read_text` 的重复 IO

---

### Task 3：Skill 优化

**体现原则 2（能力分层管理、渐进披露）· 指令层激活管理。**

#### 当前状态

已有 `SkillPackage` 抽象（本地包）、SKILL.md 解析、进程级只读 catalog、`load_skill` / `read_skill_resource` 两个工具；远程 Skill 未支持。

#### 存在的问题

1. **读取即消息**：`load_skill` 返回全文 → ToolMessage 永久驻留 messages。实测错误加载的 Skill 约占单次输入 34%，叠加错误 tool result 后优化空间 30%~50%
2. **无生命周期**：加载即永驻，UNLOADED → ACTIVE → DISCARDED 状态机缺失
3. **存储层隐患**：`_active_catalog` 为进程级全局单例，存在多会话隔离风险；包内容每次读取、无缓存
4. **冷启动信息不足**：模型面对 name-only 列表难以选择，需要 description 元数据

#### 设计目标

Skill 从「文本资源」升级为「能力包」（Capability Package = Instruction + Tool Bindings + Resources），建立完整的 Skill 生命周期管理，为能力收放提供指令层供给。

#### 设计内容

1. **Skill Registry**：catalog 保持只读，元数据含 name + description（供冷启动选择）
2. **生命周期状态机**：UNLOADED → ACTIVE → DISCARDED；支持手动 discard 与 N 轮未使用自动 expire
3. **load_skill 语义改造**（核心）：从「返回全文的消息」改为「激活 Runtime Context」——skill 内容不进 messages，由 PromptAssembler（Task 2）在每次调用前注入当前 ACTIVE skills；消息流中仅保留轻量加载事件供 trace
4. **Skill 决定 Tool Scope**：激活的 skill 声明关联工具集，供 Task 4 裁剪可见工具
5. **读取缓存**：包内容缓存，消除重复 IO

---

### Task 4：Tool 优化

**体现原则 2 · 能力层暴露管理**——Task 3 决定"激活了什么"，本任务决定"模型现在能做什么"。

#### 当前状态

`ToolRegistry` 管理注册与定义。`bind_tools` 的 tool_list 在 strategy 组装期快照生成，在 ActionNode 构造期固化为 JSON Schema，运行期不可变。

#### 存在的问题

1. **组装期快照**：运行期激活的 Skill 关联工具对模型不可见
2. **全量暴露**：MCP / Skill / 内置工具全量进入 schema——token 成本高、模型选择退化；对 Planner 类策略影响更大
3. **schema 重复构建**：`get_tools()` 每次调用全量重构，无缓存

#### 设计目标

模型可见的工具集（action space）由 Runtime 在调用期动态产出：能力激活（Task 3）决定可见工具集；Agent 不关心工具来源（内置 / MCP / Skill）。

#### 设计内容

1. **Tool Resolver**：`ToolRegistry → Skill Resolver（按 ACTIVE skills 裁剪）→ Available Tools → bind_tools`，每次调用前产出
2. **两阶段可见性**：Skill Discovery（仅暴露 name + description）→ Skill Activation（激活后可见关联工具）
3. **schema 缓存**：工具定义构建一次复用
4. **状态载体**：`active_tools` 放入 Runtime Context——扩充目前空壳的 `BaseContext`，LangGraph `context_schema` 是天然落点（现仅 `ReActContext` 存放 max_steps 等配置）；按 Task 1 原则 3，不入 State

---

### Task 5：Context 优化

**体现原则 1 + 原则 4**——组装层的视图裁剪 + 预算反馈回路。

#### 当前状态

`messages` 仅追加（`add_messages`），无计量、无裁剪、无压缩。实测基线：32 次调用、总 332,811 tokens、输入 186,620（单次 ≈5.8k）、输出 19,471、缓存命中 126,720。

#### 存在的问题

1. **无计量**：缺少 per-call token 统计，优化无触发依据与效果度量
2. **三大膨胀源**：messages 只增不减；observation / tool result 累积；Skill / MCP 描述全量常驻
3. **缓存命中只降成本不降延迟**：126,720 cached tokens 说明固定前缀大量重复，输入侧仍需治理

#### 设计目标

建立上下文生命周期管理：原则 1 的视图裁剪 + 原则 4 的计量驱动。**量化目标：单次输入从 ≈5.8k 降至 2-4k tokens/step**（32 步任务总输入控制在 100k 内）。明确不做 Memory（vector / long-term / retrieval 留待后续版本）。

#### 设计内容（按实施顺序）

1. **计量先行**：per-call token 统计（input / output / message_count / tool_count），确认增长曲线——同时落地 Harness 的可观测性职责
2. **注入前裁剪**：`system + 最近 N 轮 + summary` 的消息窗口；State 保留完整真相，裁剪只发生在组装层
3. **Tool Result 压缩**：超阈值结果自动摘要（单条最大膨胀源）
4. **历史摘要**：超 budget 时 old messages → summary（State 新增 `summary` 字段）+ recent messages
5. **协同收益**：Task 2/3 完成后 skill 详情走 Runtime Context 注入，messages 增量自然下降

兜底策略：上下文重置（清空噪音、保留关键状态）列入 v0.2.0。

---

## 开发顺序

* **Phase 1 契约定义**：Task 1（State Contract + observations 实例）→ Task 2（双生命周期 + PromptAssembler）
* **Phase 2 能力治理**：Task 3 ∥ Task 4（同一机制的两面：Skill 生命周期 + Tool Scope）
* **Phase 3 上下文管理**：Task 5（计量 → 裁剪 → 压缩 → 摘要）
* **Phase 4 回归验证**：ReAct / MCP / HITL / Skill 全链路跑通

---

## 明确排除（v0.1.0 不做）

* **Plan-and-Execute**：属 Execution Strategy，v0.2.0 作为 Harness 之上的第二个策略验证
* **Memory**（long-term / vector / retrieval）：Context Runtime 稳定前不做
* **Multi-Agent**：依赖稳定 Runtime 基础
* **新 MCP Server**：现有接入已满足验证需求

---

## v0.1.0 目标与演进

* **v0.1.0**：Harness Runtime 初版（State Contract + Prompt / Skill / Tool / Context 四个 Runtime）+ ReAct 默认策略 + MCP + HITL
* **v0.2.0**：Execution Strategy 扩展（Plan-and-Execute / Reflection）；权限梯度；上下文重置
* **v0.3.0**：Memory / Multi-Agent / Long-running Agent

完成后，echo-agent 的定位：**一个基于 LangGraph 构建的 Agent Harness Runtime——通过上下文、能力、状态三条管理主线与预算观测回路管理模型运行环境，并支持多种 Execution Strategy 扩展。**

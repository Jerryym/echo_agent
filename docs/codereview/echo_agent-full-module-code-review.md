# echo_agent 全模块 Code Review


| 项   | 内容                                                                  |
| --- | ------------------------------------------------------------------- |
| 范围  | `echo_agent/` 包内全部模块（不含 `console/`）                                 |
| 日期  | 2026-07-17（Critical#1/#2、High #3–#10 已修复并回写本文档；#7–#10 于 2026-07-19） |
| 原则  | 优先 bugs、行为回归、安全问题、缺失测试；发现项可标注修复状态                                   |


## 覆盖模块


| 模块       | 路径                                                |
| -------- | ------------------------------------------------- |
| 包入口      | `echo_agent/__init__.py`                          |
| common   | `echo_agent/common/`                              |
| prompt   | `echo_agent/prompt/`                              |
| agent    | `echo_agent/core/agent/`                          |
| llm      | `echo_agent/core/llm/`                            |
| tool     | `echo_agent/core/tool/`                           |
| model    | `echo_agent/core/model/`                          |
| graph    | `echo_agent/core/graph/`                          |
| runtime  | `echo_agent/core/runtime/`（含 HITL、interrupt）      |
| strategy | `echo_agent/core/strategy/`（含 react、plan_execute） |


---

## 总览

架构分层清晰（Agent → Graph/Strategy → LLM/Tool/HITL），ReAct + HITL 骨架与设计文档大体对齐。

**Critical #1#1 / #2#2（HITL 拒绝/取消契约）已于 2026-07-17 修复**：各 Flow / Normalize 在类内 `_resolve_status` 按 resume 协议产出 `completed`/`cancelled`，Action 对 APPROVAL 增加 `approved` 防御校验；console INPUT 取消改为 `resume({"cancelled": true})`。

**High #3#3–#5#5 已于同日修复**：工具失败归档 observations 并清空 `tool_results`；失败 ToolMessage 写入 error；`no_tool_calls` 时 Reason 可采纳 LLM 的 `in_progress`/`completed`。

**High #7#7–#10#10 已于 2026-07-19 修复**：INPUT 缺参按 `tool_call_id` 分组；非法 tool_call 形状抛错；`UserInput.text` 默认 `""`；HITL 路由收敛为单一 `Command(goto=...)`。

当前仍优先关注：剩余 Medium/Low，以及为已修复 High 项补自动化测试。

建议修复优先级：已修复项对应单测 → 其余 Medium/Low。

---

## Critical

### 1. HITL 审批拒绝后仍会执行工具 — ✅ 已修复（2026-07-17）


| 项   | 内容                                                             |
| --- | -------------------------------------------------------------- |
| 模块  | `runtime/human_in_the_loop` + `strategy/react`                 |
| 位置  | `approval_flow.py`、`normalize_result_node.py`、`action_node.py` |


**原问题**

- resume 常见载荷为 `{"approved": false}`（console / 测试均如此）。
- `ApprovalFlow` 固定写 `status="completed"`；`NormalizeResultNode` 只透传该 status，**从不**根据 `approved` 置 `cancelled`。
- Action 的 APPROVAL 分支**不读** `result["approved"]`，一律当通过并进入 tool。

**修复说明**

1. `ApprovalFlow._resolve_status`：仅当 `approved is True` 为 `completed`，否则 `cancelled`（含显式取消 / 非法载荷）。
2. `NormalizeResultNode._resolve_status` / `_resolve_approval_status`：按 type 对 `result` 二次裁定，防止 Flow 误写。
3. `ActionNode` APPROVAL 分支防御：`approved is not True` 时 `task_status=cancelled` 并清空 `tool_calls`。

**resume 协议（APPROVAL）**


| 载荷                                                       | status      |
| -------------------------------------------------------- | ----------- |
| `{"approved": true}`                                     | `completed` |
| `{"approved": false}`                                    | `cancelled` |
| `{"cancelled": true}` / `{"status": "cancelled"}` / 非法载荷 | `cancelled` |


---

### 2. HITL `cancelled` 状态机基本不可达 — ✅ 已修复（2026-07-17）


| 项   | 内容                                                                                       |
| --- | ---------------------------------------------------------------------------------------- |
| 模块  | `runtime/human_in_the_loop`（+ console 取消入口）                                              |
| 位置  | `input_flow.py`、`approval_flow.py`、`normalize_result_node.py`；`console/ui/mainwindow.py` |


**原问题**

Input/Approval 在 resume 后一律 `status="completed"`。Normalize 的「非 completed → cancelled」分支实际上走不到。Action 里对 `hitl_response.status == "cancelled"` 的处理成死代码。

**修复说明**

1. `InputFlow._resolve_status` / `ApprovalFlow._resolve_status`：显式取消与非法载荷映射为 `cancelled`。
2. `NormalizeResultNode` 按 `HITLType` 对 `result` 二次解析，保证 `cancelled` 可达并写入 `HITLOutput`。
3. console `_on_hitl_cancelled` 改为 `resume({"cancelled": true})`，避免取消后图停在 interrupt。

**resume 协议（INPUT）**


| 载荷                                                                      | status      |
| ----------------------------------------------------------------------- | ----------- |
| `{"values": {...}}`                                                     | `completed` |
| `{"cancelled": true}` / `{"status": "cancelled"}` / 非 dict / 缺 `values` | `cancelled` |


---

## High

### 3. 工具失败后 `tool_results` 不清理，Reason 被永久短路 — ✅ 已修复（2026-07-17）


| 项   | 内容                                    |
| --- | ------------------------------------- |
| 模块  | `strategy/react`                      |
| 位置  | `reason_node.py` `_handle_tool_error` |


**原问题**

`_has_tool_error` 为真时只加 `retry_count`，不调用 LLM，也**不清空** `tool_results`。`tool_results` 仅在 `ToolNode` 成功路径被覆盖。

若 Action 随后 `no_tool_calls` 回到 Reason，仍会命中旧失败结果，无法正常推理，直到 retry 耗尽。

**修复说明**

`_handle_tool_error` 先将失败结果写入 `observations`，再清空 `tool_calls` 与 `tool_results`，避免下一轮 Reason 再次被 `_has_tool_error` 短路。

---

### 4. 失败工具写入 `ToolMessage` 内容为 `null` — ✅ 已修复（2026-07-17）


| 项   | 内容                                    |
| --- | ------------------------------------- |
| 模块  | `tool`                                |
| 位置  | `tool_node.py` `_build_tool_messages` |


**原问题**

失败时 `result=None`、`error=...`，但 content 只序列化 `result` → `"null"`。Reason 能从 `tool_results` 看到错误，但 messages 历史对后续 LLM 具有误导性。

**修复说明**

成功写 `json.dumps(result)`；失败写 `tool_result.error`（缺省 `"unknown error"`），不再产生 `"null"`。

---

### 5. `no_tool_calls` 时 Reason 无法标 `completed`（纯对话必烧满 retry） — ✅ 已修复（2026-07-17）


| 项   | 内容                                |
| --- | --------------------------------- |
| 模块  | `strategy/react`                  |
| 位置  | `reason_node.py` `_handle_result` |


**原问题**

`_handle_result` 仅在 `task_status == "in_progress"` 时采纳 LLM 的 status。Action 无工具时写成 `no_tool_calls` 后，Reason 即使判断可结束也无法改成 `completed`，只能靠 `retry_count` 顶满再进 Final。

**修复说明**

`task_status in ("in_progress", "no_tool_calls")` 时均采纳 LLM 输出的 `in_progress` / `completed`，允许无工具场景下正常结束或继续，而不再被 `no_tool_calls` 锁死。

> 注：Reason 结构化 prompt 仍强调「无 confirming observations 勿 completed」；若纯对话仍偏 `in_progress`，属 prompt/产品策略问题，与本次状态机锁死修复正交。

---

### 6. APPROVAL 通过路径未校验 `approved`（与 #1 同源） — ✅ 已修复（2026-07-17）


| 项   | 内容                                             |
| --- | ---------------------------------------------- |
| 模块  | `strategy/react`                               |
| 位置  | `action_node.py` `_handle_existing_tool_calls` |


**原问题**

即便 Normalize 修好 status，Action 也应防御性检查 `approved`，避免协议漂移再次放行。

**修复说明**

APPROVAL 分支在 `status != cancelled` 时仍校验 `result.approved is True`；否则清空 `tool_calls` 并 `task_status=cancelled`。

---

### 7. `_fill_tool_calls` 按参数名全局填充，多工具会串参 — ✅ 已修复（2026-07-19）


| 项   | 内容                                                  |
| --- | --------------------------------------------------- |
| 模块  | `strategy/react`                                    |
| 位置  | `action_node.py` `_fill_tool_calls`、`_build_fields` |


**原问题**

缺参字段只用 `param` 名，resume 的 `values` 也按名匹配。两个 tool 都缺 `order_id` 时会互相覆盖/共享。

**修复说明**

1. `_build_fields` 返回 `dict[tool_call_id, list[InterruptField]]`，payload.`fields` 按 call 分组。
2. `_fill_tool_calls` 只读取 `values[tool_call_id][param]`，互不串写。
3. console / 交互脚本 resume 协议同步为嵌套 `values`。

**resume 协议（INPUT 缺参）**


| 载荷                                                               | 说明        |
| ---------------------------------------------------------------- | --------- |
| `{"values": {"<tool_call_id>": {"<param>": <value>, ...}, ...}}` | 按 call 填参 |


---

### 8. LLM tool_call 非 dict/ToolCall 形状被静默丢弃 — ✅ 已修复（2026-07-19）


| 项   | 内容                                      |
| --- | --------------------------------------- |
| 模块  | `llm`                                   |
| 位置  | `llm_client.py` `_normalize_tool_calls` |


**原问题**

只认 `ToolCall` / `dict`；其它形状在循环中被静默跳过。规范化结果为空时 Action 当作「无工具」，进入错误/重试路径，难以排查。

**修复说明**

无法识别的 tool_call 形状改为抛 `LLMResponseDecodeError`（`message="invalid tool call"`），不再静默丢弃。

---

### 9. `UserInput.text: str = None` 类型不合法 — ✅ 已修复（2026-07-19）


| 项   | 内容         |
| --- | ---------- |
| 模块  | `model`    |
| 位置  | `input.py` |


**原问题**

默认 `None` 可进 `HumanMessage(content=None)`，提供商行为未定义；注解 `str = None` 类型不合法。

**修复说明**

`text: str = Field(default="")`，`to_human_message()` 始终得到字符串 content。

---

### 10. ReAct HITL 节点存在双路由，实现语义错误 — ✅ 已修复（2026-07-19）


| 项   | 内容                                                                                  |
| --- | ----------------------------------------------------------------------------------- |
| 模块  | `strategy/react`                                                                    |
| 位置  | `action_node.py`（`_router` / `Command(goto=...)`）；`react_strategy.py`（`build` 仅静态边） |


**原问题**

进入 HITL 叠加了两套互斥的路由机制：

1. **Command 路由**：`ActionNode` 返回 `Command(..., goto="HITL")`。
2. **条件边路由**：`ReActStrategy.build` 对 action 注册 `add_conditional_edges(..., self._action_router)`，`task_status == "human_in_the_loop"` 时再返回 `"HITL"`。

同一「action → HITL」边被两套机制同时声明，路由职责不唯一，后续改边或换 LangGraph 版本时行为不可预期。

**修复说明（方案 A）**

1. `ReActStrategy.build` 删除 `_action_router` / `add_conditional_edges`；仅保留 START→reason、HITL→action、tool→reason、final→END 等静态边。
2. Action / Reason 统一经节点内 `_router` → `_select_node`，以 `Command(update=..., goto=...)` 作为唯一跳转权威。

---

## Medium


| #   | 模块                      | 问题                                                                                                          |
| --- | ----------------------- | ----------------------------------------------------------------------------------------------------------- |
| 11  | `strategy/plan_execute` | `PlanExecuteStrategy` 为 stub（`build`/`as_node` 为 `pass`），工厂一创建即不可用                                          |
| 12  | `strategy/react`        | `to_strategy_context()` 恒返回空 `ReActContext()`；路由用 strategy 上 `_max_steps`/`_retry_max_count`，与 context 字段脱节 |
| 13  | `strategy/react`        | `task_status=failed` 时 `_action_router` 不识别，可能先绕到 reason 再 final（多余 LLM）                                    |
| 14  | `strategy/react`        | `observations: list[str]` 与 `_build_observations` 的 `list[dict]` 混用                                         |
| 15  | `llm`                   | `_build_messages` 对未知 `user_input` 类型静默不加 user turn                                                         |
| 16  | `llm`                   | `api_key` 明文；`parallel_tool_calls=True` 写死                                                                  |
| 17  | `llm`                   | `_parse_structured_response` 捕获并重包已有的 `LLMResponseDecodeError`                                              |
| 18  | `tool`                  | `ToolRegistry` 非线程安全；`register` 静默覆盖；`unregister` 缺 key 抛错                                                  |
| 19  | `tool`                  | `ToolExecutor` 无 timeout/取消传播                                                                               |
| 20  | `agent`                 | `resume` 接受任意 `dict`，无按 interrupt 类型校验                                                                      |
| 21  | `agent`                 | `invoke` 注解为 `type[BaseInput]`，实际要的是实例                                                                      |
| 22  | `graph`                 | `add_node` 同名静默覆盖；无环/悬空边校验                                                                                  |
| 23  | `runtime/HITL`          | 嵌套`HITLSubgraph.invoke` 依赖 checkpointer 正确配置，否则 interrupt 难向上冒泡（文档已提醒，实现无防护）                                |
| 24  | `model`                 | `attachments` 暴露但未实现；`Role.TOOL` 转换 `NotImplementedError`                                                   |


---

## Low

- 大量 `print` 调试日志（ReAct / HITL / Tool），生产难关、易泄参。
- `ActionResult` 死代码；`emums.py` 拼写错误。
- `PromptLoader` 仅 `.md`；顶层 `__init__` 未导出 tool/HITL。
- `FinalNode` 未把 `state.messages` 作为 `history` 传入，仅塞进 dict user_input。
- `Agent` 编译后不再使用 `_agent_config`。
- `ToolNode` / `common/debug` 使用裸 `print`，无日志级别控制。

---

## 分模块结论


| 模块                        | 评估                                                                                     |
| ------------------------- | -------------------------------------------------------------------------------------- |
| **agent**                 | 会话/`thread_id` 清晰；resume 校验与类型注解偏弱                                                     |
| **llm**                   | 异常分层好；非法 tool_call 形状已显式抛错；密钥/`parallel_tool_calls` 仍待加强                               |
| **tool**                  | 执行失败不炸图是优点；ToolMessage/超时/注册表并发有坑                                                      |
| **model**                 | DTO 简洁；`UserInput.text` 已合法默认；附件/TOOL role 仍不完整                                        |
| **graph**                 | 对 LangGraph 封装干净；缺编译期校验                                                                |
| **runtime/HITL**          | 结构清楚；**拒绝/取消 status 契约已落地**（各 Flow / Normalize 类内 `_resolve_status`）                   |
| **strategy/react**        | 主路径完整；HITL 拒绝 / tool_results / no_tool_calls / 多工具缺参 / **单一 Command 路由**已修；仍有 Medium 项 |
| **strategy/plan_execute** | 未实现                                                                                    |
| **common/prompt**         | 可用；日志与加载约束偏简单                                                                          |


### 模块优点（保留）

1. **清晰分层**：Agent（编排）→ LLM（模型 I/O）→ Tool（执行）→ Model（DTO）分离良好。
2. **LLM 异常分类**：`LLMInitializeError` / `LLMInvokeError` / `LLMResponseDecodeError` 便于调用方处理。
3. **工具失败包容**：`ToolExecutor` 将异常转为 `ToolResult`，不直接炸图。
4. **ToolDefinition 辅助方法**：`required_parameters` / `requires_approval` / `get_parameter_description` 支撑 HITL 与校验。
5. **PromptLoader**：相对包根解析路径，校验扩展名与存在性。
6. **Agent 会话模型**：invoke / stream / resume / get_state 的 `thread_id` 接线一致。

---

## 测试缺口

现有 `tests/` 多为交互脚本；`echo_agent` 核心几乎无自动化断言。

### 建议优先补的用例

1. APPROVAL `approved=false` → 不得执行 tool，应 `cancelled` → final。
2. 工具失败 → ToolMessage 含 error；Reason 清空/归档后可继续推理。
3. 纯对话 / `no_tool_calls` → 能 `completed` 或有限步进 final，而非固定烧满 retry。
4. 多 tool 同名缺参填充不串写。
5. `_normalize_tool_calls` 非法形状抛 `LLMResponseDecodeError`（#8 已修，建议补单测）。
6. `UserInput` 默认空串与 `to_human_message()` 边界（#9 已修，建议补单测）。
7. `ToolRegistry` register / unregister / 重复注册行为。
8. `PromptLoader.load` 缺文件 / 错误扩展名。
9. HITL 进入路径：缺参/审批仅经 Action `_router` → `Command(goto="HITL")`；`build` 不得再对 action 注册条件边（#10 已修，建议补单测）。

### 覆盖现状（概览）


| 区域                    | 自动化测试                   | 缺口                                      |
| --------------------- | ----------------------- | --------------------------------------- |
| `core/agent`          | 多为手动脚本                  | 输入校验、resume、错误类型                        |
| `core/llm`            | 多为手动                    | `_normalize_tool_calls` 非法形状、结构化解析错误    |
| `core/tool`           | 间接                      | 失败 ToolMessage、registry、executor        |
| `core/strategy/react` | 间接/手动                   | 状态机、HITL 拒绝、Command 单一路由回归、tool_results |
| `core/runtime/HITL`   | 有部分`test_hitl_subgraph` | Normalize 对`approved=false` 的契约         |
| `plan_execute`        | 无                       | 整模块未实现                                  |


---

## 建议修复顺序

1. ~~**P0**：Critical #1#1、#2#2（HITL 拒绝/取消契约）。~~ ✅ 已完成（含 High #6 防御校验）
2. ~~**P0**：High #3#3（`tool_results` 粘滞）、#4#4（失败 ToolMessage）。~~ ✅ 已完成
3. ~~**P1**：High #5#5（`no_tool_calls` 完成路径）。~~ ✅ 已完成
4. ~~**P0**：High #10（HITL 双路由收敛为单一 `Command`）。~~ ✅ 已完成
5. ~~**P1**：High #7（多工具同名缺参串写）。~~ ✅ 已完成
6. ~~**P1**：High #8、#9（LLM 规范化、`UserInput`）。~~ ✅ 已完成
7. **P2**：Medium 项与 PlanExecute stub 决策（实现或从工厂移除）。
8. **同步**：为已修复 Critical/High 项补自动化测试。

---

## 参考

- 设计文档：`docs/strategy/react/react v0.1.1 设计文档.md`
- HITL 测试说明：`tests/docs/HITL Subgraph 测试案例文档.md`


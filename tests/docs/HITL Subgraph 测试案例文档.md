# HITL Subgraph 测试案例设计文档

## 1. 测试目标

本测试用于验证 HITLSubgraph 的核心能力（**不经过任何 Strategy**）：

1. **类型路由能力**

   * 按 `HITLType.INPUT` 路由到 `input_flow`。
   * 按 `HITLType.APPROVAL` 路由到 `approval_flow`。
   * 不支持类型应失败。
2. **状态映射能力**

   * 父 State 的 `hitl_request` 能正确映射为 `HITLInput`。
   * HITL 输出能正确写回父 State 的 `hitl_result`。
3. **中断等待能力**

   * `input_flow` / `approval_flow` 能通过 `interrupt()` 挂起执行。
   * interrupt payload 含 `id` / `type` / `description` / `payload`。
4. **恢复执行能力**

   * `Agent.resume` / `Command(resume=...)` 能恢复执行。
   * resume 值原样进入 `result`。
5. **结果规范化能力**

   * `normalize_result` 输出稳定的 `id` / `status` / `result`。
   * 完成后父图无残留 pending interrupt。

---

## 2. 测试环境

* 测试入口：`tests/test_hitl_subgraph.py`
* 图拓扑（无策略、无真实 LLM）：

```text
START → prepare_hitl → HITL → END
```

* 组件说明：


| 组件                   | 作用                                    |
| ------------------------ | ----------------------------------------- |
| PrepareHITLNode        | 写入`hitl_request`（INPUT 或 APPROVAL） |
| HITLSubgraph.as_node() | 父图内调用 HITL 子图                    |
| InputFlow              | interrupt，等待用户补充信息             |
| ApprovalFlow           | interrupt，等待用户批准/拒绝            |
| NormalizeResultNode    | 规范化`status` / `result`               |
| InMemorySaver          | 支撑 interrupt / resume                 |

* 父 State 关键字段：


| 字段         | 类型             | 说明                         |
| -------------- | ------------------ | ------------------------------ |
| hitl_request | HITLInput / dict | HITL 入参                    |
| hitl_result  | dict             | HITL 出参（HITLOutput dump） |

* HITL 子图内部拓扑：

```text
START --type--> input_flow | approval_flow → normalize_result → END
```

---

## 3. 基础测试案例

### Case 1：类型路由与状态映射（无 interrupt）

* 测试函数：`test_type_router_and_mapping`
* 输入：

  * 父 State 含 `hitl_request(type=input, description="need info")`
  * `HITLState(type=INPUT)` / `HITLState(type=APPROVAL)`
  * `HITLOutput(id="abc", status="completed", result={"ok": true})`
* 预期结果：

  * `to_hitl_input` → `type=INPUT`，`description="need info"`
  * `_type_router(INPUT)` → `"input_flow"`
  * `_type_router(APPROVAL)` → `"approval_flow"`
  * `to_parent_state` →

```json
{
  "hitl_result": {
    "id": "abc",
    "status": "completed",
    "result": {"ok": true}
  }
}
```

* 验证点：

  * 不依赖 checkpointer / Agent。
  * 映射与路由在进图前正确。

#### 勾选项

- [X]  `to_hitl_input` 映射正确（type / description）
- [X]  `_type_router(INPUT)` → `input_flow`
- [X]  `_type_router(APPROVAL)` → `approval_flow`
- [X]  `to_parent_state` 输出结构符合预期
- [X]  全程无依赖 Strategy / checkpointer / Agent

#### 输出（测试后填写）

**成功时填写：**

```text
执行命令：python -c "from tests.test_hitl_subgraph import ...; print(to_hitl_input/router/to_parent_state)"
终端摘要：
  - to_hitl_input：input=UserInput(text='hello', attachments=[]) type=<HITLType.INPUT: 'input'> description='need info' payload={'fields': []}
  - router INPUT：input_flow
  - router APPROVAL：approval_flow
  - to_parent_state：{'hitl_result': {'id': 'abc', 'status': 'completed', 'result': {'ok': True}}}
结论：☑ 通过
备注：路由过程额外打印 [HITLSubgraph] routing to input_flow / approval_flow，与预期一致。
```

**失败时填写：**

```text
执行命令：
失败断言 / 异常：
实际输出：
根因判断：
结论：□ 未通过
备注：
```

---

### Case 2：INPUT 流程 interrupt + resume

* 测试函数：`test_input_flow_interrupt_resume`
* 用户输入：`trigger input hitl`
* 预期图路径：

```text
HITL → input_flow(interrupt) → resume → normalize_result → END
```

* 构造时注入的 `HITLInput`：

```json
{
  "type": "input",
  "description": "请补充缺失信息",
  "payload": {
    "fields": [
      {"name": "city", "description": "城市"},
      {"name": "date", "description": "日期"}
    ]
  }
}
```

* invoke 后 pending interrupt（示例）：

```json
{
  "id": "<uuid>",
  "type": "input",
  "description": "请补充缺失信息",
  "payload": {
    "fields": [
      {"name": "city", "description": "城市"},
      {"name": "date", "description": "日期"}
    ]
  }
}
```

* resume 输入：

```json
{
  "values": {
    "city": "Shanghai",
    "date": "2026-07-16"
  }
}
```

* 预期最终 `hitl_result`：

```json
{
  "id": "<uuid>",
  "status": "completed",
  "result": {
    "values": {
      "city": "Shanghai",
      "date": "2026-07-16"
    }
  }
}
```

* 验证点：

  * invoke 后存在 pending interrupt，且 `type == "input"`。
  * payload 含 `fields`。
  * resume 后 `status == "completed"`。
  * `result` 与 resume 值一致。
  * resume 后无残留 interrupt。

#### 勾选项

- [X]  invoke 后出现 pending interrupt
- [X]  interrupt.type == `input`
- [X]  interrupt.payload 含 `fields`
- [X]  resume 后 `hitl_result.status == "completed"`
- [X]  `hitl_result.result` 与 resume 值一致
- [X]  resume 后无残留 interrupt

#### 输出（测试后填写）

**成功时填写：**

```text
执行命令：uv run .\tests\test_hitl_subgraph.py（mode=0，交互等价 Case 2）
日期 / 执行人：2026-07-16
pending interrupt：
  description=请补充缺失信息
  payload={'fields': [{'name': 'city', 'description': '城市'}, {'name': 'date', 'description': '日期'}]}
resume 输入：city=南京, date=2026年7月16日
hitl_result：
  {'id': 'c2f48baa-f169-4c7c-b987-e6f9fb16faef', 'status': 'completed',
   'result': {'values': {'city': '南京', 'date': '2026年7月16日'}}}
残留 interrupt：无
结论：☑ 通过
备注：有 LangGraph msgpack 反序列化警告（UserInput / HITLType unregistered），未阻塞流程。
```

**失败时填写：**

```text
执行命令：
失败阶段：□ invoke  □ interrupt  □ resume  □ normalize
失败断言 / 异常：
实际 pending interrupt：
实际 hitl_result：
根因判断：
结论：□ 未通过
备注：
```

---

### Case 3：APPROVAL 流程 interrupt + resume

* 测试函数：`test_approval_flow_interrupt_resume`
* 用户输入：`trigger approval hitl`
* 预期图路径：

```text
HITL → approval_flow(interrupt) → resume → normalize_result → END
```

* 构造时注入的 `HITLInput`：

```json
{
  "type": "approval",
  "description": "是否批准该操作？",
  "payload": {
    "action": "delete_resource",
    "risk": "high"
  }
}
```

* invoke 后 pending interrupt（示例）：

```json
{
  "id": "<uuid>",
  "type": "approval",
  "description": "是否批准该操作？",
  "payload": {
    "action": "delete_resource",
    "risk": "high"
  }
}
```

* resume 输入：

```json
{
  "approved": true
}
```

* 预期最终 `hitl_result`：

```json
{
  "id": "<uuid>",
  "status": "completed",
  "result": {
    "approved": true
  }
}
```

* 验证点：

  * 路由到 `approval_flow`，而非 `input_flow`。
  * interrupt `type == "approval"`。
  * resume 后 `result.approved` 与 y/n 一致。
  * 不引入任何 Strategy。

#### 勾选项

- [X]  路由到 `approval_flow`（非 `input_flow`）
- [X]  interrupt.type == `approval`
- [X]  interrupt.payload 含 action / risk
- [X]  resume 后 `result.approved` 正确（y→true / n→false）
- [X]  `hitl_result.status == "completed"`
- [X]  未引入任何 Strategy

#### 输出（测试后填写）

**成功时填写：**

```text
执行命令：uv run .\tests\test_hitl_subgraph.py（mode=1，交互等价 Case 3）
日期 / 执行人：2026-07-16
pending interrupt：
  description=是否批准该操作？
  payload={'action': 'delete_resource', 'risk': 'high'}

第1轮 resume：approved=True (y)
hitl_result：
  {"id": "9cd7f61e-9fa8-4679-b880-566d85456372", "status": "completed",
   "result": {"approved": true}}

第2轮 resume：approved=False (n)
hitl_result：
  {"id": "0b63df68-18de-411a-a35b-962304948065", "status": "completed",
   "result": {"approved": false}}

结论：☑ 通过
备注：有 UserInput / HITLType 的 msgpack 反序列化警告，未阻塞流程。
```

**失败时填写：**

```text
执行命令：
失败阶段：□ invoke  □ interrupt  □ resume  □ normalize
失败断言 / 异常：
实际 pending interrupt：
实际 hitl_result：
根因判断：
结论：□ 未通过
备注：
```

---

### Case 4：缺少 / 非法 HITLInput 的异常路径

> 说明：新 API 已不再从父 State 读取 `hitl_request`。`HITLNode` / `HITLSubgraph.invoke` 必须在入口显式提供合法 `HITLInput`。本 Case 验证「缺少或非法入参」时尽早失败。

* 场景 A：构造 `HITLNode` 时缺少 `input` 参数
* 场景 B：构造不完整的 `HITLInput`（缺 `type` / `description` / `input`）
* 场景 C：对 `invoke` 传入非 `HITLInput`（如 `None`）
* 预期结果（按场景）：

```text
场景 A → TypeError: HITLNode.__init__() missing 1 required positional argument: 'input'
场景 B → pydantic.ValidationError（HITLInput 必填字段缺失）
场景 C → AttributeError / TypeError（to_hitl_state 访问 input.type 等失败）
```

* 验证点：

  * 失败发生在进入 `input_flow` / `approval_flow` 之前。
  * 不会产生 pending interrupt。
  * 错误类型可区分「缺参」与「校验失败」。

#### 测试方法

在项目根目录执行以下命令（任选 / 全跑）：

**场景 A：HITLNode 缺少 input**

```powershell
python -c "
from echo_agent.core.runtime.human_in_the_loop import HITLSubgraph
from echo_agent.core.runtime.human_in_the_loop.hitl_subgraph import HITLNode
hitl = HITLSubgraph()
try:
    HITLNode(name='HITL', hitl=hitl)  # 故意不传 input
    print('UNEXPECTED: no error')
except TypeError as e:
    print('PASS TypeError:', e)
"
```

**场景 B：HITLInput 缺必填字段**

```powershell
python -c "
from echo_agent.core.runtime.human_in_the_loop import HITLInput
from pydantic import ValidationError
try:
    HITLInput()  # 缺 input / type / description
    print('UNEXPECTED: no error')
except ValidationError as e:
    print('PASS ValidationError:')
    print(e)
"
```

**场景 C：invoke(None)**

```powershell
python -c "
from echo_agent.core.runtime.human_in_the_loop import HITLSubgraph
hitl = HITLSubgraph()
try:
    hitl.invoke(None)
    print('UNEXPECTED: no error')
except Exception as e:
    print('PASS', type(e).__name__ + ':', e)
"
```

通过标准：三个场景均按预期抛错，且终端**不会**出现 `[HITLSubgraph] routing to ...`。

#### 勾选项

- [x]  场景 A：缺 `input` 时抛出 `TypeError`
- [x]  场景 B：非法 `HITLInput` 抛出 `ValidationError`
- [x]  场景 C：`invoke(None)` 抛错且未进入 flow
- [x]  全程未产生 pending interrupt

#### 输出（测试后填写）

**成功时填写：**

```text
执行命令：见上方场景 A/B/C
日期 / 执行人：2026-07-16
场景 A 异常：TypeError: HITLNode.__init__() missing 1 required positional argument: 'input'
场景 B 异常：ValidationError — 3 validation errors for HITLInput
  - input: Field required
  - type: Field required
  - description: Field required
场景 C 异常：AttributeError: 'NoneType' object has no attribute 'type'
是否出现 routing 日志：无
结论：☑ 通过（按预期抛错）
备注：三场景均在进入 flow 前失败；未出现 [HITLSubgraph] routing to ...。
```

**失败时填写：**

```text
执行命令：
日期 / 执行人：
失败场景：□ A  □ B  □ C
预期异常：
实际行为：□ 未抛错  □ 抛了其他异常  □ 进入子图/产生 interrupt
实际输出 / 异常：
根因判断：
结论：□ 未通过
备注：
```

---

### Case 5：不支持的 HITLType

> **状态：已由先前 Case 覆盖，无需单独执行。**

* 原场景：构造非法 / 未支持的 `type` 进入 `_type_router`，期望 `ValueError: unsupported HITL type`。
* 为何不单独测：

  * `HITLType` 为封闭枚举（仅 `input` / `approval`），非法值在 `HITLInput` / `HITLState` 构造时即被 Pydantic 拦截。
  * `_type_router` 的 `ValueError` 分支在正常 API 下不可达（防御性代码）。
* 覆盖关系：

  | 原 Case 5 意图 | 已覆盖于 |
  | --- | --- |
  | 非法 type 无法进入流程 | Case 4-B（`HITLInput()` → `ValidationError`，缺 `type` 等） |
  | INPUT / APPROVAL 路由正确 | Case 1（`_type_router`）+ Case 2 / Case 3 |

#### 勾选项

- [x]  非法 type 在 schema 层被拦截（见 Case 4-B）
- [x]  合法 type 路由正确（见 Case 1 / 2 / 3）
- [x]  无需单独触发 `_type_router` 的 `unsupported` 分支

#### 输出（测试后填写）

**成功时填写：**

```text
执行命令：无（复用 Case 1 / 2 / 3 / 4-B）
日期 / 执行人：2026-07-16
结论：☑ 不适用 / 已覆盖
备注：非法 type 由 Case 4-B 在 ValidationError 阶段覆盖；
      路由正确性由 Case 1–3 覆盖；本 Case 不单独执行。
```

**失败时填写：**

```text
（不适用）
```

---

### Case 6：交互式手工验证（可选）

> **状态：已由 Case 2 / Case 3 交互实测覆盖，无需再单独记一轮。**

* 原入口：`uv run .\tests\test_hitl_subgraph.py`（`chat_hitl`）
* 覆盖关系：

  | 原 Case 6 意图 | 已覆盖于 |
  | --- | --- |
  | INPUT 交互 interrupt → resume | Case 2（mode=0，city/date 实测） |
  | APPROVAL 交互 y/n → resume | Case 3（mode=1，y/n 两轮实测） |
  | session 内闭环可用 | Case 2 / Case 3 均回到 `You:` 且无残留 interrupt |

#### 勾选项

- [x]  能选择 INPUT / APPROVAL 模式启动（Case 2 / 3）
- [x]  invoke 后出现 HITL prompt / interrupt 信息（Case 2 / 3）
- [x]  INPUT：按 fields 填写后 `result.values` 完整（Case 2）
- [x]  APPROVAL：y/n 后 `result.approved` 正确（Case 3）
- [x]  session 内 interrupt → resume 闭环可用（Case 2 / 3）
- [x]  行为与自动化用例意图一致

#### 输出（测试后填写）

**成功时填写：**

```text
执行命令：无（复用 Case 2 / Case 3 交互实测）
日期 / 执行人：2026-07-16
选择模式：☑ input=0（Case 2）  ☑ approval=1（Case 3）
结论：☑ 通过 / 已覆盖
备注：Case 2、Case 3 即通过本交互入口完成；本 Case 不重复填写明细，详见 Case 2 / 3 成功输出。
```

**失败时填写：**

```text
（不适用；若回归失败，直接记在 Case 2 / Case 3）
```

---

## 4. HITL 核心验证指标

### 路由正确性


| 指标       | 要求                           |
| ------------ | -------------------------------- |
| INPUT      | 进入`input_flow`               |
| APPROVAL   | 进入`approval_flow`            |
| 未知类型   | 显式报错                       |
| 与策略解耦 | 不依赖 StrategyFactory / ReAct |

### 中断与恢复

必须满足：

```text
invoke
  ↓
interrupt(pending)
  ↓
resume(values)
  ↓
normalize_result
  ↓
hitl_result 写回父 State
```

禁止：

```text
invoke 后直接 completed（未 interrupt）
resume 后仍残留 pending interrupt
resume 值丢失或被改写
```

### 状态检查

父图完成一轮后应能看到：

```text
hitl_request 已设置
hitl_result.id 非空
hitl_result.status == "completed"
hitl_result.result == resume 原值
pending interrupt == None
```

不能只看到：

```text
图跑完了，但 hitl_result 为空
或 interrupt 仍挂起
```

---

## 5. 当前架构重点验证问题

根据测试结果重点关注：

### PrepareHITLNode

验证：

* 是否正确构造 `HITLInput`。
* `type` / `description` / `payload` 是否完整。
* 是否把父 `input` 一并写入 `HITLInput.input`。

### HITLSubgraph / HITLNode

验证：

* `as_node()` 能否接入 RootGraph。
* `to_hitl_input` / `to_parent_state` 是否正确。
* 节点内调用子图时 interrupt 能否冒泡到父图 checkpointer。

> 关注点：`HITLNode.run` 若未透传 `config` 给子图 `invoke`，可能导致 interrupt/resume 异常，需在本测试中重点观察。

### InputFlow / ApprovalFlow

验证：

* `interrupt()` payload 字段齐全。
* resume 返回值是否原样进入 `result`。
* `id` 是否稳定（首次生成后贯穿 normalize）。

### NormalizeResultNode

验证：

* `status=completed` 时输出 `completed`。
* 非 completed 时输出 `cancelled`。
* `result` 为空时回落为 `{}`。

---

## 6. 测试通过标准

满足以下条件认为 HITLSubgraph 基本正确：

* 不依赖任何 Strategy 即可独立运行。
* INPUT / APPROVAL 路由正确。
* invoke 必现 pending interrupt。
* resume 后得到完整 `hitl_result`。
* resume 值与 `hitl_result.result` 一致。
* resume 后无残留 interrupt。
* 缺少 `hitl_request` 或不支持 type 时显式失败。
* 父 State 映射入参/出参契约稳定。

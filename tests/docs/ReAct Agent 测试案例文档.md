# ReAct Agent 测试案例设计文档

## 1. 测试目标

本测试用于验证 ReAct Agent 的核心能力：

1. **工具选择能力**

   * 根据用户意图选择正确工具。
   * 避免无关工具调用。
2. **多步任务规划能力**

   * 支持连续工具调用。
   * 根据前一步工具结果决定下一步动作。
3. **工具结果理解能力**

   * 正确读取 ToolMessage。
   * 基于工具结果进行下一步推理。
4. **任务完成判断能力**

   * 信息充分后停止调用工具。
   * 输出最终结果。
5. **多轮上下文能力**

   * 保留历史消息。
   * 支持基于前序结果继续推理。

---

## 2. 测试环境

* 工具列表：


| 工具                     | 功能         |
| -------------------------- | -------------- |
| get_user_profile         | 查询用户信息 |
| get_order_detail         | 查询订单详情 |
| query_inventory          | 查询商品库存 |
| query_product_price      | 查询商品价格 |
| create_refund            | 创建退款申请 |
| get_refund_status        | 查询退款状态 |
| query_salary             | 查询员工薪资 |
| currency_exchange        | 汇率转换     |
| query_weather            | 查询天气     |
| generate_business_report | 生成业务报告 |

---

## 3. 基础测试案例

### Case 1：单工具查询

* 用户输入：查询用户u001的信息。
* 预期工具调用：get_user_profile。
* 执行结果：

```json
{
  "name": "张伟",
  "department": "研发部",
  "level": "P7",
  "status": "active"
}
```

* 预期最终回答：用户u001为张伟，属于研发部，职级为P7。
* 验证点：

  * 是否选择正确工具。
  * 是否调用一次后结束。
  * 是否没有重复调用。

### Case 2：双工具链查询

* 用户输入： 	。
* 预期工具调用：先调用 get_user_profile，再调用 get_order_detail。
* 执行结果：

```json
{
  "name": "张伟",
  "department": "研发部",
  "level": "P7",
  "status": "active"
}
```

```json
{
  "order_id": "order_1001",
  "amount": 2999,
  "status": "paid"
}
```

* 预期最终回答：用户u001为张伟，属于研发部，职级为P7；订单order_1001金额为2999元，状态为paid。
* 验证点：

  * 是否能够根据第一个工具结果继续下一步。
  * 是否保持历史 ToolMessage。
  * 是否不会重新查询已经获得的信息。

### Case 3：条件工具调用

* 用户输入：查询订单order_1001，如果金额超过2000，创建退款申请。
* 预期工具调用：先调用 get_order_detail，再根据金额判断是否调用 create_refund。
* 执行结果：

```json
{
  "order_id": "order_1001",
  "amount": 2999,
  "status": "paid"
}
```

```json
{
  "refund_id": "refund_1",
  "status": "created"
}
```

* 预期最终回答：订单order_1001金额为2999元，已超过2000元，退款申请已创建，退款单号为refund_1。
* 验证点：

  * 不允许模型直接声称退款完成。
  * 必须真实调用 create_refund。
  * 工具结果必须进入最终回答。

### Case 4：商品购买判断

* 用户输入：我准备买 iphone15，预算7000人民币，帮我判断是否可以买，并告诉我库存。
* 预期工具调用：先调用 query_product_price，再调用 query_inventory。
* 执行结果：

```json
{
  "product": "iphone15",
  "price": 5999
}
```

```json
{
  "product": "iphone15",
  "stock": 12
}
```

* 预期最终回答：iphone15价格为5999元，低于你的预算7000元，可以购买；当前库存为12台。
* 验证点：

  * 是否能够结合多个工具结果。
  * 是否能够判断条件。
  * 是否在信息完整后停止。

重点验证：

```text
不能:
price -> inventory -> price -> inventory
```

### Case 5：用户消费分析

* 用户输入：帮我分析用户u001的消费能力，查询他的职位、查询工资、查询订单金额，然后生成分析报告。
* 预期工具调用：先调用 get_user_profile，再调用 query_salary，再调用 get_order_detail，最后调用 generate_business_report。
* 执行结果：

```json
{
  "name": "张伟",
  "department": "研发部",
  "level": "P7",
  "status": "active"
}
```

```json
{
  "user_id": "u001",
  "salary": 28000
}
```

```json
{
  "order_id": "order_1001",
  "amount": 2999,
  "status": "paid"
}
```

```json
{
  "report_id": "report_001",
  "summary": "用户消费能力分析完成"
}
```

* 预期最终回答：已完成用户u001的消费能力分析，报告已生成，报告编号为report_001。
* 验证点：

  * 多工具结果融合。
  * 参数是否来自历史结果。
  * 是否能调用报告生成工具。

### Case 6：异常处理

* 用户输入：查询订单order999，如果不存在，告诉我应该怎么办。
* 预期工具调用：调用 get_order_detail。
* 执行结果：

```json
{
  "error": "order not found"
}
```

* 预期最终回答：订单order999不存在，建议确认订单编号后重新查询。
* 验证点：

  * 工具异常是否正常处理。
  * 不应该继续调用无关工具。

---

### Case 7：多轮上下文测试

* 第一轮用户输入：查询u001的信息。
* 预期工具调用：get_user_profile。
* 执行结果：

```json
{
  "name": "张伟",
  "department": "研发部",
  "level": "P7",
  "status": "active"
}
```

* 预期最终回答：用户u001为张伟，属于研发部，职级为P7。

---

* 第二轮用户输入：他的工资是多少？
* 预期工具调用：query_salary。
* 执行结果：

```json
{
  "user_id": "u001",
  "salary": 28000
}
```

* 预期最终回答：用户u001的工资为28000元。

---

* 第三轮用户输入：根据工资和订单情况分析他的消费能力。
* 预期工具调用：先调用 get_order_detail，再调用 generate_business_report。
* 执行结果：

```json
{
  "order_id": "order_1001",
  "amount": 2999,
  "status": "paid"
}
```

```json
{
  "report_id": "report_002",
  "summary": "消费能力分析完成"
}
```

* 预期最终回答：已根据工资和订单情况完成消费能力分析，报告已生成。
* 验证点：

  * session 是否保持。
  * messages 是否累计。
  * 是否能够理解“他”指代。

---

## 4. ReAct 核心验证指标

### 工具调用正确性


| 指标     | 要求         |
| ---------- | -------------- |
| 工具选择 | 正确         |
| 参数生成 | 正确         |
| 调用次数 | 合理         |
| 顺序     | 符合任务依赖 |

### 循环控制

必须满足：

```text
任务完成
    ↓
Final
```

禁止：

```text
Tool
 ↓
Tool
 ↓
Tool
 ↓
无限循环
```

### 状态检查

每轮 ReasonNode 应能够看到：

```text
HumanMessage

AIMessage(tool_call)

ToolMessage(result)

AIMessage(tool_call)

ToolMessage(result)
```

不能只看到：

```text
HumanMessage

最近一次 ToolMessage
```

---

## 5. 当前架构重点验证问题

根据测试结果重点关注：

### ReasonNode

验证：

* 是否拥有工具描述。
* 是否知道工具能力。
* 是否能够判断信息是否充分。

### ActionNode

验证：

* 是否只负责执行。
* 是否不会重复推理。
* 是否正确调用 ToolRegistry。

### ToolNode

验证：

* 是否正确执行工具。
* 是否生成标准 ToolMessage。
* 是否追加到 messages。

### FinalNode

验证：

* 是否只输出最终结果。
* 是否不会再次调用工具。

---

## 6. 测试通过标准

满足以下条件认为 ReAct Strategy 基本正确：

* 单工具调用一次结束。
* 多工具任务按依赖顺序执行。
* 工具结果可以驱动下一步决策。
* 不重复调用已经完成的信息。
* 能判断任务完成。
* 多轮上下文保持正确。
* 不出现无限循环。
* Final 输出基于真实工具结果。

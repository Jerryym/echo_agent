# Tool 模块 v0.1.0 设计文档

## 1. 版本说明


| 项目     | 内容                                                                    |
| ---------- | ------------------------------------------------------------------------- |
| 版本     | v0.1.0                                                                  |
| 状态     | 已实现，ReAct 手动测试通过                                              |
| 依赖     | Pydantic、`langchain_core.tools`、`langchain_core.messages.ToolMessage` |
| 上一版本 | —（首版）                                                              |

---

## 2. 模块定位

Tool 模块是 echo-agent 中 **工具定义、注册与执行的统一抽象层**，位于 LLM 工具选择与 Strategy 推理流程之间。

**负责：**

- 定义工具 Schema（`ToolDefinition`）
- 维护工具注册表（`ToolRegistry`）
- 执行工具调用（`ToolExecutor`）
- 提供 Graph 可复用的工具执行节点（`ToolNode`）
- 定义跨模块流转的工具调用/结果模型（`ToolCall` / `ToolResult`）

**不负责：**

- LLM 工具绑定与模型侧 tool_calls 解析（由 LLM 模块负责）
- Strategy 推理与工具选择逻辑（由 Strategy 模块负责）
- 业务工具实现（由调用方或测试层提供）
- MCP / HTTP 远程工具通信（v0.1.0 仅预留类型枚举）
- ToolMessage 历史管理与 Checkpoint（由 Graph / Runtime 负责）

---

## 3. 设计原则

### 3.1 定义与执行分离原则

Tool 模块将 **工具描述（Definition）** 与 **工具实现（Handler）** 分离：

```text
ToolDefinition（Schema + 元信息）
        +
Handler（可调用对象）
        ↓
ToolRegistry.register()
        ↓
ToolExecutor.execute(ToolCall)
```

- `ToolDefinition` 描述 LLM 可见的工具接口
- Handler 是实际执行逻辑，v0.1.0 约定为 LangChain `@tool` 对象，通过 `handler.invoke(args)` 调用

### 3.2 模型归属原则

`ToolCall` / `ToolResult` 属于 Tool 模块专属模型，不归入 Model 模块。

依据 Model 模块设计：`ToolConfig`、工具执行状态等由各模块自行维护。Tool 模块负责工具调用链路上的数据结构，Graph State 通过引用 Tool 模型字段承载运行时状态。

### 3.3 LLM 透传、Tool 承接原则

LLM 模块仅负责：

- 将 `tool_list` 绑定到 ChatModel
- 将模型返回的 raw tool_calls 规范化为 `ToolCall`

LLM **不执行工具**，也不维护 `ToolResult`。执行闭环由 Strategy → Graph → ToolNode → ToolExecutor 完成。

### 3.4 失败可观测原则

`ToolExecutor` 捕获 handler 异常，返回 `success=False` 的 `ToolResult`，而不是向上抛出未处理异常。Strategy（如 ReAct ReasonNode）可基于 `success` 字段决定重试或终止。

### 3.5 消息回写原则

`ToolNode` 执行完成后，将 `ToolResult.result` 序列化为 JSON 字符串，写入 LangChain `ToolMessage`，并通过 Graph State 的 `add_messages` reducer 追加到 `messages`，供后续 LLM 推理读取。

---

## 4. 模块结构

```text
echo_agent/core/tool/
├── __init__.py          # 对外导出
├── schema.py            # ToolDefinition / ToolCall / ToolResult / ToolType
├── tool_registry.py     # ToolRegistry
├── tool_executor.py     # ToolExecutor
└── tool_node.py         # ToolNode（Graph Node）
```

### 4.1 对外导出

```python
from echo_agent.core.tool import (
    ToolDefinition,
    ToolCall,
    ToolResult,
    ToolRegistry,
    ToolExecutor,
    ToolNode,
)
```

---

## 5. Schema 设计

### 5.1 ToolType

工具类型枚举，v0.1.0 仅 `FUNCTION` 有完整实现路径，`HTTP` / `MCP` 为后续扩展预留。

```python
class ToolType(str, Enum):
    FUNCTION = "function"
    HTTP = "http"
    MCP = "mcp"
```

### 5.2 ToolDefinition

工具定义，描述 LLM 可见的工具接口。

```python
class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    type: ToolType = ToolType.FUNCTION
```


| 字段          | 说明                                                     |
| --------------- | ---------------------------------------------------------- |
| `name`        | 工具唯一名称，与 handler 注册 key 一致                   |
| `description` | 工具描述，透传给 LLM                                     |
| `parameters`  | JSON Schema 格式的参数定义（OpenAI function parameters） |
| `type`        | 工具类型，默认`function`                                 |

### 5.3 ToolCall

工具调用请求，在 LLM 输出与 Tool 执行之间流转。

```python
class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str
    missing_args: list[str] = Field(default_factory=list)
```


| 字段           | 说明                                                                                            |
| ---------------- | ------------------------------------------------------------------------------------------------- |
| `name`         | 待调用工具名称                                                                                  |
| `args`         | 模型生成的参数字典                                                                              |
| `tool_call_id` | 调用唯一 ID，用于关联 AIMessage tool_calls 与 ToolMessage                                       |
| `missing_args` | 缺失的必填参数名列表；由 Strategy ActionNode 在参数验证阶段填充，供`human_in_the_loop` 流程使用 |

> `missing_args` 不由 LLM 模块写入。LLM 规范化时仅填充 `name` / `args` / `tool_call_id`；Strategy 在验证失败时更新该字段。

### 5.4 ToolResult

工具执行结果。

```python
class ToolResult(BaseModel):
    name: str
    result: Any = None
    success: bool = False
    tool_call_id: str
```


| 字段           | 说明                                   |
| ---------------- | ---------------------------------------- |
| `name`         | 工具名称                               |
| `result`       | 执行返回值；失败时为`{"error": "..."}` |
| `success`      | 是否执行成功                           |
| `tool_call_id` | 与对应`ToolCall.tool_call_id` 一致     |

---

## 6. ToolRegistry

`ToolRegistry` 维护工具定义与 handler 的双向映射，并提供 OpenAI function 格式的 schema 列表供 LLM 绑定。

### 6.1 职责

- 注册 / 注销工具
- 按名称查询定义与 handler
- 导出 LLM 可用的 `tool_list`

### 6.2 公开 API

```python
class ToolRegistry:
    def register(self, tool: ToolDefinition, handler: Any) -> None: ...
    def unregister(self, name: str) -> None: ...
    def get(self, name: str) -> ToolDefinition: ...
    def get_handler(self, name: str) -> Any: ...
    def get_tools(self) -> list[dict[str, Any]]: ...
    def list_definitions(self) -> list[ToolDefinition]: ...
```

### 6.3 get_tools() 输出格式

`get_tools()` 固定输出 OpenAI function calling 格式，供 `LLMClient.invoke(..., tool_list=...)` 使用：

```python
[
    {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
    for tool in self._tools.values()
]
```

### 6.4 Handler 约定

v0.1.0 约定 handler 为 LangChain `@tool` 装饰的对象，需实现：

```python
handler.invoke(args: dict) -> Any
```

注册示例（来自测试）：

```python
from langchain_core.utils.function_calling import convert_to_openai_tool

tool_schema = convert_to_openai_tool(tool_obj)
fn = tool_schema["function"]

registry.register(
    ToolDefinition(
        name=fn["name"],
        description=fn["description"],
        parameters=fn["parameters"],
    ),
    tool_obj,
)
```

---

## 7. ToolExecutor

`ToolExecutor` 负责根据 `ToolCall` 查找 handler 并执行，将结果封装为 `ToolResult`。

### 7.1 执行流程

```text
ToolCall
    ↓
registry.get_handler(name)
    ↓
handler.invoke(tool_call.args)
    ↓
ToolResult(success=True, result=...)
```

### 7.2 异常处理

任意异常均被捕获，返回：

```python
ToolResult(
    name=tool_call.name,
    result={"error": str(e)},
    success=False,
    tool_call_id=tool_call.tool_call_id,
)
```

Strategy 层通过 `state.tool_results` 中的 `success` 字段感知失败，而非依赖异常传播。

---

## 8. ToolNode

`ToolNode` 是 Graph 层的工具执行节点，继承 `echo_agent.core.graph.Node`。

### 8.1 职责

- 读取 State 中的 `tool_calls` 列表
- 逐个调用 `ToolExecutor.execute()`
- 将结果写入 `tool_results`
- 构建 `ToolMessage` 并追加到 `messages`

### 8.2 run() 输入输出

**读取：**


| State 字段   | 用途                 |
| -------------- | ---------------------- |
| `tool_calls` | 待执行的工具调用列表 |

**返回：**

```python
{
    "tool_results": list[ToolResult],
    "messages": list[ToolMessage],
}
```

### 8.3 ToolMessage 构建规则

- `content`：`json.dumps(tool_result.result, ensure_ascii=False, default=str)`
- `tool_call_id`：与 `ToolResult.tool_call_id` 一致

该规则保证工具返回的 dict / list / 基本类型均可序列化为 LLM 可读的字符串。

---

## 9. 与上层模块的关系

```text
调用方（测试 / Agent 构建）
        ↓
ToolRegistry.register(ToolDefinition, handler)
        ↓
┌───────────────────────────────────────────────────┐
│ Strategy（ReAct ActionNode）                       │
│   registry.get_tools() → LLMClient.invoke(...)    │
│   LLMResult.tool_calls → state.tool_calls         │
└───────────────────────────────────────────────────┘
        ↓
┌───────────────────────────────────────────────────┐
│ Graph State（BaseState）                           │
│   tool_calls / tool_results / messages            │
└───────────────────────────────────────────────────┘
        ↓
ToolNode → ToolExecutor → handler.invoke()
        ↓
ToolMessage → messages → ReasonNode 下一轮推理
```

### 9.1 与 LLM 模块


| 方向        | 数据                                   | 说明                                                 |
| ------------- | ---------------------------------------- | ------------------------------------------------------ |
| Tool → LLM | `get_tools()` 输出的 dict 列表         | ActionNode 传入`LLMClient.invoke(tool_list=...)`     |
| LLM → Tool | `LLMResult.tool_calls: list[ToolCall]` | `_normalize_tool_calls()` 完成 dict → ToolCall 转换 |

LLM 模块 v0.1.0 设计边界：**ToolCall 由 Tool 模块独立定义，LLM 不解析 Tool 执行状态。**

### 9.2 与 Graph 模块

`BaseState` 引用 Tool 模块模型：

```python
class BaseState(BaseModel):
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
```

Graph 负责 State 流转与 `messages` reducer；Tool 负责 `tool_calls` → `tool_results` 的语义转换。

### 9.3 与 Strategy 模块

ReAct Strategy 中的 Tool 协作关系：


| 组件            | 与 Tool 模块的关系                                              |
| ----------------- | ----------------------------------------------------------------- |
| `ReActStrategy` | 构造时注入`ToolRegistry`，创建 `ToolExecutor` 与 `ToolNode`     |
| `ActionNode`    | 通过`registry.get_tools()` 获取 schema；产出 `state.tool_calls` |
| `ReasonNode`    | 读取`state.tool_results` 构建 observations，判断工具失败        |
| `ToolNode`      | 直接调用`ToolExecutor` 执行                                     |

ActionNode 在参数验证失败时，向 `ToolCall.missing_args` 写入缺失字段，并设置 `task_status=human_in_the_loop`，**不经过 ToolExecutor 执行**。

---

## 10. 端到端调用流程

以 ReAct Strategy 为例：

```text
1. 构建期
   ToolRegistry.register(...) × N
   ReActStrategy(llm_config, tool_registry)

2. ActionNode — 工具选择
   tool_list = registry.get_tools()
   LLMClient.invoke(..., tool_list=tool_list)
   → LLMResult.tool_calls: list[ToolCall]

3. ActionNode — 参数验证
   invoke_structured(...) → ready / missing_parameters
   ready     → state.tool_calls + AIMessage(tool_calls)
   missing   → state.tool_calls（含 missing_args）+ human_in_the_loop

4. ToolNode — 执行
   for tc in state.tool_calls:
       ToolExecutor.execute(tc)
   → state.tool_results + ToolMessage[]

5. ReasonNode — 观察
   读取 tool_results → 下一轮推理
```

---

## 11. 设计边界

### 11.1 Tool 与 LLM 内置工具


| 类型                 | 配置位置                  | 绑定方式                                           | 执行者        |
| ---------------------- | --------------------------- | ---------------------------------------------------- | --------------- |
| 自定义 function 工具 | `ToolRegistry`            | `LLMClient.invoke(tool_list=registry.get_tools())` | ToolExecutor  |
| 模型内置工具         | `LLMConfig.builtin_tools` | `model.bind(tools=...)`                            | 模型/provider |

Tool 模块 v0.1.0 仅覆盖 **自定义 function 工具** 的执行闭环。内置工具由 provider 侧执行，不进入 `ToolRegistry`。

### 11.2 Tool 与 Model 模块

Model 模块 v0.1.0 设计文档明确：`ToolCall` 不属于 Model 领域模型，由 Tool 模块独立维护。Graph State 通过字段引用实现跨模块数据流转。

### 11.3 ToolNode 的 Graph 层定位

`ToolNode` 虽定义在 Tool 模块，但其本质是 **Graph Node 实现**，依赖 `BaseState` / `BaseContext`。Strategy 在构建 SubGraph 时将其作为标准节点注册，而非在 Tool 模块内自行编排图结构。

---

## 12. 已知限制


| 限制                                           | 说明                                                    |
| ------------------------------------------------ | --------------------------------------------------------- |
| 仅支持 FUNCTION 类型                           | `ToolType.HTTP` / `MCP` 未实现                          |
| Handler 接口未抽象                             | 硬约定`handler.invoke(args)`，非 LangChain tool 需适配  |
| 同步串行执行                                   | `ToolNode` 按顺序逐个执行，无并行/超时控制              |
| 无工具名冲突检测                               | `register` 同名工具会静默覆盖                           |
| 无参数校验                                     | 执行前不校验 JSON Schema，依赖 LLM 生成与 Strategy 验证 |
| 无 ToolException 体系                          | 异常被`ToolExecutor` 吞掉并转为 `ToolResult.error`      |
| `get()` / `get_handler()` 无 KeyError 友好处理 | 工具不存在时直接抛出 KeyError                           |

---

## 13. 后续版本候选（v0.1.1+）

- [ ]  Handler 协议抽象（`Callable` / Protocol），降低对 LangChain `@tool` 的耦合
- [ ]  `ToolType.HTTP` / `MCP` 执行器实现
- [ ]  工具注册冲突检测与 `ToolException` 异常体系
- [ ]  执行前 JSON Schema 参数校验
- [ ]  并行执行与超时控制
- [ ]  `ToolRegistry` 从 `@tool` 列表批量注册 helper
- [ ]  Tool Preset（按业务场景预置工具集）

---

## 14. 验证结论

v0.1.0 已通过 ReAct Agent 手动测试验证（参见 `tests/test_react_agent.py`、`tests/docs/ReAct Agent 测试案例文档.md`）：

- 工具 schema 正确导出并被 LLM 绑定
- 单工具 / 多工具链式调用均可执行
- `ToolMessage` 正确追加到 `messages` 并驱动下一轮推理
- 工具执行失败时 `success=False`，ReasonNode 可感知并重试

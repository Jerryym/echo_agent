# LLM 模块 v0.1.2 设计文档

## 1. 版本说明

| 项目 | 内容 |
|------|------|
| 版本 | v0.1.2 |
| 状态 | 已实现，ReAct Strategy 手动测试通过 |
| 依赖 | LangChain `ChatOpenAI`（`langchain-openai`）、Pydantic |
| 上一版本 | v0.1.1 |

> v0.1.1 中未变更的部分（`LLMConfig` 字段、模型初始化、双轨工具绑定、`invoke` / `stream` 基础流程等）仍适用，本文档仅描述 v0.1.2 新增与变更内容。完整基线参见 `llm模块 v0.1.1 设计文档.md`。

### 1.1 v0.1.2 变更摘要

v0.1.2 在 v0.1.1 基础上，补全 **结构化输出** 能力，并统一模型绑定逻辑，核心变化如下：

| 变更项 | v0.1.1 | v0.1.2 |
|--------|--------|--------|
| 结构化输出 | 未实现（列为后续候选） | `invoke_structured()` |
| 结构化结果字段 | 无 | `LLMResult.structured` |
| 模型绑定 | `invoke` 内联 `bind_tools` | 统一 `_configure_model()` |
| 工具调用策略 Prompt | 无 | `tool_list` 非空时自动注入 `tool_call_policy.md` |
| `user_input` 类型 | 仅 `UserInput` | `UserInput \| dict \| str` |
| Runnable 配置 | 无 | `invoke` / `stream` / `invoke_structured` 支持 `RunnableConfig` |

---

## 2. 模块定位（v0.1.2 补充）

在 v0.1.1 职责基础上，v0.1.2 新增：

- 封装 LangChain `with_structured_output`，提供统一的结构化输出入口
- 将 Pydantic Schema 解析结果写入 `LLMResult.structured`，供 Strategy Node 直接使用

仍不负责 Tool 执行、Strategy 编排、结构化 Schema 的业务定义（Schema 由调用方传入）。

---

## 3. 设计原则（v0.1.2 补充）

### 3.1 结构化与工具调用互斥原则

`invoke_structured()` **不支持** 与 `tool_list` 同时使用。二者对应不同的模型绑定路径：

| 调用方式 | 模型绑定 | 典型用途 |
|----------|----------|----------|
| `invoke(..., tool_list=...)` | `bind_tools()` | ActionNode 工具选择 |
| `invoke_structured(..., schema=...)` | `with_structured_output()` | ReasonNode / ActionNode 参数验证 |

Strategy 层通过分阶段调用实现「先选工具、再验参数」，而非在一次 LLM 调用中混合两种输出模式。

### 3.2 结构化输出统一承接原则

结构化解析结果统一写入 `LLMResult.structured`，调用方通过 Pydantic 模型访问字段：

```python
response = client.invoke_structured(
    prompt=prompt,
    user_input=input,
    history=history,
    schema=ReasonResult,
)
result = response.structured  # ReasonResult 实例
```

`content` 字段仍保留原始 AIMessage 的文本内容（可能为空），`tool_calls` 在结构化调用中为空。

### 3.3 工具策略 Prompt 按需注入原则

当 `invoke` / `stream` 传入非空 `tool_list` 时，`_build_prompt()` 会在业务 prompt 之前自动拼接 `prompt/tool_call_policy.md`，引导模型规范地使用工具。

结构化调用不注入该策略 prompt，因其不涉及工具选择。

---

## 4. LLMResult（v0.1.2 更新）

```python
class LLMResult(BaseModel):
    content: str = Field(default="")
    tool_calls: list[ToolCall] | None = Field(default_factory=list)
    raw: Any = None
    structured: BaseModel | dict[str, Any] | None = None
    response_metadata: dict[str, Any] | None = None
```

| 字段 | `invoke` / `stream` | `invoke_structured` |
|------|---------------------|---------------------|
| `content` | 规范化后的文本 | 原始 AIMessage 文本（可能为空） |
| `tool_calls` | 规范化后的 `ToolCall` 列表 | 始终为空 |
| `structured` | `None` | Pydantic 实例或 dict |
| `raw` | `AIMessage` | `AIMessage`（来自 `include_raw=True`） |

---

## 5. LLMClient（v0.1.2 更新）

### 5.1 公开 API

```python
class LLMClient:
    def invoke(
        self,
        prompt: str,
        user_input: UserInput | dict | str,
        history: Optional[Sequence[BaseMessage]] = None,
        tool_list: Optional[list[dict[str, Any]]] = None,
        config: RunnableConfig | None = None,
    ) -> LLMResult: ...

    def invoke_structured(
        self,
        schema: type[BaseModel] | dict[str, Any],
        prompt: str,
        user_input: UserInput | dict | str,
        history: Optional[Sequence[BaseMessage]] = None,
        *,
        method: Literal["json_schema", "function_calling", "json_mode"] = "json_schema",
        strict: bool | None = None,
        config: RunnableConfig | None = None,
    ) -> LLMResult: ...

    def stream(
        self,
        prompt: str,
        user_input: UserInput | dict | str,
        history: Optional[Sequence[BaseMessage]] = None,
        tool_list: Optional[list[dict[str, Any]]] = None,
        config: RunnableConfig | None = None,
    ) -> Iterator[LLMResult]: ...
```

### 5.2 invoke_structured 参数说明

| 参数 | 说明 |
|------|------|
| `schema` | Pydantic 模型类或 JSON Schema dict，定义期望输出结构 |
| `prompt` | System prompt |
| `user_input` | 当前轮输入 |
| `history` | 历史 LangChain Messages |
| `method` | 结构化输出方式，默认 `json_schema` |
| `strict` | 是否严格匹配 schema；ActionNode 参数验证使用 `strict=True` |
| `config` | LangChain RunnableConfig，透传至 `model.invoke()` |

### 5.3 user_input 构建规则（v0.1.2 扩展）

| 类型 | 转换方式 |
|------|----------|
| `UserInput` | `user_input.to_human_message()` |
| `str` | `HumanMessage(content=user_input)` |
| `dict` | `HumanMessage(content=json.dumps(user_input, ensure_ascii=False, default=str))` |

Strategy Node 通常传入 dict（如 `{"input": ..., "reasoning": ..., "tool_calls": ...}`），由 LLMClient 序列化为 HumanMessage 内容。

### 5.4 _configure_model 统一绑定

v0.1.2 将模型绑定逻辑收敛至 `_configure_model()`：

```text
_configure_model(structured=False, tool_list=...)
    │
    ├── structured=True
    │       → model.with_structured_output(
    │             schema, method, strict, include_raw=True
    │         )
    │
    └── tool_list 非空
            → model.bind_tools(tool_list, parallel_tool_calls=True)

    否则 → 返回 self._model（含初始化阶段已绑定的 builtin_tools）
```

`invoke` 通过 `_configure_model(tool_list=...)` 绑定工具；`invoke_structured` 通过 `_configure_model(structured=True, schema=...)` 绑定结构化输出。

### 5.5 invoke_structured 调用流程

```text
SystemMessage(prompt)          ← 不注入 tool_call_policy
    + history
    + user_input → HumanMessage
        ↓
model.with_structured_output(schema, method, strict, include_raw=True)
        ↓
model.invoke(messages, config)
        ↓
{"parsed": ..., "raw": AIMessage}
        ↓
_parse_structured_response()
        ↓
LLMResult(structured=parsed, raw=raw, content=normalize(raw.content))
```

### 5.6 _parse_structured_response 解析规则

LangChain `with_structured_output(include_raw=True)` 返回 dict，解析要求：

- `raw` 键必须存在，否则抛出 `LLMResponseDecodeError`
- `parsed` 键必须存在且非空，否则抛出 `LLMResponseDecodeError`
- `parsed` 为 Pydantic 实例（传入 Pydantic schema 时）或 dict（传入 JSON Schema 时）

### 5.7 Prompt 组装（v0.1.2 更新）

`_build_prompt()` 在存在 `tool_list` 时，按顺序拼接：

```text
1. prompt/tool_call_policy.md   （工具调用策略，仅 tool_list 非空时）
2. 业务 prompt                   （Node 传入的 prompt 文件内容）
```

最终合并为单个 `SystemMessage` 内容，以 `\n\n` 分隔。

---

## 6. 与 Strategy 模块的协作

ReAct Strategy 是 v0.1.2 结构化输出的主要消费方：

| Node | LLM 调用 | Schema | 用途 |
|------|----------|--------|------|
| `ReasonNode` | `invoke_structured` | `ReasonResult` | 推理结论、信息充分性、任务完成判断 |
| `ActionNode` Step-1 | `invoke` + `tool_list` | — | 生成 native tool_calls |
| `ActionNode` Step-2 | `invoke_structured` | `ActionResult` | 验证参数完整性（`strict=True`） |
| `FinalNode` | `invoke` | — | 生成最终自然语言回答 |

```text
ReasonNode
    invoke_structured(ReasonResult)
        ↓
ActionNode
    invoke(tool_list) → tool_calls
    invoke_structured(ActionResult) → ready / missing_parameters
        ↓
ToolNode（不经 LLM）
        ↓
ReasonNode（循环）
        ↓
FinalNode
    invoke() → response
```

---

## 7. 与 Tool 模块的协作

v0.1.1 行为不变，v0.1.2 补充说明：

- `invoke` / `stream` 的 `tool_list` 通常来自 `ToolRegistry.get_tools()`
- `_normalize_tool_calls()` 将 AIMessage tool_calls 转为 `ToolCall`，写入 `LLMResult.tool_calls`
- `invoke_structured` 不参与 tool_calls 生成，ActionNode 在 Step-1 完成工具选择后再做 Step-2 验证

---

## 8. 异常体系

v0.1.2 无新增异常类型，结构化调用复用现有体系：

| 异常 | 结构化场景 |
|------|-----------|
| `LLMInvokeError` | `structured=True` 但未传 `schema`；模型 invoke 失败 |
| `LLMResponseDecodeError` | 响应缺少 `raw` / `parsed`；解析失败 |

---

## 9. 已知限制

| 限制 | 说明 |
|------|------|
| 结构化输出无流式 API | `stream()` 不支持 `with_structured_output`，仅 `invoke_structured` 同步调用 |
| 结构化与工具调用不可组合 | 同一轮调用只能选择一种绑定模式 |
| 仅支持 `model_provider="openai"` | 继承 v0.1.1 限制 |

---

## 10. 后续版本候选（v0.1.3+）

- [ ] `tool_presets.py`：按 provider 预置常用 `builtin_tools`
- [ ] 支持更多 `model_provider`（anthropic、google 等）
- [ ] 流式响应 block 级解析（reasoning / tool status）

---

## 11. 验证结论

v0.1.2 已通过 ReAct Strategy 手动测试验证：

- `ReasonNode` 通过 `invoke_structured(ReasonResult)` 输出推理状态与任务完成判断
- `ActionNode` 通过 `invoke(tool_list)` 生成 tool_calls，再通过 `invoke_structured(ActionResult, strict=True)` 验证参数完整性
- `missing_parameters` 状态下 `LLMResult.structured` 正确返回缺失字段映射
- `FinalNode` 通过 `invoke()` 生成最终回答
- `tool_list` 非空时 tool_call_policy prompt 正确注入

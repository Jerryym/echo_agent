# LLM 模块 v0.1.1 设计文档

## 1. 版本说明

| 项目 | 内容 |
|------|------|
| 版本 | v0.1.1 |
| 状态 | 已实现，手动测试通过 |
| 依赖 | LangChain `ChatOpenAI`（`langchain-openai`） |
| 上一版本 | v0.1.0 |

### 1.1 v0.1.1 变更摘要

v0.1.1 在 v0.1.0 基础上，重点解决 **多 provider / 多模型内置工具差异** 问题，核心变化如下：

| 变更项 | v0.1.0 | v0.1.1 |
|--------|--------|--------|
| 内置工具配置 | 无 | `builtin_tools: list[dict]`，由调用方按模型能力传入 |
| Provider 扩展参数 | 无 | `extra_body: dict`，如 Qwen 的 `enable_thinking` |
| Responses API | 未涉及 | `use_responses_api` + `output_version` 可配置 |
| 工具绑定策略 | 未实现 | 内置工具 `bind()`，自定义工具 `bind_tools()` |
| Provider 特有 bool 开关 | — | **已移除**（不再在 Client 内硬编码 Qwen 工具逻辑） |

---

## 2. 模块定位

LLM 模块是 echo-agent 与 LangChain ChatModel 之间的 **适配层**，职责边界如下：

**负责：**

- 管理模型配置（`LLMConfig`）
- 初始化 LangChain ChatModel
- 构建 LangChain Messages 并调用模型（`invoke` / `stream`）
- 规范化模型响应为统一结构（`LLMResult`）
- 绑定模型内置工具与运行时自定义工具

**不负责：**

- Agent 推理与编排逻辑
- Tool 执行与调度
- Memory / Checkpoint 管理
- MCP 通信
- Workflow / Graph 构建

---

## 3. 设计原则

### 3.1 LangChain 依赖确定性原则

- LangChain Message 是 **执行层标准**
- echo-agent 的 `UserInput` / `BaseMessage` history 是 **领域输入标准**
- `LLMClient` 负责输入侧 Message 组装与输出侧响应规范化

### 3.2 Provider 无关原则

LLM 模块 **不感知** 具体 provider 支持哪些内置工具。  
工具能力由 **调用方**（Agent 配置、环境变量、Preset）通过 `LLMConfig.builtin_tools` 声明，`LLMClient` 只负责透传绑定。

```text
调用方（按模型选工具）
        ↓
   LLMConfig.builtin_tools / extra_body
        ↓
   LLMClient（通用绑定与调用）
        ↓
   LangChain ChatOpenAI
```

### 3.3 双轨工具绑定原则

内置工具与自定义 function 工具走不同绑定路径：

| 工具类型 | 配置来源 | 绑定方式 | 典型示例 |
|----------|----------|----------|----------|
| 内置工具 | `LLMConfig.builtin_tools` | `model.bind(tools=...)` | Qwen: `web_search`, `web_extractor` |
| 自定义工具 | `invoke/stream` 的 `tool_list` | `model.bind_tools(...)` | 业务 `@tool` function |

**原因：** LangChain 的 `bind_tools()` 会对 tool dict 做 OpenAI function 格式转换；部分 provider 内置工具（如 Qwen 的 `web_extractor`）不在 LangChain 白名单内，必须通过 `bind()` 原样透传。

### 3.4 不可变绑定原则

LangChain 的 `bind()` / `bind_tools()` **返回新 Runnable，不修改原实例**。  
调用时必须接住返回值后再 `invoke` / `stream`：

```python
model = self._model
if tool_list:
    model = model.bind_tools(tool_list)
response = model.invoke(messages)
```

---

## 4. 模块结构

```text
echo_agent/core/llm/
├── __init__.py          # 对外导出
├── llm_config.py        # 模型配置
├── llm_client.py        # 核心客户端
├── llm_result.py        # 响应承接模型
└── exception.py         # 异常体系
```

对外导出（`echo_agent.core.llm`）：

```python
LLMClient, LLMConfig, LLMResult
LLMException, LLMInitializeError, LLMInvokeError, LLMResponseDecodeError
```

---

## 5. LLMConfig

### 5.1 模型定义

```python
class LLMConfig(BaseModel):
    base_url: str
    api_key: str
    model_name: str
    model_provider: Optional[str] = "openai"
    temperature: float = 0.2
    max_tokens: int = 1024
    timeout: int = 1200
    max_retries: int = 3
    use_responses_api: bool = False
    output_version: Optional[str] = None
    builtin_tools: list[dict[str, Any]] = Field(default_factory=list)
    extra_body: dict[str, Any] = Field(default_factory=dict)
```

### 5.2 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_url` | str | — | 模型服务地址 |
| `api_key` | str | — | API Key |
| `model_name` | str | — | 模型名称 |
| `model_provider` | str | `"openai"` | 模型提供方；当前 Client 仅实现 `openai` 分支 |
| `temperature` | float | `0.2` | 采样温度 |
| `max_tokens` | int | `1024` | 最大输出 token |
| `timeout` | int | `1200` | 请求超时（秒） |
| `max_retries` | int | `3` | 最大重试次数 |
| `use_responses_api` | bool | `False` | 是否使用 OpenAI Responses API |
| `output_version` | str \| None | `None` | AIMessage 输出版本，Responses API 推荐 `"responses/v1"` |
| `builtin_tools` | list[dict] | `[]` | 模型/provider 内置工具，初始化时绑定 |
| `extra_body` | dict | `{}` | Provider 扩展请求体，如 `{"enable_thinking": true}` |

### 5.3 配置示例

**OpenAI（Chat Completions，无内置工具）：**

```python
LLMConfig(
    base_url="https://api.openai.com/v1",
    api_key="...",
    model_name="gpt-4o",
)
```

**Qwen / DashScope（Responses API + 内置工具）：**

```python
LLMConfig(
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key="...",
    model_name="qwen3-max",
    use_responses_api=True,
    output_version="responses/v1",
    builtin_tools=[
        {"type": "web_search"},
        {"type": "web_extractor"},
        {"type": "code_interpreter"},
    ],
    extra_body={"enable_thinking": True},
)
```

> **注意：** `web_extractor` 通常需与 `web_search` 配合使用，这是 Qwen 的业务约束，应在调用方配置 preset 或文档中说明，而非写入 `LLMClient`。

---

## 6. LLMClient

### 6.1 职责

- 根据 `LLMConfig` 初始化 `ChatOpenAI`
- 初始化阶段绑定 `builtin_tools`
- 调用阶段可选绑定 `tool_list`（自定义 function 工具）
- 构建 Messages、调用模型、解析响应

### 6.2 公开 API

```python
class LLMClient:
    def __init__(self, config: LLMConfig): ...

    def invoke(
        self,
        prompt: str,
        user_input: UserInput,
        history: Optional[Sequence[BaseMessage]] = None,
        tool_list: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResult: ...

    def stream(
        self,
        prompt: str,
        user_input: UserInput,
        history: Optional[Sequence[BaseMessage]] = None,
        tool_list: Optional[List[Dict[str, Any]]] = None,
    ) -> Iterator[LLMResult]: ...
```

| 参数 | 说明 |
|------|------|
| `prompt` | System prompt |
| `user_input` | 当前轮用户输入（`UserInput`） |
| `history` | 历史 LangChain Messages |
| `tool_list` | 运行时自定义 function 工具（可选） |

### 6.3 初始化流程

```text
LLMConfig
    ↓
判断 model_provider == "openai"
    ↓
构造 ChatOpenAI kwargs
    ├── model / api_key / base_url / temperature ...
    ├── use_responses_api
    ├── output_version（非空时）
    └── extra_body（非空时）
    ↓
ChatOpenAI(**kwargs)
    ↓
builtin_tools 非空 → model.bind(tools=builtin_tools)
    ↓
self._model
```

### 6.4 调用流程

```text
SystemMessage(prompt)
    + history (BaseMessage[])
    + UserInput.to_human_message()
        ↓
[可选] model.bind_tools(tool_list)
        ↓
model.invoke() / model.stream()
        ↓
AIMessage
        ↓
_normalize_content() → LLMResult
```

### 6.5 Message 构建规则

| 顺序 | 来源 | LangChain 类型 |
|------|------|----------------|
| 1 | `prompt` | `SystemMessage` |
| 2 | `history` | 原样 extend |
| 3 | `user_input` | `HumanMessage`（via `UserInput.to_human_message()`） |

当前 v0.1.1 **不** 在 LLMClient 内使用 model 模块的 `Message` / `Role` 枚举；history 直接使用 LangChain `BaseMessage`，与 Graph State 的 `messages` 字段对齐。

### 6.6 响应内容规范化

Responses API（`output_version="responses/v1"`）返回的 `content` 可能是 block 列表。`_normalize_content()` 规则：

- `str` → 原样返回
- `list` → 提取 `type=="text"` 的 block，拼接为字符串
- 其他 → `str(content)`

> v0.1.1 流式场景下，Agent 层需自行过滤非 text block（如 reasoning、tool status）；参见 `test_agent.extract_stream_text()`。

---

## 7. 与上层模块的关系

```text
AgentConfig.llm_config: LLMConfig
        ↓
Graph Node（如 LLMInvokeNode）
        ↓
LLMClient.invoke() / stream()
        ↓
LLMResult.content → State.response
LLMResult.raw     → State.messages (AIMessage)
```

- **Agent 模块**：持有 `LLMConfig` 声明，Node 内创建/复用 `LLMClient`
- **Graph State**：`messages` 字段存储 LangChain `BaseMessage` 历史
- **Model 模块**：提供 `UserInput` 作为 LLM 输入载体

---

## 8. 已知限制与后续规划

### 8.1 v0.1.1 已知限制

| 限制 | 说明 |
|------|------|
| 仅支持 `model_provider="openai"` | 其他 provider 需扩展 `_initialize_model()` 分支 |
| 无内置 Tool Preset | Qwen / OpenAI 工具组合需调用方自行配置 |
| 流式仅规范化 text block | reasoning / tool status block 需上层过滤 |
| `tool_list` 命名 | 与 `builtin_tools` 语义区分不够直观，后续可考虑重命名为 `custom_tools` |
| 无 Tool 执行闭环 | 模型返回 tool_calls 后，LLM 模块不自动二次调用 |

### 8.2 后续版本候选（v0.1.2+）

- [ ] `tool_presets.py`：按 provider 预置常用 `builtin_tools`
- [ ] 支持更多 `model_provider`（anthropic、google 等）
- [ ] 流式响应 block 级解析（reasoning / tool status）
- [ ] Tool 执行闭环（tool_call → execute → 回注 → 再 invoke）
- [ ] 结构化输出（`with_structured_output` 封装）

---

## 9. 验证结论

v0.1.1 已通过以下手动场景验证：

- Qwen Responses API + `builtin_tools`（`web_search` / `web_extractor` / `code_interpreter`）
- Agent stream 模式多轮对话
- 内置工具绑定后模型可联网查询实时信息

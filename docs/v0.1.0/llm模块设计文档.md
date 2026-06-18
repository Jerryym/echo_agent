# LLM 模块 v0.1.0 设计文档

## 1. 模块定位

LLM 模块用于统一管理与调用大语言模型能力，是 echo-agent 与 LangChain ChatModel 之间的适配层。

其核心职责是：

* 管理模型配置
* 初始化 LangChain ChatModel
* 在 Echo IR 与 LangChain Message 之间进行双向转换
* 提供统一模型调用入口（invoke）

LLM 模块不负责：

* Agent 推理逻辑
* Tool 执行与调度
* Memory 管理
* MCP 通信
* Workflow 编排

---

## 2. 设计原则

### 2.1 LangChain 依赖确定性原则

echo-agent **长期依赖 LangChain 作为底层模型执行框架**，因此：

* LangChain Message 是执行层标准
* echo-agent Message 是领域层标准
* LLMClient 负责两者之间的转换

---

### 2.2 语义双向转换

LLMClient 负责LangChain Message 和 echo-agent Message 的双向转换，不参与任何业务语义解释。

```text
echo-agent Message  →  LangChain Message（输入侧）
LangChain Message → echo-agent Message（输出侧）
```

---

## 3. 模块结构

```text
llm/
├── __init__.py
├── config.py
├── client.py
└── exception.py
```

---

## 4. LLMConfig

模型配置定义。

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
```

| 字段           | 说明         |
| -------------- | ------------ |
| base_url       | 模型服务地址 |
| api_key        | API Key      |
| model_name     | 模型名称     |
| model_provider | 模型提供方   |
| temperature    | 采样温度     |
| max_tokens     | 最大 token   |
| timeout        | 超时时间     |
| max_retries    | 重试次数     |

---

## 5. LLMClient

LLMClient 是 LLM 模块的核心组件，负责模型初始化、消息转换与模型调用。

* 核心职责
  * 初始化 LangChain ChatModel
  * 转换 echo-agent Message → LangChain Message
  * 调用模型
  * 转换 LangChain Message → echo-agent Message
* 调用流程

    ```text
    Echo Message
        ↓
    LLMClient (encode)
        ↓
    LangChain Messages
        ↓
    ChatModel.invoke()
        ↓
    AIMessage
        ↓
    LLMClient (decode)
        ↓
    Echo Message
    ```

### 消息转换规则

#### Role → LangChain

| Role      | LangChain Type |
| --------- | -------------- |
| system    | SystemMessage  |
| user      | HumanMessage   |
| assistant | AIMessage      |

Tool role 当前不参与 LLM 输入层建模。

#### LangChain → Role

仅保留：

* role = assistant
* content = AIMessage.content

工具调用及结构化信息由 Tool 模块负责处理。

---

## 6. Tool 设计边界

LLM 模块仅透传 tool prompt 描述，不参与 Tool 结构建模。

ToolCall 由 Tool 模块独立定义：

* LLM 不解析 ToolCall model
* LLM 不承载 tool execution state

---

## 7. LLMResult

LLMResult 用于承接 LangChain ChatModel 的原始返回结果，是 LLMClient 输出的统一结构化模型。其作用是：

* 解耦 LangChain 模型回复消息（AIMessage）
* 统一模型响应结构

```python
class LLMResult(BaseModel):
    """
    LLM 原始响应承接模型（LangChain → Echo-Agent）
    """

    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    raw: Any = None
    response_metadata: Optional[Dict[str, Any]] = None
```

| 字段              | 类型                 | 说明                                           |
| ----------------- | -------------------- | ---------------------------------------------- |
| content           | str                  | 模型最终文本输出                               |
| tool_calls        | Optional[List[Dict]] | 工具调用信息（若模型支持）                     |
| raw               | Any                  | LangChain 原始响应对象（AIMessage）            |
| response_metadata | Optional[Dict]       | 模型附加信息（token usage / finish reason 等） |

---

## 8. 异常体系

```python
class LLMException(Exception):
    pass

class LLMInitializeError(LLMException):
    pass

class LLMInvokeError(LLMException):
    pass
```

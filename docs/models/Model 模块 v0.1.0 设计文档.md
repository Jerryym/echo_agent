# echo-agent v0.1.0 Model 模块设计

## 1. 模块定位

Model 模块用于定义 Echo-Agent 内部公共领域模型（Domain Model）。其主要职责包括：

* 定义系统内部统一数据结构
* 提供数据校验能力
* 降低各模块之间的直接依赖
* 为 LangChain 适配层提供统一输入输出模型

Model 模块不负责：

* LLM 配置管理
* Tool 调用管理
* MCP 通信协议

以上能力由对应模块自行维护其专属模型。

---

## 2. 设计原则

### 2.1 领域模型原则

Model 模块仅存放 Agent 领域模型。所谓领域模型，是指在系统多个模块之间流转的公共数据对象。例如：

```text
UserInput
Message
Attachment
```

而以下对象不属于领域模型：

```text
LLMConfig
ToolConfig
MCPConfig
```

这些配置模型应归属于各自模块。

---

### 2.2 LangChain 解耦原则

echo-Agent 基于 LangChain 与 LangGraph 构建。但业务层不应直接依赖 LangChain 数据结构。其系统结构如下：

```text
  Business Layer
        ↓
  echo-Agent Model
        ↓
     Adapter
        ↓
    LangChain
```

Model 模块负责定义 echo-Agent 自身的数据结构。Adapter 负责完成与 LangChain 对象之间的转换。

---

## 3. 模块结构

```text
model
├── __init__.py
├── message.py
└── input.py
```

---

## 4. UserInput 模型

UserInput 用于描述用户提交的原始输入。其职责是：**用户输入了什么**。其中包含两个数据类型：UserInput 和 Attachment:

* `UserInput`：用于表示用户提交的原始输入，包括文本和多模态附件。
* `Attachment`：用于表示多模态附件，当前版本仅支持图片、音频、文件三种附件类型。

```python
class UserInput(BaseModel):
    """
    用户输入
    """
    text: Optional[str] = None
    attachments: list[Attachment] = Field(default_factory=list)

class Attachment(BaseModel):
    """
    附件
    """
    type: Literal["image", "audio", "file"]
    data: str
```

---

## 5. Message 模型

Message 用于表示会话中的消息，是 echo-Agent 对 LangChain Message 的轻量封装。其职责是：**谁说了什么**。其中包含两个数据类型：Role 和 Message：

* `Role`：定义了消息角色枚举，每个枚举对应 LangChain BaseMessage 中的 SystemMessage、HumanMessage、AIMessage 和 ToolMessage。
* `Message`：用于表示会话中的消息，包括消息角色和消息内容。

```python
class Role(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

class Message(BaseModel):
    """
    消息
    """
    role: Role
    content: str
```

> 📌**REMARK:**
> `UserInput` 用于描述用户提交的原始输入，包括文本及多模态附件。而 `Message` 用于描述会话历史中的消息，仅负责表达“谁说了什么”。
> ❗ **v0.1.0 中：`UserInput` 支持多模态输入；但 `Message` 仅承载文本内容。**

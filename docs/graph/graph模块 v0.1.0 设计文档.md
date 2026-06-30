# Graph 模块 v0.1.0 设计文档

## 1. 模块定位

Graph 模块用于对 LangGraph 进行统一抽象与封装，为 Agent 模块和 Strategy 模块提供图结构相关基础数据模型与节点抽象能力。其主要职责包括：

* 定义 Graph 结构模型（Node / Edge / Schema）
* 提供 Node 与 SubGraph 抽象规范
* 对 LangGraph StateGraph 进行轻量封装
* 为 Agent 层提供可编排的图定义对象

Graph 模块不负责：

* Graph 编译（compile）
* Graph 运行（invoke / execution）
* Agent 生命周期管理
* Agent 运行时管理
* 策略实现与编排
* Tool 调用管理
* Memory 管理
* Checkpoint 管理

---

## 2. 设计原则

### 2.1 LangGraph 解耦原则

echo-agent 基于 LangGraph 构建，但业务层不应直接依赖 LangGraph 数据结构与接口，而Graph 模块负责定义 echo-agent 自身的图领域模型。。系统结构如下：

```text
 Agent / Strategy
        ↓
      Graph
        ↓
     Adapter
        ↓
    LangGraph
```

### 2.2 最小抽象原则

Graph 模块仅提供图领域最基础的数据结构与抽象能力。不重复封装 LangGraph 的完整能力，不承担 Agent Runtime 的职责，Graph 模块仅负责为上层提供统一基础抽象。因此 v0.1.0 中不提供：

```text
Graph
Edge
Runner
Workflow DSL
```

---

## 3. 模块结构

```text
graph
├── __init__.py
│
├── schema.py
│
└── node
    ├── node.py
    └── subgraph.py
```

---

## 4. Schema 模型

Graph 模块对 LangGraph 四种 Schema 进行统一抽象。

对应关系如下：

| Echo-Agent  | LangGraph      |
| ----------- | -------------- |
| BaseInput   | input_schema   |
| BaseOutput  | output_schema  |
| BaseState   | state_schema   |
| BaseContext | context_schema |

### 4.1 BaseInput

BaseInput 用于描述 Graph 的输入参数。其职责是：**Graph接收到的输入内容**

```python
class BaseInput(BaseModel):
    pass
```

### 4.2 BaseOutput

BaseOutput 用于描述 Graph 的输出结果。其职责是：**Graph运行最终结果**

```python
class BaseOutput(BaseModel):
    pass
```

### 4.3 BaseState

BaseState 用于描述 Graph 运行过程中的状态。其职责是：**Graph当前运行状态**，Graph 中各节点通过 State 完成数据共享与传递。

```python
class BaseState(BaseModel):
    pass
```

---

### 4.4 BaseContext

BaseContext 用于描述 Graph 运行上下文。其职责是：**Graph 运行时共享上下文**。Context 生命周期与单次 Graph 运行周期一致。

```python
class BaseContext(BaseModel):
    pass
```

---

## 5. Node 抽象

Node 是 Graph 中最基础的执行单元。其职责是：**接收 State、执行节点逻辑、返回 State 更新结果**。

```python
class Node(ABC):

    @property
    def name(self) -> str:
        """
        节点名称
        """
        pass

    @abstractmethod
    async def invoke(
        self,
        state: BaseState,
        context: BaseContext
    ) -> dict:
        """
        执行节点逻辑

        Returns:
            State Patch
        """
        pass
```

Node 返回值采用 **State Patch** 模式，即：只返回需要更新的状态字段。保证 State 生命周期统一由 LangGraph Runtime 管理。

```python
✅
return {
    "messages": [...],
    "thoughts": [...]
}

❌
return state
```

---

## 6. SubGraph 抽象

SubGraph 用于表示可复用的子图结构。其职责是：**组织多个 Node、形成独立功能单元**。

```python
class SubGraph(ABC):
    pass
```

---

## 7. Graph

Graph 是 LangGraph StateGraph 的结构化封装层。其职责如下：

* Node 注册
* Edge 注册（结构定义）
* SubGraph 组织
* Schema 绑定
* 提供构建 StateGraph 的能力

```python
class Graph:
    """
    LangGraph StateGraph wrapper (structural layer)
    """

    def __init__(
        self,
        state_schema: type[BaseState],
        context_schema: type[BaseContext],
        input_schema: type[BaseInput],
        output_schema: type[BaseOutput],
    ):
        self._state_schema = state_schema
        self._context_schema = context_schema
        self._input_schema = input_schema
        self._output_schema = output_schema

        self._nodes: dict[str, Node] = {}
        self._edges: list[tuple[str, str]] = []
        self._subgraphs: list[SubGraph] = []

    def add_node(self, node: Node) -> None:
        self._nodes[node.name] = node

    def add_edge(self, from_node: str, to_node: str) -> None:
        self._edges.append((from_node, to_node))

    def add_subgraph(self, subgraph: SubGraph) -> None:
        self._subgraphs.append(subgraph)
```

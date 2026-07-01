# echo-agent v0.1.0 设计文档

## 1. 项目概述

echo-agent 是一个基于 LangChain 与 LangGraph 构建的智能体运行时框架（Agent Runtime Framework），用于提供智能体执行过程中所需的核心能力，包括工作流执行、大模型推理、工具调用、智能体策略以及运行时环境管理等。
echo-agent 的定位是一个可独立运行的智能体运行时库（Agent Runtime Library），负责智能体生命周期中的运行时能力，不承担日志管理、配置中心、接口服务、可视化编排等系统级职责。
echo-agent 既可以作为独立 Python 库直接使用，也可以作为其他系统（如 Agent 平台、Workflow 平台、GUI 编排平台）的底层执行引擎。

---

## 2. 设计目标

* 提供统一的 Agent Runtime。
* 提供统一的大模型调用能力。
* 提供统一的工具调用能力。
* 提供统一的 RuntimeConfig / RuntimeContext 抽象。
* 提供基于 LangGraph 的 Workflow 执行能力。
* 提供标准智能体策略（Strategy）实现。
* 提供统一的 Agent 构建与运行入口。

---

## 3. 架构设计

### 3.1 架构定位

echo-agent 采用 Runtime First 的设计思想。整个框架围绕 Runtime 构建，其余模块均作为 Runtime 的组成能力或扩展能力存在。

* Runtime 是 LangGraph Runtime 的最小抽象封装层，位于 Agent 与 LangGraph 执行层之间，负责提供基础运行时配置与运行时上下文能力，并隔离 LangGraph 原生运行时细节。
* Graph 负责 Workflow 的定义、编译与执行，为智能体策略提供统一的流程抽象。
* Strategy 负责智能体推理模式。
* Tool 负责工具接口定义与调用。
* Capability 负责可扩展能力抽象。

### 3.2 模块划分

```text
echo-agent
├── common
└── core
    ├── model
    ├── llm
    ├── runtime
    ├── graph
    ├── capability
    ├── tool
    ├── strategy
    └── agent
```

### 3.3 模块职责

#### Model

负责定义整个 echo-agent 内部统一的数据模型，包括：

* Message
* Input / Output
* State
* Context
* ToolCall
* ToolResult
* Runtime 相关模型

Model 是整个框架的数据基础。

#### Runtime

Runtime 是 echo-agent 对 LangGraph Runtime 的最小抽象封装层。

负责：

* 提供统一的运行时配置能力
* 提供统一的运行时上下文能力
* 隔离 LangGraph 原生运行时细节
* 为 Agent 提供统一、可控、可扩展的运行环境入口

Runtime 不负责：

* Workflow 业务逻辑
* 具体能力实现
* session 管理
* thread 生命周期管理
* 额外运行时能力建模

#### Graph

Graph 模块负责 Workflow 的抽象与执行。

主要职责：

* Workflow 定义
* Node 抽象
* Edge 抽象
* State 定义
* SubGraph
* LangGraph 适配

Graph 描述的是“流程”，而不是具体能力。

#### Strategy

Strategy 定义 Agent 的推理模式（Reasoning Pattern）。

例如：

* ReAct
* Plan-and-Execute

Strategy 负责：

* Reason
* 生成结构化决策
* Observation 分析

Strategy 不直接依赖：

* Knowledge
* Skill
* Memory
* MCP
* 具体 Tool 实现

Strategy 的输出由 Graph 或 Agent 在运行时消费。

#### Capability

Capability 表示可扩展的运行时能力抽象。

例如：

* Knowledge
* Skill
* Memory
* MCP
* Web Search
* Embedding
* Rerank

Capability 是框架的一级扩展抽象。

所有能力均通过统一 Capability 接口进行注册与调用。

Capability 的内部实现可以是：

* Python
* LangGraph Workflow
* RPC
* MCP
* Remote Service

对 Runtime 与 Strategy 保持透明。

#### Tool

Tool 用于定义可供 LLM 或 Strategy 调用的工具接口，负责：

* Tool Schema
* Tool 注册
* Tool 路由
* Tool 调用

Tool 本身不承担业务能力，而是面向调用方的统一接口定义层。

#### LLM

负责统一模型访问能力，包括：

* ChatModel 初始化
* Message 转换
* Model 配置
* Invoke
* Stream（后续版本）

屏蔽不同模型供应商差异。

#### Agent

Agent 是整个框架对外提供的统一交互入口，负责：

* Agent 构建
* Agent 运行
* Agent 调用
* Runtime 初始化
* Workflow 装载
* Strategy 装载

Agent 本身不实现推理逻辑，而负责组织 Runtime、Strategy 与 Workflow。

---

## 4. 模块关系

```text
               Agent
                 │
                 ▼
              Runtime
        ┌────────┼────────┐
        │        │        │
        ▼        ▼        ▼
    Strategy   Graph   Capability
        │                 │
        │                 │
        ▼                 ▼
      Action         Capability
        │             Registry
        └──────┬───────────┘
               ▼
              Tool
               │
               ▼
              LLM
```

整个运行流程如下：

1. Agent 接收用户请求。
2. Agent 在构建阶段准备 RuntimeConfig。
3. Agent 在运行阶段生成 RuntimeContext。
4. Runtime 将配置与上下文传递给 Graph 执行层。
5. Graph 基于 LangGraph 执行 Workflow。
6. Strategy、Tool、Capability、LLM 在 Workflow 节点或 Agent 编排中被使用。
7. Runtime 仅负责运行边界、配置与上下文隔离，不负责具体业务能力实现。

---

## 5. Common 模块

Common 提供整个框架统一基础能力。当前版本负责统一异常体系，用于统一错误语义与异常处理机制。包括：

```python
AgentException
RuntimeException
LLMException
GraphException
ToolException
StrategyException
CapabilityException
AgentException
```

---

## 6. v0.1.0 交付范围

v0.1.0 聚焦构建 echo-agent 最小可用智能体运行时（Minimum Agent Runtime）。计划交付：

* Common：统一异常体系。
* Model：统一数据模型。
* Runtime：提供 RuntimeConfig / RuntimeContext 以及对 LangGraph Runtime 的最小抽象封装。
* Graph：Workflow 抽象及 LangGraph 封装。
* Strategy：ReAct、Plan-and-Execute。
* Tool：工具定义、注册、调用。
* LLM：统一模型调用能力。
* Agent：统一智能体构建与运行入口。

Capability 模块在 v0.1.0 中完成统一抽象设计与注册机制，实现能力扩展接口，为后续 Knowledge、Skill、Memory、MCP 等能力接入提供统一扩展点。

Knowledge、Skill、Memory 等具体 Capability 不属于 v0.1.0 的交付范围，将在后续版本逐步实现。

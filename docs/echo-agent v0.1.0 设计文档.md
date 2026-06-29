# echo-agent v0.1.0 设计文档

## 1. 项目概述

echo-agent 是一个基于 LangChain 与 LangGraph 构建的智能体能力框架（Agent Runtime Framework），用于提供大模型调用、工具调用、工作流编排以及智能体策略实现等核心能力。
echo-agent 不承担日志管理、配置管理、接口暴露等系统级能力，其定位为可独立运行的智能体运行时库（Agent Runtime Library）。既可以作为独立 Python 库直接使用，也可以集成到其他系统中作为智能体执行引擎。

---

## 2. 设计目标

### 2.1 核心目标

* 提供统一的大模型调用能力
* 提供统一的工具调用能力
* 提供基于 LangGraph 的工作流执行能力
* 提供标准 Agent 策略实现

### 2.2 非目标

v0.1.0 不包含以下能力：

* 多智能体协同
* 长期记忆管理
* Checkpoint 持久化
* Human-in-the-loop
* Workflow 可视化
* 分布式执行

---

## 3. 总体架构

### 3.1 架构分层

```text
echo-agent
├── common
└── core
    ├── model
    ├── llm
    ├── graph
    ├── agent
    ├── react
    ├── plan_execute
    └── tool
```

## 3.2 模块关系

```text
Agent
│
├── Model
├── LLM
├── Tool
├── Graph
└── Strategy
    ├── ReAct
    └── PlanExecute
```

其中：

* Model：定义 echo-agent 中统一数据模型
* Agent: 负责统一智能体创建和交互入口
* Graph：负责工作流组织与执行
* LLM：提供模型推理能力
* Tool：提供工具/函数能力扩展
* Strategy：定义智能体行为模式

---

## 4. Common 模块

### 4.1 模块职责

定义整个 echo-agent 中统一的异常与错误体系。该模块不承担日志、配置等基础设施职责，仅负责统一错误语义。

### 4.2 Error & Exception

定义统一异常体系，包括：

```python
EchoAgentException
LLMException
ToolException
GraphException
AgentException
```

用于统一错误处理机制和异常，便于上层系统进行异常捕获与处理。

---

## 5. Core 模块

Core 模块是 echo-agent 的核心能力集合，由 Model、LLM、Graph、Agent、Runtime、Strategy 和 Tool 七个模块组成。

* [Model 模块](./v0.1.0/model模块设计文档.md)：负责定义 echo-agent 中统一的数据模型
* [LLM 模块](v0.1.0/llm模块设计文档.md)：负责统一大模型访问能力，屏蔽不同模型供应商差异
* [Graph 模块](v0.1.0/graph模块设计文档.md)：负责基于 LangGraph 的抽象与封装，为智能体构建提供统一的数据结构
* [Agent 模块](v0.1.0/agent模块设计文档.md)：负责智能体构建、运行及交互能力
* Runtime 模块
* Strategy 模块：负责实现智能体策略，目前支持 ReAct 和 Plan-Execute 两种策略
* Tool 模块：负责统一工具定义、注册、路由及执行能力

---

## 6. v0.1.0 交付范围

v0.1.0 聚焦于构建 echo-agent 的最小可用智能体运行时（Agent Runtime），提供智能体构建与执行所需的核心能力。本版本计划交付以下内容：

* Common 模块：统一异常与错误体系，定义框架内部标准异常类型及错误语义。
* LLM 模块：提供统一的大模型配置与调用能力，屏蔽不同模型供应商之间的实现差异。
* Tool 模块：提供工具定义、工具注册、工具路由以及工具执行能力，支持智能体调用外部工具完成任务。
* Graph 模块：基于 LangGraph 抽象节点（Node）、子图（SubGraph）以及状态（State）等核心概念，为智能体策略提供统一运行时基础。
* Agent 模块：提供智能体统一抽象与交互入口，支持智能体构建、运行与调用。
* Runtime 模块
* Strategy 模块：负责实现智能体策略，目前支持 ReAct 和 Plan-Execute 两种策略

# echo-agent v0.1.0 设计文档

## 1. 项目概述

echo-agent 是一个基于 LangChain 与 LangGraph 构建的 **Agent Harness Runtime 初版（雏形）**：在执行框架之上提供围绕模型的运行控制层，负责管理模型可见的上下文、可用的能力，以及可持久化的执行状态。

定位：

- 可独立运行的智能体运行时库（Agent Runtime Library）
- 负责智能体生命周期中的运行时能力，不承担日志管理、配置中心、接口服务、可视化编排等系统级职责
- 既可作为独立 Python 库直接使用，也可作为 Agent / Workflow / GUI 编排平台的底层执行引擎

分层关系（v0.1.0）：

```text
Application
  → Harness Runtime（上下文 / 能力 / 状态控制，雏形）
    → Execution Strategy（默认 ReAct）
      → LangGraph（执行机制）
```

详细演进目标与任务拆解见：`docs/runtime/echo-agent v0.1.0 Harness Runtime 优化设计文档.md`。

---

## 2. 设计目标

- 提供统一的 Agent 构建与运行入口。
- 提供基于 LangGraph 的 Workflow 执行能力。
- 提供统一的大模型调用与工具调用能力。
- 提供 RuntimeConfig / Runtime Context 抽象，隔离 LangGraph 细节。
- 以 ReAct 作为默认 Execution Strategy，验证 Harness 控制面。
- 提供 Skill / MCP / HITL 等能力接入，形成可控的最小闭环。

---

## 3. 架构设计

### 3.1 架构定位

echo-agent 采用 Runtime First：框架围绕 Runtime 构建，其余模块作为 Runtime 的组成能力或扩展能力存在。

v0.1.0 在既有 Runtime 之上落地 Harness 雏形：

- **上下文按调用组装**：PromptAssembler 组装 Persistent / Runtime Prompt；会话裁剪与摘要在组装层生效，State 保留完整真相。
- **能力分层**：Skill（指令层）加载进 Runtime Context，不永久堆积进消息历史；Tool（能力层）经 Registry 注册与执行。
- **状态边界**：Graph State 记录执行事实；Runtime Context 描述当前环境（含 active_skills、trace）。

### 3.2 模块划分

```text
echo-agent
├── common
├── prompt
└── core
    ├── model
    ├── llm
    ├── runtime
    ├── graph
    ├── capability
    ├── tool
    ├── strategy
    ├── trace
    └── agent
```

### 3.3 模块职责

#### Model

统一数据模型：Message、Input/Output、State、Context、ToolCall/ToolResult、Skill、Conversation、Runtime 相关模型。

#### Runtime

对 LangGraph Runtime 的抽象封装，并承载 Harness 算法能力：

- RuntimeConfig / Runtime Context
- 会话裁剪（trim）与摘要压缩（ConversationCompressor / Orchestrator）
- HITL 子图
- 隔离 LangGraph 原生细节

#### Graph

Workflow 抽象与执行：Node、Edge、State、SubGraph、LangGraph 适配。

#### Strategy

推理模式。v0.1.0 **交付 ReAct**；Plan-and-Execute 仅保留占位，属 v0.2.0。

#### Capability

可扩展能力。v0.1.0 已落地 **Skill**（解析、加载、会话级生命周期）与 **MCP Client** 接入。

#### Tool

工具 Schema、注册、路由与执行；内置 `load_skill` / `read_skill_resource`。

#### LLM

统一模型访问：初始化、消息转换、Invoke / Stream / Structured Output；经 PromptAssembler 注入 Runtime Prompt。

#### Agent

对外统一入口：构建、调用、会话级 AgentState / active_skills、Token 用量写回、按需压缩会话。

#### Prompt / Trace

- Prompt：PromptLoader、PromptAssembler（Agent / Policy / Loaded Skills）
- Trace：TokenUsage、AgentTrace（per-call 累加）

---

## 4. 模块关系

```text
               Agent
                 │
                 ▼
         Harness Runtime
        ┌────────┼────────┐
        │        │        │
        ▼        ▼        ▼
    Strategy   Graph   Capability
        │                 │
        ▼                 ▼
      Action            Skill / MCP
        │                 │
        └──────┬──────────┘
               ▼
              Tool
               │
               ▼
              LLM ← PromptAssembler
```

运行流程：

1. Agent 接收用户请求，构建 RunnableConfig 与 Runtime Context。
2. Graph 基于 LangGraph 执行 Workflow。
3. Strategy（ReAct）在节点中推理、选工具、产生 Observation。
4. Skill 激活写入 Context；LLM 调用前由 PromptAssembler 注入。
5. 交互结束后写回会话历史，累计 Token，按阈值压缩摘要。

---

## 5. Common 模块

统一异常体系，包括：

```python
AgentException
RuntimeException
LLMException
GraphException
ToolException
StrategyException
CapabilityException
```

---

## 6. v0.1.0 交付范围

v0.1.0 交付 **Harness Runtime 雏形 + ReAct 默认策略**，接受已知限制。

### 6.1 已交付


| 能力                         | 说明                                                                                          |
| -------------------------- | ------------------------------------------------------------------------------------------- |
| Agent / Graph / LLM / Tool | 统一入口、Workflow、模型与工具执行                                                                       |
| Strategy                   | **ReAct**（默认验证载体）                                                                           |
| HITL                       | 审批 / 补参中断与恢复                                                                                |
| MCP                        | Client 接入；内置 Fetch / Filesystem                                                             |
| Skill                      | 本地包解析；`load_skill` 激活 Runtime Context（详情不进 messages）；会话隔离；手动 discard；**连续 3 轮未触达自动 expire** |
| Prompt                     | PromptAssembler：Agent / Tool Policy / Skill Policy / Loaded Skills                          |
| State / Context            | State 存执行事实；Context 存 active_skills、trace、agent_state                                       |
| Context 治理                 | Token 计量；会话窗口裁剪；超阈值历史摘要并注入组装层                                                               |


### 6.2 已知限制（明确接受）

- **工具动态加载未做**：可见工具集在策略组装期快照，运行期不随 Skill 激活裁剪。
- **Skill Catalog Level 1**：冷启动 name + description 名单尚未注入 Prompt。
- **Tool Result 压缩**：超长工具结果自动摘要未做。
- **Prompt Registry / 文件缓存**：Assembler 已有，分层注册与读文件缓存未做。
- **Plan-and-Execute / Memory / 权限梯度 / Multi-Agent**：非本版本范围（见 v0.2.0+）。

### 6.3 后续版本

- **v0.2.0**：工具动态治理；Plan-and-Execute；权限梯度；上下文重置等。
- **v0.3.0**：Memory / Multi-Agent / Long-running Agent。


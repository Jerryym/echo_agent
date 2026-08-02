# Runtime

Runtime 是 echo-agent 对 LangGraph Runtime 的统一抽象与封装，作为 Agent 与 LangGraph Runtime 之间的 **运行时能力中间层（Runtime Abstraction Layer）**，为 Agent 提供一致的执行环境与运行时能力支持。

> **❓ 为什么需要 Runtime？**
>
> 在不引入 Runtime 的情况下，Agent 必须直接暴露并管理 LangGraph Runtime 的运行时能力，例如：
>
> ```python
> agent.invoke(message,
>     config={
>         "configurable": {
>             "thread_id": "...",
>             "checkpoint_id": "...",
>         }
>     },
>     checkpointer=...,
>     store=...,
>     interrupt_before=...,
> )
> ```
>
> 这会导致一个本质问题：**运行时能力（Runtime Capabilities）与 Agent 调用接口发生耦合。** 这种耦合会带来以下结构性问题：
>
> * Agent 层被迫理解并管理 LangGraph Runtime 细节
> * 运行时能力（Thread / Checkpoint / Store）分散在调用接口中，无法统一治理
> * Interrupt / Memory 等能力的引入会持续污染 Agent API
> * 系统边界被打破：Agent 不再是“调用层”，而变成“运行时编排层”
>
> **最终结果是：Agent 与 LangGraph Runtime 深度绑定，系统失去可演进性与抽象边界。**

---

## Runtime 的能力

Runtime 并不是单一功能模块，而是多个运行时能力的集合：Persistence、Interrupt、Resume、Human-in-the-loop、Memory、Time Travel、Fault Tolerance 等，这些能力共同构成 Runtime 的运行时语义层。

### Persistence

Persistence 是 Runtime 的底层能力，用于管理 Graph State 的持久化。其负责：

* Graph State 的保存和回复
* State History 的更新
* 同一个 Graph 多次运行时状态的连续性

其内部结构包含：

```text
Persistence
├── Thread
├── Checkpointer
└── Store
```

#### Thread

Thread 是 Runtime 中用于标识一次持续运行上下文的唯一标识（thread_id），用于组织同一执行链路下的多次 Graph Run 所产生的状态演化。在启用 Checkpointer 的情况下，每一次 Graph Run 的执行状态都会被持久化到对应的 Thread 中，从而形成一条连续的状态历史（State History）。所以，Thread 的本质是：**Checkpoint 的组织作用域（Checkpoint Scope）。**
Checkpointer 使用 thread_id 作为主键，对同一 Thread 下的所有 Checkpoint 进行存储与恢复，即：

* Thread 代表一段连续运行的状态空间
* Checkpoint 代表该空间中的某个状态快照
* Runtime 通过 Thread 实现跨 Run 的状态连续性与恢复能力

#### Checkpointer

Checkpoint 是某一时刻 Graph Execution State 的快照（State Snapshot），它表示 Graph 在某一时刻的完整运行状态，用于记录 execution flow 中的状态演化过程。且 Checkpoint 的生成是**运行时行为（runtime behavior）**，而不是执行结束后的结果产物。
在启用 Checkpointer 的情况下：

* Graph 每进入一个 super-step 时，会自动捕获当前 Graph State
* 并将其持久化为一个 Checkpoint
* Checkpoint 会追加到对应 Thread 的状态历史中

从而形成完整的执行轨迹（State History）。

#### Store

Store 用于管理跨 Thread 的持久化数据，并不参与 Graph State 管理：

* 用户画像
* 长期记忆
* 偏好信息
* 共享知识

### Interrupt

Interrupt 是 Runtime 的执行控制能力，用于在 Agent 运行中挂起运行，并允许外部介入后恢复执行。其核心依赖是 Checkpointer，通过 Checkpoint 保存执行过程中的 runtime state，从而实现可恢复的执行中断。如：暂停执行、外部干预、人工介入、决策等待。

### Memory

Memory 是基于 Persistence 构建的语义能力，用于在 Agent 运行之外组织和访问状态信息。

* Short-term Memory 基于 Thread + Checkpointer 的 State History
* Long-term Memory 基于 Store 的跨 Thread 数据持久化

### Human-in-the-loop

Human-in-the-loop 是基于 Interrupt 的交互扩展能力，用于在 Agent 运行时引入外部用户参与决策流程。

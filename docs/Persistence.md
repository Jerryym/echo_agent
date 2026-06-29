# Runtime 概念解析（一）：Persistence

## 1. 什么是 Persistence

Persistence 是 LangGraph Runtime 提供的**运行时持久化（Runtime Persistence）能力**。其核心职责不是简单地将数据写入数据库，而是**持久化 Graph Runtime 的运行状态（Graph State），使 Graph 能够在多次运行之间保持状态连续性**。Persistence 是 LangGraph Runtime 的基础设施，其能力支撑：

- Checkpoint
- Interrupt
- Resume
- Human-in-the-loop
- Memory
- Time Travel
- Fault Tolerance

因此，Persistence 可以理解为：**Graph Runtime State 的生命周期管理机制。**

---

## 2. 为什么需要 Persistence

默认情况下，每一次 Graph 调用都是独立运行，即：`invoke() → Graph 执行 → 结束 → State 消失`。这意味着：

- Agent 无法记住之前发生的事情；
- Graph 无法恢复中断执行；
- 无法实现 Human-in-the-loop；
- 无法实现长生命周期 Agent。

基于以上问题，系统需要设计一种机制，使 Graph State 能够跨多次 Graph Run 持续存在，这就是 Persistence 的职责。

---

## 3. Persistence 管理什么

Persistence 管理的并不是数据库中的业务数据，而是：**Graph State Context 在 Runtime 生命周期中的持续变换。** Graph 每执行一次，State 都会不断演化，而 Persistence 则负责持续记录状态变化，并保证 Graph 能够在任意时刻恢复到对应状态继续执行。

> State is the Heart. Persistence is the Brain.

---

## 4. Persistence 的核心组成

Persistence 主要由三个核心概念组成：Thread、Checkpointer、Store。三者职责完全不同。

### 4.1 Thread

Thread 是 Persistence 中最基础的概念。官方定义：

> A thread is a unique ID assigned to a series of checkpoints saved by a checkpointer.

可以理解为：**Thread 是 Graph State Context 的持久化作用域（Persistence Scope）。** 它通过唯一的 `thread_id`，将同一 Graph State Context 在多次 Graph Run 中产生的所有 Checkpoint 组织在一起。例如：

```text
Thread
│
├── Checkpoint 1
├── Checkpoint 2
├── Checkpoint 3
└── Checkpoint 4
```

❗ 需要注意的是：**Thread 并不是一次 Graph Run。** 而是：**多个相关 Graph Run 共享的一条持续状态历史（State History）。** 对于聊天机器人来说，可以近似理解为：Session（会话）。但是实际上，Thread 并不限于聊天场景，任何需要持续维护 Graph State 的任务，例如：工作流执行、长任务执行、Multi-Agent 等，都可以使用 Thread。

### 4.2 Checkpointer

Checkpointer 是 Persistence 的核心实现机制。其职责是：**保存与恢复 Graph State。** Graph 每执行一个 Super-step，Checkpointer 都会生成一个新的 Checkpoint。

```text
Thread → Checkpoint 1 → Checkpoint 2 → Checkpoint 3 → Checkpoint 4
```

Checkpoint 本质上是：**Graph State 在某一时刻的快照（Snapshot）。** Checkpointer 的职责是：

- 保存 Checkpoint
- 加载 Checkpoint
- 管理 Checkpoint History
- 恢复 Graph State

因此，Interrupt、Resume、Time Travel 等能力，本质上都建立在 Checkpointer 之上。

### 4.3 Store

Store 同样属于 Persistence，但职责与 Checkpointer 完全不同。Store 保存的是：**跨 Thread 的持久化数据（Persistent Data）。** 例如：

- 用户画像
- 用户偏好
- 长期知识
- 长期 Memory

这些数据：

- 不属于 Graph State；
- 不属于某一个 Thread；
- 生命周期远长于一次 Graph Runtime。

因此，Store 更像是 Runtime 可访问的持久化存储。

### 4.4 Checkpointer 与 Store 的区别

| 对比项 | Checkpointer | Store |
| --------- | -------------- | ------- |
| 保存对象 | Graph State（Execution State） | Application Data |
| 生命周期 | Thread 内 | 跨 Thread |
| 是否参与 Resume | ✅ | ❌ |
| 是否参与 Interrupt | ✅ | ❌ |
| 是否保存 Runtime State | ✅ | ❌ |
| 是否用于长期数据 | ❌ | ✅ |

---

## 5. Persistence 与 Graph Run

Graph 每执行一次：`invoke() / stream()`，都称为一次 **Graph Run**。因此同一个 Thread 可以包含多次 Graph Run。例如：

```text
Conversation → invoke() → invoke() → invoke() → invoke()

Thread → Run 1 → Run 2 → Run 3 → Run 5 
```

Persistence 会不断在同一个 Thread 下维护 Graph State 的连续演化。因此，**Persistence 并不是保存某一次 Graph Run，而是维护整个 Thread 的状态历史（State History）。**

---

## 6. Persistence 与 Runtime 能力

Persistence 是 Runtime 的基础能力。Runtime 的许多高级能力均建立在 Persistence 之上。

```text
Persistence
├── Thread
├── Checkpointer
├── Store
├── Interrupt
├── Resume
├── Human-in-the-loop
├── Memory
└── Time Travel
```

其中：

- Interrupt 基于 Checkpointer 实现；
- Human-in-the-loop 基于 Interrupt 实现；
- Short-term Memory 基于 Thread + Checkpointer；
- Long-term Memory 基于 Store。

因此：**Persistence 并不是某一个功能，而是 LangGraph Runtime 的底层运行时持久化基础设施。**

# 会话上下文与 AgentTurn 重构计划

## 摘要

将 `AgentSession` 保持为单个 Agent 会话窗口的聚合对象，并建立三层状态边界：

- `AgentSession.turns`：完整轮次历史，包含完成、取消和失败的 Turn。
- `SessionState.conversation`：Session 已提交的运行时会话窗口，可被摘要和压缩。
- Graph `ConversationState`：每轮从 Session 拷贝出的执行副本，随 Graph checkpoint 保存；仅在成功完成后提交回 Session。

显式 `cancel` 保留用户输入和取消轮次，不提交未完成的 Graph 上下文。历史持久化、Cancel API 扩展和客户端调度策略不在本次实现范围内。

## 数据模型与接口修改

- 将 `AgentState` 重命名为 `SessionState`：
  - 保留 `conversation`、`context_items`、`token_usage`。
  - 移除重复的 `session_id`，身份只由 `AgentSession.session_id` 管理。
  - `BaseContext.agent_state` 重命名为 `session_state`，保留只读兼容属性 `agent_state`。
- 升级 `AgentTurn`：
  - 新增 `status`、`pre_checkpoint_id`、`latest_checkpoint_id`、`error`；本阶段不增加没有实际消费场景的 Turn ID。
  - `TurnStatus` 固定为 `RUNNING`、`WAITING_INPUT`、`COMPLETED`、`CANCELLED`、`FAILED`。
  - `tool_names` 由 Turn 持有的 `AgentResult` 累计，`AgentTurn.tool_names` 通过只读属性返回副本，不重复保存同一数据。
- 扩展 `AgentResult`：
  - 新增 `tool_names: list[str]`，保持首次使用顺序并去重，作为本轮文本、reasoning、token usage 之外的执行结果信息正常参与序列化。
  - 新增 `apply_tool(name)`，集中处理空名称和重复名称。
- 调整 `AgentSession`：
  - 新增 `turns: list[AgentTurn]`，取消独立 `_results` 存储。
  - `results` 和 `get_agent_results()` 继续提供兼容视图，从已完成 Turn 的 result 派生。
  - `start_turn()` 创建 RUNNING Turn，并立即把用户消息写入 `SessionState.conversation`。
  - 增加 `wait_turn()`、`finish_turn()`、`cancel_turn()`、`fail_turn()`，统一完成归档并清除 `current_turn`。
  - 不新增 `SessionHistory` 包装类。

## Graph Schema、执行与取消流程

- 将 `ConversationState` 纳入 Graph Schema：
  - `BaseInput`/`BaseState`/`BaseOutput` 增加运行时 conversation 字段，具体 ReAct Schema 复用该字段，不再重复定义 `list[Message]`。
  - Graph 启动时深拷贝 Session conversation；Graph 内的压缩和摘要只修改该副本。
  - ReAct 的 history 构建统一读取 `state.conversation.summary + messages`，再追加本轮 `trajectory`。
  - LLM 前置 hook 显式接收当前 `ConversationState`；发生压缩时原子更新 summary/messages。
  - Reason、Action、Final 节点把更新后的 conversation 放入 Graph state update，确保 checkpoint 捕获压缩结果。
  - Graph 正常完成后，提交其 conversation 回 `SessionState`，再追加最终 assistant 消息；取消或失败时不提交 Graph 副本。
- 调整 `context_items`：
  - 从 `ConversationState` 移至 `SessionState.context_items`。
  - `SessionState.context_items` 是会话运行时唯一事实源；新增统一合并方法，继续按 item ID 更新或追加。
  - `BaseContext.session_state` 保持对 AgentSession 中同一 `SessionState` 实例的引用，Graph 节点通过 `runtime.context.session_state.context_items` 读取已有内容。
  - `ToolNode` 生成 context item 后立即合并到 `SessionState`，使同一 Turn 的后续节点和后续 Turn 都能直接访问。
  - 从 `BaseState`/`BaseOutput` 移除 `context_items` 及其 reducer，不再通过 Graph state、output 或 checkpoint 传递会话级 context item。
  - context item 仅保证在运行时上下文中可访问，不自动无条件拼接到 LLM prompt；需要使用它的节点主动读取。
  - 显式 cancel 只回滚 Graph 执行状态；已经由工具产生并写入 SessionState 的 context item 继续保留，与无法自动回滚的工具副作用和 artifact 保持一致。
- 复用 `AgentResult` 更新通道记录工具使用：
  - 不向 `BaseState` 或 `BaseOutput` 增加 `tool_names`；工具使用记录不属于 Graph 的计算、路由或可恢复状态。
  - 不向 `BaseContext` 增加 `AgentTurn` 或工具名窄引用，继续使用现有 `agent_result` 引用。
  - 在现有结果更新工具旁增加 `update_agent_tool(context, tool_name)`；其调用 `context.agent_result.apply_tool()`，并沿用 AgentResult 的流式更新通知。
  - `ToolNode` 在通过权限和参数检查、即将实际调用 `ToolExecutor` 时调用该函数；执行成功或失败均已记录，HITL 前取消和内部结构化输出工具不记录。
  - 正常完成、HITL resume 和显式 cancel 始终复用当前 Turn 持有的同一 `AgentResult`，因此结算和归档时不需要从 Graph output/checkpoint 回收工具名。
- 修复显式 cancel：
  1. 取消并等待运行 task 停止。
  2. 读取最新稳定 Graph checkpoint ID。
  3. 调用 `AgentSession.cancel_turn()`，保留 Turn 已累计的 partial result、工具名和 checkpoint 引用，并归档 Turn。
  4. 将 Graph tip 恢复到 `pre_checkpoint_id`。
  5. `restore_checkpoint()` 改为纯 Graph 操作，不再调用 `clear_turn()`。
  6. 用户输入因已在 start 时写入 Session conversation 而继续保留；partial assistant、reasoning 和 trajectory 不进入后续模型上下文；已经产生的 context item 保留在 SessionState。
  7. HITL 时将 Turn 标记为 `WAITING_INPUT`；resume 前恢复为 `RUNNING`，完成后正常提交。
- checkpoint 生命周期完全交给配置的 Saver：
  - `InMemorySaver` 随进程结束释放。
  - `SqlSaver` 按其数据库策略长期保留。
  - AgentTurn 只保存 checkpoint ID，不负责清理。

## 测试计划

- 模型与兼容性：
  - `SessionState` 新名称、`AgentState` 兼容别名和 `BaseContext.agent_state` 兼容属性。
  - `results` 仅返回已完成 Turn，现有调用行为不变。
- Turn 生命周期：
  - start 立即保留用户消息。
  - complete 提交 Graph conversation、assistant 消息和 token usage；context item 已在产生时写入 SessionState，无需再次提交。
  - cancel 归档 CANCELLED Turn、保留用户消息、工具名及已经产生的 context item，但不提交 partial assistant/reasoning/trajectory。
  - failure 归档 FAILED Turn并保留错误信息。
  - HITL interrupt/resume 保持同一个 Turn、result 和 checkpoint 关联。
- Context item 生命周期：
  - 多轮运行始终通过 `BaseContext.session_state` 看到同一份已合并集合。
  - 同一 ID 的新 item 更新旧值，不同 ID 按首次出现顺序追加。
  - ToolNode 同步/异步路径产生 item 后，下一个节点无需等待 Turn 完成即可读取。
  - cancel/Graph checkpoint 回滚不删除已写入 SessionState 的 item。
- 工具记录：
  - 同一工具多次执行只记录一次，顺序按首次执行排列。
  - 执行失败仍记录。
  - HITL 审批前取消不记录。
  - cancel 归档后 `AgentTurn.tool_names` 与其 `AgentResult.tool_names` 一致。
  - invoke/stream 返回的 `AgentResult` 正常序列化 `tool_names`，流式更新能够及时反映新记录。
  - sync/async ToolNode 行为一致。
- Graph conversation：
  - Session conversation 与 Graph 副本互不共享可变引用。
  - 压缩后的 conversation 写入 checkpoint，并在完成后提交回 Session。
  - cancel 回滚 Graph 后，下一轮仍能看到被取消轮次的用户输入。
  - summary、messages 和 tool-call/tool-result 边界在 checkpoint/resume 后保持一致。
- Adapter 回归：
  - HTTP/SSE cancel 仍返回现有 `cancelled: bool`。
  - invoke、stream、resume、stream_resume 的完成与取消路径均无遗留 `current_turn`。
  - 运行现有 agent、ReAct、HITL、skill、adapter 测试以及新增的 conversation/turn 单元测试。

## 已确定的约束

- 本次不实现 Session/Turn 跨进程持久化；相关模型保持可序列化，后续可增加 JSON 或 SQLite 存储。
- 不修改客户端对同一 Session 新请求的调度策略。
- 不扩展 Cancel API 返回结构。
- checkpoint 保留策略不由 Agent 核心层控制。
- 压缩只影响 Graph/Session 的运行时 `ConversationState`，永不删除 `AgentSession.turns`。

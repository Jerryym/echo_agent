# Runtime Adapter HTTP API（v0.1）

跨语言宿主可通过 **HTTP REST + SSE** 调用 echo-agent。语义与 gRPC 对齐；JSON 形态更自然。  
实现：`echo_agent/adapter/http/`；启动后可打开 **OpenAPI**：`http://127.0.0.1:8000/docs`。  
gRPC 快速接入见 [快速接入](./快速接入.md)。

---

## 1. 启动服务

```bash
# 仓库根目录
uv run python -m examples.integrator_runtime_http.main --host 127.0.0.1 --port 8000
```

或：

```bash
uv run python -m echo_agent.adapter.http.server \
  --factory examples.integrator_runtime.build_agent:build_agent \
  --host 127.0.0.1 --port 8000
```

- Base URL：`http://127.0.0.1:8000`
- 路由前缀：`/v1`
- 默认仅绑定回环；跨机需显式 `--host`，并由宿主终止 TLS / 鉴权（Adapter 本身 insecure）
- 工厂与 gRPC 共用：`examples.integrator_runtime.build_agent:build_agent`

---

## 2. 调用顺序

```text
POST /v1/agents  →  { "id": agent_id }
宿主自管 session_id（多轮 / HITL 必填，映射 thread_id）
POST .../invoke 或 POST .../stream
若 interrupted → 收集人机结果 → POST .../resume 或 .../resume/stream
运行中可随时 POST .../cancel 中止当轮
业务结束 → DELETE /v1/agents/{agent_id}
```

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| `POST` | `/v1/agents` | 调用注入 factory 创建 Agent，返回 `id` |
| `DELETE` | `/v1/agents/{agent_id}` | 销毁进程内 Agent（204 无 body） |
| `POST` | `/v1/agents/{agent_id}/sessions/{session_id}/invoke` | 同步一轮 |
| `POST` | `/v1/agents/{agent_id}/sessions/{session_id}/resume` | HITL 恢复（同步） |
| `POST` | `/v1/agents/{agent_id}/sessions/{session_id}/cancel` | 中止当轮 |
| `POST` | `/v1/agents/{agent_id}/sessions/{session_id}/stream` | SSE 流式 invoke |
| `POST` | `/v1/agents/{agent_id}/sessions/{session_id}/resume/stream` | HITL 恢复（SSE） |

`Content-Type: application/json`（SSE 响应为 `text/event-stream`）。

---

## 3. 错误与状态码

错误体：`{"detail": "<string>"}`。

| HTTP | 典型原因 | 对齐 gRPC |
| ---- | -------- | --------- |
| `400` | 校验失败 / `ValueError`（如缺 `session_id`、非法 `metadata`） | `INVALID_ARGUMENT` |
| `404` | Agent 不存在（`KeyError`） | `NOT_FOUND` |
| `409` | 同一 session 已有活跃 turn（`RuntimeError`） | `FAILED_PRECONDITION` |
| `429` | `max_agents` 超额 | `RESOURCE_EXHAUSTED` |
| `499` | 当轮被 Cancel 中止（同步 RPC） | `CANCELLED` |
| `500` | 内部错误；文案脱敏为 `{Operation} failed` | `INTERNAL` |

**SSE 特例**：`StreamingResponse` 一旦开始即已发出 **200**，之后无法改 status。终端语义看事件类型（`done` / `interrupt` / `error` / `cancelled`），不要仅凭 HTTP 200 当成功。流开始前的校验（空 id、未知 agent）仍走上表。

---

## 4. CreateAgent

`POST /v1/agents`

**请求** `CreateAgentBody`

```json
{
  "config": {
    "name": "demo",
    "llm_config": {
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-...",
      "model_name": "gpt-4o-mini",
      "model_provider": "openai",
      "temperature": 0.2,
      "max_tokens": 1024
    },
    "skill_list": [],
    "mcp_servers": []
  },
  "runtime_options": {
    "checkpointer_kind": "memory",
    "checkpointer_uri": null
  }
}
```

- `config`：`AgentConfig`（字段以 Python 模型为准）。启用内置 Filesystem 时需 `allowed_directories`。
- `runtime_options` 可选；缺省为进程内 Memory checkpointer。

**响应** `200` `AgentHandleBody`

```json
{ "id": "aid-1" }
```

---

## 5. DeleteAgent

`DELETE /v1/agents/{agent_id}`

**响应** `204`（无 body）。未知 `agent_id` → `404`。

---

## 6. Invoke

`POST /v1/agents/{agent_id}/sessions/{session_id}/invoke`

**请求** `InvokeBody`

```json
{
  "input": { "text": "hello", "attachments": [] },
  "agent_mode": "agent",
  "http_request": {
    "url": null,
    "headers": { "Authorization": "Bearer xxx" }
  },
  "metadata": {
    "trace_id": "abc"
  }
}
```

| 字段 | 说明 |
| ---- | ---- |
| `input` | `UserInput`：`text`；`attachments` 可选（v0.1 仅 text 进模型） |
| `agent_mode` | 默认 `"agent"`；另有 `"ask"`（只读） |
| `http_request` | 可选；`headers` 供 Skill / 出站 HTTP 鉴权 |
| `metadata` | 可选 `map<string,string>`，透传到 `RunnableConfig.configurable["metadata"]` |

**metadata 约定**（与 gRPC 相同）

- 业务键由宿主约定；echo-agent **不解释**（如 `user_id` / `tenant_id`）。
- **保留键 `http_headers`**：值为 **JSON object 字符串**（如 `"{\"Authorization\":\"Bearer xxx\"}"`）。入口校验后解析为 `dict[str, str]`。非法则 `400`。

路径上的 `agent_id` / `session_id` 必填；`session_id` 由宿主管理（无 CreateSession）。

**响应** `200` `AgentResponseBody`

```json
{
  "output": "最终回复",
  "interrupted": false,
  "interrupt": null,
  "agent_result": null
}
```

- `interrupted=true`：停在 HITL，读 `interrupt`（对象，非 JSON 字符串）。
- 被 Cancel 中止的同步 Invoke → **`499`**。

---

## 7. Resume

`POST /v1/agents/{agent_id}/sessions/{session_id}/resume`

**请求** `ResumeBody`：`values` **必填**（可为 `{}`，须为 JSON object）。

```json
{
  "values": { "approved": true },
  "agent_mode": "agent",
  "metadata": { "trace_id": "abc" }
}
```

信息补全示例（字段以当时 `interrupt` 为准）：

```json
{ "values": { "city": "上海", "date": "2026-07-24" } }
```

**响应** 同 Invoke 的 `AgentResponseBody`。

---

## 8. Cancel

`POST /v1/agents/{agent_id}/sessions/{session_id}/cancel`

无 JSON body。只停当前这一轮，不删 Agent、不换 `session_id`。

**与 HITL 取消的区别**

| | `Cancel` | HITL `Resume` + `{"cancelled": true}` |
| -- | -- | -- |
| 时机 | 图正在跑 / 正在流式输出 | 已停在 interrupt |
| 效果 | `task.cancel()` + tip 回滚到开跑前 checkpoint | 继续图，走 cancelled 状态机 |

**响应** `200`

```json
{ "cancelled": true }
```

- `true`：当时有活跃 turn，已取消并回滚  
- `false`：当时无活跃 turn（幂等成功）

同一 `agent_id` + `session_id` **同时只允许一轮**；并发第二轮 → `409`。

宿主推荐：前端点停止 → 断开 SSE（若有）→ 再调 Cancel → 同 session 可立刻下一轮。断流时服务端也会走同一取消路径。

---

## 9. Stream / StreamResume（SSE）

`POST /v1/agents/{agent_id}/sessions/{session_id}/stream`  
请求体同 **Invoke**。

`POST /v1/agents/{agent_id}/sessions/{session_id}/resume/stream`  
请求体同 **Resume**。

响应：`200` + `Content-Type: text/event-stream`。

帧格式：

```text
event: <type>
data: <json>

```

实现：`event: <type>\ndata: <json>\n\n`。

事件顺序：`message*` → 以 `interrupt` | `done` | `error` | `cancelled` 之一收尾。可选 `tool_result` / `agent_result`。

| type | 含义 |
| ---- | ---- |
| `message` | 模型/消息片段，如 `{"role":"assistant","content":"..."}` |
| `interrupt` | HITL 挂起 |
| `done` | 正常结束，如 `{"output":"..."}` |
| `error` | 错误，如 `{"message":"...","type":"..."}`；随后结束流 |
| `cancelled` | 当轮被中止（Cancel 或断流） |

**失败契约**：出现 `error` 后服务端结束流。HTTP 无法再改 status，宿主须以 **事件类型** 判断成败（勿仅因流结束当成功）。

**取消契约**：出现 `cancelled` 或客户端断开后，checkpoint tip 已回滚；勿把半截 `message` 当正式终态。

curl 示例：

```bash
curl -N -X POST "http://127.0.0.1:8000/v1/agents/aid-1/sessions/sess-1/stream" \
  -H "Content-Type: application/json" \
  -d '{"input":{"text":"hello"}}'
```

---

## 10. 注意

- **不提供** CreateSession / DeleteSession；`session_id` 由宿主管理  
- 同一 `agent_id` + 同一 `session_id` 共享 Checkpoint，才能多轮与 Resume  
- 一阶段工具来自 MCP + Skill；无本地业务 Tool 注册 API  
- 详细字段以 FastAPI OpenAPI、`echo_agent.adapter.http.schemas` 与 gRPC proto 为准

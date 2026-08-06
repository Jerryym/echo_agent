# Adapter 模块 Code Review


| 项   | 内容                                                                 |
| --- | ------------------------------------------------------------------ |
| 范围  | `echo_agent/adapter/`（含 gRPC / proto / AgentRuntime / convert / events） |
| 对照  | 设计目标见下方 §设计目标；设计文档 `docs/runtime adapter/runtime adapter v0.1.0 设计文档.md` |
| 日期  | 2026-08-05                                                         |
| 原则  | 优先 bugs、行为回归、安全问题、缺失测试；条目状态见下方「处理状态一览」 |


## 覆盖文件


| 区域            | 路径                                                                 |
| ------------- | ------------------------------------------------------------------ |
| 包入口           | `echo_agent/adapter/__init__.py`                                   |
| Runtime 适配入口  | `echo_agent/adapter/agent_runtime.py`                              |
| 事件映射          | `echo_agent/adapter/events.py`                                     |
| 协议辅助类型        | `echo_agent/adapter/schema.py`                                     |
| RuntimeConfig | `echo_agent/adapter/runtime_config.py`                             |
| Proto ↔ 模型    | `echo_agent/adapter/convert.py`                                    |
| gRPC Servicer | `echo_agent/adapter/grpc/service.py`                               |
| gRPC Server   | `echo_agent/adapter/grpc/server.py`                                |
| 契约              | 源：`echo_agent/adapter/proto/echo_agent.proto`；生成物：`echo_agent/adapter/grpc/pb/` |
| 测试            | `tests/test_adapter_grpc.py`                                       |
| 集成示例          | `examples/integrator_runtime/`                                     |


## 设计目标（审查基准）

1. 通过 gRPC 等协议，让非 Python 客户端能够调用 echo-agent Runtime  
2. 仅负责协议适配：请求/响应转换、通信管理；不承担业务逻辑  
3. 保持 Runtime 独立性：Adapter 不侵入 Agent 执行流程  
4. 提供统一交互接口  
5. 支持业务场景扩展：通过 metadata/context 透传业务信息；不在 Adapter 中定义用户/租户/权限/计费等业务模型  
6. 不承担平台能力：认证、权限、用量计费、Skill/KB 管理  
7. 保持轻量可替换：独立接入层；未来可扩展 HTTP/WebSocket  


## 总览

分层大体正确：`AgentRuntime` 薄转发 + gRPC Servicer 做协议映射，未侵入 `core` 执行路径；通过注入 `AgentFactory` 将组装留给集成方，比设计稿「Adapter 内写死 ReAct」更贴合目标 2/7。

### 处理状态一览（本轮收口）


| # | 标题 | 状态 |
| --- | --- | --- |
| 1 | CreateAgent / stdio MCP 面 | **部分**：方案 1 已落地；方案 2/3 **延期**（Pending Gateway，文件内标注） |
| 2 | metadata 透传 | **已处理** |
| 3 | Stream 错误 vs gRPC OK | **已处理**（方案 B） |
| 4 | DeleteAgent / 上限 | **已处理** |
| 5 | convert 拆离 pb | **延期**（暂不处理） |
| 6 | temperature=0 | **已处理**（仅 temperature） |
| 7 | JSON → INVALID_ARGUMENT | **已处理** |
| 8 | 测试覆盖 | **部分**：已补核心单测；完整 e2e **延期** |
| 9 | INTERNAL 脱敏 | **已处理**（固定短文案 + 日志） |
| 10 | Proto 字段缺口（builtin/conversation 等） | **延期** |
| 11 | Proto 收口到 adapter | **已处理** |

延期项仅作标注，本轮不再跟进。开放余量：#8 e2e（若需要再开）。

---

## Critical

### 1. CreateAgent 可触发任意进程执行（stdio MCP）


| 项   | 内容                                                         |
| --- | ---------------------------------------------------------- |
| 模块  | `adapter/convert` + `adapter/grpc/server` + 集成方 factory     |
| 位置  | `convert.py` `mcp_connection_from_proto`；`server.py` `create_server`；`AgentConfig.mcp_servers` |
| 目标  | 与目标 6「不做认证」不冲突，但暴露了未鉴权下的执行面                               |


**问题**

- Proto 允许 `MCPConnectionConfig.type = "stdio"` 并传入任意 `command` / `args`。
- 服务默认 `add_insecure_port`，无拦截器。
- 任意能连端口的客户端：`CreateAgent` → factory `register_mcp_tools()` → 拉起本地进程。

**改动建议方案**

分三层，可按部署环境组合：

1. **默认绑定收紧（立即）— 已落地**  
   - `create_server` / `start` / CLI 默认 `host=127.0.0.1`。  
   - 启动日志：`insecure; host must terminate TLS/auth`；CLI help / 快速接入已说明。

2. **CreateAgent 策略开关 — Pending（依赖 Runtime Gateway）**  
   - 远程是否允许任意 `stdio` command、内置 Fetch 能力开关、同名覆盖规则等属 **信任边界 / 能力策略**，更适合 Runtime Gateway（或宿主控制面），而非当前仅做协议映射的 Adapter。  
   - 仓库尚无 Gateway 设计与实现；此时在 Adapter 内写死「一律禁 stdio」会误伤内置 Fetch（本身为 stdio），也不宜半吊子放行。  
   - **落地前缓解**：方案 1 默认 loopback；跨机须宿主网络隔离 + 鉴权。残余风险：本机或显式公网绑定下，CreateAgent + 任意 stdio 仍可用。  
   - Gateway 就绪后再定：`allow_remote_stdio_mcp`、远程 `enable_builtin_*`、禁止用 `mcp_servers` 覆盖内置 command 等。

3. **宿主鉴权挂钩（不做成平台，仅扩展点）— 可与 Gateway 同批**  
   - 提供可选 `grpc.aio.ServerInterceptor` 注入点（如 `create_server(..., interceptors=())`），Adapter **不实现** JWT/RBAC，只留钩子。  
   - 快速接入文档增加「生产必须：网络隔离 + 宿主鉴权 + 禁止匿名 CreateAgent」。

**验收**

- 默认配置下外网打不到服务端口（方案 1）。  
- 文档与 CLI help 可见 insecure / 回环基线说明。  
- 方案 2 策略待 Gateway 设计后验收。

---

## High

### 2. 无 metadata/context 透传通道（目标 5）— **已处理**


| 项   | 内容                                                    |
| --- | ----------------------------------------------------- |
| 模块  | proto + `AgentRuntime` + `Agent`                        |
| 位置  | `adapter/proto`；`agent_runtime.py`；`agent.py`；`runnable_metadata.py` |
| 目标  | 目标 5                                                  |


**原问题**

- 请求契约仅有 `agent_id` / `session_id` / `input|values_json`，宿主无法透传运行时上下文。

**落地**

1. Proto：`InvokeRequest` / `ResumeRequest` 增加 `map<string,string> metadata = 4`。  
2. Servicer → `AgentRuntime` → `Agent` 原样下传。  
3. `Agent._build_runnable_config` 写入 `RunnableConfig.configurable["metadata"]`。  
4. 保留键 `http_headers`（常量见 `runnable_metadata.py`）：请求侧为 JSON 字符串，规范化后为 `dict[str, str]`（方案 B）。其它键不解释。  
5. Adapter 无 User/Tenant/Billing 类型。

**验收**

- Invoke/Resume 可带 metadata；节点可读 `configurable["metadata"]`。  
- `http_headers` 非法 → `ValueError` / gRPC `INVALID_ARGUMENT`。

---

### 3. 流式错误被吞成 `error` 事件，gRPC 仍 OK — **已处理（方案 B）**


| 项   | 内容                                      |
| --- | --------------------------------------- |
| 模块  | `adapter/events` + `adapter/grpc/service` |
| 位置  | `events.py` `iter_agent_events`；`service.py` `Stream` / `StreamResume` |


**原问题**

- `iter_agent_events` 捕获异常并 `yield error` 后不再抛出 → Servicer 正常结束 → **gRPC status = OK**。  
- 与 Invoke（`abort(INTERNAL)`）不一致。

**落地**

1. `iter_agent_events` / sync：yield `error` 后 **re-raise**。  
2. `Stream` / `StreamResume`：下发 `error` 事件后 `context.abort(INTERNAL, "Stream failed")`（短文案，不附带异常原文）。  
3. 快速接入写清：`message* → (interrupt|done|error)`；出现 `error` 时 RPC 非 OK。

**验收**

- 流失败时可拿到 `error` 事件，且 RPC status ≠ OK。

---

### 4. `AgentRuntime` 无销毁/上限 → 进程内泄漏 — **已处理**


| 项   | 内容                          |
| --- | --------------------------- |
| 模块  | `adapter/agent_runtime` + proto + Servicer |
| 位置  | `delete_agent`；`max_agents`；`DeleteAgent` RPC |


**原问题**

- 仅有 Create，无 Delete；无上限 → 长跑泄漏。

**落地**

1. Proto：`rpc DeleteAgent(DeleteAgentRequest) returns (DeleteAgentResponse)`。  
2. `AgentRuntime.delete_agent`：`pop` 实例；若存在 `aclose`/`close` 则调用。  
3. `AgentRuntime(..., max_agents=N)`：超额 Create 抛 `AgentLimitExceededError` → gRPC `RESOURCE_EXHAUSTED`。  
4. 文档：宿主业务结束时 DeleteAgent。

**验收**

- Delete 后同一 `agent_id` → NOT_FOUND。  
- `max_agents` 超额 → `RESOURCE_EXHAUSTED`。

---

## Medium

### 5. `convert.py` 绑死 gRPC proto，削弱协议可替换性 — **暂不处理**


| 项   | 内容                    |
| --- | --------------------- |
| 模块  | `adapter/convert`     |
| 位置  | `convert.py` 顶部 `from .grpc.pb import ...` |
| 目标  | 目标 7                  |


**问题**

- 协议无关的 Runtime/schema 之上，转换层直接依赖 `echo_agent_pb2`。  
- 增加 HTTP/WebSocket 时要么复制转换，要么硬拉 protobuf。

**决定**

当前仅 gRPC 一种协议，拆层收益有限；**延期**至引入 HTTP/WebSocket 或明确多协议时再做。建议方案仍保留如下，供后续实施：

```text
proto / HTTP JSON
    → adapter/grpc/convert_grpc.py   (pb ↔ schema/DTO)
    → adapter/convert.py             (DTO ↔ AgentConfig/UserInput)  # 无 pb 依赖
    → AgentRuntime
```

**验收（未来）**

- `echo_agent.adapter.convert` 的 import 图中无 `grpc` / `pb2`。  
- 现有测试改 import 路径后仍通过。

---

### 6. Proto3 零值导致 `temperature=0` 无法设置 — **已处理（收窄）**


| 项   | 内容                |
| --- | ----------------- |
| 模块  | `adapter/convert` + proto |
| 位置  | `llm_config_from_proto`；`LLMConfig.temperature` |


**原问题**

- `temperature == 0.0` 被当成未设置，回退默认 `0.2`。

**落地**

1. proto：`optional double temperature = 5;`，convert 用 `HasField("temperature")`。  
2. **仅 temperature 支持显式 0**；`max_tokens` / `timeout` / `max_retries` 仍以 `> 0` 表示已设置（`0` = 未设置 → Python 默认）。不把「合法 0」扩到这些字段。

**验收**

- 客户端设 `temperature=0` → `LLMConfig.temperature == 0.0`。  
- 未设 temperature → 默认 `0.2`；`max_tokens=0` 等仍回退默认。

---

### 7. 校验错误映射不一致（JSON → INTERNAL vs INVALID_ARGUMENT）— **已处理**


| 项   | 内容                         |
| --- | -------------------------- |
| 模块  | `convert` + `grpc/service` |
| 位置  | `llm_config_from_proto`；`_parse_resume` |


**原问题**

- `values_json` 非法 → `ValueError` → INVALID_ARGUMENT。  
- `extra_json` 非法 → `JSONDecodeError` → INTERNAL。

**落地**

1. `llm_config_from_proto`：`json.loads(extra_json)` 捕获 `JSONDecodeError` 并包装为 `ValueError`。  
2. Servicer 保持：`ValueError` → INVALID_ARGUMENT；`KeyError` → NOT_FOUND；其余 → INTERNAL。  
3. 单测覆盖非法 `extra_json` / `values_json` 均抛 `ValueError`。

**验收**

- 同类输入错误一律可映射为 INVALID_ARGUMENT。

---

### 8. 测试覆盖偏薄 — **部分完成**


| 项   | 内容                     |
| --- | ---------------------- |
| 模块  | `tests/test_adapter_grpc.py` |
| 位置  | 转换 + bind + metadata / events / INTERNAL |


**原问题**

缺 Runtime、events、e2e RPC、错误码映射测试。

**已补（同文件）**

- temperature=0、非法 `extra_json` / `values_json`  
- metadata / `http_headers` 规范化与 Runtime 转发  
- `iter_agent_events` error 后 re-raise  
- `_internal_details` 默认脱敏  

**仍缺（可后续拆文件）**

| 用例组 | 内容 |
| --- | --- |
| `test_adapter_grpc_e2e.py` | in-process gRPC：CreateAgent / Invoke / Stream status 契约 |
| events 映射单测 | `map_stream_chunk` 对 AI/Human/Tool；done / interrupt 收尾 |
| DeleteAgent | 待 #4 落地后补 |

**验收（余量）**

- CI 覆盖 in-process e2e 与 Stream 失败 status。

---

## Low

### 9. INTERNAL 详情可能泄露敏感信息 — **已处理**


| 项   | 内容                |
| --- | ----------------- |
| 模块  | `grpc/service.py` |
| 位置  | `_internal_details`；各 RPC `except Exception` |


**原问题**

异常原文（路径、MCP 命令、偶发密钥片段）经 `abort(..., f"...: {exc}")` 回传客户端。

**落地**

1. 对外固定短文案：`"{Op} failed"`；细节仅 `logger.exception(...)`，**不**回传异常原文。  
2. `INVALID_ARGUMENT` / `NOT_FOUND` / `RESOURCE_EXHAUSTED` 仍返回可读校验/资源文案。

**验收**

- INTERNAL details 无绝对路径 / api_key / 异常栈原文。

---

### 10. 契约与文档缺口（完整性 / 对齐）


| 项   | 内容 |
| --- | --- |
| 模块  | proto + 设计文档 + convert |
| 位置  | `AgentConfig` 字段；设计文档 §3.5 / §14 |


**问题**

| 缺口 | 影响 |
| --- | --- |
| 无 `conversation_max_tokens` | 跨语言无法调压缩阈值 |
| 无 `enable_builtin_fetch` / `enable_builtin_filesystem` | 只能靠本地 factory 打开 |
| `skill_list: map<string,string>` vs Python `dict[str, Any]` | 非 string 值无法表达 |
| 设计文档写「Adapter 内默认 ReAct 组装」，实现已外置 factory | 文档与实现对齐；**外置更符合目标 2/7** |

**改动建议方案**

1. **Proto 增量（可与 #2/#4/#6 同小版本）**  
   - `int32 conversation_max_tokens = 9;`（0 = 未设置 → Python 默认）  
   - `bool enable_builtin_fetch = 10;` / `bool enable_builtin_filesystem = 11;`（bool 默认 false 与当前 Python 默认一致，可接受）  
   - `skill_list`：短期保持 `map<string,string>`；若需 Any，增加 `string skill_list_json = 12` 并在文档弃用 map，或约定复杂值只走 JSON。

2. **文档回写**  
   - §3.5 / §14 / §15：改为「Adapter 提供 `AgentRuntime` + 可注入 factory；**默认 ReAct 组装在集成方示例**（`examples/integrator_runtime`），不进入 core，也不强制进 Adapter 库内」。  
   - 与目标 2/7 一致，避免读者以为必须在 adapter 包内写死 ReAct。

3. **convert**  
   - 映射新增字段；builtin 开关显式传入，替代注释「只能在 Python 打开」。

**验收**

- 设计文档与 `examples/integrator_runtime`、实际代码路径一致。  
- 跨语言可设置 conversation / builtin 开关。

---

### 11. Proto 源与生成物分离，未在 Adapter 内统一管理 — **已处理**


| 项   | 内容 |
| --- | --- |
| 模块  | `adapter/proto` + `adapter/grpc/` |
| 位置（现） | 源：`echo_agent/adapter/proto/echo_agent.proto`；生成物：`adapter/grpc/pb/`；脚本：`adapter/grpc/generate.py` |
| 目标  | 目标 2（协议归属接入层）、目标 7（轻量可替换、边界清晰） |


**原问题**

契约资产曾拆成两处：`.proto` 在包根 `echo_agent/proto/`，stubs 在 `adapter/grpc/pb/`，边界不清、所有权分散。

**落地**

1. proto 源迁至 `echo_agent/adapter/proto/echo_agent.proto`（与 grpc 实现并列，便于二期 HTTP 复用契约而不挂在 `grpc/` 下）。
2. `generate.py` 的 `-I` / 输入路径改为 `echo_agent/adapter/proto`；`package echo_agent.v1` 与字段号未改（纯路径迁移）。
3. 删除包根 `echo_agent/proto/`；快速接入 / 跨语言 / 设计文档路径已对齐。
4. 验收：`uv run python -m echo_agent.adapter.grpc.generate` 成功，并 patch `pb2_grpc` 相对 import。

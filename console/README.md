# echo-agent console

PySide6 交互测试壳：固定 `MainWindow`，测例逻辑放在 `case/`。

## Setup

```bash
# 在仓库根目录
uv sync
cp console/.env.template console/.env   # 填写模型配置
```

## Run

```bash
cd console
uv run --project .. python app.py
```

## Test Cases

| Case | 说明 |
|------|------|
| LLM Client | 直接测 LLMClient |
| Agent（无策略） | 单 LLM 节点 Agent |
| ReAct（无HITL） | ReAct + business tools，无审批 |
| ReAct（有HITL） | ReAct + `create_refund` 需审批 |
| ReAct MCP（无HITL） | ReAct + builtin(Fetch/Filesystem) + stdio + http，异步轨 |
| ReAct MCP（有HITL） | 同上 + `create_refund` / filesystem 写操作需审批 |
| HITL Subgraph | 无模型；消息含 `approval` 走审批，否则补参 |

### MCP Cases

固定同时启用：

- **builtin**：Fetch + Filesystem（`mcp_allowed_directories` 由调用方传入）
- **stdio**：`@modelcontextprotocol/server-everything`
- **http**：`http://localhost:8000/mcp`（需另开终端）

```bash
# 终端 1：本地 http MCP（含 create_refund 等）
uv run python tests/mcp_server.py

# 终端 2：console
cd console
uv run --project .. python app.py
```

首次发消息时会在后台线程拉起 MCP 并 `register_tools`，可能稍慢。

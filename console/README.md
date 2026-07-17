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
| HITL Subgraph | 无模型；消息含 `approval` 走审批，否则补参 |

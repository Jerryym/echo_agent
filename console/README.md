# echo-agent console

PyQt6 交互测试壳：固定 `MainWindow`，测例逻辑放在 `module/`，依赖与核心库隔离。

## Setup

```bash
cd example
uv sync
cp .env.template .env   # 填写模型配置
```

使用本目录独立 `.venv`，不会把 PyQt6 装进仓库根环境。

## Run

```bash
uv run python app.py
```

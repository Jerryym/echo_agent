"""
集成方入口：注入 Agent 工厂并启动本库 HTTP（REST + SSE）。

仓库根目录执行：

  uv run python -m examples.integrator_runtime_http.main --host 127.0.0.1 --port 8000

或：

  uv run python -m echo_agent.adapter.http.server \\
    --factory examples.integrator_runtime.build_agent:build_agent \\
    --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from echo_agent.adapter import AgentRuntime
from echo_agent.adapter.http.server import start

from ..build_agent import build_agent


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Integrator runtime: factory + HTTP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(list(argv) if argv is not None else None)

    runtime = AgentRuntime(factory=build_agent)
    start(runtime, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

"""HTTP 服务启动入口（uvicorn）。"""

from __future__ import annotations

from collections.abc import Sequence

import uvicorn

from ...common import get_logger
from ..agent_runtime import AgentRuntime
from ..factory import load_factory
from .app import create_app

logger = get_logger("adapter.http")

__all__ = ["create_app", "start", "main", "load_factory"]


def start(
    runtime: AgentRuntime,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """
    启动 HTTP server 并阻塞。

    默认仅绑定回环地址。跨机访问需显式传入 ``host``，并由宿主终止 TLS / 鉴权。
    """
    app = create_app(runtime)
    logger.info(
        "echo-agent HTTP listening on %s:%s (insecure; host must terminate TLS/auth)",
        host,
        port,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


def main(argv: Sequence[str] | None = None) -> None:
    """CLI：需指定集成方工厂，例如 `--factory pkg.module:build_agent`。"""
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "echo-agent Runtime Adapter HTTP server "
            "(insecure; default bind is loopback only)"
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind host (default 127.0.0.1; use 0.0.0.0/[::] only behind TLS/auth)",
    )
    parser.add_argument("--port", type=int, default=8000, help="bind port (default 8000)")
    parser.add_argument(
        "--factory",
        required=True,
        help="Agent factory as module:attr (e.g. examples.integrator_runtime.build_agent:build_agent)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    runtime = AgentRuntime(factory=load_factory(args.factory))
    start(runtime, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

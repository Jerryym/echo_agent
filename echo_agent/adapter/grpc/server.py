"""gRPC 服务启动入口。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import grpc

from ...common import get_logger
from ..agent_runtime import AgentRuntime
from ..factory import load_factory
from .pb import echo_agent_pb2_grpc as pb_grpc
from .service import EchoAgentServicer

logger = get_logger("adapter.grpc")

__all__ = ["create_server", "start", "main", "load_factory"]


async def create_server(
    runtime: AgentRuntime,
    *,
    host: str = "127.0.0.1",
    port: int = 50051,
    max_workers: int | None = None,
) -> tuple[grpc.aio.Server, AgentRuntime, str]:
    """
    创建并绑定 gRPC server（未 start）。

    默认仅绑定回环地址，避免误暴露到公网。跨机访问需显式传入 ``host``
    （如 ``0.0.0.0`` / ``[::]``），并由宿主侧终止 TLS / 鉴权。

    Returns:
        (server, runtime, listen_addr)
    """
    del max_workers  # aio server 不使用 ThreadPoolExecutor workers
    server = grpc.aio.server()
    pb_grpc.add_EchoAgentServiceServicer_to_server(EchoAgentServicer(runtime), server)
    bind_target = f"{host}:{port}"
    bound_port = server.add_insecure_port(bind_target)
    if bound_port == 0:
        raise RuntimeError(f"failed to bind gRPC port: {bind_target}")
    listen_addr = f"{host}:{bound_port}"
    return server, runtime, listen_addr


async def start(
    runtime: AgentRuntime,
    *,
    host: str = "127.0.0.1",
    port: int = 50051,
) -> None:
    """启动 gRPC server 并阻塞至终止。"""
    server, _, listen_addr = await create_server(runtime, host=host, port=port)
    await server.start()
    logger.info(
        "echo-agent gRPC listening on %s (insecure; host must terminate TLS/auth)",
        listen_addr,
    )
    await server.wait_for_termination()


def main(argv: Sequence[str] | None = None) -> None:
    """CLI：需指定集成方工厂，例如 `--factory pkg.module:build_agent`。"""
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "echo-agent Runtime Adapter gRPC server "
            "(insecure channel; default bind is loopback only)"
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind host (default 127.0.0.1; use 0.0.0.0/[::] only behind TLS/auth)",
    )
    parser.add_argument("--port", type=int, default=50051, help="bind port (default 50051)")
    parser.add_argument(
        "--factory",
        required=True,
        help="Agent factory as module:attr (e.g. examples.integrator_runtime.build_agent:build_agent)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    runtime = AgentRuntime(factory=load_factory(args.factory))
    asyncio.run(start(runtime, host=args.host, port=args.port))


if __name__ == "__main__":
    main()

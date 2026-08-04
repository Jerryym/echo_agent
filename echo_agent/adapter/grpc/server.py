"""gRPC 服务启动入口。"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Sequence

import grpc

from ...common import get_logger
from ..agent_runtime import AgentFactory, AgentRuntime
from .pb import echo_agent_pb2_grpc as pb_grpc
from .service import EchoAgentServicer

logger = get_logger("adapter.grpc")


def load_factory(spec: str) -> AgentFactory:
    """
    从 `module:attr` 加载 Agent 工厂。

    例：`examples.integrator_runtime.build_agent:build_agent`
    """
    module_name, sep, attr = spec.partition(":")
    if not sep or not module_name.strip() or not attr.strip():
        raise ValueError(
            f"invalid factory spec {spec!r}; expected 'module:attr'"
        )
    module = importlib.import_module(module_name.strip())
    factory = getattr(module, attr.strip(), None)
    if factory is None or not callable(factory):
        raise ValueError(f"factory not found or not callable: {spec}")
    return factory


async def create_server(
    runtime: AgentRuntime,
    *,
    host: str = "[::]",
    port: int = 50051,
    max_workers: int | None = None,
) -> tuple[grpc.aio.Server, AgentRuntime, str]:
    """
    创建并绑定 gRPC server（未 start）。

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
    host: str = "[::]",
    port: int = 50051,
) -> None:
    """启动 gRPC server 并阻塞至终止。"""
    server, _, listen_addr = await create_server(runtime, host=host, port=port)
    await server.start()
    logger.info("echo-agent gRPC listening on %s", listen_addr)
    await server.wait_for_termination()


def main(argv: Sequence[str] | None = None) -> None:
    """CLI：需指定集成方工厂，例如 `--factory pkg.module:build_agent`。"""
    import argparse

    parser = argparse.ArgumentParser(description="echo-agent Runtime Adapter gRPC server")
    parser.add_argument("--host", default="[::]", help="bind host (default [::])")
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

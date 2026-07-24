"""gRPC 服务启动入口。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import grpc

from ..agent_runtime import AgentRuntime
from .pb import echo_agent_pb2_grpc as pb_grpc
from .service import EchoAgentServicer


async def create_server(
    runtime: AgentRuntime | None = None,
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
    runtime = runtime or AgentRuntime()
    server = grpc.aio.server()
    pb_grpc.add_EchoAgentServiceServicer_to_server(EchoAgentServicer(runtime), server)
    bind_target = f"{host}:{port}"
    bound_port = server.add_insecure_port(bind_target)
    if bound_port == 0:
        raise RuntimeError(f"failed to bind gRPC port: {bind_target}")
    listen_addr = f"{host}:{bound_port}"
    return server, runtime, listen_addr


async def start(
    runtime: AgentRuntime | None = None,
    *,
    host: str = "[::]",
    port: int = 50051,
) -> None:
    """启动 gRPC server 并阻塞至终止。"""
    server, _, listen_addr = await create_server(runtime, host=host, port=port)
    await server.start()
    print(f"echo-agent gRPC listening on {listen_addr}")
    await server.wait_for_termination()


def main(argv: Sequence[str] | None = None) -> None:
    """CLI：`python -m echo_agent.adapter.grpc.server [--host HOST] [--port PORT]`。"""
    import argparse

    parser = argparse.ArgumentParser(description="echo-agent Runtime Adapter gRPC server")
    parser.add_argument("--host", default="[::]", help="bind host (default [::])")
    parser.add_argument("--port", type=int, default=50051, help="bind port (default 50051)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    asyncio.run(start(host=args.host, port=args.port))


if __name__ == "__main__":
    main()

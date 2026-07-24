"""gRPC Adapter 子包。

推荐显式导入::

    from echo_agent.adapter.grpc.server import start
    from echo_agent.adapter.grpc.service import EchoAgentServicer
"""

from __future__ import annotations

__all__ = ["EchoAgentServicer", "create_server", "start"]


def __getattr__(name: str):
    if name == "EchoAgentServicer":
        from .service import EchoAgentServicer

        return EchoAgentServicer
    if name in ("create_server", "start"):
        from . import server

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

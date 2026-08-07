"""FastAPI 应用工厂。"""

from __future__ import annotations

from fastapi import FastAPI

from ..agent_runtime import AgentRuntime
from .errors import register_exception_handlers
from .routes import router


def create_app(runtime: AgentRuntime) -> FastAPI:
    """
    创建绑定 ``AgentRuntime`` 的 HTTP 应用。

    路由前缀 ``/v1``；流式为独立路径 ``.../stream``、``.../resume/stream``（SSE）。
    """
    app = FastAPI(
        title="echo-agent Runtime Adapter",
        version="0.1.0",
        description="HTTP adapter for echo-agent Runtime (insecure; terminate TLS/auth at host)",
    )
    app.state.runtime = runtime
    register_exception_handlers(app)
    app.include_router(router, prefix="/v1")
    return app

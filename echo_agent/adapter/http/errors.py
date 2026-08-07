"""HTTP 异常 → 状态码（对齐 gRPC Servicer 映射）。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ...common import get_logger
from ..agent_runtime import AgentLimitExceededError

logger = get_logger("adapter.http")


class InternalAdapterError(Exception):
    """对外脱敏的 INTERNAL；细节已由调用方 logger.exception 记录。"""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(internal_message(operation))


class TurnCancelledError(Exception):
    """当轮被 Cancel 中止（对齐 gRPC CANCELLED）。"""


def internal_message(operation: str) -> str:
    """对外 INTERNAL 短文案（不附带异常原文）。"""
    return f"{operation} failed"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc.errors())})

    @app.exception_handler(AgentLimitExceededError)
    async def _limit(_request: Request, exc: AgentLimitExceededError) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def _not_found(_request: Request, exc: KeyError) -> JSONResponse:
        detail = str(exc).strip("'")
        return JSONResponse(status_code=404, content={"detail": detail})

    @app.exception_handler(ValueError)
    async def _bad_request(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RuntimeError)
    async def _precondition(_request: Request, exc: RuntimeError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(TurnCancelledError)
    async def _cancelled(_request: Request, _exc: TurnCancelledError) -> JSONResponse:
        # 非标准 499，与 nginx client-closed / gRPC CANCELLED 对齐
        return JSONResponse(status_code=499, content={"detail": "cancelled"})

    @app.exception_handler(InternalAdapterError)
    async def _internal(_request: Request, exc: InternalAdapterError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

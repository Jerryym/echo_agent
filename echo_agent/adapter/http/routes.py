"""HTTP 路由：Create / Delete / Invoke / Resume / Cancel / Stream / StreamResume。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from ...common import get_logger
from ..agent_runtime import AgentLimitExceededError, AgentRuntime
from .errors import InternalAdapterError, TurnCancelledError
from .schemas import (
    AgentHandleBody,
    AgentResponseBody,
    CancelResponseBody,
    CreateAgentBody,
    InvokeBody,
    ResumeBody,
)
from .sse import iter_sse

logger = get_logger("adapter.http")

router = APIRouter()

_RERAISE = (
    ValueError,
    KeyError,
    RuntimeError,
    AgentLimitExceededError,
    TurnCancelledError,
    InternalAdapterError,
)

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _runtime(request: Request) -> AgentRuntime:
    return request.app.state.runtime


def _agent_response(result) -> AgentResponseBody:
    return AgentResponseBody(
        output=result.output or "",
        interrupted=bool(result.interrupted),
        interrupt=result.interrupt_payload if result.interrupted else None,
    )


def _map_cancelled(exc: asyncio.CancelledError) -> TurnCancelledError:
    del exc
    return TurnCancelledError("cancelled")


def _require_agent_session(runtime: AgentRuntime, agent_id: str, session_id: str) -> None:
    """流开始前校验（StreamingResponse 会先发 200，须提前失败）。"""
    if not (agent_id or "").strip():
        raise ValueError("agent_id is required")
    if not (session_id or "").strip():
        raise ValueError("session_id is required")
    runtime.get_agent(agent_id)


@router.post("/agents", response_model=AgentHandleBody)
async def create_agent(body: CreateAgentBody, request: Request) -> AgentHandleBody:
    runtime = _runtime(request)
    try:
        options = None
        if body.runtime_options is not None:
            options = body.runtime_options.to_runtime_options()
        agent_id = await runtime.create_agent(body.config, options)
        return AgentHandleBody(id=agent_id)
    except asyncio.CancelledError as exc:
        raise _map_cancelled(exc) from exc
    except _RERAISE:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("CreateAgent failed")
        raise InternalAdapterError("CreateAgent") from exc


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, request: Request) -> Response:
    runtime = _runtime(request)
    try:
        await runtime.delete_agent(agent_id)
        return Response(status_code=204)
    except asyncio.CancelledError as exc:
        raise _map_cancelled(exc) from exc
    except _RERAISE:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("DeleteAgent failed")
        raise InternalAdapterError("DeleteAgent") from exc


@router.post(
    "/agents/{agent_id}/sessions/{session_id}/invoke",
    response_model=AgentResponseBody,
)
async def invoke(
    agent_id: str,
    session_id: str,
    body: InvokeBody,
    request: Request,
) -> AgentResponseBody:
    runtime = _runtime(request)
    try:
        result = await runtime.invoke(
            agent_id,
            session_id,
            body.input,
            http_request=body.http_request,
            metadata=body.metadata,
        )
        return _agent_response(result)
    except asyncio.CancelledError as exc:
        raise _map_cancelled(exc) from exc
    except _RERAISE:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Invoke failed")
        raise InternalAdapterError("Invoke") from exc


@router.post(
    "/agents/{agent_id}/sessions/{session_id}/resume",
    response_model=AgentResponseBody,
)
async def resume(
    agent_id: str,
    session_id: str,
    body: ResumeBody,
    request: Request,
) -> AgentResponseBody:
    runtime = _runtime(request)
    try:
        result = await runtime.resume(
            agent_id,
            session_id,
            body.values,
            http_request=body.http_request,
            metadata=body.metadata,
        )
        return _agent_response(result)
    except asyncio.CancelledError as exc:
        raise _map_cancelled(exc) from exc
    except _RERAISE:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Resume failed")
        raise InternalAdapterError("Resume") from exc


@router.post(
    "/agents/{agent_id}/sessions/{session_id}/cancel",
    response_model=CancelResponseBody,
)
async def cancel(
    agent_id: str,
    session_id: str,
    request: Request,
) -> CancelResponseBody:
    runtime = _runtime(request)
    try:
        cancelled = await runtime.cancel(agent_id, session_id)
        return CancelResponseBody(cancelled=cancelled)
    except asyncio.CancelledError as exc:
        raise _map_cancelled(exc) from exc
    except _RERAISE:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Cancel failed")
        raise InternalAdapterError("Cancel") from exc


@router.post("/agents/{agent_id}/sessions/{session_id}/stream")
async def stream(
    agent_id: str,
    session_id: str,
    body: InvokeBody,
    request: Request,
) -> StreamingResponse:
    runtime = _runtime(request)
    _require_agent_session(runtime, agent_id, session_id)
    events = runtime.stream(
        agent_id,
        session_id,
        body.input,
        http_request=body.http_request,
        metadata=body.metadata,
    )
    return StreamingResponse(
        iter_sse(
            request,
            runtime,
            agent_id,
            session_id,
            events,
            operation="Stream",
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/agents/{agent_id}/sessions/{session_id}/resume/stream")
async def stream_resume(
    agent_id: str,
    session_id: str,
    body: ResumeBody,
    request: Request,
) -> StreamingResponse:
    runtime = _runtime(request)
    _require_agent_session(runtime, agent_id, session_id)
    events = runtime.stream_resume(
        agent_id,
        session_id,
        body.values,
        http_request=body.http_request,
        metadata=body.metadata,
    )
    return StreamingResponse(
        iter_sse(
            request,
            runtime,
            agent_id,
            session_id,
            events,
            operation="StreamResume",
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )

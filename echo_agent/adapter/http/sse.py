"""AgentEvent → SSE 帧；流式迭代与断开/取消收尾。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request

from ...common import get_logger
from ..agent_runtime import AgentRuntime
from ..schema import AgentEvent
from .errors import internal_message

logger = get_logger("adapter.http")


def format_sse(event: AgentEvent) -> str:
    """编码为 ``event: <type>\\ndata: <json>\\n\\n``。"""
    payload: Any = event.data if event.data is not None else {}
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event.type}\ndata: {data}\n\n"


async def ensure_cancelled(
    runtime: AgentRuntime,
    agent_id: str,
    session_id: str,
) -> None:
    """断流 / CancelledError 时确保当轮 Task 取消（幂等）。"""
    if not agent_id or not session_id:
        return
    try:
        await runtime.cancel(agent_id, session_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "ensure cancel failed agent_id=%s session_id=%s",
            agent_id,
            session_id,
        )


async def iter_sse(
    request: Request,
    runtime: AgentRuntime,
    agent_id: str,
    session_id: str,
    events: AsyncIterator[AgentEvent],
    *,
    operation: str,
) -> AsyncIterator[str]:
    """
    将 AgentEvent 流写成 SSE。

    与 gRPC 方案 B 对齐：出现 ``error`` 事件后结束流。
    注意：HTTP 在 ``StreamingResponse`` 启动后已发出 200，无法再改 status；
    终端语义以事件类型（error / cancelled / done / interrupt）为准。
    流开始前的校验错误应由路由在返回 StreamingResponse 之前抛出。
    """
    try:
        async for event in events:
            if await request.is_disconnected():
                await ensure_cancelled(runtime, agent_id, session_id)
                return
            yield format_sse(event)
            if event.type == "error":
                return
    except asyncio.CancelledError:
        await ensure_cancelled(runtime, agent_id, session_id)
        if not await request.is_disconnected():
            yield format_sse(AgentEvent(type="cancelled", data={}))
        return
    except (ValueError, KeyError, RuntimeError) as exc:
        # 流中途 / 首包前（已 200）的协议错误：下发 error 事件后结束
        if not await request.is_disconnected():
            yield format_sse(
                AgentEvent(
                    type="error",
                    data={"type": type(exc).__name__, "message": str(exc)},
                )
            )
        return
    except Exception:  # noqa: BLE001
        logger.exception("%s failed", operation)
        if not await request.is_disconnected():
            yield format_sse(
                AgentEvent(
                    type="error",
                    data={
                        "type": "InternalError",
                        "message": internal_message(operation),
                    },
                )
            )
        return

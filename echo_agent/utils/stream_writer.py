from __future__ import annotations

from langgraph.config import get_stream_writer

from ..core.graph.schema import BaseContext
from ..core.model.token_usage import TokenUsage


def update_agent_result(context: BaseContext | None, content: str, token_usage: TokenUsage) -> None:
    """
    更新 AgentResult
    """
    if context is None or context.agent_result is None:
        return
    context.agent_result.apply_llm_result(content, token_usage)
    _emit_agent_result_update()


def _emit_agent_result_update() -> None:
    """通知 Agent.stream：本轮 AgentResult 已更新（invoke 路径无 writer 则忽略）。"""
    try:
        writer = get_stream_writer()
    except Exception:
        return
    if writer is None:
        return
    try:
        writer({"type": "agent_result"})
    except Exception:
        return

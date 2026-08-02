"""
Runtime Adapter：跨语言 gRPC 接入 + 默认 ReAct 组装（不侵入 echo_agent.core）。
"""

from .agent_runtime import AgentRuntime
from .schema import AgentEvent, AgentInvokeResult, RuntimeOptions

__all__ = [
    "AgentRuntime",
    "AgentEvent",
    "AgentInvokeResult",
    "RuntimeOptions",
]

"""
Runtime Adapter：跨语言 gRPC 接入 + 可注入 Agent 工厂（不侵入 echo_agent.core）。
"""

from .agent_runtime import AgentFactory, AgentLimitExceededError, AgentRuntime
from .runtime_config import build_runtime_config
from .schema import AgentEvent, AgentInvokeResult, RuntimeOptions

__all__ = [
    "AgentFactory",
    "AgentLimitExceededError",
    "AgentRuntime",
    "AgentEvent",
    "AgentInvokeResult",
    "RuntimeOptions",
    "build_runtime_config",
]

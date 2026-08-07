"""从 ``module:attr`` 加载 Agent 工厂（gRPC / HTTP 共用）。"""

from __future__ import annotations

import importlib

from .agent_runtime import AgentFactory


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

"""由 RuntimeOptions 构建 RuntimeConfig（供集成方工厂复用）。"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from echo_agent.core.runtime import RuntimeConfig

from .schema import RuntimeOptions


def build_runtime_config(options: RuntimeOptions | None = None) -> RuntimeConfig:
    """根据 RuntimeOptions 构建 RuntimeConfig。v0.1 默认 InMemorySaver。"""
    kind = (options.checkpointer_kind if options else "memory") or "memory"
    kind = kind.strip().lower()
    if kind in ("memory", "mem", "inmemory", ""):
        return RuntimeConfig(checkpointer=InMemorySaver())
    if kind == "sqlite":
        raise ValueError(
            "checkpointer_kind=sqlite is not enabled in v0.1; use memory "
            "or add a persistence dependency in a later phase"
        )
    raise ValueError(f"unsupported checkpointer_kind: {kind!r}")

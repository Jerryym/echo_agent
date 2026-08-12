from typing import Any

from langchain_core.runnables.config import RunnableConfig
from pydantic import BaseModel, Field


class RuntimeConfig(BaseModel):
    """
    运行时配置：对应 LangGraph 的 RunnableConfig

    参数：
        thread_id: 线程ID
        session_id: 会话ID
        metadata: 元数据
    """
    thread_id: str
    session_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_graph_runnable_config(self) -> RunnableConfig:
        return RunnableConfig(
            configurable={
                "thread_id": self.thread_id,
                "session_id": self.session_id,
                "metadata": self.metadata,
            }
        )

    def to_llm_runnable_config(self) -> RunnableConfig:
        return RunnableConfig(
            configurable={
                "thread_id": self.thread_id,
                "metadata": self.metadata,
            }
        )

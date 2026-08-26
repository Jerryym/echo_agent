from typing import Any

from langchain_core.runnables.config import RunnableConfig
from langgraph.config import get_config
from pydantic import BaseModel, Field

from ...common.network import HttpRequest
from ..model.agent import AgentMode


class RuntimeConfig(BaseModel):
    """
    运行时配置：对应 LangGraph 的 RunnableConfig

    参数:
        agent_id: Agent ID
        thread_id: 线程ID
        session_id: 会话ID
        agent_mode: 智能体模式
        http_request: HTTP请求配置
        metadata: 元数据
    """
    agent_id: str
    thread_id: str
    session_id: str
    agent_mode: AgentMode = Field(default=AgentMode.AGENT)
    http_request: HttpRequest | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_graph_runnable_config(self) -> RunnableConfig:
        return RunnableConfig(
            configurable={
                "agent_id": self.agent_id,
                "thread_id": self.thread_id,
                "session_id": self.session_id,
                "agent_mode": self.agent_mode,
                "http_request": (self.http_request or HttpRequest()).model_dump(),
            },
            metadata=self.metadata,
        )

    def to_llm_runnable_config(self) -> RunnableConfig:
        return RunnableConfig(
            configurable={
                "agent_id": self.agent_id,
                "thread_id": self.thread_id,
                "agent_mode": self.agent_mode,
                "http_request": (self.http_request or HttpRequest()).model_dump(),
            },
            metadata=self.metadata,
        )

    @staticmethod
    def get_runtime_config() -> "RuntimeConfig":
        """获取运行时配置"""
        config: RunnableConfig = get_config()
        configurable = config.get("configurable", {})
        return RuntimeConfig(
            agent_id=configurable["agent_id"],
            thread_id=configurable["thread_id"],
            session_id=configurable["session_id"],
            http_request=(
                HttpRequest.model_validate(configurable["http_request"])
                if configurable.get("http_request") is not None
                else None
            ),
            agent_mode=configurable["agent_mode"],
            metadata=config.get("metadata", {}),
        )

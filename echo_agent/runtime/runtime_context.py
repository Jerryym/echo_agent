from typing import Any

from pydantic import BaseModel, Field


class RuntimeContext(BaseModel):
    """
    Runtime 执行上下文（运行期）

    参数：
        thread_id: 线程ID
        session_id: 会话ID
        metadata: 元数据
    """
    thread_id: str
    session_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
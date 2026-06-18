from typing import Any, Optional, List, Dict
from pydantic import BaseModel


class LLMResult(BaseModel):
    """
    LLM 原始响应承接模型

    参数:
        content: 响应内容
        tool_calls: 工具调用
        raw: 原始响应
        response_metadata: 响应元数据
    """
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    raw: Any = None
    response_metadata: Optional[Dict[str, Any]] = None
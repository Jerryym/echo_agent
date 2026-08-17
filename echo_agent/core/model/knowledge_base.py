from pydantic import BaseModel, Field
from typing import Any


class KBDocument(BaseModel):
    """
    知识库文档

    参数:
        content: 文档内容
        metadata: 文档元数据
    """
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KBResult(BaseModel):
    """
    知识库查询结果

    参数:
        content: 知识库根据查询结果整理后的最终内容
        documents: 支撑查询结果的来源文档列表
    """
    content: str
    documents: list[KBDocument] = Field(default_factory=list)

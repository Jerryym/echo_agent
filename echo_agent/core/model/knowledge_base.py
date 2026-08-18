from pydantic import BaseModel, Field
from typing import Any


class KBDocument(BaseModel):
    """
    知识库文档

    参数:
        content: 文档内容
        score: 命中分数
        metadata: 文档元数据（默认包含：kb_id、document_id、chunk_id）
    """
    content: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class KBResult(BaseModel):
    """
    知识库查询结果

    参数:
        content: 知识库根据查询结果整理后的最终内容
        results: 支撑查询结果的来源文档列表
    """
    content: str = Field(default="", description="知识库根据查询结果整理后的最终内容")
    results: list[KBDocument] = Field(default_factory=list)


class KBQueryRequest(BaseModel):
    """
    知识库查询请求

    参数:
        kb_list: 知识库列表
        query: 查询语句
        top_k: 返回结果数量
    """
    kb_list: list[str] = Field(default_factory=list)
    query: str = Field(default="")
    top_k: int = Field(default=10)

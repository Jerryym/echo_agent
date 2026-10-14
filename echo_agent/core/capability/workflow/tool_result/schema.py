from pydantic import BaseModel, Field

from ....model.tool import ToolResultItem


class ToolResultAnalyseInput(BaseModel):
    """
    Tool Result 分析工作流输入

    参数：
        result_item: 工具执行结果项
        requirement: 分析需求描述
    """
    result_item: ToolResultItem = Field(
        description="Tool result to analyse."
    )
    requirement: str = Field(
        description="Information requirement for analysing the result."
    )

class ToolResultAnalyseResult(BaseModel):
    """
    Tool Result 分析工作流结果

    参数：
        content: 分析结果内容
        completed: 是否已完整遍历工具结果
    """
    content: str = Field(
        description="Consolidated information extracted from the tool result."
    )
    completed: bool = Field(
        description="Whether the result has been completely processed."
    )


class ToolResultChunkAnalysis(BaseModel):
    """
    Tool Result 内容块分析结果

    参数：
        content: 当前 Chunk 提取出的有效信息
    """
    content: str = Field(
        description=(
            "Information extracted from the chunk according to "
            "the analysis requirement."
        )
    )


class ToolResultAnalyseDecision(BaseModel):
    """
    工具结果分析完成性判断

    参数：
        content: 分析结果内容
        sufficient: 是否满足分析需求
    """
    content: str = Field(
        description=(
            "Consolidated information relevant to the analysis requirement."
        )
    )
    sufficient: bool = Field(
        description=(
            "Whether the accumulated information is sufficient "
            "to satisfy the analysis requirement."
        )
    )

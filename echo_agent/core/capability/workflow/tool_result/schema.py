from pydantic import BaseModel, Field

from ....model.tool import ToolResultItem


class ToolResultPlan(BaseModel):
    """
    ToolResult 本轮执行计划

    参数：
        analysis_requirement: 本轮分析需求
        max_chunks: 本轮最大处理块数
        next_action: 本轮执行后推荐的动作
    """
    analysis_requirement: str = Field(
        description="Specific information to extract from the tool result in this execution."
    )
    max_chunks: int = Field(
        ge=1,
        le=8,
        description="Maximum number of data chunks to process in this execution."
    )
    next_action: str = Field(
        description="Recommended next action for the agent after processing the current data."
    )


class ToolResultAnalyseInput(BaseModel):
    """
    Tool Result 分析工作流输入

    参数：
        result_item: 工具执行结果项
        requirement: 分析需求描述
        offset: 本次读取的起始逻辑字节偏移
        next_action: 本轮执行后推荐的动作
    """
    result_item: ToolResultItem = Field(
        description="Tool result to analyse."
    )
    requirement: str = Field(
        description="Information requirement for analysing the result."
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Logical UTF-8 byte offset from which reading starts."
    )
    next_action: str = Field(
        description="Recommended next action for the agent based on the analysis results."
    )

class ToolResultAnalyseResult(BaseModel):
    """
    Tool Result 分析工作流结果

    参数：
        content: 分析结果内容
        completed: 是否已完整遍历工具结果
        next_offset: 本次分析结束后的逻辑字节偏移
    """
    content: str = Field(
        description="Consolidated information extracted from the tool result."
    )
    completed: bool = Field(
        description="Whether the result has been completely processed."
    )
    next_offset: int = Field(
        ge=0,
        description="Logical UTF-8 byte offset for the next read."
    )
    next_action: str = Field(
        description=(
            "Planned next action for the agent after processing the current data."
        )
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
    

class ToolResultTaskState(BaseModel):
    """
    工具结果分析工作流任务状态

    参数：
        result_item: 工具执行结果项
        requirement: 分析需求描述
        offset: 本次读取的起始逻辑字节偏移
        accumulated_content: 已累计的分析结果内容
    """
    result_item: ToolResultItem
    requirement: str
    offset: int = Field(default=0, ge=0)
    accumulated_content: str = ""

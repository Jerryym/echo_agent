from pydantic import BaseModel, Field


class ToolArtifactAnalyseInput(BaseModel):
    """Tool Artifact 分析工作流输入"""
    tool_call_id: str = Field(
        description="Tool call ID associated with the artifact."
    )
    requirement: str = Field(
        description="Information requirement for analysing the artifact."
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Byte offset from which analysis should continue."
    )


class ToolArtifactAnalyseResult(BaseModel):
    """Tool Artifact 分析工作流结果"""
    content: str = Field(
        description="Information extracted from the processed artifact batch."
    )
    next_offset: int = Field(
        description="Byte offset for continuing artifact analysis."
    )
    completed: bool = Field(
        description="Whether the artifact has been completely processed."
    )


class ToolArtifactChunk(BaseModel):
    """Tool Artifact 内容块"""
    content: str = Field(
        description="Raw content read from the artifact."
    )
    offset: int = Field(
        description="Byte offset at which this chunk starts."
    )
    next_offset: int = Field(
        description="Byte offset immediately after this chunk."
    )
    eof: bool = Field(
        description="Whether this chunk reaches the end of the artifact."
    )


class ToolArtifactChunkAnalysis(BaseModel):
    """Tool Artifact 内容块分析结果"""
    content: str = Field(
        description=(
            "Information extracted from the chunk according to "
            "the analysis requirement."
        )
    )
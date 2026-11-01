from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from typing import Any, Literal, Self


class ToolCall(BaseModel):
    """
    工具调用

    Args:
        name: 工具名称
        args: 工具参数
        tool_call_id: 工具调用ID
        missing_args: 缺少的参数列表
    """
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str
    missing_args: list[str] = Field(default_factory=list)


class ToolResult(BaseModel):
    """
    工具执行结果

    Args:
        name: 工具名称
        success: 工具执行是否成功
        result: 工具执行结果
        error: 工具执行错误信息, 当success为False时有效
        tool_call_id: 工具调用ID, 同对应ToolCall的tool_call_id
    """
    name: str
    success: bool = False
    result: Any = None
    error: str | None = None
    tool_call_id: str
    

class ToolResultItem(BaseModel):
    """
    工具执行结果项

    Args:
        tool_call_id: 工具调用ID, 同对应ToolCall的tool_call_id
        name: 工具名称
        success: 工具执行是否成功
        error: 工具执行错误信息, 当success为False时有效
        storage: 工具执行结果存储方式, 可选值为"memory"或"file"
        result: 工具执行结果, 当storage为"memory"时有效
        path: 工具执行结果文件路径, 当storage为"file"时有效
    """
    tool_call_id: str
    name: str
    success: bool
    error: str | None = None

    storage: Literal["memory", "file"]
    result: Any = None
    path: Path | None = None

    @model_validator(mode="after")
    def validate_storage(self) -> Self:
        if self.storage == "memory":
            if self.path is not None:
                raise ValueError("Memory storage cannot have a path")
        else:
            if self.path is None:
                raise ValueError("File storage requires a path")
            if self.result is not None:
                raise ValueError("File storage cannot contain inline result")

        return self


class ToolResultChunk(BaseModel):
    """工具结果内容块"""
    content: str = Field(
        description="Content read from the tool result."
    )
    offset: int = Field(
        ge=0,
        description="Logical byte offset at which this chunk starts."
    )
    next_offset: int = Field(
        ge=0,
        description="Logical byte offset immediately after this chunk."
    )
    eof: bool = Field(
        description="Whether this chunk reaches the end of the result."
    )


class ToolState(BaseModel):
    """
    工具状态

    Args:
        tool_call: 工具调用
        tool_result: 工具执行结果
    """
    tool_call: ToolCall
    tool_result: ToolResultItem | None = None

from pydantic import BaseModel, Field

from ....model.tool import ToolResultItem


class ToolResultTaskState(BaseModel):
    """
    工具结果分析工作流任务状态

    参数：
        result_item: 工具执行结果项
        task_id: 任务ID
        offset: 本次读取的起始逻辑字节偏移
    """
    result_item: ToolResultItem
    task_id: str
    offset: int = Field(default=0, ge=0)


class ToolResultReadResult(BaseModel):
    """
    单次读取结果

    参数：
        content: 当前读取到的有效信息
        next_offset: 本次分析结束后的逻辑字节偏移
        eof: 是否已读取到文件末尾
    """
    content: str
    next_offset: int = Field(ge=0)
    eof: bool

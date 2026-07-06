from typing import Literal

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    """
    附件

    参数:
        type: 附件类型
        data: 附件数据(Base64编码 或 Url)
    """
    type: Literal["image", "audio", "file"]
    data: str


class UserInput(BaseModel):
    """
    用户输入

    参数:
        text: 用户输入文本
        attachments: 多模态附件
    """
    text: str = None
    attachments: list[Attachment] = Field(default_factory=list)
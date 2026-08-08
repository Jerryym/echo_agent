from typing import Literal

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    """
    附件

    参数:
        type: 附件类型(image, audio, file)
        format: 附件格式(base64 或 url)
        data: 附件数据
    """
    type: Literal["image", "audio", "file"]
    format: Literal["base64", "url"]
    data: str


class UserInput(BaseModel):
    """
    用户输入

    参数:
        text: 用户输入文本
        attachments: 多模态附件
    """
    text: str = Field(default="")
    attachments: list[Attachment] = Field(default_factory=list)

from typing import Literal

from langchain_core.messages import HumanMessage
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
    text: str = Field(default="")
    attachments: list[Attachment] = Field(default_factory=list)

    # TODO: 未来支持多模态附件
    def to_human_message(self) -> HumanMessage:
        return HumanMessage(content=self.text)
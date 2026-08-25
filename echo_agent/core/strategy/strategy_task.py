from typing import Any

from pydantic import BaseModel, Field

from ..model.input import Attachment


class StrategyTask(BaseModel):
    """
    策略任务：用于描述一次执行目标

    Args:
        name: 任务名称
        description: 任务描述
        goal: 任务目标
        attachments: 本轮用户附件
    """
    name: str = Field(default="", description="任务名称")
    description: str = Field(default="", description="任务描述")
    goal: str = Field(default="", description="任务目标")
    attachments: list[Attachment] = Field(default_factory=list, description="本轮用户附件")

    def dump_attachments(self) -> dict[str, Any]:
        payload = self.model_dump()
        payload["attachments"] = [
            {
                "type": att.type,
                "format": att.format,
                "data": att.data if att.format == "url" else f"<base64 omitted len={len(att.data)}>",
            }
            for att in self.attachments
        ]
        return payload

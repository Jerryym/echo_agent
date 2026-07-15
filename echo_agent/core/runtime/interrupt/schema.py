from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


class InterruptType(str, Enum):
    """
    中断类型
    """
    APPROVAL = "approval"
    INFORMATION_COLLECTION = "information_collection"


class InterruptRequest(BaseModel):
    """
    中断请求基类
    """
    type: InterruptType
    description: str


class InterruptResponse(BaseModel):
    """
    中断响应基类
    """
    pass


class ApprovalRequest(InterruptRequest):
    """
    审批请求
    """
    type: Literal[InterruptType.APPROVAL] = InterruptType.APPROVAL


class ApprovalResponse(InterruptResponse):
    """
    审批响应
    """
    approved: bool


class InterruptField(BaseModel):
    """
    信息补全字段
    """
    name: str
    description: str


class InformationCollectionRequest(InterruptRequest):
    """
    信息补全请求
    """
    type: Literal[InterruptType.INFORMATION_COLLECTION] = InterruptType.INFORMATION_COLLECTION
    fields: list[InterruptField]


class InformationCollectionResponse(InterruptResponse):
    """
    信息补全响应
    """
    values: dict[str, Any]

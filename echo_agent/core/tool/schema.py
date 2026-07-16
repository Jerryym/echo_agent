from enum import Enum
from typing import Any

from pydantic import BaseModel, Field   


class ToolType(str, Enum):
    """
    工具类型
    """
    FUNCTION = "function"
    HTTP = "http"
    MCP = "mcp"


class ToolDefinition(BaseModel):
    """
    工具定义

    Args:
        name: 工具名称
        description: 工具描述
        parameters: 参数
        type: 工具类型
        meta_data: 元数据
            required_approval: 是否需要审批
    """
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    type: ToolType = ToolType.FUNCTION
    meta_data: dict[str, Any] = Field(default_factory=dict)

    @property
    def required_parameters(self) -> list[str]:
        """
        获取必填参数名称
        """
        return self.parameters.get(
            "required",
            []
        )

    @property
    def parameter_schema(self) -> dict[str, Any]:
        """
        获取参数 schema
        """
        return self.parameters.get(
            "properties",
            {}
        )

    @property
    def requires_approval(self) -> bool:
        """
        获取是否需要人工审核
        """
        return bool(self.meta_data.get("required_approval", False))

    def get_parameter_description(self, param_name: str) -> str:
        """
        获取参数描述
        """
        parameter_schema = self.parameter_schema.get(param_name)
        if parameter_schema:
            return parameter_schema.get(
                "description",
                param_name
            )
        return param_name


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

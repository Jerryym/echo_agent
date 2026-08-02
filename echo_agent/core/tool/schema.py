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

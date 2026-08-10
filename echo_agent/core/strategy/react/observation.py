import json
from typing import Any

from pydantic import BaseModel

from ...model.tool import ToolResult


class Observation(BaseModel):
    """
    Observation 模型

    参数：
        source：来源
        content：内容
        metadata：元数据
    """
    source: str
    content: str
    metadata: dict[str, Any]


class ObservationBuilder:
    """
    ObservationBuilder 是用于构建 Observation 的类
    """
    @staticmethod
    def build(tool_result: ToolResult) -> Observation:
        if tool_result.success:
            content = json.dumps(
                tool_result.result,
                ensure_ascii=False,
                default=str
            )
        else:
            content = (
                f"Tool execution failed: "
                f"{tool_result.error or 'unknown error'}"
            )
        observation = Observation(
            source=tool_result.name,
            content=content,
            metadata={
                "tool_call_id": tool_result.tool_call_id,
                "success": tool_result.success,
            },
        )
        return observation


def append_observations(current_observations: list[Observation], new_observations: list[Observation]) -> list[Observation]:
    return current_observations + new_observations
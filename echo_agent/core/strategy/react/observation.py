from typing import Any, Literal

from pydantic import BaseModel

from ...model.tool import ToolResult
from ...tool.utils import format_tool_content


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
            content = format_tool_content(tool_result.result)
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

    @staticmethod
    def build_from_task_status(task_status: Literal["no_tool_calls", "invalid_tools", "failed", "cancelled"], details: str | list[str] | None = None) -> Observation:
        """
        根据任务状态构建 Observation
        """
        if task_status == "no_tool_calls":
            content = (
                "Action produced no tool calls. "
                "Re-evaluate whether execution is still required, "
                "or whether the objective can be marked completed."
            )
        elif task_status == "invalid_tools":
            if isinstance(details, list):
                detail_text  = ', '.join(details)
            else:
                detail_text = details or ""
            content = (
                "Action selected tools that are not in the available tool set"
                + (f": {detail_text}." if detail_text else ".")
                + " Re-plan the next capability without unavailable tools."
            )
        elif task_status == "failed":
            content = details or "Action failed to execute."
        elif task_status == "cancelled":
            content = "Task was cancelled." + (f": {details}." if details else ".")
        return Observation(
            source="system",
            content=content,
            metadata={
                "event": task_status,
                "success": False,
            },
        )


def append_observations(current_observations: list[Observation], new_observations: list[Observation]) -> list[Observation]:
    return current_observations + new_observations

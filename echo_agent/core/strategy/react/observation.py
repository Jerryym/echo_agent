from typing import Any, Literal

from pydantic import BaseModel

from ...model.tool import ToolResultItem


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
    ObservationBuilder: Observation构建器
    """
    @staticmethod
    def build(result_item: ToolResultItem) -> Observation:
        if not result_item.success:
            content = (
                f"Tool {result_item.name} failed: "
                f"{result_item.error or 'unknown error'}"
            )
        elif result_item.storage == "file":
            content = (
                f"Tool {result_item.name} succeeded. "
                "The complete result was stored externally. "
                f"Use tool_call_id '{result_item.tool_call_id}' "
                "to access or analyse it."
            )
        else:
            content = f"Tool {result_item.name} succeeded."

        return Observation(
            source=result_item.name,
            content=content,
            metadata={
                "tool_call_id": result_item.tool_call_id,
                "success": result_item.success,
            },
        )

    @staticmethod
    def build_from_task_status(task_status: Literal["no_tool_calls", "invalid_tools", "failed", "cancelled", "blocked"], details: str | list[str] | None = None) -> Observation:
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
        elif task_status == "blocked":
            content = "Task was blocked due to tool authorization failure." + (f": {details}." if details else ".")
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

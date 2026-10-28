from typing import Any

from langchain_core.tools import BaseTool, tool
from langgraph.config import get_config
from langgraph.pregel import Pregel
from langgraph.runtime import get_runtime

from ...capability.workflow.builder import WorkflowTaskBuilder
from ...capability.workflow.tool_result.schema import ToolResultReadResult, ToolResultTaskState
from ...capability.workflow.tool_result.workflow import build_read_payload, validate_read_budget
from ...model.session import SessionItem, SessionItemType
from ...model.tool import ToolResultItem


def create_read_tool_result_tool(workflow: Pregel) -> BaseTool:
    """创建增量读取工具结果的 Workflow 工具"""

    @tool
    async def read_tool_result(tool_call_id: str = "", task_id: str | None = None) -> dict[str, Any]:
        """
        Read a bounded portion of a previously executed tool result.

        For the first read, provide tool_call_id from the original tool execution.
        For subsequent reads, provide task_id returned by an earlier read.
        Returns the original content chunk, task_id, next_offset, and eof.
        """
        runtime = get_runtime()
        context = runtime.context
        if context is None:
            raise RuntimeError("Tool result runtime context is not available")

        if task_id is None:
            if not tool_call_id.strip():
                raise ValueError("tool_call_id is required for the first read")
            session_state = context.session_state
            result_item = _resolve_tool_result_item(tool_call_id, session_state.items)
            # 先分配 task_id，供 Workflow 的完整返回预算校验使用。
            task = WorkflowTaskBuilder.build(ToolResultTaskState(result_item=result_item, task_id="pending"))
            state = ToolResultTaskState(result_item=result_item, task_id=task.task_id)
            task.update(state)
            context.workflow_tasks[task.task_id] = task
            created = True
        else:
            task = context.workflow_tasks.get(task_id)
            if task is None:
                raise LookupError(f"Workflow task not found: {task_id}")
            if task.status != "active":
                raise RuntimeError(f"Workflow task is not active: {task_id} (status={task.status})")
            state = ToolResultTaskState.model_validate(task.state)
            created = False

        try:
            result = await workflow.ainvoke(state.model_copy(deep=True), config=get_config(), context=context)
            validated = ToolResultReadResult.model_validate(result)
            if validated.next_offset < state.offset:
                raise ValueError("Workflow next_offset cannot move backwards")
            if not validated.eof and validated.next_offset == state.offset:
                raise ValueError("Non-EOF read must advance offset")
            payload = build_read_payload(task.task_id, validated.content, validated.next_offset, validated.eof)
            validate_read_budget(payload)
        except Exception:
            if created:
                task.fail()
                context.workflow_tasks.pop(task.task_id, None)
            raise

        state.offset = validated.next_offset
        task.update(state)
        if validated.eof:
            task.finish()
        return payload

    read_tool_result.metadata = {
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    }
    return read_tool_result


def _resolve_tool_result_item(tool_call_id: str, session_items: list[SessionItem]) -> ToolResultItem:
    item_id = f"tool_result:{tool_call_id}"
    for item in session_items:
        if item.id == item_id and item.type == SessionItemType.TOOL_RESULT:
            return ToolResultItem.model_validate(item.content)
    raise LookupError(f"Tool result not found: {tool_call_id}")

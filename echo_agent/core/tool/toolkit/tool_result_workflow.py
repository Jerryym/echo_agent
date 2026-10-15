from typing import Any

from langchain_core.tools import BaseTool, tool
from langgraph.config import get_config
from langgraph.pregel import Pregel
from langgraph.runtime import get_runtime

from ...capability.workflow.builder import WorkflowTaskBuilder
from ...capability.workflow.tool_result.schema import (
    ToolResultAnalyseResult,
    ToolResultTaskState,
)
from ...model.conversation import ConversationContextItem, ConversationContextType
from ...model.tool import ToolResultItem


def create_trigger_tool_result_analyse_tool(workflow: Pregel) -> BaseTool:
    """创建 Tool Result 分析工作流触发工具"""

    @tool
    async def trigger_tool_result_analyse(tool_call_id: str, requirement: str, task_id: str | None = None) -> dict[str, Any]:
        """
        Analyse a previously executed tool result.

        Use this tool to extract information from a stored tool result.

        For a new analysis, provide tool_call_id and requirement.
        To continue an existing analysis, provide task_id.

        The workflow reads the stored result incrementally and
        maintains progress across invocations.

        Args:
            tool_call_id: Previous tool execution ID for a new task.
            requirement: Information to extract for a new task.
            task_id: Existing workflow task ID to continue.

        Returns:
            Workflow task ID, extracted content, reading progress,
            and task status.
        """
        runtime = get_runtime()
        context = runtime.context
        if context is None:
            raise RuntimeError("Tool result runtime context is not available")

        # 首次调用：创建工作流任务
        if task_id is None:
            if not tool_call_id or not requirement:
                raise ValueError("tool_call_id and requirement are required when creating a workflow task")

            # 解析工具结果
            result_item = _resolve_tool_result_item(tool_call_id, context.session_state.context_items)
            # 创建工作流任务
            state = ToolResultTaskState(
                result_item=result_item,
                requirement=requirement,
            )
            task = WorkflowTaskBuilder.build(state)
            # 注册工作流任务
            context.workflow_tasks[task.task_id] = task
        else:
            # 获取工作流任务
            task = context.workflow_tasks.get(task_id)
            if task is None:
                raise LookupError(f"Workflow task not found: {task_id}")
            if task.status != "active":
                raise RuntimeError(f"Workflow task is not active: {task_id} (status={task.status})")
            state = ToolResultTaskState.model_validate(task.state)

        # 执行 Tool Result Analyse Workflow
        result = await workflow.ainvoke(
            state.model_copy(deep=True),
            config=get_config(),
            context=context,
        )
        validated = ToolResultAnalyseResult.model_validate(result)

        # 更新工作流任务进度
        if validated.next_offset < state.offset:
            raise ValueError("Workflow next_offset cannot be smaller than the current task offset")
        state.offset = validated.next_offset
        if validated.content:
            if state.accumulated_content:
                state.accumulated_content += "\n" + validated.content
            else:
                state.accumulated_content = validated.content
        task.update(state)

        # 工具结果完整遍历后，结束任务
        if validated.completed:
            task.finish()

        return {
            "task_id": task.task_id,
            "content": validated.content,
            "accumulated_content": state.accumulated_content,
            "next_offset": state.offset,
            "completed": validated.completed,
            "next_action": validated.next_action,
            "status": task.status,
        }
    
    trigger_tool_result_analyse.metadata = {
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    }

    return trigger_tool_result_analyse


def _resolve_tool_result_item(tool_call_id: str, context_items: list[ConversationContextItem]) -> ToolResultItem:
    item_id = f"tool_result:{tool_call_id}"
    for item in context_items:
        if (item.id == item_id and item.type == ConversationContextType.TOOL_RESULT):
            return ToolResultItem.model_validate(item.content)
    raise LookupError(f"Tool result not found: {tool_call_id}")

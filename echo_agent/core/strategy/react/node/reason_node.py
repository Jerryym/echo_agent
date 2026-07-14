from typing import Literal

from pydantic import BaseModel, Field

from .....common import debug_print_messages
from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ..schema import ReActContext, ReActState


class ReasonResult(BaseModel):
    """
    Reason节点结构化输出

    参数:
        reasoning: 推理结果
        action_intent: 下一步行动意图
        information_status: 信息状态
            sufficient: 信息充足
            insufficient: 信息不足
        task_status: 任务状态
            in_progress: 任务进行中
            completed: 任务完成
    """
    reasoning: str = Field(
        description=(
            "A concise assessment of the current task state, "
            "including known information, missing information, "
            "and the reason for the next step."
        )
    )
    action_intent: str = Field(
        description=(
            "Describe the intended next action. "
            "This output will be consumed by the Action node. "
            "Do not select tools. "
            "Do not mention tool names. "
            "Describe only what capability or operation should be performed."
        )
    )
    information_status: Literal["sufficient", "insufficient"] = Field(
        description=(
            "Whether the currently available information is sufficient "
            "for the agent to decide and perform the next step."
        )
    )
    task_status: Literal["in_progress", "completed"] = Field(
        description=(
            "Whether the user's requested objective has been achieved.\n\n"
            "'completed': "
            "All requested work has been successfully completed.\n\n"
            "'in_progress': "
            "Further execution steps are still required."
        )
    )


class ReasonNode(Node):
    """
    Reason Node：推理节点

    职责：
        1. 判断当前任务状态
        2. 判断信息是否满足下一步执行要求
        3. 生成下一步动作意图

    不负责：
        1. 工具选择
        2. 参数生成
        3. 工具执行
    """
    def __init__(self, name: str, llm_config: LLMConfig):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/reasoning.md")

    def run(self, state: ReActState, context: ReActContext | None = None) -> dict:
        """
        Run the node
        """
        print(f"[ReAct][reason] enter | step={state.step_count} retry={state.retry_count} ")
        debug_print_messages("[ReAct][reason]", state.messages)

        # 检查工具执行失败
        if self._has_tool_error(state):
            return self._handle_tool_error(
                state,
                context,
            )

        # 构建输入
        input = self._build_input(state)
        # 调用llm-结构化输出
        response = self._llm_client.invoke_structured(
            prompt=self._prompt,
            user_input=input,
            history=state.messages,
            schema=ReasonResult,
        )
        result = response.structured
        print(
            "[ReAct][reason] "
            f"information={result.information_status} "
            f"task={result.task_status} "
            f"intent={result.action_intent}"
        )

        return self._handle_result(result, state)

    def _build_input(self, state: ReActState) -> dict:
        """
        构建输入
        """
        return {
            "input": state.input,
            "messages": state.messages,
            "observations": state.observations + self._build_observations(state),
        }

    def _build_observations(self, state: ReActState) -> list[str]:
        """
        构建观察结果
        """
        return [
            tool_result.result
            for tool_result in state.tool_results
        ]

    def _has_tool_error(self, state: ReActState) -> bool:
        """
        判断是否存在工具执行失败错误
        """
        return any(not result.success for result in state.tool_results)

    def _handle_tool_error(self, state: ReActState, context: ReActContext | None) -> dict:
        """
        处理工具错误
        """
        failed_tools = [r.name for r in state.tool_results if not r.success]
        print(f"[ReAct][reason] tool error detected: {failed_tools}")

        retry_count = state.retry_count + 1
        result = {
            "retry_count": retry_count,
        }

        # 重试次数达到最大，则返回失败
        if context and retry_count >= context.retry_max_count: 
            result["task_status"] = "failed"
            result["reasoning"] = "Tool execution failed and retry limit reached."
            
        return result

    def _handle_result(self, response: ReasonResult, state: ReActState) -> dict:
        """
        处理Reason结果
        """
        reasoning = (
            f"{response.reasoning}\n\n"
            f"Next action intent: {response.action_intent}"
        )

        result = {
            "reasoning": reasoning,
        }

        # 只有in_progress状态由 Reason负责
        if state.task_status == "in_progress":
            result["task_status"] = response.task_status

        return result

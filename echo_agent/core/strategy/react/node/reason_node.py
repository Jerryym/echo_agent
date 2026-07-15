from typing import Literal

from pydantic import BaseModel, Field

from .....common import debug_print_messages, format_debug
from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ..schema import ReActContext, ReActState


class ReasonStructuredOutput(BaseModel):
    """
    Reason节点结构化输出

    参数:
        thought: 思考结果，面向调试和可观测性的思考过程
        reasoning: 推理结果，面向 Action 节点的推理结果，用于指导下一步能力选择，不包含工具信息
        task_status: 任务状态，用于驱动 ReAct 流程
    """
    thought: str = Field(
        description=(
            "A concise description of the reasoning process used to analyze "
            "the current task. This field is intended for tracing, debugging, "
            "and runtime visualization only. It is not used for tool selection "
            "or execution."
        )
    )
    reasoning: str = Field(
        description=(
            "A structured execution-oriented reasoning result describing what "
            "capability or operation should be performed next. This output will "
            "be consumed by the Action node for capability and tool selection. "
            "Do not mention tool names, implementation details, or specific "
            "tool parameters."
        )
    )
    task_status: Literal["in_progress", "completed"] = Field(
        description=(
            "The current lifecycle status of the task. "
            "'in_progress' indicates that additional execution steps are "
            "required. 'completed' indicates that the user's requested task "
            "has been fully completed and the workflow can proceed to the "
            "final response."
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
            schema=ReasonStructuredOutput,
        )
        result = response.structured
        print(
            "[ReAct][reason] "
            f"thought={result.thought} \n"
            f"reasoning={result.reasoning} \n"
            f"task_status={result.task_status}"
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

    def _build_observations(self, state: ReActState) -> list[dict]:
        """
        构建观察结果
        """
        observations = []
        for tool_result in state.tool_results:
            observation = {
                "name": tool_result.name,
                "success": tool_result.success,
                "tool_call_id": tool_result.tool_call_id,
            }
            if tool_result.success:
                observation["result"] = tool_result.result
            else:
                observation["error"] = tool_result.error or "unknown error"
            observations.append(observation)
        return observations

    def _has_tool_error(self, state: ReActState) -> bool:
        """
        判断是否存在工具执行失败错误
        """
        return any(not result.success for result in state.tool_results)

    def _handle_tool_error(self, state: ReActState, context: ReActContext | None) -> dict:
        """
        处理工具错误
        """
        failed_tools = [r.name for r in state.tool_results if r.error]
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

    def _handle_result(self, response: ReasonStructuredOutput, state: ReActState) -> dict:
        """
        处理Reason结果
        """
        result = {
            "reasoning": response.reasoning,
        }

        # 只有in_progress状态由 Reason负责
        if state.task_status == "in_progress":
            result["task_status"] = response.task_status

        return result

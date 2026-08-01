from typing import Literal

from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel, Field

from .....common import debug_print_messages
from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....model.message import Message
from ....model.tool import ToolState
from ....trace import TokenUsage
from ..observation import Observation, ObservationBuilder
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
            "Reason-owned lifecycle signal only. "
            "Allowed values: 'in_progress' | 'completed'. "
            "Do NOT output human_in_the_loop, no_tool_calls, cancelled, or failed "
            "(those are set by Action/runtime). "
            "'in_progress': the user objective is not yet achieved; further execution "
            "is required. Put the next required capability in 'reasoning'. "
            "'completed': the user objective has been achieved AND confirmed by "
            "existing observations (tool results). "
            "If there are no confirming observations, you MUST use 'in_progress' "
            "even when a conversational reply seems sufficient—Final, not Reason, "
            "produces the user-facing answer. "
            "Never mark 'completed' because Action produced no tool calls; "
            "that signal is handled by runtime status, not by this field."
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
        super().__init__(name, is_async=True)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/reasoning.md")

    def run(self, state: ReActState, runtime: Runtime[ReActContext]) -> Command:
        """
        Run the node
        """
        print(f"[ReAct][reason] enter | step={state.step_count} retry={state.retry_count} ")
        history = self._build_history(state, runtime.context)
        debug_print_messages("[ReAct][reason]", history)

        # 检查工具执行失败
        if self._has_tool_error(state):
            return self._handle_tool_error(state, runtime.context)

        # 构建输入
        input = self._build_input(state)
        # 调用llm-结构化输出
        response = self._llm_client.invoke_structured(
            prompt=self._prompt,
            user_input=input,
            history=history,
            schema=ReasonStructuredOutput,
        )
        self._accumulate_token_usage(runtime.context, response.token_usage)
        result = response.structured
        print(
            "[ReAct][reason] "
            f"thought={result.thought} \n"
            f"reasoning={result.reasoning} \n"
            f"task_status={result.task_status}"
        )

        return self._handle_result(result, state, runtime.context)

    async def arun(self, state: ReActState, runtime: Runtime[ReActContext]) -> Command:
        """
        异步运行
        """
        print(f"[ReAct][reason] enter | step={state.step_count} retry={state.retry_count} ")
        history = self._build_history(state, runtime.context)
        debug_print_messages("[ReAct][reason]", history)

        # 检查工具执行失败
        if self._has_tool_error(state):
            return self._handle_tool_error(state, runtime.context)

        # 构建输入
        input = self._build_input(state)
        # 调用llm-结构化输出
        response = await self._llm_client.ainvoke_structured(
            prompt=self._prompt,
            user_input=input,
            history=history,
            schema=ReasonStructuredOutput,
        )
        self._accumulate_token_usage(runtime.context, response.token_usage)
        result = response.structured
        print(
            "[ReAct][reason] "
            f"thought={result.thought} \n"
            f"reasoning={result.reasoning} \n"
            f"task_status={result.task_status}"
        )

        return self._handle_result(result, state, runtime.context)

    def _build_history(self, state: ReActState, context: ReActContext | None = None) -> list[Message]:
        """
        构建跨轮会话历史与本轮执行轨迹。
        """
        if context is None:
            raise ValueError("ReActContext is required for ReasonNode")
        return [
            *state.conversation,
            *state.trajectory,
        ]

    @staticmethod
    def _accumulate_token_usage(context: ReActContext | None, token_usage: TokenUsage) -> None:
        if context is None or context.trace is None:
            return
        context.trace.token_usage = context.trace.token_usage.add(token_usage)

    def _build_input(self, state: ReActState) -> dict:
        """
        构建输入
        """
        return {
            "task": state.task.model_dump(),
            "trajectory": state.trajectory,
            "observations": state.observations + self._build_observations(state),
        }

    def _build_observations(self, state: ReActState) -> list[Observation]:
        """
        构建观察结果
        """
        observations = []
        for tool_result in state.tool_state.tool_results:
            observation = ObservationBuilder.build(tool_result)
            observations.append(observation)
        return observations

    def _has_tool_error(self, state: ReActState) -> bool:
        """
        判断是否存在工具执行失败错误
        """
        return any(not result.success for result in state.tool_state.tool_results)

    def _handle_tool_error(self, state: ReActState, context: ReActContext | None) -> Command:
        """
        处理工具错误
        """
        failed_tools = [r.name for r in state.tool_state.tool_results if r.error]
        print(f"[ReAct][reason] tool error detected: {failed_tools}")

        retry_count = state.retry_count + 1
        result = {
            "retry_count": retry_count,
            "tool_state": ToolState(tool_calls=[], tool_results=[]), # 清空工具调用和执行结果
            "observations": self._build_observations(state), # 包含工具执行失败的结果
        }

        # 重试次数达到最大，则返回失败
        if context and retry_count >= context.retry_max_count: 
            result["task_status"] = "failed"
            result["reasoning"] = "Tool execution failed and retry limit reached."

        return self._router(state, context, result)

    def _handle_result(self, response: ReasonStructuredOutput, state: ReActState, context: ReActContext | None) -> Command:
        """
        处理Reason结果
        """
        result = {
            "reasoning": response.reasoning,
        }

        if state.task_status in ("in_progress", "no_tool_calls"):
            result["task_status"] = response.task_status

        return self._router(state, context, result)

    def _router(self, state: ReActState, context: ReActContext | None, update_state: dict) -> Command:
        next_node = self._select_node(state, context, update_state)
        print(f"[ReAct][route] reason -> {next_node}")
        return Command(update=update_state, goto=next_node)

    def _select_node(self, state: ReActState, context: ReActContext | None, update_state: dict) -> Literal["action", "final"]:
        task_status = update_state.get("task_status", state.task_status)
        step_count = update_state.get("step_count", state.step_count)
        retry_count = update_state.get("retry_count", state.retry_count)
        max_steps = getattr(context, "max_steps", 10)
        retry_max = getattr(context, "retry_max_count", 3)

        if task_status in ("completed", "cancelled", "failed"):
            return "final"
        if step_count >= max_steps:
            return "final"
        if retry_count >= retry_max:
            return "final"
        return "action"

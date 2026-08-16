from typing import Literal

from langgraph.runtime import Runtime
from langgraph.types import Command, RunnableConfig
from pydantic import BaseModel, Field

from .....common import get_logger, log_messages
from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....model.message import Message
from ....model.tool import ToolState
from ....runtime.runtime_config import RuntimeConfig
from .....utils import update_agent_result
from ..observation import Observation, ObservationBuilder
from ..schema import ReActContext, ReActState

logger = get_logger("react.reason")


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
            "Do NOT output human_in_the_loop, no_tool_calls, invalid_tools, cancelled, or failed "
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

    节点职责：
        1. 分析当前 ReAct Loop 的执行结果与观察信息
        2. 判断当前任务状态及是否满足下一步执行要求
        3. 基于当前任务上下文和 Observation 生成下一步动作意图
        4. 管理 ReAct Loop 的 step_count，并判断是否达到最大执行步数
        5. 根据任务状态、执行步数和重试次数决定下一节点
        6. 将当前 ReAct Loop 的 Observation 累积到 ReActState
    """
    def __init__(self, name: str, llm_config: LLMConfig):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/reasoning.md")

    def run(self, state: ReActState, runtime: Runtime[ReActContext], config: RunnableConfig | None = None) -> Command:
        """
        Run the node
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)

        # 构建Observation
        observation_list = self._build_observations(state)
        # 构建历史记录
        history = self._build_history(state, runtime.context)
        log_messages(logger, "reason", history)

        # 如果任务状态为取消、失败或阻塞，则直接返回
        if state.task_status in ("cancelled", "failed", "blocked"):
            return self._router(state, runtime.context, {
                "task_status": state.task_status,
                "observations": observation_list,
            })
        # 检查工具执行失败
        if self._has_tool_error(state):
            return self._handle_tool_error(state, runtime.context, observation_list)

        # 构建输入
        input = self._build_input(state, observation_list)
        # 调用llm-结构化输出
        response = self._llm_client.invoke_structured(
            prompt=self._prompt,
            user_input=input,
            history=history,
            schema=ReasonStructuredOutput,
            context=runtime.context,
            agent_resources=runtime.context.resources,
            config=self._build_runnable_config(config),
        )
        result = response.structured
        
        # 更新AgentResult
        update_agent_result(runtime.context, result.reasoning, response.token_usage)
        logger.info("thought=%s reasoning=%s task_status=%s", result.thought, result.reasoning, result.task_status)

        # 处理Reason结果
        return self._handle_result(result, state, runtime.context, observation_list)

    async def arun(self, state: ReActState, runtime: Runtime[ReActContext], config: RunnableConfig | None = None) -> Command:
        """
        异步运行
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)

        # 构建Observation
        observation_list = self._build_observations(state)
        # 构建历史记录
        history = self._build_history(state, runtime.context)
        log_messages(logger, "reason", history)

        # 如果任务状态为取消或失败，则直接返回
        if state.task_status in ("cancelled", "failed"):
            return self._router(state, runtime.context, {
                "task_status": state.task_status,
                "observations": observation_list,
            })
        # 检查工具执行失败
        if self._has_tool_error(state):
            return self._handle_tool_error(state, runtime.context, observation_list)

        # 构建输入
        input = self._build_input(state, observation_list)
        # 调用llm-结构化输出
        response = await self._llm_client.ainvoke_structured(
            prompt=self._prompt,
            user_input=input,
            history=history,
            schema=ReasonStructuredOutput,
            context=runtime.context,
            agent_resources=runtime.context.resources,
            config=self._build_runnable_config(config),
        )
        result = response.structured

        # 更新AgentResult
        update_agent_result(runtime.context, result.reasoning, response.token_usage)
        logger.info("thought=%s reasoning=%s task_status=%s", result.thought, result.reasoning, result.task_status)

        # 处理Reason结果
        return self._handle_result(result, state, runtime.context, observation_list)

    def _build_runnable_config(self, config: RunnableConfig | None) -> RunnableConfig:
        conf = (config or {}).get("configurable") or {}
        thread_id = str(conf.get("thread_id") or "")
        return RuntimeConfig(
            thread_id=thread_id,
            session_id=str(conf.get("session_id") or thread_id),
            metadata=dict(conf.get("metadata") or {}),
        ).to_llm_runnable_config()

    def _build_observations(self, state: ReActState) -> list[Observation]:
        """
        构建Observation
        """
        observations = []

        if state.task_status == "in_progress":
            for tool_result in state.tool_state.tool_results:
                observation = ObservationBuilder.build(tool_result)
                observations.append(observation)
        elif state.task_status == "invalid_tools": # 非法工具
            invalid_tools = [tool.name for tool in state.tool_state.tool_calls]
            observation = ObservationBuilder.build_from_task_status(state.task_status, invalid_tools)
            observations.append(observation)
        elif state.task_status == "no_tool_calls": # 没有工具调用
            observation = ObservationBuilder.build_from_task_status(state.task_status)
            observations.append(observation)
        elif state.task_status == "failed": # 失败
            observation = ObservationBuilder.build_from_task_status(state.task_status)
            observations.append(observation)
        elif state.task_status == "cancelled": # 取消
            observation = ObservationBuilder.build_from_task_status(state.task_status)
            observations.append(observation)
        elif state.task_status == "blocked": # 阻塞
            observation = ObservationBuilder.build_from_task_status(state.task_status)
            observations.append(observation)

        return observations

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

    def _build_input(self, state: ReActState, observation_list: list[Observation]) -> dict:
        """
        构建输入
        """
        return {
            "task": state.task.model_dump(),
            "observations": state.observations + observation_list, # 本次ReAct Loop完整的观察结果
        }

    def _has_tool_error(self, state: ReActState) -> bool:
        """
        判断是否存在工具执行失败错误
        """
        return any(not result.success for result in state.tool_state.tool_results)

    def _handle_tool_error(self, state: ReActState, context: ReActContext | None, observation_list: list[Observation]) -> Command:
        """
        处理工具错误
        """
        failed_tools = [r.name for r in state.tool_state.tool_results if r.error]
        logger.warning("tool error detected: %s", failed_tools)

        result = {
            "step_count": state.step_count + 1,
            "tool_state": ToolState(tool_calls=[], tool_results=[]), # 清空工具调用和执行结果
            "observations": observation_list, # 包含工具执行失败的结果
        }
        return self._router(state, context, result)

    def _handle_result(self, response: ReasonStructuredOutput, state: ReActState, context: ReActContext | None, observation_list: list[Observation]) -> Command:
        """
        处理Reason结果
        """
        result = {
            "task_status": response.task_status,
            "reasoning": response.reasoning,
            "observations": observation_list, # 更新observations
        }

        # 非法工具时，清空工具状态
        if state.task_status == "invalid_tools":
            result["tool_state"] = ToolState(tool_calls=[], tool_results=[])

        # 只有确定进入下一次 Action 执行时，才消耗 step
        if response.task_status == "in_progress":
            result["step_count"] = state.step_count + 1

        return self._router(state, context, result)

    def _router(self, state: ReActState, context: ReActContext | None, update_state: dict) -> Command:
        next_node = self._select_node(state, context, update_state)
        logger.info("route reason -> %s", next_node)
        return Command(update=update_state, goto=next_node)

    def _select_node(self, state: ReActState, context: ReActContext | None, update_state: dict) -> Literal["action", "final"]:
        task_status = update_state.get("task_status", state.task_status)
        step_count = update_state.get("step_count", state.step_count)
        retry_count = update_state.get("retry_count", state.retry_count)
        max_steps = getattr(context, "max_steps", 10)
        retry_max = getattr(context, "retry_max_count", 3)

        if task_status in ("completed", "cancelled", "failed", "blocked"):
            return "final"
        if step_count >= max_steps:
            return "final"
        if retry_count >= retry_max:
            return "final"
        return "action"

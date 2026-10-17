from typing import Any, Literal

from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import ValidationError

from .....common import get_logger
from .....prompt import PromptAssembler, PromptLoader
from .....utils import update_agent_result
from ....app import Application
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....model.agent import AgentMode
from ....model.message import Message
from ....model.tool import ToolState
from ....runtime.runtime_config import RuntimeConfig
from ..observation import Observation, ObservationBuilder
from ..schema import (
    ReActContext,
    ReActState,
    ReasonStructuredOutput,
    build_react_history,
)

logger = get_logger("react.reason")


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

    def run(self, state: ReActState, runtime: Runtime[ReActContext]) -> Command:
        """
        Run the node
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)

        # 构建Observation
        observation_list = self._build_observations(state, runtime.context)

        # 如果任务状态为取消、失败或阻塞，则直接返回
        if state.task_status in ("cancelled", "failed", "blocked"):
            return self._router(state, runtime.context, {
                "task_status": state.task_status,
                "observations": observation_list,
                "tool_list": [],
            })
        try:
            result = self._invoke(state, runtime, observation_list)
        except (ValidationError, ValueError) as exc:
            logger.warning("reason failed: %s", exc)
            return self._router(state, runtime.context, {
                "task_status": "failed",
                "observations": observation_list,
                "tool_list": [],
            })
        logger.info("result=%r", result)
        return self._handle_result(result, state, runtime.context, observation_list)

    async def arun(self, state: ReActState, runtime: Runtime[ReActContext]) -> Command:
        """
        异步运行
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)

        # 构建Observation
        observation_list = self._build_observations(state, runtime.context)

        # 如果任务状态为取消、失败或阻塞，则直接返回
        if state.task_status in ("cancelled", "failed", "blocked"):
            return self._router(state, runtime.context, {
                "task_status": state.task_status,
                "observations": observation_list,
                "tool_list": [],
            })
        try:
            result = await self._ainvoke(state, runtime, observation_list)
        except (ValidationError, ValueError) as exc:
            logger.warning("reason failed: %s", exc)
            return self._router(state, runtime.context, {
                "task_status": "failed",
                "observations": observation_list,
                "tool_list": [],
            })
        logger.info("result=%r", result)
        return self._handle_result(result, state, runtime.context, observation_list)

    def _invoke(self, state: ReActState, runtime: Runtime[ReActContext], observation_list: list[Observation]) -> ReasonStructuredOutput:
        """生成并校验结构化推理结果"""
        kwargs = self._prepare_invoke(state, runtime, observation_list)
        runtime_config = RuntimeConfig.get_runtime_config()
        session = Application.get_application().get_agent(runtime_config.agent_id).get_sesion(runtime_config.session_id)
        return self._invoke_reason_result(kwargs, runtime, session.before_model)

    async def _ainvoke(self, state: ReActState, runtime: Runtime[ReActContext], observation_list: list[Observation]) -> ReasonStructuredOutput:
        """异步生成并校验结构化推理结果"""
        kwargs = self._prepare_invoke(state, runtime, observation_list)
        runtime_config = RuntimeConfig.get_runtime_config()
        session = Application.get_application().get_agent(runtime_config.agent_id).get_sesion(runtime_config.session_id)
        return await self._ainvoke_reason_result(kwargs, runtime, session.abefore_model)

    def _invoke_reason_result(
        self,
        kwargs: dict[str, Any],
        runtime: Runtime[ReActContext],
        before_model: Any,
    ) -> ReasonStructuredOutput:
        """生成并校验一轮结构化推理结果"""
        response = self._llm_client.invoke_structured(
            schema=ReasonStructuredOutput,
            **kwargs,
            before_model=before_model,
        )
        try:
            result = ReasonStructuredOutput.model_validate(response.structured)
        except ValidationError as exc:
            raise ValueError("Invalid structured reason result.") from exc
        self._validate_reason_result(result)
        # 结构化输出的text可能为空，使用assessment记录本轮任务推进判断
        update_agent_result(runtime.context, result.assessment, response.token_usage)
        return result

    async def _ainvoke_reason_result(self, kwargs: dict[str, Any], runtime: Runtime[ReActContext], abefore_model: Any) -> ReasonStructuredOutput:
        """异步生成并校验一轮结构化推理结果"""
        response = await self._llm_client.ainvoke_structured(
            schema=ReasonStructuredOutput,
            **kwargs,
            abefore_model=abefore_model,
        )
        try:
            result = ReasonStructuredOutput.model_validate(response.structured)
        except ValidationError as exc:
            raise ValueError("Invalid structured reason result.") from exc
        self._validate_reason_result(result)
        # 结构化输出的text可能为空，使用assessment记录本轮任务推进判断
        update_agent_result(runtime.context, result.assessment, response.token_usage)
        return result

    def _validate_reason_result(self, result: ReasonStructuredOutput) -> None:
        """校验结构化结果与ReasonNode状态是否一致"""
        if not result.assessment.strip():
            raise ValueError("Reason result assessment must not be empty.")
        if result.task_status == "in_progress" and not result.next_action.strip():
            raise ValueError("In-progress reason result requires next_action.")
        if result.task_status == "completed" and result.next_action.strip():
            raise ValueError("Completed reason result requires empty next_action.")
        if result.task_status == "completed" and result.tool_list:
            raise ValueError("task_status='completed' requires an empty tool_list.")
        if result.task_status == "in_progress" and not result.tool_list:
            raise ValueError("task_status='in_progress' requires at least one tool.")

    def _build_observations(self, state: ReActState, context: ReActContext) -> list[Observation]:
        """构建Observation"""
        observations = []

        if state.task_status == "in_progress":
            for result_item in state.tool_state.tool_results:
                observation = ObservationBuilder.build(result_item)
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

    def _prepare_invoke(self, state: ReActState, runtime: Runtime[ReActContext], observation_list: list[Observation]) -> dict[str, Any]:
        # 获取运行时信息
        runtime_config = RuntimeConfig.get_runtime_config()
        # 获取tool registry
        tool_registry = Application.get_application().get_agent(runtime_config.agent_id).tool_registry
        # 获取工具信息
        tool_informations = tool_registry.get_tool_infomations()

        return {
            "prompt": self._build_prompt(runtime.context, tool_informations, runtime_config.agent_mode),
            "user_input": self._build_input(state, observation_list), # 用户输入
            "history": self._build_history(state, runtime.context), # 历史记录
            "conversation": state.conversation,
            "config": runtime_config.to_llm_runnable_config(),
        }

    def _build_prompt(self, context: ReActContext, tool_informations: list[dict[str, str]], agent_mode: AgentMode) -> str:
        """构建系统提示词"""
        resources = context.resources
        return PromptAssembler.assemble(
            agent_prompt=resources.system_prompt if resources else None,
            system_prompt=self._prompt,
            agent_mode=agent_mode,
            tool_informations=tool_informations,
            skill_frontmatter_list=resources.skill_frontmatter_list if resources else None,
            active_skills=context.active_skills,
            is_task_exec=True,
        )

    def _build_history(self, state: ReActState, context: ReActContext | None = None) -> list[Message]:
        """构建跨轮会话历史与本轮执行轨迹"""
        if context is None:
            raise ValueError("ReActContext is required for ReasonNode")
        return build_react_history(state.conversation, state.trajectory)

    def _build_input(self, state: ReActState, observation_list: list[Observation]) -> dict:
        """构建输入"""
        return {
            "task": state.task.dump_attachments(),
            "observations": observation_list, # 本次ReAct Loop完整的观察结果
        }

    def _handle_result(self, response: ReasonStructuredOutput, state: ReActState, context: ReActContext | None, observation_list: list[Observation]) -> Command:
        """处理Reason结果"""
        result = {
            "task_status": response.task_status,
            "assessment": response.assessment,
            "next_action": response.next_action,
            "observations": observation_list, # 更新observations
            "tool_list": response.tool_list,
        }

        # 清空Tool State
        if state.task_status == "invalid_tools" or response.task_status == "in_progress":
            result["tool_state"] = ToolState(tool_calls=[], tool_results=[])

        return self._router(state, context, result)

    def _router(self, state: ReActState, context: ReActContext | None, update_state: dict) -> Command:
        next_node = self._select_node(state, context, update_state)
        update_state["conversation"] = state.conversation
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

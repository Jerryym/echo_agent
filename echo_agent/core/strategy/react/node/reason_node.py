from typing import Any, Literal

from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import ValidationError

from .....common import get_logger
from .....prompt import PromptAssembler, PromptLoader
from .....utils import (
    sha256_hex,
    update_agent_reasoning,
    update_agent_result,
    update_token_usage,
)
from ....app import Application
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....model.agent import AgentMode
from ....model.message import Message
from ....model.step import Step
from ....model.tool import ToolState
from ....runtime.context import ContextCompactor
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
        4. 根据任务状态、重复指纹次数和重试次数决定下一节点
        5. 将当前 ReAct Loop 的 Observation 累积到 ReActState
    """
    def __init__(self, name: str, llm_config: LLMConfig):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/reasoning.md")
        self._context_compactor = ContextCompactor(llm_config) # 上下文压缩器

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

        # 判断是否需要压缩上下文
        if self._context_compactor.should_compact(state.context):
            compacted_context, token_usage = self._context_compactor.compress(state.context)
            logger.info("context compacted | tokens=%s", token_usage.total_tokens)
            state.context = compacted_context
            update_agent_result(runtime.context, '上下文已压缩', token_usage) 

        self._apply_tool_fingerprint_outcome(state, runtime.context)
        if self._duplicate_fingerprint_limit_reached(state, runtime.context):
            return self._built_fail_resaon(state, runtime.context, observation_list)
            
        try:
            result = self._invoke(state, runtime, observation_list)
        except (ValidationError, ValueError) as exc:
            logger.warning("reason failed: %s", exc)
            return self._router(state, runtime.context, {
                "task_status": "failed",
                "observations": observation_list,
                "tool_list": [],
            })
        if result is None:
            return self._router(state, runtime.context, {
                "task_status": "failed",
                "observations": observation_list,
                "tool_list": [],
            })
        if self._duplicate_fingerprint_limit_reached(state, runtime.context):
            return self._built_fail_resaon(state, runtime.context, observation_list)
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

        # 判断是否需要压缩上下文
        if self._context_compactor.should_compact(state.context):
            compacted_context, token_usage = await self._context_compactor.acompress(state.context)
            logger.info("context compacted | tokens=%s", token_usage.total_tokens)
            state.context = compacted_context
            update_agent_result(runtime.context, '上下文已压缩', token_usage) 

        self._apply_tool_fingerprint_outcome(state, runtime.context)
        if self._duplicate_fingerprint_limit_reached(state, runtime.context):
            return self._built_fail_resaon(state, runtime.context, observation_list)

        try:
            result = await self._ainvoke(state, runtime, observation_list)
        except (ValidationError, ValueError) as exc:
            logger.warning("reason failed: %s", exc)
            return self._router(state, runtime.context, {
                "task_status": "failed",
                "observations": observation_list,
                "tool_list": [],
            })
        if result is None:
            return self._router(state, runtime.context, {
                "task_status": "failed",
                "observations": observation_list,
                "tool_list": [],
            })
        if self._duplicate_fingerprint_limit_reached(state, runtime.context):
            return self._built_fail_resaon(state, runtime.context, observation_list)
        logger.info("result=%r", result)
        return self._handle_result(result, state, runtime.context, observation_list)

    def _invoke(self, state: ReActState, runtime: Runtime[ReActContext], observation_list: list[Observation]) -> ReasonStructuredOutput | None:
        """生成并校验结构化推理结果，Reason 指纹重复时重新推理"""
        kwargs = self._prepare_invoke(state, runtime, observation_list)
        while True:
            result = self._invoke_reason_result(state, kwargs, runtime)
            if result is None:
                return None
            duplicate = self._append_reason_duplicate_observation(state, runtime.context, observation_list)
            self._record_fingerprint_outcome(state, runtime.context, duplicate)
            if not duplicate or self._duplicate_fingerprint_limit_reached(state, runtime.context):
                return result
            kwargs["user_input"] = self._build_input(state, observation_list)

    async def _ainvoke(self, state: ReActState, runtime: Runtime[ReActContext], observation_list: list[Observation]) -> ReasonStructuredOutput | None:
        """异步生成并校验结构化推理结果，Reason 指纹重复时重新推理"""
        kwargs = self._prepare_invoke(state, runtime, observation_list)
        while True:
            result = await self._ainvoke_reason_result(state, kwargs, runtime)
            if result is None:
                return None
            duplicate = self._append_reason_duplicate_observation(state, runtime.context, observation_list)
            self._record_fingerprint_outcome(state, runtime.context, duplicate)
            if not duplicate or self._duplicate_fingerprint_limit_reached(state, runtime.context):
                return result
            kwargs["user_input"] = self._build_input(state, observation_list)

    def _invoke_reason_result(self, state: ReActState, kwargs: dict[str, Any], runtime: Runtime[ReActContext]) -> ReasonStructuredOutput | None:
        """生成并校验一轮结构化推理结果"""
        step = Step()
        state.steps = [*state.steps, step]
        state.current_step = step
        try:
            response = self._llm_client.invoke_structured(
                schema=ReasonStructuredOutput,
                **kwargs,
            )
            step.token_usage = response.token_usage.model_copy(deep=True)
            update_token_usage(runtime.context, response.token_usage)
        except Exception as exc:
            step.error = str(exc)
            logger.warning("reason step failed: %s", exc)
            return None
        finally:
            state.current_step = None
        try:
            result = ReasonStructuredOutput.model_validate(response.structured)
        except ValidationError:
            step.error = "Invalid structured reason result."
            logger.warning("reason step failed: %s", step.error)
            return None
        try:
            self._validate_reason_result(result)
        except ValueError as exc:
            step.error = str(exc)
            logger.warning("reason step failed: %s", exc)
            return None
        # 运行步保存完整结构化输出
        self._record_reason_output(step, result)
        update_agent_reasoning(runtime.context, result.assessment)
        return result

    async def _ainvoke_reason_result(self, state: ReActState, kwargs: dict[str, Any], runtime: Runtime[ReActContext]) -> ReasonStructuredOutput | None:
        """异步生成并校验一轮结构化推理结果"""
        step = Step()
        state.steps = [*state.steps, step]
        state.current_step = step
        try:
            response = await self._llm_client.ainvoke_structured(
                schema=ReasonStructuredOutput,
                **kwargs,
            )
            step.token_usage = response.token_usage.model_copy(deep=True)
            update_token_usage(runtime.context, response.token_usage)
        except Exception as exc:
            step.error = str(exc)
            logger.warning("reason step failed: %s", exc)
            return None
        finally:
            state.current_step = None
        try:
            result = ReasonStructuredOutput.model_validate(response.structured)
        except ValidationError:
            step.error = "Invalid structured reason result."
            logger.warning("reason step failed: %s", step.error)
            return None
        try:
            self._validate_reason_result(result)
        except ValueError as exc:
            step.error = str(exc)
            logger.warning("reason step failed: %s", exc)
            return None
        # 运行步保存完整结构化输出
        self._record_reason_output(step, result)
        update_agent_reasoning(runtime.context, result.assessment)
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
            for tool_state in state.tool_states.values():
                if tool_state.tool_result is None:
                    continue
                observation = ObservationBuilder.build(tool_state.tool_result)
                observations.append(observation)
        elif state.task_status == "invalid_tools": # 非法工具
            invalid_tools = [tool_state.tool_call.name for tool_state in state.tool_states.values()]
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

        # 追加工具重复结果
        self._append_tool_duplicate_observations(state, context, observations)
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
        return build_react_history(state.context)

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
            result["tool_states"] = {}

        return self._router(state, context, result)

    def _router(self, state: ReActState, context: ReActContext | None, update_state: dict) -> Command:
        # 重置重试次数
        if "retry_count" not in update_state and self._reset_retry_count(state):
            update_state["retry_count"] = 0
        next_node = self._select_node(state, context, update_state)

        update_state["steps"] = state.steps
        update_state["current_step"] = state.current_step
        update_state["context"] = state.context
        update_state["duplicate_fingerprint_count"] = state.duplicate_fingerprint_count
        update_state["duplicate_fingerprint_clear_count"] = state.duplicate_fingerprint_clear_count
        return Command(update=update_state, goto=next_node)

    def _select_node(self, state: ReActState, context: ReActContext | None, update_state: dict) -> Literal["action", "final"]:
        task_status = update_state.get("task_status", state.task_status)
        retry_count = update_state.get("retry_count", state.retry_count)
        retry_max = getattr(context, "retry_max_count", 3)

        if task_status in ("completed", "cancelled", "failed", "blocked"):
            return "final"
        if retry_count >= retry_max:
            return "final"
        return "action"

    def _apply_tool_fingerprint_outcome(self, state: ReActState, context: ReActContext) -> None:
        """当前 Tool Step 构成一个有效指纹评估单元时更新计数"""
        if state.task_status != "in_progress":
            return
        current = next((step for step in reversed(state.steps) if step.content_type == "tool"), None)
        if current is None or not self._has_valid_fingerprint(current):
            return
        window = self._get_recent_fingerprints(state.steps, context.fingerprint_window_size)
        duplicate = bool(self._duplicate_tool_calls(current, window))
        self._record_fingerprint_outcome(state, context, duplicate)

    def _record_fingerprint_outcome(self, state: ReActState, context: ReActContext, duplicate: bool) -> None:
        if duplicate:
            state.duplicate_fingerprint_count += 1
            state.duplicate_fingerprint_clear_count = 0
            return
        state.duplicate_fingerprint_clear_count += 1

        # 如果连续清空次数达到阈值，则重置指纹计数
        if state.duplicate_fingerprint_clear_count >= context.duplicate_fingerprint_reset_threshold:
            state.duplicate_fingerprint_count = 0
            state.duplicate_fingerprint_clear_count = 0

    def _duplicate_fingerprint_limit_reached(self, state: ReActState, context: ReActContext) -> bool:
        """判断重复指纹是否达到上限"""
        return state.duplicate_fingerprint_count >= context.duplicate_fingerprint_max_count

    def _built_fail_resaon(self, state: ReActState, context: ReActContext | None, observation_list: list[Observation]) -> Command:
        """重复指纹达到上限时构建失败原因"""
        reason = "Stopped because repeated decisions or tool results reached the duplicate fingerprint limit."
        if state.steps:
            state.steps[-1].error = reason
        return self._router(state, context, {
            "task_status": "failed",
            "assessment": reason,
            "observations": observation_list,
            "tool_list": [],
        })

    def _reset_retry_count(self, state: ReActState) -> bool:
        """重置重试次数"""
        if state.task_status != "in_progress" or state.retry_count == 0:
            return False
        return any(
            tool_state.tool_result is not None
            for tool_state in state.tool_states.values()
        )

    def _record_reason_output(self, step: Step, result: ReasonStructuredOutput) -> None:
        step.content_type = "json"
        step.content = result.model_dump(mode="json")
        # 计算指纹
        step.fingerprint = sha256_hex({
            "next_action": result.next_action,
            "tool_list": result.tool_list,
            "task_status": result.task_status,
        })

    def _get_recent_fingerprints(self, steps: list[Step], window_size: int) -> list[Step]:
        """获取最近的指纹列表"""
        if window_size <= 0:
            return []
        selected = [step for step in steps if self._has_valid_fingerprint(step)]
        return selected[-window_size:]

    def _has_valid_fingerprint(self, step: Step) -> bool:
        """判断运行步是否包含有效的指纹"""
        fingerprint = step.fingerprint
        if isinstance(fingerprint, str):
            return bool(fingerprint)
        if isinstance(fingerprint, dict):
            return any(isinstance(value, str) and value for value in fingerprint.values())
        return False

    def _append_tool_duplicate_observations(self, state: ReActState, context: ReActContext, observations: list[Observation]) -> None:
        """将当前 Tool Step 的重复结果写入本轮 Observation。"""
        current = next((step for step in reversed(state.steps) if step.content_type == "tool"), None)
        if current is None:
            return
        window = self._get_recent_fingerprints(state.steps, context.fingerprint_window_size)
        for tool_name, tool_call_id in self._duplicate_tool_calls(current, window):
            observations.append(Observation(
                source=tool_name,
                content=(
                    f"Tool {tool_name} returned the same result as its previous execution. "
                    "The current operation produced no new result. "
                    "Re-evaluate task progress and avoid repeating the same operation."
                ),
                metadata={"event": "duplicate_tool_result", "tool_call_id": tool_call_id},
            ))

    def _append_reason_duplicate_observation(self, state: ReActState, context: ReActContext, observations: list[Observation]) -> bool:
        """Reason 指纹重复时追加 Observation"""
        if not state.steps:
            return False
        current = state.steps[-1]
        window = self._get_recent_fingerprints(state.steps, context.fingerprint_window_size)
        if not self._is_duplicate_reason(current, window):
            return False
        observations.append(Observation(
            source="system",
            content=(
                "This Reason decision repeats a recent decision. "
                "Re-evaluate the current task state and existing results, "
                "and avoid repeating the same operation."
            ),
            metadata={"event": "duplicate_reason", "step_id": current.id},
        ))
        return True

    def _is_duplicate_reason(self, current: Step, window: list[Step]) -> bool:
        """判断当前Reason指纹是否与窗口内最近一次Reason指纹相同"""
        fingerprint = current.fingerprint
        if not isinstance(fingerprint, str) or not fingerprint:
            return False
        previous: str | None = None
        for step in window:
            if step.id == current.id:
                break
            if isinstance(step.fingerprint, str) and step.fingerprint:
                previous = step.fingerprint
        return previous == fingerprint

    def _duplicate_tool_calls(self, current: Step, window: list[Step]) -> list[tuple[str, str]]:
        """返回当前 Tool Step 中与同名工具最近结果重复的 (tool_name, tool_call_id)"""
        records = self._expand_tool_fingerprints(window)
        duplicates: list[tuple[str, str]] = []
        for index, (step_id, tool_call_id, tool_name, fingerprint) in enumerate(records):
            if step_id != current.id:
                continue
            previous: str | None = None
            for _earlier_step_id, _earlier_call_id, earlier_name, earlier_fingerprint in reversed(records[:index]):
                if earlier_name == tool_name:
                    previous = earlier_fingerprint
                    break
            if previous == fingerprint:
                duplicates.append((tool_name, tool_call_id))
        return duplicates

    def _expand_tool_fingerprints(self, window: list[Step]) -> list[tuple[str, str, str, str]]:
        """按执行顺序展开为 (step_id, tool_call_id, tool_name, fingerprint)"""
        records: list[tuple[str, str, str, str]] = []
        for step in window:
            fingerprint = step.fingerprint
            if step.content_type != "tool" or not isinstance(fingerprint, dict):
                continue
            content = step.content
            if not isinstance(content, dict):
                continue
            for tool_call_id, digest in fingerprint.items():
                if not isinstance(digest, str) or not digest:
                    continue
                tool_state = content.get(tool_call_id)
                if not isinstance(tool_state, ToolState):
                    continue
                records.append((step.id, tool_call_id, tool_state.tool_call.name, digest))
        return records

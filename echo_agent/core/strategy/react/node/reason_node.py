import json
from typing import Any, Literal

from langchain.tools import BaseTool
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import ValidationError

from .....common import get_logger
from .....prompt import PromptLoader
from .....utils import MessageAdapter, update_agent_result
from ....app import Application
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....model.message import Message, Role
from ....model.tool import ToolState
from ....runtime.runtime_config import RuntimeConfig
from ....tool import ToolGateWay, ToolType
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
        self._tool_gateway = ToolGateWay()
        self.MAX_ROUNDS: int = 6
        self.MAX_OUTPUT_REPAIRS: int = 2
        self.MAX_TOOL_MESSAGE_CHARS = 12000

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
            result = self._invoke_loop(state, runtime, observation_list)
        except RuntimeError as exc:
            logger.warning("reason loop failed: %s", exc)
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
            result = await self._ainvoke_loop(state, runtime, observation_list)
        except RuntimeError as exc:
            logger.warning("reason loop failed: %s", exc)
            return self._router(state, runtime.context, {
                "task_status": "failed", 
                "observations": observation_list, 
                "tool_list": [],
            })
        logger.info("result=%r", result)
        return self._handle_result(result, state, runtime.context, observation_list)

    def _invoke_loop(self, state: ReActState, runtime: Runtime[ReActContext], observation_list: list[Observation]) -> ReasonStructuredOutput:
        kwargs = self._prepare_invoke(state, runtime, observation_list)
        workflows = self._resolve_workflow()
        self._append_workflow_information(kwargs, workflows)
        history: list[Message] = list(kwargs["history"])
        runtime_config = RuntimeConfig.get_runtime_config()
        session = Application.get_application().get_agent(runtime_config.agent_id).get_sesion(runtime_config.session_id)

        for round_index in range(self.MAX_ROUNDS):
            kwargs["history"] = history
            try:
                result = self._invoke_reason_result(
                    kwargs,
                    runtime,
                    session.before_model,
                )
                self._validate_reason_result(result, workflows)
            except ValueError as exc:
                logger.warning("invalid reason result | round=%s error=%s", round_index + 1, exc)
                self._append_reason_feedback(history, str(exc))
                continue

            if not result.continue_reasoning:
                return result

            # 保存当前结构化结果，作为内部Workflow选择与下一轮推理的依据。
            history.append(self._to_reason_message(result))
            self._invoke_workflow(
                result,
                workflows,
                kwargs,
                history,
                runtime,
                session.before_model,
            )

        # 正常循环预算耗尽后只生成结构化结果，不再执行内部Workflow。
        return self._finalize_result(kwargs, history, runtime, session.before_model)

    async def _ainvoke_loop(self, state: ReActState, runtime: Runtime[ReActContext], observation_list: list[Observation]) -> ReasonStructuredOutput:
        kwargs = self._prepare_invoke(state, runtime, observation_list)
        workflows = self._resolve_workflow()
        self._append_workflow_information(kwargs, workflows)
        history: list[Message] = list(kwargs["history"])
        runtime_config = RuntimeConfig.get_runtime_config()
        session = Application.get_application().get_agent(runtime_config.agent_id).get_sesion(runtime_config.session_id)

        for round_index in range(self.MAX_ROUNDS):
            kwargs["history"] = history
            try:
                result = await self._ainvoke_reason_result(
                    kwargs,
                    runtime,
                    session.abefore_model,
                )
                self._validate_reason_result(result, workflows)
            except ValueError as exc:
                logger.warning("invalid async reason result | round=%s error=%s", round_index + 1, exc)
                self._append_reason_feedback(history, str(exc))
                continue

            if not result.continue_reasoning:
                return result

            # 保存当前结构化结果，作为内部Workflow选择与下一轮推理的依据。
            history.append(self._to_reason_message(result))
            await self._ainvoke_workflow(
                result,
                workflows,
                kwargs,
                history,
                runtime,
                session.abefore_model,
            )

        # 正常循环预算耗尽后只生成结构化结果，不再执行内部Workflow。
        return await self._afinalize_result(kwargs, history, runtime, session.abefore_model)

    def _invoke_reason_result(
        self,
        kwargs: dict[str, Any],
        runtime: Runtime[ReActContext],
        before_model: Any,
    ) -> ReasonStructuredOutput:
        """生成并校验一轮结构化推理结果。"""
        response = self._llm_client.invoke_structured(
            schema=ReasonStructuredOutput,
            **kwargs,
            before_model=before_model,
        )
        update_agent_result(runtime.context, response.text, response.token_usage)
        try:
            return ReasonStructuredOutput.model_validate(response.structured)
        except ValidationError as exc:
            raise ValueError("Invalid structured reason result.") from exc

    async def _ainvoke_reason_result(self, kwargs: dict[str, Any], runtime: Runtime[ReActContext], abefore_model: Any) -> ReasonStructuredOutput:
        """异步生成并校验一轮结构化推理结果"""
        response = await self._llm_client.ainvoke_structured(
            schema=ReasonStructuredOutput,
            **kwargs,
            abefore_model=abefore_model,
        )
        update_agent_result(runtime.context, response.text, response.token_usage)
        try:
            return ReasonStructuredOutput.model_validate(response.structured)
        except ValidationError as exc:
            raise ValueError("Invalid structured reason result.") from exc

    def _invoke_workflow(
        self,
        result: ReasonStructuredOutput,
        workflows: list[BaseTool],
        kwargs: dict[str, Any],
        history: list[Message],
        runtime: Runtime[ReActContext],
        before_model: Any,
    ) -> None:
        """根据结构化推理结果选择并执行内部Workflow"""
        response = self._llm_client.invoke(
            prompt=self._build_workflow_prompt(),
            user_input={"reasoning": result.reasoning},
            history=history,
            tool_list=workflows,
            context=kwargs["context"],
            agent_resources=kwargs["agent_resources"],
            config=kwargs["config"],
            before_model=before_model,
            conversation=kwargs["conversation"],
        )
        update_agent_result(runtime.context, response.text, response.token_usage)
        self._handle_workflow_response(response.raw, workflows, history)

    async def _ainvoke_workflow(
        self,
        result: ReasonStructuredOutput,
        workflows: list[BaseTool],
        kwargs: dict[str, Any],
        history: list[Message],
        runtime: Runtime[ReActContext],
        abefore_model: Any,
    ) -> None:
        """异步选择并执行内部Workflow"""
        response = await self._llm_client.ainvoke(
            prompt=self._build_workflow_prompt(),
            user_input={"reasoning": result.reasoning},
            history=history,
            tool_list=workflows,
            context=kwargs["context"],
            agent_resources=kwargs["agent_resources"],
            config=kwargs["config"],
            abefore_model=abefore_model,
            conversation=kwargs["conversation"],
        )
        update_agent_result(runtime.context, response.text, response.token_usage)
        await self._ahandle_workflow_response(response.raw, workflows, history)

    def _handle_workflow_response(self, message: Any, workflows: list[BaseTool], history: list[Message]) -> None:
        """处理Workflow选择结果"""
        if not isinstance(message, AIMessage):
            self._append_reason_feedback(history, "Workflow selection must return an AIMessage.")
            return

        history.append(MessageAdapter.to_message(message))
        if message.invalid_tool_calls:
            self._reject_tool_calls(message, history, "Workflow selection contains malformed tool calls.")
            return
        if not message.tool_calls:
            self._append_reason_feedback(history, "continue_reasoning=true requires at least one Workflow call.")
            return

        feedback = self._execute_workflow(message, workflows)
        history.extend(MessageAdapter.to_message(item) for item in feedback)

    async def _ahandle_workflow_response(self, message: Any, workflows: list[BaseTool], history: list[Message]) -> None:
        """异步处理Workflow选择结果"""
        if not isinstance(message, AIMessage):
            self._append_reason_feedback(history, "Workflow selection must return an AIMessage.")
            return

        history.append(MessageAdapter.to_message(message))
        if message.invalid_tool_calls:
            self._reject_tool_calls(message, history, "Workflow selection contains malformed tool calls.")
            return
        if not message.tool_calls:
            self._append_reason_feedback(history, "continue_reasoning=true requires at least one Workflow call.")
            return

        feedback = await self._aexecute_workflow(message, workflows)
        history.extend(MessageAdapter.to_message(item) for item in feedback)

    def _reject_tool_calls(self, message: AIMessage, history: list[Message], error: str) -> None:
        """拒绝本轮合法工具调用，并补齐对应的ToolMessage"""
        for call in message.tool_calls:
            history.append(MessageAdapter.to_message(ToolMessage(
                content=f"Workflow call was not executed: {error}",
                tool_call_id=call["id"],
                name=call["name"],
            )))
        self._append_reason_feedback(history, error)

    def _execute_workflow(self, message: AIMessage, tools: list[BaseTool]) -> list[ToolMessage]:
        available = {tool.name: tool for tool in tools}
        feedback: list[ToolMessage] = []
        for call in message.tool_calls:
            name, call_id = call["name"], call["id"]
            selected = available.get(name)
            if selected is None:
                content = f"Unknown or unauthorized workflow: {name}"
            else:
                try:
                    output = selected.invoke(call["args"])
                    content = self._format_internal_output(output)
                except (Exception,) as exc:
                    content = f"Workflow error ({name}): {type(exc).__name__}: {exc}"
            feedback.append(ToolMessage(content=content, tool_call_id=call_id, name=name))
        return feedback

    async def _aexecute_workflow(self, message: AIMessage, tools: list[BaseTool]) -> list[ToolMessage]:
        available = {tool.name: tool for tool in tools}
        feedback: list[ToolMessage] = []
        for call in message.tool_calls:
            name, call_id = call["name"], call["id"]
            selected = available.get(name)
            if selected is None:
                content = f"Unknown or unauthorized workflow: {name}"
            else:
                try:
                    output = await selected.ainvoke(call["args"])
                    content = self._format_internal_output(output)
                except (Exception,) as exc:
                    content = f"Workflow error ({name}): {type(exc).__name__}: {exc}"
            feedback.append(ToolMessage(content=content, tool_call_id=call_id, name=name))
        return feedback

    def _validate_reason_result(self, result: ReasonStructuredOutput, workflows: list[BaseTool]) -> None:
        """校验结构化结果与ReasonNode内部状态是否一致"""
        if not result.reasoning.strip():
            raise ValueError("Reason result reasoning must not be empty.")

        if result.continue_reasoning:
            if result.task_status != "in_progress":
                raise ValueError("continue_reasoning=true requires task_status='in_progress'.")
            if result.tool_list:
                raise ValueError("tool_list must be empty while continue_reasoning=true.")
            if not workflows:
                raise ValueError("continue_reasoning=true requires an available Workflow.")
            return

        if result.task_status == "completed" and result.tool_list:
            raise ValueError("task_status='completed' requires an empty tool_list.")
        if result.task_status == "in_progress" and not result.tool_list:
            raise ValueError("A final in_progress result requires at least one external tool.")

    def _finalize_result(
        self,
        kwargs: dict[str, Any],
        history: list[Message],
        runtime: Runtime[ReActContext],
        before_model: Any,
    ) -> ReasonStructuredOutput:
        final_kwargs = dict(kwargs)
        final_kwargs["user_input"] = self._build_final_input(kwargs["user_input"])
        last_error = "No final reason result was produced."

        for repair_index in range(self.MAX_OUTPUT_REPAIRS):
            final_kwargs["history"] = history
            try:
                result = self._invoke_reason_result(final_kwargs, runtime, before_model)
                if result.continue_reasoning:
                    raise ValueError("Final reason result must set continue_reasoning=false.")
                self._validate_reason_result(result, [])
                return result
            except ValueError as exc:
                last_error = str(exc)
                logger.warning("invalid final reason result | repair=%s error=%s", repair_index + 1, exc)
                self._append_reason_feedback(history, last_error)

        raise RuntimeError(f"Reason result finalization failed: {last_error}")

    async def _afinalize_result(
        self,
        kwargs: dict[str, Any],
        history: list[Message],
        runtime: Runtime[ReActContext],
        abefore_model: Any,
    ) -> ReasonStructuredOutput:
        final_kwargs = dict(kwargs)
        final_kwargs["user_input"] = self._build_final_input(kwargs["user_input"])
        last_error = "No final reason result was produced."

        for repair_index in range(self.MAX_OUTPUT_REPAIRS):
            final_kwargs["history"] = history
            try:
                result = await self._ainvoke_reason_result(final_kwargs, runtime, abefore_model)
                if result.continue_reasoning:
                    raise ValueError("Final reason result must set continue_reasoning=false.")
                self._validate_reason_result(result, [])
                return result
            except ValueError as exc:
                last_error = str(exc)
                logger.warning("invalid async final reason result | repair=%s error=%s", repair_index + 1, exc)
                self._append_reason_feedback(history, last_error)

        raise RuntimeError(f"Reason result finalization failed: {last_error}")

    def _append_workflow_information(self, kwargs: dict[str, Any], workflows: list[BaseTool]) -> None:
        """向结构化推理输入注入可用的内部Workflow信息。"""
        user_input = kwargs.get("user_input")
        if not isinstance(user_input, dict):
            return
        # 结构化推理和Workflow执行使用两次独立的模型调用。
        user_input["reason_contract"] = {
            "continue_reasoning": (
                "Set true when an internal Workflow is required. ReasonNode will "
                "select and execute the Workflow after this structured response."
            ),
            "tool_list": (
                "Keep empty while continue_reasoning is true. When false, include "
                "only external tools required by ActionNode."
            ),
        }
        user_input["workflows"] = [
            {"name": workflow.name, "description": workflow.description}
            for workflow in workflows
        ]

    def _append_reason_feedback(self, history: list[Message], error: str) -> None:
        """追加节点内部纠错信息，不增加外层retry_count。"""
        history.append(Message(
            role=Role.USER,
            content=(
                f"The previous ReasonNode round was invalid: {error} "
                "Generate a complete ReasonStructuredOutput again."
            ),
        ))

    def _to_reason_message(self, result: ReasonStructuredOutput) -> Message:
        """将结构化推理结果保存为无工具调用的内部历史消息。"""
        return Message(
            role=Role.ASSISTANT,
            content=json.dumps({"reason_result": result.model_dump(mode="json")}, ensure_ascii=False),
        )

    def _build_final_input(self, user_input: Any) -> dict[str, Any]:
        """构建禁止继续调用Workflow的收尾输入。"""
        final_input = dict(user_input) if isinstance(user_input, dict) else {"input": user_input}
        final_input["reason_instruction"] = (
            "The internal Workflow budget is exhausted. Generate the best deliverable "
            "ReasonStructuredOutput now. Set continue_reasoning=false."
        )
        return final_input

    def _build_workflow_prompt(self) -> str:
        """构建ReasonNode内部Workflow选择提示。"""
        return (
            "You are the internal Workflow execution stage of ReasonNode. "
            "Use the supplied reasoning to call one or more available Workflows. "
            "Do not produce the final user-facing response."
        )

    def _format_internal_output(self, output: Any) -> str:
        if isinstance(output, str):
            content = output
        else:
            content = json.dumps(output, ensure_ascii=False, default=str)
        if len(content) > self.MAX_TOOL_MESSAGE_CHARS:
            return content[:self.MAX_TOOL_MESSAGE_CHARS] + "\n[Output truncated; use artifact workflow for large results.]"
        return content

    def _build_observations(self, state: ReActState, context: ReActContext) -> list[Observation]:
        """
        构建Observation
        """
        observations = []

        if state.task_status == "in_progress":
            for tool_result in state.tool_state.tool_results:
                observation = ObservationBuilder.build(tool_result, context.tool_artifacts.get(tool_result.tool_call_id))
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

        # 获取外部工具信息
        tool_informations = tool_registry.get_tool_infomations(
            tool_types={
                ToolType.FUNCTION,
                ToolType.HTTP,
                ToolType.MCP,
            }
        )

        return {
            "prompt": self._prompt,
            "user_input": self._build_input(state, observation_list), # 用户输入
            "history": self._build_history(state, runtime.context), # 历史记录
            "conversation": state.conversation,
            "tool_informations": tool_informations,
            "context": runtime.context,
            "agent_resources": runtime.context.resources,
            "config": runtime_config.to_llm_runnable_config(),
        }

    def _build_history(self, state: ReActState, context: ReActContext | None = None) -> list[Message]:
        """
        构建跨轮会话历史与本轮执行轨迹。
        """
        if context is None:
            raise ValueError("ReActContext is required for ReasonNode")
        return build_react_history(state.conversation, state.trajectory)

    def _build_input(self, state: ReActState, observation_list: list[Observation]) -> dict:
        """
        构建输入
        """
        return {
            "task": state.task.dump_attachments(),
            "observations": observation_list, # 本次ReAct Loop完整的观察结果
        }

    def _handle_result(self, response: ReasonStructuredOutput, state: ReActState, context: ReActContext | None, observation_list: list[Observation]) -> Command:
        """
        处理Reason结果
        """
        result = {
            "task_status": response.task_status,
            "reasoning": response.reasoning,
            "observations": observation_list, # 更新observations
            "tool_list": response.tool_list,
        }

        # 非法工具时，清空工具状态
        if state.task_status == "invalid_tools":
            result["tool_state"] = ToolState(tool_calls=[], tool_results=[])

        # 只有确定进入下一次 Action 执行时，才消耗 step
        if response.task_status == "in_progress":
            result["step_count"] = state.step_count + 1
            result["tool_state"] = ToolState(tool_calls=[], tool_results=[])

        return self._router(state, context, result)

    def _router(self, state: ReActState, context: ReActContext | None, update_state: dict) -> Command:
        next_node = self._select_node(state, context, update_state)
        logger.info("route reason -> %s", next_node)
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

    def _resolve_workflow(self) -> list[BaseTool]:
        runtime_config = RuntimeConfig.get_runtime_config()
        tool_registry = Application.get_application().get_agent(runtime_config.agent_id).tool_registry

        # 获取所有工作流工具定义
        definitions = tool_registry.list_definitions(tool_types={ToolType.WORKFLOW})
        # 根据当前 AgentMode 和 Tool Annotations 过滤授权工具
        authorized_tools = self._tool_gateway.filter(
            definitions,
            runtime_config.agent_mode,
            tool_types={ToolType.WORKFLOW},
        )

        handlers: list[BaseTool] = []
        for tool in authorized_tools:
            handler = tool_registry.get_handler(tool.name)
            if isinstance(handler, BaseTool):
                handlers.append(handler)
        return handlers


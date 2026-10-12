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
    submit_reason_result,
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
        # 检查工具执行失败
        if self._has_tool_error(state):
            return self._handle_tool_error(state, runtime.context, observation_list)

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
        # 检查工具执行失败
        if self._has_tool_error(state):
            return self._handle_tool_error(state, runtime.context, observation_list)

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
        # 准备调用参数
        kwargs = self._prepare_invoke(state, runtime, observation_list)
        tools = self._resolve_tools()
        kwargs["tool_list"] = tools
        history: list[Message] = list(kwargs["history"])
        runtime_config = RuntimeConfig.get_runtime_config()
        session = Application.get_application().get_agent(runtime_config.agent_id).get_sesion(runtime_config.session_id)
        for _ in range(self.MAX_ROUNDS):
            kwargs["history"] = history
            response = self._llm_client.invoke(**kwargs, before_model=session.before_model)
            update_agent_result(runtime.context, response.text, response.token_usage)
            message = response.raw
            if not isinstance(message, AIMessage):
                raise RuntimeError("Reason LLM response must be AIMessage")
            history.append(MessageAdapter.to_message(message))

            # 无效工具调用
            if message.invalid_tool_calls:
                raise RuntimeError("Reason LLM returned malformed tool calls")
            
            try:
                result = self._parse_result_tool_call(message)
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            
            if result is not None:
                return result
            
            if message.tool_calls:
                feedback = self._execute_workflow(message, tools)
                history.extend(MessageAdapter.to_message(item) for item in feedback)
            else:
                history.append(Message(role=Role.USER, content="Call a workflow or submit_reason_result. Do not answer in plain text."))
        raise RuntimeError("Reason workflow round budget exceeded")

    async def _ainvoke_loop(self, state: ReActState, runtime: Runtime[ReActContext], observation_list: list[Observation]) -> ReasonStructuredOutput:
        kwargs = self._prepare_invoke(state, runtime, observation_list)
        tools = self._resolve_tools()
        kwargs["tool_list"] = tools
        history: list[Message] = list(kwargs["history"])
        runtime_config = RuntimeConfig.get_runtime_config()
        session = Application.get_application().get_agent(runtime_config.agent_id).get_sesion(runtime_config.session_id)
        for _ in range(self.MAX_ROUNDS):
            kwargs["history"] = history
            response = await self._llm_client.ainvoke(**kwargs, abefore_model=session.abefore_model)
            update_agent_result(runtime.context, response.text, response.token_usage)
            message = response.raw
            if not isinstance(message, AIMessage):
                raise RuntimeError("Reason LLM response must be AIMessage")
            history.append(MessageAdapter.to_message(message))

            # 无效工具调用
            if message.invalid_tool_calls:
                raise RuntimeError("Reason LLM returned malformed tool calls")
            try:
                result = self._parse_result_tool_call(message)
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            
            if result is not None:
                return result
            
            if message.tool_calls:
                feedback = await self._aexecute_workflow(message, tools)
                history.extend(MessageAdapter.to_message(item) for item in feedback)
            else:
                history.append(Message(role=Role.USER, content="Call a workflow or submit_reason_result. Do not answer in plain text."))
        raise RuntimeError("Reason workflow round budget exceeded")

    def _execute_workflow(self, message: AIMessage, tools: list[BaseTool]) -> list[ToolMessage]:
        available = {tool.name: tool for tool in tools if tool.name != submit_reason_result.name}
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
        available = {tool.name: tool for tool in tools if tool.name != submit_reason_result.name}
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
            "tool_list": [],
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

    def _resolve_tools(self) -> list[BaseTool]:
        workflows = self._resolve_workflow()
        if any(tool.name == submit_reason_result.name for tool in workflows):
            raise ValueError(f"Reserved tool name: {submit_reason_result.name}")

        return [
            *workflows,
            submit_reason_result,
        ]

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

    def _parse_result_tool_call(self, message: AIMessage) -> ReasonStructuredOutput | None:
        result_calls = [
            call
            for call in message.tool_calls
            if call["name"] == submit_reason_result.name
        ]

        if not result_calls:
            return None

        # Ensure the result submission is the only tool call.
        if len(message.tool_calls) != 1:
            raise ValueError("Reason result submission must be the only tool call.")

        try:
            return ReasonStructuredOutput.model_validate(result_calls[0]["args"])
        except ValidationError as exc:
            raise ValueError("Invalid structured reason result.") from exc

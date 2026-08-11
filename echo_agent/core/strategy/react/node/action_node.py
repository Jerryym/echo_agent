from typing import Any, Literal

from langgraph.runtime import Runtime
from langgraph.types import Command, RunnableConfig

from .....common import get_logger
from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....model.hitl import HITLInput, HITLInteraction, HITLOutput, HITLType
from ....model.message import Message, Role
from ....model.skill import SkillStatus
from ....model.tool import ToolCall, ToolState
from ....runtime.interrupt import InterruptField
from ....tool import ToolDefinition, ToolRegistry
from ....tool.utils import to_openai_tool_json_schema
from .....utils import MessageAdapter, update_agent_result
from ..schema import ReActContext, ReActState

logger = get_logger("react.action")


class ActionNode(Node):
    """
    Action Node：动作节点
    """
    def __init__(self, name: str, llm_config: LLMConfig, tool_registry: ToolRegistry):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/action.md")
        self._tool_registry = tool_registry

    def run(self, state: ReActState, runtime: Runtime[ReActContext], config: RunnableConfig | None = None) -> Command:
        """
        Run the node
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)
        if state.tool_state.tool_calls:
            return self._handle_tool_calls(state)

        available_tools = self._available_tools(runtime.context)
        response = self._llm_client.invoke(
            prompt=self._prompt,
            user_input={"reasoning": state.reasoning},
            history=self._build_history(state, runtime.context),
            tool_list=to_openai_tool_json_schema(available_tools),
            context=runtime.context,
            agent_prompt=runtime.context.agent_prompt,
        )
        update_agent_result(runtime.context, response.text, response.token_usage)
        return self._route_after_tool_selection(state, response.tool_calls, available_tools)

    async def arun(self, state: ReActState, runtime: Runtime[ReActContext], config: RunnableConfig | None = None) -> Command:
        """
        异步运行
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)
        if state.tool_state.tool_calls:
            return self._handle_tool_calls(state)

        available_tools = self._available_tools(runtime.context)
        response = await self._llm_client.ainvoke(
            prompt=self._prompt,
            user_input={"reasoning": state.reasoning},
            history=self._build_history(state, runtime.context),
            tool_list=to_openai_tool_json_schema(available_tools),
            context=runtime.context,
            agent_prompt=runtime.context.agent_prompt,
        )
        update_agent_result(runtime.context, response.text, response.token_usage)
        return self._route_after_tool_selection(state, response.tool_calls, available_tools)

    def _route_after_tool_selection(
        self,
        state: ReActState,
        tool_calls: list[ToolCall] | None,
        available_tools: list[ToolDefinition],
    ) -> Command:
        """LLM 选型后的公共分支（run / arun 共用）。"""
        if not tool_calls:
            return self._handle_no_tool_calls(state)

        invalid_names = self._get_invalid_tools(tool_calls, available_tools)
        if invalid_names:
            logger.warning(
                "invalid_tools selected=%s invalid=%s available=%s",
                [tc.name for tc in tool_calls],
                invalid_names,
                [tool.name for tool in available_tools],
            )
            invalid_tools = [tc for tc in tool_calls if tc.name in invalid_names]
            return self._handle_invalid_tools(invalid_tools, state)

        missing_parameters_map = self._get_missing_parameters(tool_calls)
        if missing_parameters_map:
            return self._handle_missing_parameters(tool_calls, missing_parameters_map, state)

        if self._need_approval(tool_calls):
            return self._handle_approval(tool_calls, state)

        return self._handle_ready(tool_calls, state)

    def _build_history(self, state: ReActState, context: ReActContext | None = None) -> list[Message]:
        """
        构建跨轮会话历史与本轮执行轨迹。
        """
        if context is None:
            raise ValueError("ReActContext is required for ActionNode")
        return [
            *state.conversation,
            Message(role=Role.USER, content=state.task.description or state.task.goal),
            *state.trajectory,
        ]

    def _handle_tool_calls(self, state: ReActState) -> Command:
        """
        处理工具调用的情况
        """
        hitl_state = state.hitl_state
        if hitl_state.response:
            # HITL 被取消
            if hitl_state.response.status == "cancelled":
                return self._router(state, {
                    "task_status": "cancelled",
                    "tool_state": ToolState(tool_calls=[]),
                    "hitl_state": HITLInteraction(request=None, response=None),
                    "step_count": state.step_count + 1,
                })

            if hitl_state.request:
                if hitl_state.request.type == HITLType.INPUT:# INPUT 类型
                    tool_calls = self._fill_tool_calls(state.tool_state.tool_calls, hitl_state.response)
                    missing_map = self._get_missing_parameters(tool_calls)
                    if missing_map:# 仍缺参：再走一轮 INPUT HITL（可顺带清掉本次已消费的 response）
                        return self._handle_missing_parameters(tool_calls, missing_map, state)
                    tool_calls = self._mark_missing_parameters(tool_calls, {})
                    # 判断是否需要人工审核
                    if self._need_approval(tool_calls):
                        return self._handle_approval(tool_calls, state)
                    return self._router(state, {
                        "task_status": "in_progress",
                        "tool_state": ToolState(tool_calls=tool_calls),
                        "hitl_state": HITLInteraction(request=None, response=None),
                        "trajectory": [
                            MessageAdapter.to_tool_call_message(tool_calls)
                        ],
                        "step_count": state.step_count + 1,
                    })
                if hitl_state.request.type == HITLType.APPROVAL:# APPROVAL 类型
                    approved = (hitl_state.response.result or {}).get("approved")
                    if approved is not True:
                        return self._router(state, {
                            "task_status": "cancelled",
                            "tool_state": ToolState(tool_calls=[]),
                            "hitl_state": HITLInteraction(request=None, response=None),
                            "step_count": state.step_count + 1,
                        })
                    return self._router(state, {
                        "task_status": "in_progress",
                        "tool_state": ToolState(tool_calls=state.tool_state.tool_calls),
                        "hitl_state": HITLInteraction(request=None, response=None),
                        "trajectory": [
                            MessageAdapter.to_tool_call_message(state.tool_state.tool_calls)
                        ],
                        "step_count": state.step_count + 1,
                    })

        logger.warning(
            "tool_calls present without hitl response; refuse execution | tools=%s",
            [tc.name for tc in state.tool_state.tool_calls],
        )
        return self._router(state, {
            "task_status": "failed",
            "tool_state": ToolState(tool_calls=[], tool_results=[]),
            "hitl_state": HITLInteraction(request=None, response=None),
            "step_count": state.step_count + 1,
        })

    def _handle_no_tool_calls(self, state: ReActState) -> Command:
        """
        处理没有工具调用的情况
        """
        return self._router(state, {
            "task_status": "no_tool_calls", # 没有工具调用
            "step_count": state.step_count + 1,
            "retry_count": state.retry_count + 1,
        })

    def _handle_invalid_tools(self, invalid_tools: list[ToolCall], state: ReActState) -> Command:
        """
        处理非法工具的情况
        """
        return self._router(state, {
            "task_status": "invalid_tools", # 非法工具
            "tool_state": ToolState(tool_calls=invalid_tools), # 传入非法工具
            "step_count": state.step_count + 1,
            "retry_count": state.retry_count + 1,
        })

    def _handle_ready(self, tool_calls: list[ToolCall], state: ReActState) -> Command:
        """
        处理ready状态
        """
        return self._router(state, {
            "task_status": "in_progress",
            "tool_state": ToolState(tool_calls=tool_calls),
            "trajectory": [
                MessageAdapter.to_tool_call_message(tool_calls)
            ],
            "step_count": state.step_count + 1,
        })

    def _handle_missing_parameters(
        self,
        tool_calls: list[ToolCall],
        missing_parameters_map: dict[str, list[str]],
        state: ReActState,
    ) -> Command:
        """
        处理缺少参数状态
        """
        updated_tool_calls = self._mark_missing_parameters(tool_calls, missing_parameters_map)

        # 构建 HITL 请求（fields / resume values 均按 tool_call_id 分组，避免多工具同名缺参串写）
        fields_by_call = self._build_fields(updated_tool_calls, missing_parameters_map)
        request = HITLInput(
            type=HITLType.INPUT,
            description="Please provide the missing parameters. ",
            payload={
                "fields": {
                    tool_call_id: [field.model_dump() for field in fields]
                    for tool_call_id, fields in fields_by_call.items()
                },
                "tool_calls": [
                    {
                        "tool_call_id": tc.tool_call_id,
                        "name": tc.name,
                        "missing_args": tc.missing_args,
                    }
                    for tc in updated_tool_calls
                ],
            },
        )

        # 更新状态
        update_state = {
            "task_status": "human_in_the_loop",
            "tool_state": ToolState(tool_calls=updated_tool_calls),
            "hitl_state": HITLInteraction(request=request, response=None),
        }

        return self._router(state, update_state)

    def _handle_approval(self, tool_calls: list[ToolCall], state: ReActState) -> Command:
        """
        处理人工审核状态
        """
        request = HITLInput(
            type=HITLType.APPROVAL,
            description="Please approve the execution of this action. ",
            payload={
                "tool_calls": [
                    {
                        "tool_call_id": tc.tool_call_id,
                        "name": tc.name,
                        "args": tc.args,
                    }
                    for tc in tool_calls
                ],
            },
        )

        # 更新状态
        update_state = {
            "task_status": "human_in_the_loop",
            "tool_state": ToolState(tool_calls=tool_calls),
            "hitl_state": HITLInteraction(request=request, response=None),
        }

        return self._router(state, update_state)

# region: Router Functions
    def _router(self, state: ReActState, update_state: dict) -> Command:
        next_node = self._select_node(state, update_state)
        logger.info("route action -> %s | status=%s", next_node, update_state.get("task_status", state.task_status))
        return Command(update=update_state, goto=next_node)

    def _select_node(self, state: ReActState, update_state: dict) -> Literal["HITL", "tool", "reason"]:
        task_status = update_state.get("task_status", state.task_status)
        if task_status == "human_in_the_loop":
            return "HITL"
        if task_status == "in_progress":
            return "tool"
        # no_tool_calls / invalid_tools / cancelled / failed
        return "reason"
# endregion

    def _available_tools(self, context: ReActContext) -> list[ToolDefinition]:
        """Return tools visible to the model for the current skill state."""
        tool_list = self._tool_registry.list_definitions()
        default_tools = self._tool_registry.default_tools()

        if not context.skill_list:
            return tool_list

        loaded_skills = [
            skill
            for skill in context.active_skills.values()
            if skill.status == SkillStatus.LOADED
        ]
        if not loaded_skills:
            return default_tools

        allowed_names: set[str] = set()
        has_explicit_allowlist = False
        for skill in loaded_skills:
            configured = skill.package.frontmatter.allowed_tools
            if configured is None:
                continue
            has_explicit_allowlist = True
            allowed_names.update(configured)

        # Backward compatibility: existing skills without allowed_tools keep
        # the previous all-tools behavior after they are explicitly loaded.
        if not has_explicit_allowlist:
            return tool_list

        default_names = {tool.name for tool in default_tools}
        business_tools = [
            tool
            for tool in tool_list
            if tool.name not in default_names
            and (
                tool.name in allowed_names
                or tool.meta_data.get("original_name") in allowed_names
            )
        ]
        return [*default_tools, *business_tools]

    def _get_invalid_tools(self, tool_calls: list[ToolCall], available_tools: list[ToolDefinition] | None = None) -> list[str]:
        """
        获取非法工具
        """
        valid_names = self._valid_tool_names(available_tools)
        return [
            tc.name
            for tc in tool_calls
            if tc.name not in valid_names
        ]

    def _valid_tool_names(self, available_tools: list[ToolDefinition] | None = None) -> set[str]:
        """
        获取合法工具名称列表
        """
        tools = (
            available_tools
            if available_tools is not None
            else self._tool_registry.list_definitions()
        )
        return {tool.name for tool in tools}

    def _build_fields(self, tool_calls: list[ToolCall], missing_parameters_map: dict[str, list[str]]) -> dict[str, list[InterruptField]]:
        """
        按 tool_call_id 构建信息补全字段，避免多工具同名缺参互相覆盖。
        """
        fields_by_call: dict[str, list[InterruptField]] = {}
        for tool_call in tool_calls:
            missing_parameters = missing_parameters_map.get(tool_call.tool_call_id, [])
            if not missing_parameters:
                continue
            tool_definition = self._tool_registry.get(tool_call.name)
            fields_by_call[tool_call.tool_call_id] = [
                InterruptField(
                    name=param,
                    description=(
                        tool_definition.get_parameter_description(param)
                        if tool_definition
                        else param
                    ),
                )
                for param in missing_parameters
            ]
        return fields_by_call

    def _mark_missing_parameters(self, tool_calls: list[ToolCall], missing_parameters_map: dict[str, list[str]]) -> list[ToolCall]: 
        """
        标记待补充参数
        """
        for tool_call in tool_calls:
            tool_call.missing_args = missing_parameters_map.get(tool_call.tool_call_id, [])
        return tool_calls

    def _fill_tool_calls(self, tool_calls: list[ToolCall], response: HITLOutput) -> list[ToolCall]:
        """
        使用 interrupt 返回值按 tool_call_id 填充工具参数。

        resume 协议：{"values": {tool_call_id: {param: value, ...}, ...}}
        """
        values = (response.result or {}).get("values") or {}
        updated_tool_calls = []
        for tool_call in tool_calls:
            per_call = values.get(tool_call.tool_call_id)
            if isinstance(per_call, dict):
                for key in tool_call.missing_args:
                    if key in per_call:
                        tool_call.args[key] = per_call[key]

            # tool_call.missing_args = []
            updated_tool_calls.append(tool_call)
        return updated_tool_calls

    def _get_missing_parameters(self, tool_calls: list[ToolCall]) -> dict[str, list[str]]:
        """
        获取缺失的参数
        """
        missing_params_map = {}
        for tool_call in tool_calls:
            definition = self._tool_registry.get(tool_call.name)
            if not definition:
                continue

            missing_args = []
            for required in definition.required_parameters:
                if required not in tool_call.args or self._is_missing(tool_call.args[required]):
                    missing_args.append(required)

            if missing_args:
                missing_params_map[tool_call.tool_call_id] = missing_args

        return missing_params_map

    def _is_missing(self, value: Any) -> bool:
        """
        判断参数值是否缺失
        """
        if value is None:
            return True

        if isinstance(value, str):
            return not value.strip()
        return False

    def _need_approval(self, tool_calls: list[ToolCall]) -> bool:
        """
        判断是否需要人工审核
        """
        for tool_call in tool_calls:
            definition = self._tool_registry.get(tool_call.name)
            if definition and definition.requires_approval:
                return True

        return False

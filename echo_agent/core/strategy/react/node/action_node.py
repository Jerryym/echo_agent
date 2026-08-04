from typing import Any, Literal

from langgraph.runtime import Runtime
from langgraph.types import Command, RunnableConfig

from .....common import get_logger
from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....mcp.builtin_mcp import FETCH_SERVER_NAME, FILESYSTEM_SERVER_NAME
from ....model.hitl import HITLInput, HITLInteraction, HITLOutput, HITLType
from ....model.message import Message, Role
from ....model.skill import SkillStatus
from ....model.tool import ToolCall, ToolResult, ToolState
from ....runtime.interrupt import InterruptField
from ....tool import ToolDefinition
from ....tool.utils import get_tool_definition
from ....trace import TokenUsage
from ..observation import ObservationBuilder
from ..schema import ReActContext, ReActState

logger = get_logger("react.action")

# Always-visible skill meta tools + builtin MCP servers.
_META_TOOL_NAMES = frozenset({"load_skill", "read_skill_resource"})
_ALWAYS_EXPOSED_MCP_SERVERS = frozenset({FETCH_SERVER_NAME, FILESYSTEM_SERVER_NAME})


class ActionNode(Node):
    """
    Action Node：动作节点
    """
    def __init__(self, name: str, llm_config: LLMConfig, tool_list: list[ToolDefinition] | None = None):
        super().__init__(name, is_async=True)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/action.md")
        self._tool_list = tool_list or []
        
    @staticmethod
    def _to_tool_json_schema(tool_list: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tool_list
        ]

    def _default_tools(self) -> list[ToolDefinition]:
        """Skill meta tools + fetch/filesystem MCP tools (always exposed)."""
        return [
            tool
            for tool in self._tool_list
            if (
                tool.name in _META_TOOL_NAMES
                or tool.meta_data.get("mcp_server") in _ALWAYS_EXPOSED_MCP_SERVERS
            )
        ]

    def _available_tools(self, context: ReActContext) -> list[ToolDefinition]:
        """Return tools visible to the model for the current skill state."""
        default_tools = self._default_tools()
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
            return self._tool_list

        default_names = {tool.name for tool in default_tools}
        business_tools = [
            tool
            for tool in self._tool_list
            if tool.name not in default_names
            and (
                tool.name in allowed_names
                or tool.meta_data.get("original_name") in allowed_names
            )
        ]
        return [*default_tools, *business_tools]

    def run(self, state: ReActState, runtime: Runtime[ReActContext], config: RunnableConfig | None = None) -> Command:
        """
        Run the node
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)

        # 如果存在工具调用，则跳过工具选择
        logger.debug("state.tool_calls=%s", state.tool_state.tool_calls)
        if state.tool_state.tool_calls:
            return self._handle_tool_calls(state)

        # 构建输入
        input = {
            "reasoning": state.reasoning,
        }
        available_tools = self._available_tools(runtime.context)
        self._log_available_tools(runtime.context, available_tools)
        # 选择工具
        response = self._llm_client.invoke(
            prompt=self._prompt,
            user_input=input,
            history=self._build_history(state, runtime.context),
            tool_list=self._to_tool_json_schema(available_tools),
            context=runtime.context,
            agent_prompt=runtime.context.agent_prompt,
        )
        self._accumulate_token_usage(runtime.context, response.token_usage)
        logger.debug("tool_selection_response=%s", response)
        logger.info("tool_selection_response.tool_calls=%s", response.tool_calls)

        # 没有工具调用，则返回 no_tool_calls 状态
        if not response.tool_calls:
            logger.info("branch=no_tool_calls")
            return self._handle_no_tool_calls(state)

        tool_calls = response.tool_calls
        # 工具合法性校验
        invalid_tools = self._get_invalid_tools(tool_calls, available_tools)
        if invalid_tools:
            logger.warning(
                "branch=invalid_tools selected=%s invalid=%s available=%s",
                [tc.name for tc in tool_calls],
                invalid_tools,
                [tool.name for tool in available_tools],
            )
            return self._handle_invalid_tools(invalid_tools, state, available_tools)
        # 参数校验
        missing_parameters_map = self._get_missing_parameters(tool_calls)

        # 参数缺失，需要收集信息
        if missing_parameters_map:
            logger.info("branch=missing_parameters map=%s", missing_parameters_map)
            return self._handle_missing_parameters(tool_calls, missing_parameters_map, state)

        # 人工审核
        if self._need_approval(tool_calls):
            logger.info("branch=approval tools=%s", [tc.name for tc in tool_calls])
            return self._handle_approval(tool_calls, state)

        logger.info("branch=ready tools=%s", [tc.name for tc in tool_calls])
        return self._handle_ready(tool_calls, state)

    async def arun(self, state: ReActState, runtime: Runtime[ReActContext], config: RunnableConfig | None = None) -> Command:
        """
        异步运行
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)

        # 如果存在工具调用，则跳过工具选择
        logger.debug("state.tool_calls=%s", state.tool_state.tool_calls)
        if state.tool_state.tool_calls:
            return self._handle_tool_calls(state)

        # 构建输入
        input = {
            "reasoning": state.reasoning,
        }
        available_tools = self._available_tools(runtime.context)
        self._log_available_tools(runtime.context, available_tools)
        # 选择工具
        response = await self._llm_client.ainvoke(
            prompt=self._prompt,
            user_input=input,
            history=self._build_history(state, runtime.context),
            tool_list=self._to_tool_json_schema(available_tools),
            context=runtime.context,
            agent_prompt=runtime.context.agent_prompt,
        )
        self._accumulate_token_usage(runtime.context, response.token_usage)
        logger.debug("tool_selection_response=%s", response)
        logger.info("tool_selection_response.tool_calls=%s", response.tool_calls)

        # 没有工具调用，则返回 no_tool_calls 状态
        if not response.tool_calls:
            logger.info("branch=no_tool_calls")
            return self._handle_no_tool_calls(state)

        tool_calls = response.tool_calls
        # 工具合法性校验
        invalid_tools = self._get_invalid_tools(tool_calls, available_tools)
        if invalid_tools:
            logger.warning(
                "branch=invalid_tools selected=%s invalid=%s available=%s",
                [tc.name for tc in tool_calls],
                invalid_tools,
                [tool.name for tool in available_tools],
            )
            return self._handle_invalid_tools(invalid_tools, state, available_tools)
        # 参数校验
        missing_parameters_map = self._get_missing_parameters(tool_calls)

        # 参数缺失，需要收集信息
        if missing_parameters_map:
            logger.info("branch=missing_parameters map=%s", missing_parameters_map)
            return self._handle_missing_parameters(tool_calls, missing_parameters_map, state)

        # 人工审核
        if self._need_approval(tool_calls):
            logger.info("branch=approval tools=%s", [tc.name for tc in tool_calls])
            return self._handle_approval(tool_calls, state)

        logger.info("branch=ready tools=%s", [tc.name for tc in tool_calls])
        return self._handle_ready(tool_calls, state)

    def _build_history(self, state: ReActState, context: ReActContext | None = None) -> list[Message]:
        """
        构建跨轮会话历史与本轮执行轨迹。
        """
        if context is None:
            raise ValueError("ReActContext is required for ActionNode")
        return [
            *state.conversation,
            *state.trajectory,
        ]

    @staticmethod
    def _accumulate_token_usage(context: ReActContext | None, token_usage: TokenUsage) -> None:
        if context is None or context.trace is None:
            return
        context.trace.token_usage = context.trace.token_usage.add(token_usage)

    def _handle_tool_calls(self, state: ReActState) -> Command:
        """
        处理工具调用的情况
        """
        hitl_state = state.hitl_state
        if hitl_state.response:
            logger.info("applying hitl response to tool_calls")
            # HITL 被取消
            if hitl_state.response.status == "cancelled":
                return self._router(state, {
                    "task_status": "cancelled",
                    "tool_state": ToolState(tool_calls=[]),
                    "step_count": state.step_count + 1,
                })

            if hitl_state.request:
                if hitl_state.request.type == HITLType.INPUT:# INPUT 类型
                    tool_calls = self._fill_tool_calls(state.tool_state.tool_calls, hitl_state.response)
                    # 判断是否需要人工审核
                    if self._need_approval(tool_calls):
                        return self._handle_approval(tool_calls, state)
                    return self._router(state, {
                        "task_status": "in_progress",
                        "tool_state": ToolState(tool_calls=tool_calls),
                        "hitl_state": HITLInteraction(request=None, response=None),
                        "trajectory": [
                            self._build_tool_call_message(tool_calls)
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
                            self._build_tool_call_message(state.tool_state.tool_calls)
                        ],
                        "step_count": state.step_count + 1,
                    })

        logger.debug("no hitl response, continue to generate tool calls")
        return self._router(state, {
            "task_status": "in_progress",
            "tool_state": ToolState(tool_calls=state.tool_state.tool_calls),
            "trajectory": [
                self._build_tool_call_message(state.tool_state.tool_calls)
            ],
        })

    def _log_available_tools(
        self,
        context: ReActContext,
        available_tools: list[ToolDefinition],
    ) -> None:
        """记录本轮可见工具与已加载 skill 的 allowlist，便于排查非法工具路由。"""
        loaded = [
            {
                "name": name,
                "status": skill.status.value,
                "idle_rounds": skill.idle_rounds,
                "allowed_tools": skill.package.frontmatter.allowed_tools,
            }
            for name, skill in context.active_skills.items()
            if skill.status == SkillStatus.LOADED
        ]
        logger.info(
            "available_tools=%s loaded_skills=%s",
            [tool.name for tool in available_tools],
            loaded,
        )

    def _handle_no_tool_calls(self, state: ReActState) -> Command:
        """
        处理没有工具调用的情况
        """
        logger.info(
            "handle_no_tool_calls step=%s retry=%s -> %s",
            state.step_count,
            state.retry_count,
            state.retry_count + 1,
        )
        return self._router(state, {
            "task_status": "no_tool_calls",
            "step_count": state.step_count + 1,
            "retry_count": state.retry_count + 1,
            "observations": [
                ObservationBuilder.build(ToolResult(
                    name="",
                    success=False,
                    result=None,
                    error="Action stage did not generate executable tool calls.",
                    tool_call_id="",
                ))
            ],
        })

    def _handle_invalid_tools(
        self,
        invalid_tools: list[str],
        state: ReActState,
        available_tools: list[ToolDefinition] | None = None,
    ) -> Command:
        """
        处理非法工具的情况
        """
        available_names = (
            [tool.name for tool in available_tools] if available_tools is not None else None
        )
        logger.warning(
            "handle_invalid_tools invalid=%s available=%s retry=%s -> %s",
            invalid_tools,
            available_names,
            state.retry_count,
            state.retry_count + 1,
        )
        return self._router(state, {
            "task_status": "no_tool_calls",
            "reasoning": f"Invalid tools selected: {', '.join(invalid_tools)}",
            "tool_state": ToolState(tool_calls=[]),
            "step_count": state.step_count + 1,
            "retry_count": state.retry_count + 1,
        })

    def _handle_ready(self, tool_calls: list[ToolCall], state: ReActState) -> Command:
        """
        处理ready状态
        """
        logger.info(
            "handle_ready tools=%s ids=%s",
            [tc.name for tc in tool_calls],
            [tc.tool_call_id for tc in tool_calls],
        )
        return self._router(state, {
            "task_status": "in_progress",
            "tool_state": ToolState(tool_calls=tool_calls),
            "trajectory": [
                self._build_tool_call_message(tool_calls)
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
        logger.debug("updated tool_calls=%s", updated_tool_calls)

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

    def _router(self, state: ReActState, update_state: dict) -> Command:
        next_node = self._select_node(state, update_state)
        logger.info("route action -> %s", next_node)
        return Command(update=update_state, goto=next_node)

    def _select_node(self, state: ReActState, update_state: dict) -> Literal["HITL", "tool", "reason"]:
        task_status = update_state.get("task_status", state.task_status)
        tool_state = update_state.get("tool_state", state.tool_state)
        tool_calls = tool_state.tool_calls
        tool_names = [tc.name for tc in tool_calls]

        if task_status == "human_in_the_loop":
            next_node: Literal["HITL", "tool", "reason"] = "HITL"
        elif tool_calls:
            next_node = "tool"
        else:
            next_node = "reason"

        logger.info(
            "select_node task_status=%s tool_calls=%s -> %s",
            task_status,
            tool_names,
            next_node,
        )
        return next_node

    def _build_tool_call_message(self, tool_calls: list[ToolCall]) -> Message:
        """
        构建包含 tool_calls 的 Message
        """
        return Message(
            role=Role.ASSISTANT,
            tool_calls=tool_calls,
        )

    def _get_invalid_tools(
        self,
        tool_calls: list[ToolCall],
        available_tools: list[ToolDefinition] | None = None,
    ) -> list[str]:
        """
        获取非法工具
        """
        valid_names = self._valid_tool_names(available_tools)
        return [
            tc.name
            for tc in tool_calls
            if tc.name not in valid_names
        ]

    def _valid_tool_names(
        self,
        available_tools: list[ToolDefinition] | None = None,
    ) -> set[str]:
        """
        获取合法工具名称列表
        """
        return {
            tool.name
            for tool in available_tools if available_tools is not None
        } if available_tools is not None else {
            tool.name
            for tool in self._tool_list
        }

    def _build_fields(
        self,
        tool_calls: list[ToolCall],
        missing_parameters_map: dict[str, list[str]],
    ) -> dict[str, list[InterruptField]]:
        """
        按 tool_call_id 构建信息补全字段，避免多工具同名缺参互相覆盖。
        """
        fields_by_call: dict[str, list[InterruptField]] = {}
        for tool_call in tool_calls:
            missing_parameters = missing_parameters_map.get(tool_call.tool_call_id, [])
            if not missing_parameters:
                continue
            tool_definition = get_tool_definition(self._tool_list, tool_call.name)
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
        values = response.result.get("values") or {}
        updated_tool_calls = []
        for tool_call in tool_calls:
            per_call = values.get(tool_call.tool_call_id)
            if isinstance(per_call, dict):
                for key in tool_call.missing_args:
                    if key in per_call:
                        tool_call.args[key] = per_call[key]

            tool_call.missing_args = []
            updated_tool_calls.append(tool_call)
        return updated_tool_calls

    def _get_missing_parameters(self, tool_calls: list[ToolCall]) -> dict[str, list[str]]:
        """
        获取缺失的参数
        """
        missing_params_map = {}
        for tool_call in tool_calls:
            definition = get_tool_definition(
                self._tool_list,
                tool_call.name,
            )

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
            definition = get_tool_definition(self._tool_list, tool_call.name)

            if definition and definition.requires_approval:
                return True

        return False

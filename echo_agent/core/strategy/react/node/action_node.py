from typing import Any, Literal

from langgraph.runtime import Runtime
from langgraph.types import Command

from .....common import get_logger
from ....app import Application
from .....prompt import PromptAssembler, PromptLoader
from .....utils import MessageAdapter, update_agent_result
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....model.agent import AgentMode
from ....model.step import Step, StepStatus
from ....model.hitl import HITLInput, HITLInteraction, HITLOutput, HITLType
from ....model.message import Message, append_messages
from ....model.skill import SkillStatus
from ....model.tool import ToolCall, ToolState
from ....runtime.runtime_config import RuntimeConfig
from ....runtime.context import ContextCompactor
from ....tool import ToolDefinition, ToolGateWay, ToolRegistry, ToolType
from ....tool.exception import ToolAuthorizationError
from ....tool.utils import get_tool_definition, to_openai_tool_json_schema
from ..schema import ReActContext, ReActState, build_react_history

logger = get_logger("react.action")


class ActionNode(Node):
    """
    Action Node：动作节点

    节点职责：
        1. 根据 Reason 节点的 tool_list 确定本次工具范围
        2. 生成工具调用及工具参数
        3. 工具参数校验
        4. HITL 交互处理
        5. 工具执行前的业务 Step 预算检查与计数
    """
    def __init__(self, name: str, llm_config: LLMConfig):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/action.md")
        self._tool_gateway = ToolGateWay()
        self._context_compactor = ContextCompactor(llm_config) # 上下文压缩器

    def run(self, state: ReActState, runtime: Runtime[ReActContext]) -> Command:
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)
        # 获取运行时信息
        runtime_config = RuntimeConfig.get_runtime_config()
        # 获取tool registry
        tool_registry = Application.get_application().get_agent(runtime_config.agent_id).tool_registry
        # 已存在待处理的 HITL 请求或响应，仅允许通过 HITL 恢复流程继续
        if state.hitl_state.request or state.hitl_state.response:
            return self._handle_hitl(state, runtime.context, runtime_config.agent_mode, tool_registry)

        # 生成tool_list
        bound_tools = self._resolve_tools(state, runtime.context, runtime_config.agent_mode, tool_registry)
        if not bound_tools:
            return self._handle_blocked([], state)
        tool_list = to_openai_tool_json_schema(bound_tools)

        # 判断是否需要压缩上下文
        if self._context_compactor.should_compact(state.context):
            compacted_context, token_usage = self._context_compactor.compress(state.context)
            logger.info("context compacted | tokens=%s", token_usage.total_tokens)
            state.context = compacted_context
            update_agent_result(runtime.context, '上下文已压缩', token_usage) 

        # 调用llm
        step = Step()
        state.steps = [*state.steps, step]
        state.current_step = step
        try:
            response = self._llm_client.invoke(
                prompt=self._build_prompt(runtime.context, runtime_config.agent_mode, tool_list),
                user_input={
                    "assessment": state.assessment,
                    "next_action": state.next_action,
                },
                history=self._build_history(state, runtime.context),
                tool_list=tool_list,
                config=runtime_config.to_llm_runnable_config(),
            )
            step.token_usage = response.token_usage.model_copy(deep=True)
        except Exception as exc:
            step.status = StepStatus.FAILED
            step.error = str(exc)
            logger.warning("action step failed: %s", exc)
            return self._router(state, {
                "task_status": "failed",
                "tool_states": {},
            })

        update_agent_result(runtime.context, response.text, response.token_usage)
        return self._route_after_tool_selection(state, runtime.context, runtime_config.agent_mode, tool_registry, response.tool_calls, bound_tools)

    async def arun(self, state: ReActState, runtime: Runtime[ReActContext]) -> Command:
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)
        # 获取运行时信息
        runtime_config = RuntimeConfig.get_runtime_config()
        # 获取tool registry
        tool_registry = Application.get_application().get_agent(runtime_config.agent_id).tool_registry
        # 已存在待处理的 HITL 请求或响应，仅允许通过 HITL 恢复流程继续
        if state.hitl_state.request or state.hitl_state.response:
            return self._handle_hitl(state, runtime.context, runtime_config.agent_mode, tool_registry)

        # 生成tool_list
        bound_tools = self._resolve_tools(state, runtime.context, runtime_config.agent_mode, tool_registry)
        if not bound_tools:
            return self._handle_blocked([], state)
        tool_list = to_openai_tool_json_schema(bound_tools)

        # 判断是否需要压缩上下文
        if self._context_compactor.should_compact(state.context):
            compacted_context, token_usage = await self._context_compactor.acompress(state.context)
            logger.info("context compacted | tokens=%s", token_usage.total_tokens)
            state.context = compacted_context
            update_agent_result(runtime.context, '上下文已压缩', token_usage) 

        # 调用llm
        step = Step()
        state.steps = [*state.steps, step]
        state.current_step = step
        try:
            response = await self._llm_client.ainvoke(
                prompt=self._build_prompt(runtime.context, runtime_config.agent_mode, tool_list),
                user_input={
                    "assessment": state.assessment,
                    "next_action": state.next_action,
                },
                history=self._build_history(state, runtime.context),
                tool_list=tool_list,
                config=runtime_config.to_llm_runnable_config(),
            )
            step.token_usage = response.token_usage.model_copy(deep=True)
        except Exception as exc:
            step.status = StepStatus.FAILED
            step.error = str(exc)
            logger.warning("action step failed: %s", exc)
            return self._router(state, {
                "task_status": "failed",
                "tool_states": {},
            })
       
        update_agent_result(runtime.context, response.text, response.token_usage)
        return self._route_after_tool_selection(state, runtime.context, runtime_config.agent_mode, tool_registry, response.tool_calls, bound_tools)

    def _route_after_tool_selection(self, state: ReActState, context: ReActContext, agent_mode: AgentMode, tool_registry: ToolRegistry, tool_calls: list[ToolCall] | None, bound_tools: list[ToolDefinition]) -> Command:
        if not tool_calls:
            return self._handle_no_tool_calls(state)

        # 在任何参数校验、审批和字典构造前拒绝重复调用 ID。
        try:
            self._build_tool_states(tool_calls)
        except ValueError as exc:
            logger.warning("invalid tool call IDs: %s", exc)
            self._update_current_step(state, StepStatus.FAILED, tool_calls=[], error=str(exc))
            return self._router(state, {
                "task_status": "invalid_tools",
                "tool_states": {},
            })

        # 判断是否存在非法工具
        invalid_names = self._get_invalid_tools(tool_calls, bound_tools)
        if invalid_names:
            logger.warning(
                "invalid_tools selected=%s invalid=%s available=%s",
                [tc.name for tc in tool_calls],
                invalid_names,
                [tool.name for tool in bound_tools],
            )
            invalid_tools = [tc for tc in tool_calls if tc.name in invalid_names]
            return self._handle_invalid_tools(invalid_tools, state)

        # 检查工具权限
        for tool_call in tool_calls:
            if self._authorize_tool(bound_tools, tool_call, agent_mode) is False:
                logger.warning(
                    "tool_call blocked=%s tool=%s",
                    tool_call.name,
                    tool_call.args,
                )
                return self._handle_blocked(tool_calls, state)

        # 判断是否存在缺失参数
        missing_parameters_map = self._get_missing_parameters(tool_registry, tool_calls)
        if missing_parameters_map:
            return self._handle_missing_parameters(state, tool_registry, tool_calls, missing_parameters_map)

        # 判断是否需要人工审核
        if self._need_approval(tool_registry, tool_calls):
            return self._handle_approval(state, tool_calls)

        return self._handle_ready(tool_calls, state, context, tool_registry)

    def _build_prompt(self, context: ReActContext, agent_mode: AgentMode, tool_list: list[Any]) -> str:
        """构建系统提示词"""
        resources = context.resources
        return PromptAssembler.assemble(
            agent_prompt=resources.system_prompt if resources else None,
            system_prompt=self._prompt,
            agent_mode=agent_mode,
            tool_list=tool_list,
            skill_frontmatter_list=resources.skill_frontmatter_list if resources else None,
            active_skills=context.active_skills,
        )

    def _build_history(self, state: ReActState, context: ReActContext | None = None) -> list[Message]:
        """构建跨轮会话历史与本轮执行轨迹"""
        if context is None:
            raise ValueError("ReActContext is required for ActionNode")
        return build_react_history(state.context)

    def _authorize_tool(self, tool_definitions: list[ToolDefinition], tool_call: ToolCall, mode: AgentMode) -> bool:
        """检查工具权限"""
        definition = get_tool_definition(tool_definitions, tool_call.name)
        if definition is None:
            return False
        try:
            self._tool_gateway.authorize(definition, mode)
            return True
        except ToolAuthorizationError:
            return False

    def _handle_hitl(self, state: ReActState, context: ReActContext, agent_mode: AgentMode, tool_registry: ToolRegistry) -> Command:
        """ 处理 HITL 恢复场景"""
        hitl_state = state.hitl_state
        # HITL 响应为空
        if hitl_state.response is None or state.current_step is None:
            logger.warning("tool_calls present without hitl response; refuse execution | tools=%s", [item.tool_call.name for item in state.tool_states.values()])
            # 更新运行步状态
            self._update_current_step(state, StepStatus.FAILED, error="HITL response or current step not found.")
            return self._router(state, {
                "task_status": "failed",
                "tool_states": {},
                "hitl_state": HITLInteraction(request=None, response=None),
            })

        # HITL 被取消
        if hitl_state.response.status == "cancelled":
            # 更新运行步状态
            self._update_current_step(state, StepStatus.CANCELLED)
            return self._router(state, {
                "task_status": "cancelled",
                "tool_states": {},
                "hitl_state": HITLInteraction(request=None, response=None),
            })

        # 处理 HITL 请求
        if hitl_state.request:
            if hitl_state.request.type == HITLType.INPUT: # INPUT 类型
                return self._handle_hitl_input(state, context, agent_mode, tool_registry, hitl_state)
            if hitl_state.request.type == HITLType.APPROVAL: # APPROVAL 类型
                return self._handle_hitl_approval(state, context, agent_mode, tool_registry, hitl_state)

        # 更新运行步状态
        self._update_current_step(state, StepStatus.FAILED, error="HITL request missing or unsupported.")
        return self._router(state, {
            "task_status": "failed",
            "tool_states": {},
            "hitl_state": HITLInteraction(request=None, response=None),
        })

    def _handle_hitl_input(self, state: ReActState, context: ReActContext, agent_mode: AgentMode, tool_registry: ToolRegistry, hitl_interaction: HITLInteraction) -> Command:
        """处理 HITL INPUT 类型"""
        # 填充工具参数
        tool_calls = self._fill_tool_calls(self._get_tool_calls(state.tool_states), hitl_interaction.response)
        # 参数校验
        missing_map = self._get_missing_parameters(tool_registry, tool_calls)
        if missing_map:
            return self._handle_missing_parameters(state, tool_registry, tool_calls, missing_map)
        
        # 参数完整，清理 missing_args
        tool_calls = self._mark_missing_parameters(tool_calls, {})
        # 判断是否需要人工审核
        if self._need_approval(tool_registry, tool_calls):
            return self._handle_approval(state, tool_calls)
        
        return self._handle_ready(tool_calls, state, context, tool_registry, clear_hitl=True)

    def _handle_hitl_approval(self, state: ReActState, context: ReActContext, agent_mode: AgentMode, tool_registry: ToolRegistry, hitl_interaction: HITLInteraction) -> Command:
        """处理 HITL APPROVAL 类型"""
        approved = (hitl_interaction.response.result or {}).get("approved")
        if approved is not True:
            # 更新运行步状态
            self._update_current_step(state, StepStatus.CANCELLED)
            return self._router(state, {
                "task_status": "cancelled",
                "tool_states": {},
                "hitl_state": HITLInteraction(request=None, response=None),
            })
        tool_calls = self._get_tool_calls(state.tool_states)
        return self._handle_ready(tool_calls, state, context, tool_registry, clear_hitl=True)

    def _handle_no_tool_calls(self, state: ReActState) -> Command:
        """处理没有工具调用的情况"""
        # 更新运行步状态
        self._update_current_step(state, StepStatus.FAILED, tool_calls=[], error="No tool calls selected.")
        return self._router(state, {
            "task_status": "no_tool_calls", # 没有工具调用
            "retry_count": state.retry_count + 1,
        })

    def _handle_invalid_tools(self, invalid_tools: list[ToolCall], state: ReActState) -> Command:
        """处理非法工具的情况"""
        # 更新运行步状态
        self._update_current_step(state, StepStatus.FAILED, tool_calls=invalid_tools, error="Invalid tools selected.")
        return self._router(state, {
            "task_status": "invalid_tools", # 非法工具
            "tool_states": self._build_tool_states(invalid_tools), # 传入非法工具
            "retry_count": state.retry_count + 1,
        })

    def _handle_blocked(self, tool_calls: list[ToolCall], state: ReActState) -> Command:
        """处理阻塞状态"""
        # 更新运行步状态
        self._update_current_step(state, StepStatus.FAILED, tool_calls=tool_calls, error="Blocked by tool authorization.")
        return self._router(state, {
            "task_status": "blocked", # 工具权限验证失败
            "tool_states": self._build_tool_states(tool_calls), # 传入阻塞工具
            "retry_count": state.retry_count + 1,
        })

    def _handle_ready(self, tool_calls: list[ToolCall], state: ReActState, context: ReActContext, tool_registry: ToolRegistry, clear_hitl: bool = False) -> Command:
        """统一的工具执行入口；在进入 ToolNode 前检查并更新 Step"""
        if not tool_calls:
            return self._handle_no_tool_calls(state)
        try:
            increment = self._get_step_increment(tool_calls, tool_registry)
        except ValueError as exc:
            logger.warning("tool selection invalid before execution: %s", exc)
            return self._handle_invalid_tools(tool_calls, state)

        next_step_count = state.step_count + increment
        if next_step_count > context.max_steps:
            logger.warning(
                "action budget exhausted | current=%s increment=%s max=%s tools=%s",
                state.step_count,
                increment,
                context.max_steps,
                [tool_call.name for tool_call in tool_calls],
            )
            # 禁止执行，交由 Reason 根据 failed 状态路由 Final
            self._update_current_step(state, StepStatus.FAILED, tool_calls=tool_calls, error="Action step budget exhausted.")
            update_state: dict[str, Any] = {
                "task_status": "failed",
                "tool_states": {},
            }
            # 清除 HITL 状态
            if clear_hitl:
                update_state["hitl_state"] = HITLInteraction(request=None, response=None)
            return self._router(state, update_state)

        # 更新运行步状态
        self._update_current_step(state, StepStatus.PENDING, tool_calls=tool_calls)
        # 更新状态
        update_state = {
            "task_status": "in_progress",
            "step_count": next_step_count,
            "tool_states": self._build_tool_states(tool_calls),
            "trajectory": [MessageAdapter.to_tool_call_message(tool_calls)],
        }
        # 清除 HITL 状态
        if clear_hitl:
            update_state["hitl_state"] = HITLInteraction(request=None, response=None)
        return self._router(state, update_state)

    def _handle_missing_parameters(self, state: ReActState, tool_registry: ToolRegistry, tool_calls: list[ToolCall], missing_parameters_map: dict[str, list[str]]) -> Command:
        """
        处理缺少参数状态
        """
        updated_tool_calls = self._mark_missing_parameters(tool_calls, missing_parameters_map)

        # 构建 HITL 请求（fields / resume values 均按 tool_call_id 分组，避免多工具同名缺参串写）
        fields_by_call = self._build_fields(tool_registry, updated_tool_calls, missing_parameters_map)
        request = HITLInput(
            type=HITLType.INPUT,
            description="Please provide the missing parameters. ",
            payload={
                "fields": {
                    tool_call_id: fields
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

        # 更新运行步状态
        self._update_current_step(state, StepStatus.WAITING, tool_calls=updated_tool_calls)
        # 更新状态
        update_state = {
            "task_status": "human_in_the_loop",
            "tool_states": self._build_tool_states(updated_tool_calls),
            "hitl_state": HITLInteraction(request=request, response=None),
        }
        return self._router(state, update_state)

    def _handle_approval(self, state: ReActState, tool_calls: list[ToolCall]) -> Command:
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

        # 更新运行步状态
        self._update_current_step(state, StepStatus.WAITING, tool_calls=tool_calls)
        # 更新状态
        update_state = {
            "task_status": "human_in_the_loop",
            "tool_states": self._build_tool_states(tool_calls),
            "hitl_state": HITLInteraction(request=request, response=None),
        }
        return self._router(state, update_state)

    @staticmethod
    def _build_tool_states(tool_calls: list[ToolCall]) -> dict[str, ToolState]:
        tool_states: dict[str, ToolState] = {}
        for tool_call in tool_calls:
            call_id = tool_call.tool_call_id
            if call_id in tool_states:
                raise ValueError(f"Duplicate tool_call_id: {call_id}")
            tool_states[call_id] = ToolState(tool_call=tool_call.model_copy(deep=True))
        return tool_states

    @staticmethod
    def _get_tool_calls(tool_states: dict[str, ToolState]) -> list[ToolCall]:
        return [tool_state.tool_call for tool_state in tool_states.values()]

    @staticmethod
    def _update_current_step(state: ReActState, status: StepStatus, tool_calls: list[ToolCall] | None = None, error: str | None = None) -> None:
        """更新当前运行步"""
        step = state.current_step
        if step is None:
            return

        step.status = status
        if tool_calls is not None:
            step.content_type = "tool"
            step.content = ActionNode._build_tool_states(tool_calls)
        if error is not None:
            step.error = error

# region: Router Functions
    def _router(self, state: ReActState, update_state: dict) -> Command:
        # 轨迹增量同时写入工作消息；完整轨迹不参与历史重建。
        messages = update_state.get("trajectory")
        if messages:
            context = state.context.model_copy(deep=True)
            context.messages = append_messages(context.messages, messages)
            state.context = context
        next_node = self._select_node(state, update_state)
        logger.info("route action -> %s | status=%s", next_node, update_state.get("task_status", state.task_status))
        
        step = state.current_step
        if step is not None:
            snapshot = step.model_copy(deep=True)
            if any(item.id == step.id for item in state.steps):
                state.steps = [snapshot if item.id == step.id else item for item in state.steps]
            else:
                state.steps = [*state.steps, snapshot]
            if step.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.CANCELLED):
                state.current_step = None
        
        update_state["steps"] = state.steps
        update_state["current_step"] = state.current_step
        update_state["context"] = state.context
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

    def _get_invalid_tools(self, tool_calls: list[ToolCall], bound_tools: list[ToolDefinition] | None = None) -> list[str]:
        """
        获取非法工具
        """
        valid_names = self._valid_tool_names(bound_tools)
        return [
            tc.name
            for tc in tool_calls
            if tc.name not in valid_names
        ]

    def _valid_tool_names(self, bound_tools: list[ToolDefinition] | None = None) -> set[str]:
        """获取合法工具名称列表"""
        return {tool.name for tool in bound_tools}

    def _build_fields(self, tool_registry: ToolRegistry, tool_calls: list[ToolCall], missing_parameters_map: dict[str, list[str]]) -> dict[str, list[dict[str, str]]]:
        """按 tool_call_id 构建信息补全字段，避免多工具同名缺参互相覆盖"""
        fields_by_call: dict[str, list[dict[str, str]]] = {}
        for tool_call in tool_calls:
            missing_parameters = missing_parameters_map.get(tool_call.tool_call_id, [])
            if not missing_parameters:
                continue
            tool_definition = tool_registry.get(tool_call.name)
            fields_by_call[tool_call.tool_call_id] = [
                {   
                    "name": param,
                    "description": (
                        tool_definition.get_parameter_description(param)
                        if tool_definition
                        else param
                    ),
                }
                for param in missing_parameters
            ]
        return fields_by_call

    def _mark_missing_parameters(self, tool_calls: list[ToolCall], missing_parameters_map: dict[str, list[str]]) -> list[ToolCall]: 
        """标记待补充参数"""
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

            updated_tool_calls.append(tool_call)
        return updated_tool_calls

    def _get_missing_parameters(self, tool_registry: ToolRegistry, tool_calls: list[ToolCall]) -> dict[str, list[str]]:
        """获取缺失的参数"""
        missing_params_map = {}
        for tool_call in tool_calls:
            definition = tool_registry.get(tool_call.name)
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
        """判断参数值是否缺失"""
        if value is None:
            return True

        if isinstance(value, str):
            return not value.strip()
        return False

    def _need_approval(self, tool_registry: ToolRegistry, tool_calls: list[ToolCall]) -> bool:
        """判断是否需要人工审核"""
        for tool_call in tool_calls:
            definition = tool_registry.get(tool_call.name)
            if definition and definition.requires_approval:
                return True

        return False

    def _resolve_tools(self, state: ReActState, context: ReActContext, agent_mode: AgentMode, tool_registry: ToolRegistry) -> list[ToolDefinition]:
        """"根据reasonnode生成的tool_list，解析出可用的工具列表"""
        tool_names = set(state.tool_list)

        # 获取active skill中的可用工具
        for skill in context.active_skills.values():
            if skill.status != SkillStatus.LOADED:
                continue
            allowed_tools= skill.package.frontmatter.allowed_tools
            if allowed_tools:
                tool_names.update(allowed_tools)

        if not tool_names:
            return []
        tools = tool_registry.resolve_tools(list(tool_names))

        # 根据 AgentMode 过滤工具
        return self._tool_gateway.filter(tools, agent_mode)

    def _get_step_increment(self, tool_calls: list[ToolCall], tool_registry: ToolRegistry,) -> int:
        """按执行批次计数：存在非 WORKFLOW 工具则增加一次业务 Step"""
        increment = 0
        for tool_call in tool_calls:
            definition = tool_registry.get(tool_call.name)
            if definition is None:
                raise ValueError(f"Tool is not registered: {tool_call.name}")
            if definition.type != ToolType.WORKFLOW:
                increment = 1
        return increment

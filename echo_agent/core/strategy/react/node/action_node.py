from typing import Any, Literal

from langchain_core.messages import AIMessage
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....tool import ToolCall
from ....tool.utils import get_tool_definition, to_tool_list
from ..schema import ReActContext, ReActState
from ....runtime.interrupt import InformationCollectionRequest, InformationCollectionResponse, InterruptField, InterruptType


class ActionResult(BaseModel):
    """
    Action节点结构化输出

    参数：
        status: 状态
            ready: 可执行工具调用已生成
            missing_parameters: 缺少参数
        missing_parameters: 缺失的参数名称列表，当 status 为 missing_parameters 时有效，否则为空列表
    """
    status: Literal["ready", "missing_parameters"] = Field(
        description=(
            "Validation result of the generated native tool calls.\n\n"

            "'ready': "
            "All generated tool calls contain all required arguments "
            "and are ready for immediate execution.\n\n"

            "'missing_parameters': "
            "One or more generated tool calls are missing required "
            "arguments and cannot be executed until additional information "
            "is provided."
        )
    )
    missing_parameters: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "Missing required arguments grouped by tool_call_id.\n\n"

            "The key is the identifier of the generated tool call "
            "(tool_call_id).\n"

            "The value is a list of missing argument names for that "
            "specific tool call.\n\n"

            "Example:\n"
            "{\n"
            "  \"call_xxx\": [\"order_id\", \"reason\"]\n"
            "}\n\n"

            "Return an empty object when status is 'ready'."
        ),
    )


class ActionNode(Node):
    """
    Action Node：动作节点
    """
    def __init__(self, name: str, llm_config: LLMConfig, tool_list: list[dict[str, Any]] | None = None):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/action.md")
        self._tool_json_schema = tool_list or []
        self._tool_list = to_tool_list(self._tool_json_schema)

    def run(self, state: ReActState, context: ReActContext | None = None) -> dict:
        """
        Run the node
        """
        print(f"[ReAct][action] enter | step={state.step_count} retry={state.retry_count}")

        # 如果存在工具调用，则跳过工具选择
        print(f"[ReAct][action] state.tool_calls={state.tool_calls}")
        if state.tool_calls:
            print("[ReAct][action] existing tool_calls detected, skip tool selection")
            return {
                "task_status": "in_progress",
                "tool_calls": state.tool_calls,
            }

        # 构建输入
        input = {
            "reasoning": state.reasoning,
        }
        # 选择工具
        response = self._llm_client.invoke(
            prompt=self._prompt,
            user_input=input,
            history=state.messages,
            tool_list=self._tool_json_schema,
        )
        print(f"[ReAct][action] tool_selection_response={response}")
        print(f"[ReAct][action] tool_selection_response.tool_calls={response.tool_calls}")

        # 没有工具调用，则返回 no_tool_calls 状态
        if not response.tool_calls:
            return self._handle_no_tool_calls(state)

        tool_calls = response.tool_calls
        # 工具合法性校验
        invalid_tools = self._get_invalid_tools(tool_calls)
        if invalid_tools:
            return self._handle_invalid_tools(invalid_tools, state)
        # 参数校验
        missing_parameters_map = self._get_missing_parameters(tool_calls)
        if missing_parameters_map:
            return self._handle_missing_parameters(tool_calls, missing_parameters_map, state)

        return self._handle_ready(tool_calls, state)

    def _handle_no_tool_calls(self, state: ReActState) -> dict:
        """
        处理没有工具调用的情况
        """
        return {
            "task_status": "no_tool_calls",
            "step_count": state.step_count + 1,
            "retry_count": state.retry_count + 1,
            "observations":[
                "Action stage did not generate executable tool calls."
            ]
        }

    def _handle_invalid_tools(self, invalid_tools: list[str], state: ReActState) -> dict:
        """
        处理非法工具的情况
        """
        return {
            "task_status": "failed",
            "reasoning": f"Invalid tools selected: {', '.join(invalid_tools)}",
            "step_count": state.step_count + 1,
            "retry_count": state.retry_count + 1,
        }

    def _handle_ready(self, tool_calls: list[ToolCall], state: ReActState) -> dict:
        """
        处理ready状态
        """
        return {
            "task_status": "in_progress",
            "tool_calls": tool_calls,
            "messages": [
                self._build_tool_call_message(tool_calls)
            ],
            "step_count": state.step_count + 1,
        }

    def _handle_missing_parameters(self, tool_calls: list[ToolCall], missing_parameters_map: dict[str, list[str]], state: ReActState) -> dict:
        """
        处理缺少参数状态
        """
        updated_tool_calls = self._mark_missing_parameters(tool_calls, missing_parameters_map)
        print(f"[ReAct][action] updated tool_calls={updated_tool_calls}")

        # 更新状态
        state.task_status = "human_in_the_loop"
        state.tool_calls = updated_tool_calls
        print(f"[ReAct][action] updated state={state}")

        # 构造 interruption request
        request = InformationCollectionRequest(
            type=InterruptType.INFORMATION_COLLECTION,
            description="Please provide the missing parameters. ",
            fields=self._build_fields(updated_tool_calls, missing_parameters_map)
        )
        print(f"[ReAct][action] interruption request={request}")

        # 触发中断
        values = interrupt(request.model_dump())
        print(f"[ReAct][action] interruption values={values}")

        # 构造 interruption response
        interruption_response = InformationCollectionResponse(**values)
        print(f"[ReAct][action] interruption response={interruption_response}")

        # 更新工具调用
        final_tool_calls = self._fill_tool_calls(updated_tool_calls, interruption_response)
        print(f"[ReAct][action] final tool_calls={final_tool_calls}")

        return {
            "task_status": "in_progress",
            "tool_calls": final_tool_calls ,
            "messages": [
                self._build_tool_call_message(final_tool_calls)
            ],
            "step_count": state.step_count + 1,
        }

    def _build_tool_call_message(self, tool_calls: list[ToolCall]) -> AIMessage:
        """
        构建包含 tool_calls 的 AIMessage
        """
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": tool_call.name,
                    "args": tool_call.args,
                    "id": tool_call.tool_call_id,
                }
                for tool_call in tool_calls
            ],
        )

    def _get_invalid_tools(self, tool_calls: list[ToolCall]) -> list[str]:
        """
        获取非法工具
        """
        valid_names = self._valid_tool_names()
        return [
            tc.name
            for tc in tool_calls
            if tc.name not in valid_names
        ]

    def _valid_tool_names(self) -> set[str]:
        """
        获取合法工具名称列表
        """
        return {
            tool.name
            for tool in self._tool_list
        }

    def _build_fields(self, tool_calls: list[ToolCall], missing_parameters_map: dict[str, list[str]]) -> list[InterruptField]:
        """
        构建信息补全字段
        """
        fields = []
        for tool_call in tool_calls:
            missing_parameters = missing_parameters_map.get(tool_call.tool_call_id, [])
            # 获取工具定义
            tool_definition = get_tool_definition(self._tool_list, tool_call.name)
            for param in missing_parameters:
                fields.append(InterruptField(
                    name=param, 
                    description=tool_definition.get_parameter_description(param)
                    if tool_definition else param
                ))
        return fields

    def _mark_missing_parameters(self, tool_calls: list[ToolCall], missing_parameters_map: dict[str, list[str]]) -> list[ToolCall]: 
        """
        标记待补充参数
        """
        for tool_call in tool_calls:
            tool_call.missing_args = missing_parameters_map.get(tool_call.tool_call_id, [])
        return tool_calls

    def _fill_tool_calls(self, tool_calls: list[ToolCall], response: InformationCollectionResponse) -> list[ToolCall]:
        """
        使用 interrupt 返回值填充工具参数
        """
        for tool_call in tool_calls:
            for key, value in response.values.items():
                if key in tool_call.missing_args:
                    tool_call.args[key] = value
            
            tool_call.missing_args = []
        return tool_calls

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

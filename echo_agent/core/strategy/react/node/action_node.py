from typing import Any, Literal

from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig, LLMResult
from ....tool import ToolCall
from ..schema import ReActContext, ReActState


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

    流程：
        Step-1: 选择工具
        Step-2: 验证工具参数是否齐全
            如果参数不齐全，则返回 human_in_the_loop 状态，并等待用户输入
            如果参数齐全，则返回 ready 状态，并执行工具
    """
    def __init__(self, name: str, llm_config: LLMConfig, tool_list: list[dict[str, Any]] | None = None):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._tool_selection_prompt = PromptLoader.load("core/strategy/react/prompt/tool_selection.md")
        self._tool_validation_prompt = PromptLoader.load("core/strategy/react/prompt/tool_validation.md")
        self._tool_list = tool_list or []

    def run(self, state: ReActState, context: ReActContext | None = None) -> dict:
        """
        Run the node
        """
        print(f"[ReAct][action] enter | step={state.step_count} retry={state.retry_count}")

        # 构建输入
        input = self._build_input(state)
        # Step-1: 选择工具
        tool_selection_response = self._llm_client.invoke(
            prompt=self._tool_selection_prompt,
            user_input=input,
            history=state.messages,
            tool_list=self._tool_list,
        )
        print(f"[ReAct][action] tool_selection_response={tool_selection_response}")
        print(f"[ReAct][action] tool_selection_response.tool_calls={tool_selection_response.tool_calls}")
        # 没有工具调用，则返回完成状态
        if not tool_selection_response.tool_calls:
            return self._handle_no_tool_calls(state)

        # Step-2: 验证工具参数是否齐全, 本步骤不进行工具调用
        tool_calls = [
            tc.model_dump()
            for tc in tool_selection_response.tool_calls
        ]
        validation_input = {
            "input": state.input,
            "reasoning": state.reasoning,
            "tool_calls": tool_calls
        }
        tool_validation_response = self._llm_client.invoke_structured(
            prompt=self._tool_validation_prompt,
            user_input=validation_input,
            history=state.messages,
            schema=ActionResult,
            strict=True
        )
        print(f"[ReAct][action] action_validation_response={tool_validation_response}")
        print(f"[ReAct][action] action_validation_response.structured={tool_validation_response.structured}")

        # 处理结果
        return self._handle_result(tool_selection_response, tool_validation_response, state)

    def _build_input(self, state: ReActState) -> dict:
        """
        Build the input
        """
        return {
            "input": state.input,
            "messages": state.messages,
            "reasoning": state.reasoning,
        }

    def _handle_no_tool_calls(self, state: ReActState) -> dict:
        """
        处理没有工具调用的情况
        """
        return {
            "task_status": "completed",
            "reasoning": "No executable tool calls required.",
            "step_count": state.step_count + 1,
        }

    def _handle_result(self, tool_selection_response: LLMResult, action_validation_response: LLMResult, state: ReActState) -> dict:
        """
        Handle the result
        """
        # 验证工具调用是否合法
        tool_calls = tool_selection_response.tool_calls
        invalid_tools = self._get_invalid_tools(tool_calls)
        # 有非法工具，则返回失败，重试次数加1
        if invalid_tools:
            return {
                "task_status": "failed",
                "reasoning": f"Invalid tools selected: {', '.join(invalid_tools)}",
                "step_count": state.step_count + 1,
                "retry_count": state.retry_count + 1,
            }

        status = action_validation_response.structured.status
        print(f"[ReAct][action] status={status}")

        result: dict = {}
        if status == "ready":# 可执行工具调用已生成
            result = self._handle_ready(tool_calls, state)
        elif status == "missing_parameters":# 缺少参数
            result = self._handle_missing_parameters(tool_calls, action_validation_response, state)

        return result

    def _handle_ready(self, tool_calls: list[ToolCall], state: ReActState) -> dict:
        """
        处理ready状态
        """
        # 没有工具调用，则返回失败，重试次数加1
        if not tool_calls:
            return {
                "task_status": "failed",
                "reasoning": "Action marked ready, but no tool calls generated.",
                "step_count": state.step_count + 1,
                "retry_count": state.retry_count + 1,
            }

        # 返回结果
        return {
            "task_status": "in_progress",
            "tool_calls": tool_calls,
            "messages": [
                self._build_tool_call_message(tool_calls)
            ],
            "step_count": state.step_count + 1,
        }

    def _handle_missing_parameters(self, tool_calls: list[ToolCall], response: LLMResult, state: ReActState) -> dict:
        """
        处理缺少参数状态
        """
        result = response.structured
        missing_parameters_map = result.missing_parameters
        updated_tool_calls = self._update_tool_calls(tool_calls, missing_parameters_map)
        return {
            "task_status": "human_in_the_loop",
            "tool_calls": updated_tool_calls,
            "reasoning": f"Missing required parameters: {missing_parameters_map}",
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
        """从 OpenAI tool schema 列表提取合法工具名。"""
        names: set[str] = set()
        for tool in self._tool_list:
            if "function" in tool and "name" in tool["function"]:
                names.add(tool["function"]["name"])
            elif "name" in tool:
                names.add(tool["name"])
        return names

    def _update_tool_calls(self, tool_calls: list[ToolCall], missing_parameters_map: dict[str, list[str]]) -> list[ToolCall]:
        """
        更新工具调用，添加缺少的参数
        """
        updated_tool_calls = []
        for tool_call in tool_calls:
            missing_parameters = missing_parameters_map.get(tool_call.tool_call_id, [])
            if missing_parameters:
                tool_call.missing_args = missing_parameters
            updated_tool_calls.append(tool_call)
        return updated_tool_calls

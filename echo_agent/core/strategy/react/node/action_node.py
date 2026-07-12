import json
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
            "All generated tool calls contain every required argument "
            "and can be executed immediately.\n\n"

            "'missing_parameters': "
            "One or more generated tool calls are missing required "
            "arguments that cannot be inferred from the current context "
            "or obtained from available observations."
        )
    )
    missing_parameters: list[str] = Field(
        default_factory=list,
        description=(
            "Names of missing required parameters. "
            "Leave empty when status is 'ready'."
        ),
    )


class ActionNode(Node):
    """
    Action Node：动作节点
    """
    def __init__(self, name: str, llm_config: LLMConfig, tool_list: list[dict[str, Any]] | None = None):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._tool_selection_prompt = PromptLoader.load("core/strategy/react/prompt/tool_selection.md")
        self._action_validation_prompt = PromptLoader.load("core/strategy/react/prompt/action_validation.md")
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

        # Step-2: 验证工具参数是否齐全
        if not tool_selection_response.tool_calls:
            validation_input = {
                "input": state.input,
                "reasoning": state.reasoning,
                "tool_calls": [],
                "available_tools": self._tool_list,
            }
        else:
            validation_input = {
                "input": state.input,
                "reasoning": state.reasoning,
                "tool_calls": [
                    tc.model_dump()
                    for tc in tool_selection_response.tool_calls
                ],
            }
        action_validation_response = self._llm_client.invoke_structured(
            prompt=self._action_validation_prompt,
            user_input=validation_input,
            history=state.messages,
            schema=ActionResult,
            strict=True
        )
        print(f"[ReAct][action] action_validation_response={action_validation_response}")
        print(f"[ReAct][action] action_validation_response.structured={action_validation_response.structured}")

        # 处理结果
        return self._handle_result(tool_selection_response, action_validation_response, state)

    def _build_input(self, state: ReActState) -> dict:
        """
        Build the input
        """
        return {
            "input": state.input,
            "messages": state.messages,
            "reasoning": state.reasoning,
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
        return {
            "task_status": "human_in_the_loop",
            "tool_calls": tool_calls,
            "reasoning": (
                "Missing required parameters: "
                f"{', '.join(result.missing_parameters)}"
            ),
            "missing_parameters": result.missing_parameters,
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

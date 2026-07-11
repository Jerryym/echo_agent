import json
from typing import Any, Literal

from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....tool import ToolCall
from ..schema import ReActContext, ReActState


class ActionResult(BaseModel):
    """
    Action节点结构化输出

    参数：
        action_status: 动作状态
            ready: 可执行工具调用已生成
            need_information: 需要信息
            failed: 动作计划失败
        tool_calls: 工具调用
        reasoning: 动作计划的原因
    """
    action_status: Literal["ready", "need_information", "failed"] = Field(
        description=(
            "Action planning result.\n"

            "'ready': "
            "Only when valid executable tool calls "
            "are generated and all required parameters "
            "are available.\n"

            "'need_information': "
            "Required user information is missing. "
            "No tool call should be generated.\n"

            "'failed': "
            "The action cannot be executed because "
            "of invalid tool selection or unrecoverable error."
        )
    )
    tool_calls: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Executable tool calls."
    )
    reasoning: str = Field(
        description="Explain why this action result was selected."
    )


class ActionNode(Node):
    """
    Action Node：动作节点
    """
    def __init__(self, name: str, llm_config: LLMConfig, tool_list: list[dict[str, Any]] | None = None):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/action.md")
        self._tool_list = tool_list if tool_list is not None else []

    def run(self, state: ReActState, context: ReActContext | None = None) -> dict:
        """
        Run the node
        """
        print(f"[ReAct][action] enter | step={state.step_count} retry={state.retry_count}")

        # 构建输入
        input = self._build_input(state)
        # 调用llm-结构化输出
        response = self._llm_client.invoke_structured(
            schema=ActionResult,
            prompt=self._prompt,
            user_input=input,
            tool_list=self._tool_list,
        )
        print(f"[ReAct][action] status={response.action_status} reasoning={response.reasoning}")
        # 处理结果
        return self._handle_result(response, state)

    def _build_input(self, state: ReActState) -> dict:
        """
        Build the input
        """
        return {
            "input": state.input,
            "messages": state.messages,
            "reasoning": state.reasoning,
        }

    def _handle_result(self, result: ActionResult, state: ReActState) -> dict:
        """
        Handle the result
        """
        print(f"[ReAct][action] status={result.action_status}")
        if result.action_status == "ready":# 可执行工具调用已生成
            return self._handle_ready(result, state)
        elif result.action_status == "need_information":# 需要信息
            return {
                "task_status": "human_in_the_loop",
                "reasoning": result.reasoning,
                "step_count": state.step_count + 1,
            }
        
        return self._handle_failed(result, state)

    def _handle_ready(self, result: ActionResult, state: ReActState) -> dict:
        """
        处理ready状态
        """
        # 没有工具调用，则返回失败，重试次数加1
        if not result.tool_calls:
            return {
                "task_status": "failed",
                "reasoning": "Action marked ready, but no tool calls generated.",
                "step_count": state.step_count + 1,
                "retry_count": state.retry_count + 1,
            }

        # 标准化工具调用
        tool_calls = self._normalize_tool_calls(result.tool_calls)
        # 获取无效工具
        invalid_tools = self._get_invalid_tools(tool_calls)
        # 有无效工具，则返回失败，重试次数加1
        if invalid_tools:
            return {
                "task_status": "failed",
                "reasoning": f"Action failed because invalid tools were generated: {invalid_tools}",
                "step_count": state.step_count + 1,
                "retry_count": state.retry_count + 1,
            }

        # 返回结果
        return {
            "tool_calls": tool_calls,
            "messages": [
                self._build_tool_call_message(tool_calls)
            ],
            "step_count": state.step_count + 1,
            "reasoning": result.reasoning,
        }

    def _handle_failed(self, result: ActionResult, state: ReActState) -> dict:
        """
        处理failed状态
        """
        # 返回失败，重试次数加1
        return {
            "task_status": "failed",
            "reasoning": result.reasoning,
            "step_count": state.step_count + 1,
            "retry_count": state.retry_count + 1,
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

    def _normalize_tool_calls(self, tool_calls: list[ToolCall]) -> list[ToolCall]:
        """
        标准化工具调用
        """
        seen = set()
        result = []
        for tc in tool_calls:
            key = (
                tc.name,
                json.dumps(tc.args, sort_keys=True)
            )
            if key in seen:
                continue

            seen.add(key)
            result.append(tc)

        return result

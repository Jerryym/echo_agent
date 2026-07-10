from typing import Any

from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....tool import ToolCall
from ..schema import ReActContext, ReActState


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
        # print(
        #     f"[ReAct][action] enter | step={state.step_count} retry={state.retry_count}"
        # )
        # print(f"[ReAct][action] valid_tools={self._valid_tool_names()}")

        # 构建输入
        input = self._build_input(state)
        # 调用llm
        response = self._llm_client.invoke(prompt=self._prompt, user_input=input, tool_list=self._tool_list)
        # 没有工具调用，则认为完成
        if not response.tool_calls:
            # print("[ReAct][action] no tool_calls -> is_finished=True")
            return {
                "tool_calls": [],
                "is_finished": True,
            }

        tool_info = [
            {"name": tc.name, "args": tc.args, "id": tc.tool_call_id}
            for tc in response.tool_calls
        ]
        print(f"[ReAct][action] tool_calls={tool_info}")

        # 有工具调用，则更新状态
        result = {
            "tool_calls": response.tool_calls,
            "step_count": state.step_count + 1,
        }

        # 工具不存在
        if self._has_invalid_tool(response.tool_calls):
            valid_names = self._valid_tool_names()
            invalid = [tc.name for tc in response.tool_calls if tc.name not in valid_names]
            # print(f"[ReAct][action] invalid tools: {invalid}")
            result["retry_count"] = state.retry_count + 1
            if context and state.retry_count + 1 >= context.retry_max_count:
                result["is_finished"] = True

        # print(f"[ReAct][action] return step={result.get('step_count')} "
        #       f"retry={result.get('retry_count', state.retry_count)} "
        #       f"finished={result.get('is_finished', False)}")
        return result

    def _build_input(self, state: ReActState) -> dict:
        """
        Build the input
        """
        return {
            "input": state.input,
            "messages": state.messages,
            "reasoning": state.reasoning,
        }

    def _has_invalid_tool(self, tool_calls: list[ToolCall]) -> bool:
        """
        判断工具是否存在
        """
        valid_names = self._valid_tool_names()
        return any(tool_call.name not in valid_names for tool_call in tool_calls)

    def _valid_tool_names(self) -> set[str]:
        """从 OpenAI tool schema 列表提取合法工具名。"""
        names: set[str] = set()
        for tool in self._tool_list:
            if "function" in tool and "name" in tool["function"]:
                names.add(tool["function"]["name"])
            elif "name" in tool:
                names.add(tool["name"])
        return names

from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMConfig
from ..schema import ReActContext, ReActState


class ActionNode(Node):
    """
    Action Node：动作节点
    """
    def __init__(self, name: str, llm_config: LLMConfig):
        super().__init__(name, llm_config)
        self._prompt = PromptLoader.load("strategy/react/prompt/action.md")

    def run(self, state: ReActState, context: ReActContext | None = None) -> dict:
        """
        Run the node
        """
        # 构建输入
        input = self._build_input(state)
        # 调用llm
        response = self._llm_client.invoke(prompt=self._prompt, user_input=input, tool_list=context.tool_list if context else None)
        # 更新状态
        return {
            "tool_calls": response.tool_calls,
        }

    def _build_input(self, state: ReActState) -> dict:
        """
        Build the input
        """
        return {
            "input": state.input,
            "reasoning": state.reasoning,
        }
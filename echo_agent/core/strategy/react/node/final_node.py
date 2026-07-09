from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ..schema import ReActContext, ReActState


class FinalNode(Node):
    """
    Final Node：最终节点
    """
    def __init__(self, name: str, llm_config: LLMConfig):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("strategy/react/prompt/final.md")

    def run(self, state: ReActState, context: ReActContext | None = None) -> dict:
        """
        Run the node
        """
        # 构建输入
        input = self._build_input(state)
        # 调用llm
        response = self._llm_client.invoke(prompt=self._prompt, user_input=input)
        # 更新状态
        return {
            "response": response.content,
        }

    def _build_input(self, state: ReActState) -> dict:
        """
        Build the input
        """
        return {
            "input": state.input,
            "observations": state.observations,
        }

from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ..schema import ReActContext, ReActState


class ReasonNode(Node):
    """
    Reason Node：推理节点
    """
    def __init__(self, name: str, llm_config: LLMConfig):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("strategy/react/prompt/reasoning.md")

    def run(self, state: ReActState, context: ReActContext | None = None) -> dict:
        """
        Run the node
        """
        if context and state.step_count >= context.max_steps:
            return {
                "reasoning": state.reasoning,
                "observations": [
                    "Maximum reasoning steps reached. Execution stopped."
                ],
            }

        # 构建输入
        input = self._build_input(state)
        # 调用llm
        response = self._llm_client.invoke(prompt=self._prompt, user_input=input)
        # 更新状态
        return {
            "step_count": state.step_count,
            "reasoning": response.content,
        }

    def _build_input(self, state: ReActState) -> dict:
        """
        构建输入
        """
        return {
            "input": state.input,
            "observations": state.observations + self._build_observations(state),
        }

    def _build_observations(self, state: ReActState) -> list[str]:
        """
        构建观察结果
        """
        return [
            result.content
            for result in state.tool_results
        ]

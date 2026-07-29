from langchain_core.runnables import RunnableConfig

from .....common import debug_print_messages
from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....model import Message, Role
from ..schema import ReActContext, ReActState


class FinalNode(Node):
    """
    Final Node：最终节点
    """
    def __init__(self, name: str, llm_config: LLMConfig):
        super().__init__(name, is_async=True)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/final.md")

    def run(self, state: ReActState, context: ReActContext | None = None, config: RunnableConfig | None = None) -> dict:
        """
        Run the node
        """
        print(f"[ReAct][final] enter | step={state.step_count} retry={state.retry_count}")
        debug_print_messages("[ReAct][final]", state.messages)

        # 构建输入
        input = self._build_input(state)
        # 调用llm
        response = self._llm_client.invoke(prompt=self._prompt, user_input=input, config=config)
        # 更新状态
        preview = response.content[:300]
        suffix = "..." if len(response.content) > 300 else ""
        print(f"[ReAct][final] response={preview}{suffix}")
        return {
            "response": response.content,
            "messages": [Message(role=Role.ASSISTANT, content=response.content)],
        }

    async def arun(self, state: ReActState, context: ReActContext | None = None, config: RunnableConfig | None = None) -> dict:
        """
        异步运行
        """
        print(f"[ReAct][final] enter | step={state.step_count} retry={state.retry_count}")
        debug_print_messages("[ReAct][final]", state.messages)

        # 构建输入
        input = self._build_input(state)
        # 调用llm
        response = await self._llm_client.ainvoke(prompt=self._prompt, user_input=input, config=config)
        # 更新状态
        preview = response.content[:300]
        suffix = "..." if len(response.content) > 300 else ""
        print(f"[ReAct][final] response={preview}{suffix}")
        return {
            "response": response.content,
            "messages": [Message(role=Role.ASSISTANT, content=response.content)],
        }

    def _build_input(self, state: ReActState) -> dict:
        """
        Build the input
        """
        return {
            "input": state.input,
            "messages": state.messages,
            "reasoning": state.reasoning,
            "observations": state.observations,
        }

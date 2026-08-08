from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from .....common import get_logger, log_messages
from .....prompt import PromptLoader
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....model.message import Message, Role
from ....trace import TokenUsage
from ..schema import ReActContext, ReActState

logger = get_logger("react.final")


class FinalNode(Node):
    """
    Final Node：最终节点
    """
    def __init__(self, name: str, llm_config: LLMConfig):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._prompt = PromptLoader.load("core/strategy/react/prompt/final.md")

    def run(self, state: ReActState, runtime: Runtime[ReActContext], config: RunnableConfig | None = None) -> dict:
        """
        Run the node
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)
        history = self._build_history(state, runtime.context)
        log_messages(logger, "final", history)

        # 构建输入
        input = self._build_input(state)
        # 调用llm
        response = self._llm_client.invoke(
            prompt=self._prompt,
            user_input=input,
            history=history,
            context=runtime.context,
            agent_prompt=runtime.context.agent_prompt,
            config=config,
        )
        self._accumulate_token_usage(runtime.context, response.token_usage)
        # 更新状态
        preview = response.content[:300]
        suffix = "..." if len(response.content) > 300 else ""
        logger.info("response=%s%s", preview, suffix)
        return {
            "response": response.content,
            "trajectory": [Message(role=Role.ASSISTANT, content=response.content)],
        }

    async def arun(self, state: ReActState, runtime: Runtime[ReActContext], config: RunnableConfig | None = None) -> dict:
        """
        异步运行
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)
        history = self._build_history(state, runtime.context)
        log_messages(logger, "final", history)

        # 构建输入
        input = self._build_input(state)
        # 调用llm
        response = await self._llm_client.ainvoke(
            prompt=self._prompt,
            user_input=input,
            history=history,
            context=runtime.context,
            agent_prompt=runtime.context.agent_prompt,
            config=config,
        )
        self._accumulate_token_usage(runtime.context, response.token_usage)
        # 更新状态
        preview = response.content[:300]
        suffix = "..." if len(response.content) > 300 else ""
        logger.info("response=%s%s", preview, suffix)
        return {
            "response": response.content,
            "trajectory": [Message(role=Role.ASSISTANT, content=response.content)],
        }

    def _build_history(self, state: ReActState, context: ReActContext | None = None) -> list[Message]:
        """
        构建跨轮会话历史与本轮执行轨迹。
        """
        if context is None:
            raise ValueError("ReActContext is required for FinalNode")
        return [
            *state.conversation,
            *state.trajectory,
        ]

    @staticmethod
    def _accumulate_token_usage(context: ReActContext | None, token_usage: TokenUsage) -> None:
        if context is None or context.trace is None:
            return
        context.trace.token_usage = context.trace.token_usage.add(token_usage)

    def _build_input(self, state: ReActState) -> dict:
        """
        Build the input
        """
        return {
            "task": state.task.model_dump(),
            "trajectory": state.trajectory,
            "reasoning": state.reasoning,
            "observations": state.observations,
        }

from langgraph.runtime import Runtime

from .....common import get_logger, log_messages
from .....prompt import PromptLoader
from .....utils import update_agent_result
from ....graph import Node
from ....llm import LLMClient, LLMConfig
from ....model.message import Message, Role
from ....runtime.runtime_config import RuntimeConfig
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

    def run(self, state: ReActState, runtime: Runtime[ReActContext]) -> dict:
        """
        Run the node
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)
        logger.info("observations=%s", [observation.model_dump_json() for observation in state.observations])

        history = self._build_history(state, runtime.context)
        log_messages(logger, "final", history)

        # 获取运行时信息
        runtime_config = RuntimeConfig.get_runtime_config()
        # 构建输入
        input = self._build_input(state)
        # 调用llm
        response = self._llm_client.invoke(
            prompt=self._prompt,
            user_input=input,
            history=history,
            context=runtime.context,
            agent_resources=runtime.context.resources,
            config=runtime_config.to_llm_runnable_config(),
        )
        update_agent_result(runtime.context, response.text, response.token_usage)
        return {
            "response": response.text,
            "trajectory": [Message(role=Role.ASSISTANT, content=response.text)],
        }

    async def arun(self, state: ReActState, runtime: Runtime[ReActContext]) -> dict:
        """
        异步运行
        """
        logger.info("enter | step=%s retry=%s", state.step_count, state.retry_count)
        logger.info("observations=%s", [observation.model_dump_json() for observation in state.observations])

        # 获取运行时信息
        runtime_config = RuntimeConfig.get_runtime_config()
        # 构建输入
        input = self._build_input(state)
        # 构建历史记录
        history = self._build_history(state, runtime.context)
        # 调用llm
        response = await self._llm_client.ainvoke(
            prompt=self._prompt,
            user_input=input,
            history=history,
            context=runtime.context,
            agent_resources=runtime.context.resources,
            config=runtime_config.to_llm_runnable_config(),
        )
        update_agent_result(runtime.context, response.text, response.token_usage)
        return {
            "response": response.text,
            "trajectory": [Message(role=Role.ASSISTANT, content=response.text)],
        }

# region Private Functions
    def _build_input(self, state: ReActState) -> dict:
        """
        Build the input
        """
        return {
            "task": state.task.dump_attachments(),
            "reasoning": state.reasoning,
            "observations": state.observations,
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
# endregion

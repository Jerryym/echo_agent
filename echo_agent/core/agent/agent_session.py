from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

from ...common import get_logger
from ...utils import ContextUsageCalculator, MessageAdapter
from ..graph import BaseInput
from ..llm import LLMConfig
from ..model.agent import AgentResult, AgentState
from ..model.input import UserInput
from ..model.message import Message, Role
from ..model.skill import SkillRuntimeContext
from ..runtime.algorithm import ConversationCompressor
from .agent_turn import AgentTurn

logger = get_logger("agetnt_session")


class AgentSession:
    def __init__(self, session_id: str, max_context_tokens: int, llm_config: LLMConfig):
        self._session_id: str = session_id
    
        self._state: AgentState = AgentState(session_id=session_id)
        self._results: list[AgentResult] = []
        self._current_turn: AgentTurn | None = None
        # 当前会话中活动的SKill
        self._active_skills: dict[str, SkillRuntimeContext] = {}

        # 会话最大上下文长度
        self._max_context_tokens: int = max_context_tokens
        # 会话上下文使用量
        self._context_usage: int = 0
        # 会话压缩器
        self._conversation_compressor = ConversationCompressor(llm_config, max_context_tokens)

# region 属性
    @property
    def session_id(self) -> str:
        """会话ID"""
        return self._session_id

    @property
    def state(self) -> AgentState:
        """获取Agent状态"""
        return self._state

    @property
    def active_skills(self) -> dict[str, SkillRuntimeContext]:
        """获取当前已加载的Skill"""
        return self._active_skills

    @property
    def results(self) -> list[AgentResult]:
        """获取已完成的AgentResult"""
        return self._results

    @property
    def current_turn(self) -> AgentTurn | None:
        """获取当前交互轮次信息"""
        return self._current_turn

    @property
    def context_usage(self) -> int:
        """获取当前会话上下文用量"""
        return self._context_usage
# endregion

    def start_turn(self, input: UserInput | type[BaseInput]) -> AgentTurn:
        turn = AgentTurn(
            input=input,
            result=AgentResult(),
        )
        self._current_turn = turn
        return turn

    def finish_turn(self, result: AgentResult) -> None:
        if self._current_turn is None:
            return

        self._add_result(result)
        self._current_turn = None

        # 更新上下文使用量
        self._context_usage += result.token_usage.total_tokens
        logger.info("conversation context usage | context usage=%s, ratio=%.2f", self._context_usage, self._context_usage / self._max_context_tokens)

    def clear_turn(self) -> None:
        self._current_turn = None

    def _add_result(self, result: AgentResult) -> None:
        """添加执行结果"""
        self._results.append(result)

    def before_model(self, messages: list[BaseMessage], tools: list[dict[str, Any] | BaseTool] | None = None) -> list[Message] | None:
        """模型调用前处理上下文"""
        usage = ContextUsageCalculator.calculate(messages=messages, tools=tools)
        logger.info("request context usage | tokens=%s", usage)
        compressed = self._conversation_compressor.compress(self._state.conversation, self._context_usage + usage)
        if not compressed:
            return None
        
        # 构建上下文
        updated_history = self._build_conversation_messages()
        lc_messages = MessageAdapter.to_langchain_messages(updated_history)
        # 更新会话上下文使用量
        self._context_usage = ContextUsageCalculator.calculate(messages=lc_messages)
        logger.info(f"更新会话上下文使用量: {self._context_usage}")
        return updated_history

    async def abefore_model(self, messages: list[BaseMessage], tools: list[dict[str, Any] | BaseTool] | None = None) -> list[Message] | None:
        """模型调用前处理上下文（异步）"""
        usage = ContextUsageCalculator.calculate(messages=messages, tools=tools)
        logger.info("request context usage | tokens=%s", usage)
        compressed = await self._conversation_compressor.acompress(self._state.conversation, self._context_usage + usage)
        if not compressed:
            return None
        
        # 构建上下文
        updated_history = self._build_conversation_messages()
        lc_messages = MessageAdapter.to_langchain_messages(updated_history)
        # 更新会话上下文使用量
        self._context_usage = ContextUsageCalculator.calculate(messages=lc_messages)
        logger.info(f"更新会话上下文使用量: {self._context_usage}")
        return updated_history

    def _build_conversation_messages(self) -> list[Message]:
        """构建会话消息"""
        conversation = self._state.conversation
        logger.info("conversation: %s", conversation)
        messages: list[Message] = []
        if conversation.summary is not None:
            messages.append(Message(role=Role.SYSTEM, content=conversation.summary.render()))
        messages.extend(conversation.messages)
        return messages

import json
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

from ...common import get_logger
from ...utils import ContextUsageCalculator, MessageAdapter
from ..graph import BaseInput
from ..llm import LLMConfig
from ..model.agent import AgentResult
from ..model.conversation import ConversationState
from ..model.session import SessionState
from ..model.input import UserInput
from ..model.message import Message, Role, append_messages
from ..model.skill import SkillRuntimeContext
from ..model.tool import ToolArtifact
from ..runtime.algorithm import ConversationCompressor
from .agent_turn import AgentTurn, TurnStatus

logger = get_logger("agetnt_session")


class AgentSession:
    """
    Agent 会话窗口
    """
    def __init__(self, session_id: str, max_context_tokens: int, llm_config: LLMConfig):
        self._session_id: str = session_id
    
        self._state: SessionState = SessionState()
        self._turns: list[AgentTurn] = []
        self._current_turn: AgentTurn | None = None

        # 当前会话中活动的SKill
        self._active_skills: dict[str, SkillRuntimeContext] = {}
        # 当前会话中工具调用结果
        self._tool_artifacts: dict[str, ToolArtifact] = {}

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
    def state(self) -> SessionState:
        """获取会话运行时状态"""
        return self._state

    @property
    def active_skills(self) -> dict[str, SkillRuntimeContext]:
        """获取当前已加载的Skill"""
        return self._active_skills

    @property
    def tool_artifacts(self) -> dict[str, ToolArtifact]:
        """获取当前工具调用结果"""
        return self._tool_artifacts

    @property
    def turns(self) -> list[AgentTurn]:
        """完整轮次历史，包含完成、取消和失败的 Turn"""
        return self._turns

    @property
    def results(self) -> list[AgentResult]:
        """已完成 Turn 的结果"""
        return [
            turn.result
            for turn in self._turns
            if turn.status == TurnStatus.COMPLETED
        ]

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
        """创建 Turn，并立即保留用户消息"""
        turn = AgentTurn(
            input=input,
            result=AgentResult(),
        )
        turn.status = TurnStatus.RUNNING
        self._current_turn = turn
        conversation = self._state.conversation
        conversation.messages = append_messages(
            conversation.messages,
            [self._build_input(input)],
        )
        return turn

    def wait_turn(self) -> None:
        """将当前 Turn 标为等待输入，保留同一 Turn 供后续恢复"""
        if self._current_turn is None:
            return
        self._current_turn.status = TurnStatus.WAITING_INPUT

    def finish_turn(self, result: AgentResult | None = None) -> None:
        """归档已完成 Turn，并累计本轮 token 用量"""
        turn = self._current_turn
        if turn is None:
            return
        if result is not None:
            turn.result = result
        turn.status = TurnStatus.COMPLETED
        self._archive_turn(turn)
        self._context_usage += turn.result.token_usage.total_tokens
        logger.info("conversation context usage | context usage=%s, ratio=%.2f", self._context_usage, self._context_usage / self._max_context_tokens)

    def cancel_turn(self, latest_checkpoint_id: str | None = None) -> None:
        """归档已取消 Turn，并保留最新 checkpoint 引用"""
        turn = self._current_turn
        if turn is None:
            return
        turn.latest_checkpoint_id = latest_checkpoint_id
        turn.status = TurnStatus.CANCELLED
        self._archive_turn(turn)

    def fail_turn(self, error: str | None = None) -> None:
        """归档失败 Turn，并保留错误信息"""
        turn = self._current_turn
        if turn is None:
            return
        turn.status = TurnStatus.FAILED
        turn.error = error
        self._archive_turn(turn)

    def clear_turn(self) -> None:
        self._current_turn = None

    def _archive_turn(self, turn: AgentTurn) -> None:
        self._turns.append(turn)
        self._current_turn = None

    def _build_input(self, input: UserInput | type[BaseInput]) -> Message:
        value = getattr(input, "input", input)
        if isinstance(value, UserInput):
            text = value.text
        elif isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, default=str)
        return Message(role=Role.USER, content=text)

    def before_model(self, conversation: ConversationState, messages: list[BaseMessage], tools: list[dict[str, Any] | BaseTool] | None = None) -> list[Message] | None:
        """压缩 Graph 会话副本，并返回更新后的历史"""
        usage = ContextUsageCalculator.calculate(messages=messages, tools=tools)
        logger.info("request context usage | tokens=%s", usage)
        compressed = self._conversation_compressor.compress(conversation, self._context_usage + usage)
        if not compressed:
            return None
        
        updated_history = self._build_conversation_messages(conversation)
        lc_messages = MessageAdapter.to_langchain_messages(updated_history)
        self._context_usage = ContextUsageCalculator.calculate(messages=lc_messages)
        logger.info(f"更新会话上下文使用量: {self._context_usage}")
        return updated_history

    async def abefore_model(self, conversation: ConversationState, messages: list[BaseMessage], tools: list[dict[str, Any] | BaseTool] | None = None) -> list[Message] | None:
        """压缩 Graph 会话副本，并返回更新后的历史（异步）"""
        usage = ContextUsageCalculator.calculate(messages=messages, tools=tools)
        logger.info("request context usage | tokens=%s", usage)
        compressed = await self._conversation_compressor.acompress(conversation, self._context_usage + usage)
        if not compressed:
            return None
        
        updated_history = self._build_conversation_messages(conversation)
        lc_messages = MessageAdapter.to_langchain_messages(updated_history)
        self._context_usage = ContextUsageCalculator.calculate(messages=lc_messages)
        logger.info(f"更新会话上下文使用量: {self._context_usage}")
        return updated_history

    def _build_conversation_messages(self, conversation: ConversationState) -> list[Message]:
        """构建会话消息"""
        logger.info("conversation: %s", conversation)
        messages: list[Message] = []
        if conversation.summary is not None:
            messages.append(Message(role=Role.SYSTEM, content=conversation.summary.render()))
        messages.extend(conversation.messages)
        return messages

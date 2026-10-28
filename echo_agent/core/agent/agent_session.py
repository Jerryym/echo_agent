import json

from ...common import get_logger
from ..graph import BaseInput
from ..llm import LLMConfig
from ..model.agent import AgentResult
from ..model.context import ContextState
from ..model.input import UserInput
from ..model.message import Message, Role, append_messages
from ..model.session import SessionState
from ..model.skill import SkillRuntimeContext
from ..llm import ContextBudgetGateway
from .agent_turn import AgentTurn, TurnStatus

logger = get_logger("agent_session")


class AgentSession:
    """
    Agent 会话窗口
    """
    def __init__(self, session_id: str, context_window: int, llm_config: LLMConfig):
        self._session_id: str = session_id
    
        self._state: SessionState = SessionState(
            context=ContextState(context_window=context_window),
        )
        self._turns: list[AgentTurn] = []
        self._current_turn: AgentTurn | None = None

        # 当前会话中活动的SKill
        self._active_skills: dict[str, SkillRuntimeContext] = {}

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
        return ContextBudgetGateway.calculate_tokens(self._state.context.messages)
# endregion

    def start_turn(self, input: UserInput | type[BaseInput]) -> AgentTurn:
        """创建 Turn"""
        turn = AgentTurn(
            input=input,
            result=AgentResult(),
        )
        turn.status = TurnStatus.RUNNING
        self._current_turn = turn

        # 写入用户输入
        user_message = self._build_input(input)
        # 更新会话记录
        self._state.conversation.messages = append_messages(
            self._state.conversation.messages,
            [user_message],
        )
        # 更新上下文
        self._state.context.messages = append_messages(
            self._state.context.messages,
            [user_message.model_copy(deep=True)],
        )
        return turn

    def wait_turn(self) -> None:
        """将当前 Turn 标为等待输入，保留同一 Turn 供后续恢复"""
        if self._current_turn is None:
            return
        self._current_turn.status = TurnStatus.WAITING_INPUT

    def finish_turn(self, result: AgentResult | None = None) -> None:
        """归档已完成 Turn，记录当前已提交工作上下文的用量"""
        turn = self._current_turn
        if turn is None:
            return
        if result is not None:
            turn.result = result
        turn.status = TurnStatus.COMPLETED
        self._archive_turn(turn)
        usage = self.context_usage
        logger.info("context usage | tokens=%s, ratio=%.2f", usage, usage / self._state.context.context_window)

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
        turn.workflow_tasks.clear() # 清理当前 Turn 的工作流任务
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

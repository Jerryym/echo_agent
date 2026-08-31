from ..model.agent import AgentResult, AgentState
from ..model.skill import SkillRuntimeContext
from ..model.input import UserInput
from ..graph import BaseInput
from .agent_turn import AgentTurn


class AgentSession:

    def __init__(self, session_id: str):
        self._session_id: str = session_id
        self._state: AgentState = AgentState(session_id=session_id)
        self._active_skills: dict[str, SkillRuntimeContext] = {}
        self._results: list[AgentResult] = []
        self._current_turn: AgentTurn | None = None

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
# endregion

    def start_turn(self, input: UserInput | type[BaseInput]) -> AgentTurn:
        turn = AgentTurn(
            input=input,
            result=AgentResult(),
        )
        self._current_turn = turn
        return turn

    def finish_turn(self) -> None:
        if self._current_turn is None:
            return

        self.add_result(self._current_turn.result)
        self._current_turn = None

    def clear_turn(self) -> None:
        self._current_turn = None

    def add_result(self, result: AgentResult) -> None:
        """添加执行结果"""
        self._results.append(result)

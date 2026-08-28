from ..model.agent import AgentResult, AgentState
from ..model.skill import SkillRuntimeContext


class AgentSession:

    def __init__(self, session_id: str):
        self._session_id: str = session_id
        self._state: AgentState = AgentState(session_id=session_id)
        self._active_skills: dict[str, SkillRuntimeContext] = {}
        self._results: list[AgentResult] = []

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
# endregion

    def add_result(self, result: AgentResult) -> None:
        """添加执行结果"""
        self._results.append(result)

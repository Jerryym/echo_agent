from ..graph import BaseInput
from ..llm import LLMConfig
from ..model.agent import AgentResult, AgentState
from ..model.input import UserInput
from ..model.skill import SkillRuntimeContext
from ..runtime.algorithm import ConversationCompressor
from .agent_turn import AgentTurn
    

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
        # TODO: 上下文使用量, 后续改成ContextUsage类
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

    # @property
    # def conversation_summary_context(self) -> str:
    #     """获取可注入模型上下文的会话摘要"""
    #     summary = self._state.conversation.summary
    #     if summary is None:
    #         return ""
    #     return summary.render()
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

    def compress_conversation(self) -> bool:
        """压缩会话"""
        # BUG：不能使用state中的token usage，因为此token usage不代表会话上下文用量
        return self._conversation_compressor.compress(self._state.conversation, self._state.token_usage)

    async def acompress_conversation(self) -> bool:
        """压缩会话（异步）"""
        # BUG：不能使用state中的token usage，因为此token usage不代表会话上下文用量
        return await self._conversation_compressor.acompress(self._state.conversation, self._state.token_usage)

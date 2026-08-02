from uuid import UUID

from model.session import SessionInfo


class SessionManager:
    """
    会话管理器
    """
    def __init__(self):
        self._sessions: dict[UUID, SessionInfo] = {}
        self._current: UUID | None = None

    def create(self) -> SessionInfo:
        """
        创建会话
        """
        session = SessionInfo()

        self._sessions[session.id] = session
        self._current = session.id

        return session
    
    @property
    def current_session(self) -> SessionInfo | None:
        if self._current is None:
            return None
        return self._sessions.get(self._current)

    def switch_session(self, session_id: UUID) -> None:
        """
        切换会话
        """
        if session_id not in self._sessions:
            raise ValueError(f"会话 {session_id} 不存在")

        self._current = session_id

    def list_sessions(self) -> list[SessionInfo]:
        """
        列出所有会话
        """
        return list(self._sessions.values())

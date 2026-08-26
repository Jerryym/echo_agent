from __future__ import annotations

from ..agent import Agent


class Application:
    """
    EchoAgent Runtime Application, 负责：
        - 管理 Application 实例
        - 管理 Agent 生命周期
        - 管理 Agent Registry
        - 提供 Runtime 中的 Application 访问入口
    """
    _instance: Application | None = None

    def __init__(self) -> None:
        if Application._instance is not None:
            raise RuntimeError("Application has already been initialized.")

        Application._instance = self
        self._agent_dict: dict[str, Agent] = {}

    @staticmethod
    def get_application() -> Application:
        """获取当前应用程序实例"""
        application = Application._instance
        if application is None:
            raise RuntimeError("Application has not been initialized.")
        return application

    def add_agent(self, agent: Agent) -> str:
        """添加Agent"""
        agent_id = agent.agent_id

        if agent_id in self._agent_dict:
            raise ValueError(f"Agent with id '{agent_id}' already exists.")

        self._agent_dict[agent_id] = agent
        return agent_id

    def remove_agent(self, agent_id: str) -> bool:
        """删除Agent"""
        if agent_id in self._agent_dict:
            self._agent_dict.pop(agent_id)
            return True
        return False

    def get_agent(self, agent_id: str) -> Agent:
        """获取Agent"""
        try:
            return self._agent_dict[agent_id]
        except KeyError:
            raise ValueError(f"Agent with id '{agent_id}' does not exist.")

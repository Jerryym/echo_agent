from abc import ABC, abstractmethod

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from ..schema import BaseContext, BaseState


class Node(ABC):
    """
    Graph 节点抽象

    Attributes:
        name: 节点名称
    """
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        """
        节点名称
        """
        return self._name

    @abstractmethod
    def run(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        """
        运行

        Parameters:
            state: 状态
            runtime: 运行时上下文
            
        Returns:
            dict: 状态
        """
        pass

    @abstractmethod
    async def arun(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        """
        异步运行

        Parameters:
            state: 状态
            runtime: 运行时上下文
            
        Returns:
            dict: 状态
        """
        pass

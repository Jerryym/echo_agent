from abc import ABC, abstractmethod

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from ..schema import BaseContext, BaseState


class Node(ABC):
    """
    Graph 节点抽象

    Attributes:
        name: 节点名称
        is_async: 是否异步
    """
    def __init__(self, name: str, is_async: bool = False):
        self._name = name
        self._is_async = is_async

    @property
    def name(self) -> str:
        """
        节点名称
        """
        return self._name

    @property
    def is_async(self) -> bool:
        """
        是否异步
        """
        return self._is_async
    
    @abstractmethod
    def run(self, state: BaseState, runtime: Runtime[BaseContext], config: RunnableConfig | None = None,) -> dict:
        """
        运行

        Parameters:
            state: 状态
            context: 上下文
            config: 配置
            
        Returns:
            dict: 状态
        """
        pass

    @abstractmethod
    async def arun(self, state: BaseState, runtime: Runtime[BaseContext], config: RunnableConfig | None = None,) -> dict:
        """
        异步运行

        Parameters:
            state: 状态
            context: 上下文
            config: 配置
            
        Returns:
            dict: 状态
        """
        pass

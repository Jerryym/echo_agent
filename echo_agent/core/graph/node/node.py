from abc import ABC, abstractmethod

from langchain_core.runnables import RunnableConfig

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
    def run(self, state: BaseState, context: BaseContext | None = None, config: RunnableConfig | None = None,) -> dict:
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

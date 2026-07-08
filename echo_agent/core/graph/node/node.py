from abc import ABC, abstractmethod

from ..schema import BaseContext, BaseState
from ...llm import LLMClient, LLMConfig


class Node(ABC):
    """
    Graph 节点抽象

    Attributes:
        name: 节点名称
    """
    def __init__(self, name: str, llm_config: LLMConfig | None = None):
        self._name = name
        self._llm_client = LLMClient(llm_config)

    @property
    def name(self) -> str:
        """
        节点名称
        """
        return self._name
    
    @abstractmethod
    def run(self, state: BaseState, context: BaseContext | None = None) -> dict:
        """
        运行

        Parameters:
            state: 状态
            context: 上下文

        Returns:
            dict: 状态
        """
        pass
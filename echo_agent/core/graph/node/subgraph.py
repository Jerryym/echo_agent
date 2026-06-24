from abc import ABC
from typing import List

from node import Node


class SubGraph(ABC):
    """
    Graph 子图

    参数:
        name: 子图名称
        nodeList: 节点列表
    """
    def __init__(self, name: str):
        self._name = name
        self._nodeList: list[Node] = []

    @property
    def name(self) -> str:
        """
        子图名称
        """
        return self._name

    @property
    def nodeList(self) -> List[Node]:
        """
        节点列表
        """
        return self._nodeList
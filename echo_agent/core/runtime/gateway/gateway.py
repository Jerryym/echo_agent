from abc import ABC, abstractmethod
from typing import Any


class BaseGateWay(ABC):
    """
    Gateway 基类
    """
    @abstractmethod
    def authorize(self, target: Any, **kwargs: Any) -> None:
        """授权检查"""
        pass